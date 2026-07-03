#!/usr/bin/env python3
"""
CS2 industry monitor + Telegram autoposter (v1).

Polls CS2 news sources, detects genuinely NEW newsworthy items, drafts an
EN post (with an optional CTA), and posts it to a Telegram channel via the
Bot API. All brand/site specifics are injected via environment variables,
so this code stays generic and shareable.

Design goals:
- Speed to breaking: poll every ~5 min, post within seconds of detection.
- No spam: only items that pass the newsworthiness filter, with a rate limit.
- Safe test: runs against a TEST channel first (autopost mode).

Config via environment variables (see README.md):
  TELEGRAM_BOT_TOKEN   required — BotFather token
  TELEGRAM_CHANNEL     required — @channelusername or numeric -100... id
  SITE_URL             optional — CTA link (kept private via secrets/.env)
  BRAND_NAME           optional — brand name used in the LLM voice prompt
  ANTHROPIC_API_KEY    optional — if set, posts are written by Claude (better);
                                  otherwise a smart template is used
  MAX_POSTS_PER_RUN    optional — default 2 (anti-spam)
  SEEN_FILE            optional — default seen.json (dedupe store)
  POLL_SECONDS         optional — loop mode interval, default 300 (5 min)
"""
import os, json, time, html, re, sys, hashlib
from datetime import datetime, timezone
import urllib.request, urllib.error, urllib.parse

