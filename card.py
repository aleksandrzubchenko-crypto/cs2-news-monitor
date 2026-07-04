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


def _line_to_img(tokens, font, sp):
    """Render one line of (word, color) tokens to a tight RGBA image."""
    asc, desc = font.getmetrics(); h = asc + desc
    w = int(sum(t[2] for t in tokens) + sp * max(len(tokens) - 1, 0)) + 6
    im = Image.new("RGBA", (max(w, 1), h + 8), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im); x = 0
    for word, col, ww in tokens:
        dd.text((x, 0), word, font=font, fill=col); x += ww + sp
    return im


def _italic(im, k=0.20):
    w, h = im.size; ext = int(h * k)
    return im.transform((w + ext, h), Image.AFFINE, (1, k, -ext, 0, 1, 0), resample=Image.BICUBIC)


def _paste_center(base, line_im, y):
    base.paste(line_im, ((S - line_im.width) // 2, y), line_im)


def make_card(headline, out_path, highlight=None, hero=None, seed=0, category=None, sub=None,
              team_logo=None):
    img = _cover(hero) if hero else _brand_bg(seed)
    d = ImageDraw.Draw(img, "RGBA")

    # top watermark strip
    d.rectangle([0, 0, S, 52], fill=(0, 0, 0, 120))
    d.text((16, 14), ("#ESPORTS      FARMSKINS NEWS      ") * 2, font=_mont(20), fill=(255, 255, 255, 55))

    # headline layout (centered, autofit); words inside `highlight` are yellow
    hlset = set((highlight or "").upper().split())
    words = [(w, YELLOW if w.upper().strip(".,!?") in hlset else WHITE) for w in headline.upper().split()]
    maxw = S - 150
    for size in range(92, 40, -4):
        f = _burb(size); sp = d.textlength(" ", font=f); lines = [[]]; wln = 0
        for w, c in words:
            ww = d.textlength(w, font=f)
            if wln + ww > maxw and lines[-1]:
                lines.append([]); wln = 0
            lines[-1].append((w, c, ww)); wln += ww + sp
        if len(lines) * (size + 12) <= 250:
            break
    f = _burb(size); sp = d.textlength(" ", font=f)
    line_h = size + 12
    extra = (46 if sub else 0) + (96 if team_logo else 0)
    block_h = len(lines) * line_h + extra
    panel_top = S - 130 - block_h

    # BLUE gradient bottom panel (matches template) + soft blue glow
    panel = Image.new("RGBA", (S, S), (0, 0, 0, 0)); pd = ImageDraw.Draw(panel)
    grad = 150
    for i in range(grad):
        pd.line([(0, panel_top - grad + i), (S, panel_top - grad + i)], fill=(14, 22, 46, int(238 * i / grad)))
    pd.rectangle([0, panel_top, S, S], fill=(14, 22, 46, 238))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([int(S * 0.18), panel_top + 20, int(S * 0.82), S + 130], fill=(38, 92, 210, 70))
    panel = Image.alpha_composite(panel, glow.filter(ImageFilter.GaussianBlur(95)))
    img = Image.alpha_composite(img.convert("RGBA"), panel).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")

    # centered italic headline
    y = panel_top + 46
    for ln in lines:
        _paste_center(img, _italic(_line_to_img(ln, f, int(sp))), y); y += line_h
    # centered italic sub-line
    if sub:
        sf = _mont(30); st = sub.upper()
        _paste_center(img, _italic(_line_to_img([(st, (205, 216, 238), d.textlength(st, font=sf))], sf, 0), k=0.16), y + 8)
        y += 52
    # centered team logo (if provided)
    if team_logo:
        try:
            tl = Image.open(team_logo).convert("RGBA"); th = 70
            tl = tl.resize((int(tl.width * th / tl.height), th))
            img.paste(tl, ((S - tl.width) // 2, y + 10), tl)
        except Exception:
            pass

    # bottom-left watermark + Farmskins logo bottom-right
    d.text((60, S - 58), "T.ME / FARMSKINS", font=_mont(22), fill=GREY)
    try:
        logo = Image.open(LOGO_WHITE).convert("RGBA"); lw = 235
        logo = logo.resize((lw, int(logo.height * lw / logo.width)))
        img.paste(logo, (S - lw - 46, S - logo.height - 40), logo)
    except Exception:
        pass

    # corner bracket accents
    br, cw = 42, 3
    for x, yy, dx, dy in [(34, 34, 1, 1), (S - 34, 34, -1, 1), (34, S - 34, 1, -1), (S - 34, S - 34, -1, -1)]:
        d.line([(x, yy), (x + dx * br, yy)], fill=(255, 255, 255, 110), width=cw)
        d.line([(x, yy), (x, yy + dy * br)], fill=(255, 255, 255, 110), width=cw)

    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "fs_card_test.png")
    make_card("Aurora signed ash", p, highlight="ash",
              sub="ash becomes Aurora's new coach")
    print("rendered", p)
