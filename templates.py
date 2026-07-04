"""
templates.py — реестр PSD-шаблонов карточек и сборка строк под их зоны.

Рабочий набор (пиксель-перфект из PSD, одиночное фото):
  • base     — W-or-L / поллы: [заголовок, W/L (2 строки), саб]
  • quote    — цитата (фул-фото + полупрозрачная панель): [заголовок, атрибуция]
  • seredina — заголовок сверху + фото-полоса + атрибуция снизу: [заголовок, атрибуция]
  • update   — новость с врезкой (фото в рамке + бейдж): [заголовок]

Отложенные (мульти-слот/спец, не в ротации): photo2/3/4/6/8, photo7, *_gorizont,
stats, shablon_oblozhki.

Builder возвращает `lines` СТРОГО в порядке зон шаблона (сверху вниз) — как их ждёт
card_psd.render. Поля берутся из структурированного вывода LLM (card fields).
"""

# набор, разрешённый в ротацию (у остальных папок зоны/фото ещё не доведены)
# photo2 (VS) включён: монитор резолвит 2 лого команд, иначе уходит в seredina.
ENABLED = ("base", "quote", "seredina", "update", "photo2")


def _wl(f):
    return f"W  —  {f.get('wl_w','')}\nL  —  {f.get('wl_l','')}"


# builder на слаг: lines строго по зонам шаблона (порядок = zones.json texts)
BUILDERS = {
    "base": lambda f: [
        {"text": f.get("headline", ""), "highlight": f.get("highlight", "")},
        {"text": _wl(f), "highlight": "W L"},
        {"text": f.get("sub", "")},
    ],
    "quote": lambda f: [
        {"text": f.get("headline", ""), "highlight": f.get("highlight", "")},
        {"text": f.get("attribution", "")},
    ],
    "seredina": lambda f: [
        {"text": f.get("headline", ""), "highlight": f.get("highlight", "")},
        {"text": f.get("attribution", f.get("sub", ""))},
    ],
    "update": lambda f: [
        {"text": f.get("headline", ""), "highlight": f.get("highlight", "")},
    ],
    # VS / матч-результат: 2 фото-слота (команды), зоны [заголовок VS, счёт, саб]
    "photo2": lambda f: [
        {"text": f.get("headline") or f"{f.get('team1','')} VS {f.get('team2','')}".strip(),
         "highlight": f.get("highlight", "VS")},
        {"text": f.get("score", "")},
        {"text": f.get("sub", "")},
    ],
}

# тип карточки (из LLM/категории) → слаг шаблона
TYPE_SLUG = {
    "poll": "base", "wl": "base", "w_or_l": "base", "vs": "base", "hot_take": "base",
    "quote": "quote", "interview": "quote",
    "reddit": "seredina", "news": "seredina", "transfer": "seredina", "results": "seredina",
    "update": "update", "patch": "update", "workshop": "update", "skins": "update",
    "vs": "photo2", "match": "photo2",   # требует 2 hero — включим в ENABLED после 2-hero-врезки
}

# нужен ли шаблону фото-hero (все текущие — да; на будущее для без-фото форматов)
NEEDS_HERO = {"base": True, "quote": True, "seredina": True, "update": True}


def resolve_slug(card_type):
    """card_type → включённый слаг. Дефолт — seredina (универсальная новость с фото)."""
    slug = TYPE_SLUG.get((card_type or "news").lower(), "seredina")
    return slug if slug in ENABLED else "seredina"


def build_lines(slug, fields):
    b = BUILDERS.get(slug)
    return b(fields) if b else [{"text": fields.get("headline", "")}]