def _load_dotenv(path=".env"):
    """Minimal .env loader (no external deps). Existing env vars win."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()

UA = "Mozilla/5.0 (CS2NewsMonitor/1.0)"
SITE_URL = os.getenv("SITE_URL", "").strip()
BRAND_NAME = os.getenv("BRAND_NAME", "").strip()
SEEN_FILE = os.getenv("SEEN_FILE", "seen.json")
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "4"))

# Primary-source X ingestion via a POOL of Nitter instances (free, best-effort).
# Instances die often — keep this list fresh via the NITTER_INSTANCES env var.
NITTER_INSTANCES = [x.strip() for x in os.getenv(
    "NITTER_INSTANCES", "https://nitter.net,https://xcancel.com,https://nitter.poast.org"
).split(",") if x.strip()]
PRIMARY_SOURCES_FILE = os.getenv("PRIMARY_SOURCES_FILE", "primary_sources.txt")
PRIMARY_MAX_PER_ACCOUNT = int(os.getenv("PRIMARY_MAX_PER_ACCOUNT", "3"))
TOPICS_FILE = os.getenv("TOPICS_FILE", "topics.json")  # story-level dedupe store

# --- newsworthiness: keyword weights ---------------------------------------
KEYWORDS = {
    # roster / transfers
    "sign": 3, "signs": 3, "signed": 3, "roster": 3, "transfer": 3, "bench": 3,
    "joins": 3, "leaves": 3, "steps down": 3, "igl": 2, "coach": 2, "loan": 2,
    # competition
    "major": 4, "final": 3, "champions": 3, "wins": 3, "beat": 2, "upset": 3,
    "mvp": 3, "playoffs": 2, "grand final": 4, "qualify": 2, "eliminated": 2,
    # game / economy
    "update": 3, "patch": 3, "case": 3, "skin": 3, "operation": 3, "knife": 2,
    "price": 2, "market": 2, "ban": 3, "vac": 3, "cheat": 2, "nerf": 2, "buff": 2,
}
MIN_SCORE = 3  # threshold to consider "newsworthy"

# Skip items whose title promotes a competing skin/case/gambling brand.
COMPETITORS = [
    "skin.club", "skinclub", "hellcase", "key-drop", "keydrop", "csgoroll",
    "csgo roll", "csgoempire", "csgo empire", "gamdom", "datdrop", "clash.gg",
    "cases.gg", "rustclash", "bandit.camp", "skinsmonkey", "tradeit",
    "cs.money", "csmoney", "bloodycase", "daddyskins", "duelbits", "rollbit",
    "howl.gg", "skinport", "waxpeer", "dmarket", "csgofast", "csgoluck",
]


def is_blocked(it):
    t = it["title"].lower()
    return any(c in t for c in COMPETITORS)


# Drop items about OTHER games / off-topic (primary accounts cross-post a lot).
OTHER_GAMES = [
    "valorant", "league of legends", "teamfight tactics", "wild rift", "dota 2",
    "dota2", "apex legends", "fortnite", "rainbow six", "ea fc", "fifa",
    "rocket league", "overwatch", "call of duty", "warzone", "marvel rivals",
    "riot games", "pubg", "mobile legends", "honor of kings",
]
_OTHER_RX = re.compile(r"\b(lol|r6|cod|tft|hok)\b")


def is_offtopic(it):
    t = it["title"].lower()
    return any(g in t for g in OTHER_GAMES) or bool(_OTHER_RX.search(t))


# If draft_llm returns one of these (or the SKIP sentinel), do NOT post it.
_REFUSAL = (
    "skip", "i can't", "i cannot", "isn't cs2", "not cs2", "wrong game",
    "outside the scope", "outside our", "please share", "i'll get it done",
    "nothing to post", "completely outside", "can't repurpose", "can't write",
    "not our game", "league of legends", "valorant",
)


def is_unusable(text):
    if not text:
        return True
    tl = text.strip().lower()
    if tl.rstrip(".!").strip() == "skip":
        return True
    return any(m in tl for m in _REFUSAL)


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# --- sources ---------------------------------------------------------------
def src_reddit():
    """r/GlobalOffensive newest posts (free JSON, no auth)."""
    out = []
    try:
        data = json.loads(_get("https://www.reddit.com/r/GlobalOffensive/new.json?limit=25"))
        for c in data.get("data", {}).get("children", []):
            d = c["data"]
            out.append({
                "id": "reddit_" + d["id"],
                "title": html.unescape(d.get("title", "")),
                "url": "https://reddit.com" + d.get("permalink", ""),
                "source": "Reddit r/GlobalOffensive",
                "score_hint": d.get("score", 0),
            })
    except Exception as e:
        log(f"reddit error: {e}")
    return out


def src_steam():
    """Official CS2 (appid 730) news — patches, updates, cases."""
    out = []
    try:
        url = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
               "?appid=730&count=10&maxlength=300&format=json")
        data = json.loads(_get(url))
        for it in data.get("appnews", {}).get("newsitems", []):
            out.append({
                "id": "steam_" + str(it["gid"]),
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "source": "Steam / Valve",
                "score_hint": 0,
                "force": True,  # official updates are always worth a look
            })
    except Exception as e:
        log(f"steam error: {e}")
    return out


def _parse_rss(xml, source, prefix):
    out = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        block = m.group(1)
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
        l = re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", block, re.S)
        if not t or not l:
            continue
        title = html.unescape(re.sub("<.*?>", "", t.group(1)).strip())
        link = l.group(1).strip()
        # Stable, cross-process id: built-in hash() is randomized per run (PYTHONHASHSEED),
        # which broke dedup entirely. Use md5, and strip scheme+host so the same tweet served
        # by a different Nitter instance (pool rotates) maps to one id.
        key = re.sub(r"^https?://[^/]+", "", link) or link
        out.append({"id": prefix + hashlib.md5(key.encode("utf-8")).hexdigest()[:16],
                    "title": title, "url": link, "source": source, "score_hint": 0})
    return out


def src_hltv():
    """HLTV RSS. May be Cloudflare-protected; failure is non-fatal."""
    try:
        return _parse_rss(_get("https://www.hltv.org/rss/news"), "HLTV", "hltv_")
    except Exception as e:
        log(f"hltv error (ok to ignore): {e}")
        return []


def src_googlenews():
    """Broad CS2 coverage as a safety net (last 1 day)."""
    try:
        url = ("https://news.google.com/rss/search?q=%22CS2%22+OR+%22Counter-Strike%22"
               "+when:1d&hl=en-US&gl=US&ceid=US:en")
        items = _parse_rss(_get(url), "Google News", "gn_")
        for it in items:
            # Google News appends " - Publisher" to titles; strip it (no source in posts)
            it["title"] = re.sub(r"\s+[-–—]\s+[^-–—]+$", "", it["title"]).strip()
        return items
    except Exception as e:
        log(f"googlenews error: {e}")
        return []


def load_primary_handles():
    """Read primary_sources.txt → list of handles (without @), skipping comments."""
    out = []
    try:
        with open(PRIMARY_SOURCES_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(line.lstrip("@"))
    except FileNotFoundError:
        pass
    return out


def src_primary_x():
    """Read primary-source accounts via a pool of Nitter instances (free, best-effort).
    Failover across instances; tags each item with its author for attribution."""
    out = []
    handles = load_primary_handles()
    for h in handles:
        xml = None
        for base in NITTER_INSTANCES:
            try:
                xml = _get(f"{base.rstrip('/')}/{h}/rss", timeout=12)
                if xml and "<item>" in xml:
                    break
                xml = None
            except Exception:
                xml = None
        if not xml:
            log(f"primary X: no Nitter instance served @{h}")
            continue
        items = _parse_rss(xml, f"X:@{h}", f"x_{h}_")[:PRIMARY_MAX_PER_ACCOUNT]
        for it in items:
            it["author"] = h
            it["primary"] = True
        out.extend(items)
    if handles:
        log(f"primary X: {len(out)} items from {len(handles)} accounts")
    return out


SOURCES = [src_primary_x, src_reddit, src_steam, src_hltv, src_googlenews]


# --- filtering -------------------------------------------------------------
def score_item(it):
    if it.get("force"):
        return MIN_SCORE
    text = it["title"].lower()
    s = sum(w for k, w in KEYWORDS.items() if k in text)
    # a strongly-upvoted reddit post is inherently notable
    if it.get("score_hint", 0) >= 300:
        s += 2
    # primary-source posts (straight from the account) are higher-value signal
    if it.get("primary"):
        s += 2
    return s


def category(it):
    t = it["title"].lower()
    if any(k in t for k in ("sign", "roster", "transfer", "bench", "joins", "igl", "coach")):
        return "roster"
    if any(k in t for k in ("case", "skin", "operation", "knife", "price", "market")):
        return "skins"
    if any(k in t for k in ("update", "patch", "nerf", "buff")):
        return "update"
    if any(k in t for k in ("major", "final", "wins", "mvp", "champions", "playoffs")):
        return "results"
    return "news"


# --- drafting --------------------------------------------------------------
def _cta(base):
    return base + (f" 👉 {SITE_URL}" if SITE_URL else "")


CTA = {
    "roster":  _cta("New rosters = new meta = new stories. Build your inventory while they rebuild"),
    "skins":   _cta("Feeling it? Open a case and chase that drop"),
    "update":  _cta("Fresh patch, fresh grind. Test your luck on a case"),
    "results": _cta("Champions get skins. So can you — open a case"),
    "news":    _cta("Stay in the game. Open a case"),
}
EMOJI = {"roster": "🔁", "skins": "💎", "update": "🛠️", "results": "🏆", "news": "📰"}

# Editorial voice: 4 author personas mapped by news category (see project voice guide).
PERSONAS = {
    "roster":  ("The Insider", "breaking-news insider — confident, a little cryptic, no-spin; treats a transfer as a statement"),
    "results": ("The Hype Man", "pure adrenaline about the moment — high energy, 'did you SEE that'"),
    "update":  ("The Shitposter", "self-aware internet humor and light memes about the patch/update"),
    "skins":   ("The Hype Man", "hype about the drop / skin / market moment"),
    "news":    ("The Analyst", "sharp hot-take with a debate hook — smart, opinionated, a bit provocative"),
}


def draft_template(it):
    cat = category(it)
    post = f"{EMOJI[cat]} <b>{html.escape(it['title'])}</b>"
    if SITE_URL:                      # CTA only when a link is configured
        post += f"\n\n{CTA[cat]}"
    return post


def draft_llm(it):
    """Optional: let an LLM write the post in the configured brand voice."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        cat = category(it)
        persona, style = PERSONAS.get(cat, PERSONAS["news"])
        author_ctx = ""
        if it.get("author"):
            author_ctx = (f"\nThis came DIRECTLY from the X account @{it['author']} (a primary source). "
                          "If it's their opinion, insider leak, or claim, attribute it to them by name; "
                          "treat leaks as unconfirmed, not fact.\n")
        cta = (f"If — and only if — it feels natural, you may nudge readers to open cases at {SITE_URL}. "
               if SITE_URL else "No call-to-action and no links. ")
        prompt = (
            "You are one of several authors running a top-tier CS2 news Telegram channel for English-speaking fans. "
            f"Write ONE Telegram post in the voice of \"{persona}\": {style}.\n"
            "If this news is NOT about Counter-Strike (CS2/CS:GO) — e.g., another game (Valorant, League, "
            "Dota), merch, or anything off-topic — reply with exactly one word: SKIP (nothing else). "
            "Never write an explanation, apology, or 'please share' message.\n"
            + author_ctx +
            "\nFIRST, read the news and judge its context: How big is it? Is it divisive/debatable, "
            "emotional/legendary, funny/absurd, or routine/informational? Let that judgment drive the post — "
            "the format must FIT the story, not a template.\n"
            "- Divisive/debatable news → a sharp take or a genuine question can work.\n"
            "- Legendary/emotional moment → awe and hype; a rhetorical flourish, not a survey question.\n"
            "- Funny/absurd → a joke or meme line; no question needed.\n"
            "- Routine/small → one witty, confident line; deliver it and stop.\n\n"
            "Do NOT reflexively end with 'Drop your take' / 'W or L?' / a question — MOST posts should just land "
            "with personality and stop. Use an engagement prompt only when the topic genuinely earns it, and vary it. "
            "Vary your structure, length, and opening so no two posts feel alike. Match the energy to the news.\n\n"
            "Hard rules: English only; ~15-45 words; 1-2 relevant emojis; no hashtags.\n"
            "Sourcing:\n"
            "- Do NOT credit the outlet/site that merely republished the news (no 'via <site>').\n"
            "- BUT if the content is a specific person's OPINION, INSIDER LEAK, RUMOR or CLAIM, you MUST "
            "attribute it to that person by name when a name is present (e.g., 'per KRL', 'Richard Lewis reports', "
            "'Thorin argues'). Never pass someone's take or scoop off as ours — that's a copyright/credibility issue.\n"
            "- If it's clearly a rumor/leak but no person is named in what you're given, frame it as an unconfirmed "
            "leak — do NOT invent a source name.\n"
            "- Treat leaks/rumors as unconfirmed, not established fact.\n"
            + cta +
            "Provoke debate about the game/scene, never harass or defame real people; punch up, not down. "
            "STRICTLY never mention or reference politics, war, or the social/economic situation in any "
            "country — completely off-limits, in any form. "
            "(Covering players, teams and transfers from ANY country — incl. Ukraine, Russia, etc. — is welcome; "
            "nationality/flag as a neutral fact is fine. Just never add any political, war, or country-situation "
            "commentary or framing.) "
            "Style: do NOT write whole sentences in ALL CAPS (a word or two max, rarely); avoid clichéd tics like "
            "'someone pinch me', 'hold me', 'let that sit' — vary your openers and phrasing every single time. "
            "Do NOT invent facts, numbers, or quotes — react only to what is given. "
            "Do NOT name competing skin/case/gambling brands.\n\n"
            "News: \"" + it["title"] + "\".")
        body = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        text = "".join(b.get("text", "") for b in resp.get("content", []))
        return text.strip() or None
    except Exception as e:
        log(f"llm draft error (fallback to template): {e}")
        return None


