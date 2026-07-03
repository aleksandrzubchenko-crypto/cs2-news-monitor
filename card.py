"""Farmskins branded news card (Pillow). cs2news-style square 1080 card:
brand bg / hero image + bottom headline (Burbank, yellow accent) + logo + watermark.
Assets live in ./assets (committed). See Farmskins_TG_Card_Design.md for the spec."""
import os, re, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "assets")
BURB = os.path.join(A, "font", "burbankbigcondensed_bold.otf")
MONT = os.path.join(A, "font", "Montserrat-SemiBold.ttf")
LOGO_WHITE = os.path.join(A, "logo", "farmskins-logo-white.png")

S = 1080
YELLOW = (251, 195, 0); WHITE = (255, 255, 255)
GREY = (163, 171, 191); GREY2 = (115, 119, 137); DARK = (32, 34, 43)


def _burb(sz): return ImageFont.truetype(BURB, sz)
def _mont(sz): return ImageFont.truetype(MONT, sz)


def _brand_bg(seed=0):
    random.seed(seed)
    img = Image.new("RGB", (S, S), DARK); px = img.load()
    for y in range(S):
        t = y / S
        for x in range(S):
            px[x, y] = (int(32 - 8 * t), int(34 - 8 * t), int(43 - 6 * t))
    # Our own style: dark base + subtle geometric shards + a soft yellow brand glow.
    d = ImageDraw.Draw(img, "RGBA")
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([int(S * 0.55), int(S * 0.02), S + 260, int(S * 0.45)],
                                 fill=(251, 195, 0, 24))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(14):
        cx, cy = random.randint(0, S), random.randint(40, int(S * 0.70)); s = random.randint(50, 150)
        d.polygon([(cx, cy), (cx + s, cy + random.randint(-30, 30)),
                   (cx + random.randint(-20, 40), cy + s)], outline=(80, 84, 104, 55), width=3)
    # vignette (darker edges → focus center)
    vig = Image.new("L", (S, S), 0)
    ImageDraw.Draw(vig).ellipse([-280, -280, S + 280, S + 280], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(170))
    img = Image.composite(img, Image.new("RGB", (S, S), (10, 11, 16)), vig)
    return img


def _cover(hero_path):
    """Full-bleed cover-fit of a hero image; None on failure."""
    try:
        h = Image.open(hero_path).convert("RGB")
        r = max(S / h.width, S / h.height)
        h = h.resize((int(h.width * r), int(h.height * r)))
        return h.crop(((h.width - S) // 2, 0, (h.width - S) // 2 + S, S))
    except Exception:
        return None


def text_zone_busy(hero_path, y0=0.60, thresh=20.0):
    """True if the bottom text zone is high-detail (faces/text of an already-finished
    graphic) → better to post the image raw than overlay our headline on it."""
    try:
        from PIL import ImageStat, ImageFilter
        im = Image.open(hero_path).convert("L")
        im = im.resize((400, int(400 * im.height / im.width)))
        w, h = im.size
        r = im.crop((0, int(h * y0), w, h)).filter(ImageFilter.FIND_EDGES)
        return ImageStat.Stat(r).mean[0] > thresh
    except Exception:
        return False


def make_card(headline, out_path, highlight=None, hero=None, seed=0, category=None):
    img = _cover(hero) if hero else None
    if img is None:
        img = _brand_bg(seed)
    d = ImageDraw.Draw(img, "RGBA")

    # top watermark strip
    d.rectangle([0, 0, S, 52], fill=(0, 0, 0, 120))
    d.text((16, 14), ("#ESPORTS      FARMSKINS NEWS      ") * 2, font=_mont(20), fill=(255, 255, 255, 55))

    # headline layout (Burbank, autofit + wrap); words inside `highlight` are yellow
    hlset = set((highlight or "").upper().split())
    words = [(w, YELLOW if w.upper().strip(".,!?") in hlset else WHITE) for w in headline.upper().split()]
    maxw = S - 120
    for size in range(96, 40, -4):
        f = _burb(size); sp = d.textlength(" ", font=f); lines = [[]]; wln = 0
        for w, c in words:
            ww = d.textlength(w, font=f)
            if wln + ww > maxw and lines[-1]:
                lines.append([]); wln = 0
            lines[-1].append((w, c, ww)); wln += ww + sp
        if len(lines) * (size + 8) <= 300:
            break
    f = _burb(size); sp = d.textlength(" ", font=f)
    y = S - 150 - len(lines) * (size + 8)

    # Text/image separation (matches template): soft gradient fade into a dark
    # bottom band. Image reads on top; text reads on the dark band below.
    panel_top = y - (92 if category else 26)
    band = Image.new("RGBA", (S, S), (0, 0, 0, 0)); bd = ImageDraw.Draw(band)
    grad = 140
    for i in range(grad):
        bd.line([(0, panel_top - grad + i), (S, panel_top - grad + i)],
                fill=(18, 20, 28, int(236 * i / grad)))
    bd.rectangle([0, panel_top, S, S], fill=(18, 20, 28, 236))
    img = Image.alpha_composite(img.convert("RGBA"), band).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")

    # category chip (angular white banner) above the headline
    if category:
        cf = _mont(28); lbl = category.upper(); tw = d.textlength(lbl, font=cf)
        cx0, cy0 = 60, y - 74
        d.polygon([(cx0, cy0), (cx0 + tw + 74, cy0), (cx0 + tw + 52, cy0 + 52), (cx0, cy0 + 52)], fill=WHITE)
        d.rectangle([cx0, cy0 + 52, cx0 + 46, cy0 + 58], fill=YELLOW)
        d.text((cx0 + 26, cy0 + 12), lbl, font=cf, fill=(24, 26, 34))
    for ln in lines:
        x = 60
        for w, c, ww in ln:
            d.text((x, y), w, font=f, fill=c); x += ww + sp
        y += size + 8

    # bottom-left watermark
    d.text((60, S - 58), "T.ME / FARMSKINS", font=_mont(22), fill=GREY)
    # logo bottom-right
    try:
        logo = Image.open(LOGO_WHITE).convert("RGBA"); lw = 250
        logo = logo.resize((lw, int(logo.height * lw / logo.width)))
        img.paste(logo, (S - lw - 46, S - logo.height - 40), logo)
    except Exception:
        pass

    # corner bracket accents (subtle "designed" frame)
    br, cw = 42, 3
    for x, y, dx, dy in [(34, 34, 1, 1), (S - 34, 34, -1, 1), (34, S - 34, 1, -1), (S - 34, S - 34, -1, -1)]:
        d.line([(x, y), (x + dx * br, y)], fill=(255, 255, 255, 110), width=cw)
        d.line([(x, y), (x, y + dy * br)], fill=(255, 255, 255, 110), width=cw)

    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "fs_card_test.png")
    make_card("BetBoom have no plans to buy out fl4mus, contract runs to 2029",
              p, highlight="BetBoom", category="TRANSFER")
    print("rendered", p)