def make_post(it):
    return draft_llm(it) or draft_template(it)


# --- telegram --------------------------------------------------------------
def post_to_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHANNEL"]
    body = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


# --- dedupe store ----------------------------------------------------------
# ── story-level dedupe (same news from many sources = one post) ──────────────
_STOP = set((
    "the a an of to in on at for and or with as is are was were be been being "
    "new news official team clan esports cs2 csgo counter strike major after over "
    "into out from this that his her their have has had will just now more most "
    "per reports report says said sign signs signed joins wins update"
).split())


def topic_sig(title):
    """Salient tokens of a headline (names/orgs), lowercased, stopwords removed."""
    toks = re.findall(r"[A-Za-z0-9']+", html.unescape(title).lower())
    return sorted({t for t in toks if len(t) > 3 and t not in _STOP})


def load_topics():
    try:
        with open(TOPICS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_topics(topics):
    with open(TOPICS_FILE, "w") as f:
        json.dump(topics[-120:], f)


def is_dup_topic(sig, topics):
    s = set(sig)
    if len(s) < 2:
        return False
    for past in topics:
        if len(s & set(past)) >= 2:   # shares 2+ salient tokens → same story
            return True
    return False


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    keep = list(seen)[-2000:]  # cap file size
    with open(SEEN_FILE, "w") as f:
        json.dump(keep, f)


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


# --- one polling cycle -----------------------------------------------------
def run_once():
    seen = load_seen()
    items = []
    for src in SOURCES:
        items.extend(src())
    log(f"fetched {len(items)} items from {len(SOURCES)} sources")

    # new + newsworthy, best first
    fresh = [it for it in items if it["id"] not in seen]
    scored = [(score_item(it), it) for it in fresh
              if not is_blocked(it) and not is_offtopic(it)]
    picks = [it for s, it in sorted(scored, key=lambda x: -x[0]) if s >= MIN_SCORE]

    topics = load_topics()
    posted = 0
    handled = set()          # ids we're done with (posted / dup) → mark seen
    for it in picks:
        if posted >= MAX_POSTS_PER_RUN:
            break            # remaining newsworthy picks stay eligible next run
        sig = topic_sig(it["title"])
        if is_dup_topic(sig, topics):        # same story already covered → skip
            log(f"skip dup [{category(it)}] {it['title'][:70]}")
            handled.add(it["id"])
            continue
        text = make_post(it)
        if is_unusable(text):            # non-CS2 / refusal / SKIP → never post
            log(f"skip non-CS2/unusable [{it['title'][:60]}]")
            handled.add(it["id"])
            continue
        try:
            post_to_telegram(text)
            posted += 1
            topics.append(sig)
            handled.add(it["id"])
            log(f"POSTED [{category(it)}] {it['title'][:80]}")
        except Exception as e:
            log(f"telegram error: {e}")   # keep eligible on send failure

    # Mark seen: everything fresh EXCEPT newsworthy picks we didn't reach this run
    # (so overflow news isn't silently lost — it resurfaces next run).
    pick_ids = {it["id"] for it in picks}
    for it in fresh:
        if it["id"] in pick_ids and it["id"] not in handled:
            continue
        seen.add(it["id"])
    save_seen(seen)
    save_topics(topics)
    log(f"cycle done: {posted} posted, {len(fresh)} fresh")


def main():
    if os.getenv("RUN_ONCE") == "1" or "--once" in sys.argv:
        run_once()
        return
    interval = int(os.getenv("POLL_SECONDS", "300"))
    log(f"starting loop, every {interval}s")
    while True:
        try:
            run_once()
        except Exception as e:
            log(f"run error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
