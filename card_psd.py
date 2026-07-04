"""
card_psd.py — рендер карточки ПОВЕРХ пиксель-перфект рамки из PSD.

Рамка (frame.png) и зоны (zones.json) экспортируются tools/extract_psd.py на хосте
в assets/templates/<slug>/. Здесь мы только:
  hero → в photo_bbox (cover) → frame.png (реальные пиксели PSD) → текст в точные зоны.
Никакой «реконструкции на глаз»: панель/полоса/акценты/лого — из PSD как есть.

API:
    from card_psd import render
    render("quote", out_path,
           hero="hero.png",
           lines=[{"text":"IS SNUS THE 6TH MAN?","highlight":"6TH MAN"},
                  {"text":"W  —  PRO SCENE RUNS ON IT"},
                  {"text":"L  —  TOUR HYGIENE, PLEASE"}],
           team_logo="falcons.png")
`lines` идут в ТОМ ЖЕ порядке, что zones["texts"] (сверху вниз). Лишние зоны — пропускаются.
"""
import os, re, json
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_ROOT = os.path.join(HERE, "assets", "templates")
FONT_DIR = os.path.join(HERE, "assets", "font")
BURB = os.path.join(FONT_DIR, "burbankbigcondensed_bold.otf")     # заголовки/W-L
MONT = os.path.join(FONT_DIR, "Montserrat-SemiBold.ttf")          # body/футнот
YELLOW = (251, 195, 0)


def _font(px, big):
    return ImageFont.truetype(BURB if big else MONT, px)


def _cover(path, w, h):
    im = Image.open(path).convert("RGBA")
    r = max(w / im.width, h / im.height)
    im = im.resize((max(int(im.width * r), 1), max(int(im.height * r), 1)))
    x = (im.width - w) // 2
    return im.crop((x, 0, x + w, h))


def _fit(im):  # 0.62 ~ шрифт крупнее bbox: используем ширину для автоподгона
    return im


def _italic(im, k=0.20):
    w, h = im.size; ext = int(h * k)
    return im.transform((w + ext, h), Image.AFFINE, (1, k, -ext, 0, 1, 0), resample=Image.BICUBIC)


def _tokens_width(draw, tokens, font, sp):
    return sum(draw.textlength(w, font=font) for w, _ in tokens) + sp * max(len(tokens) - 1, 0)


def _line_image(tokens, font, sp):
    asc, desc = font.getmetrics(); h = asc + desc
    w = 0
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for word, _ in tokens:
        w += tmp.textlength(word, font=font)
    w += sp * max(len(tokens) - 1, 0)
    im = Image.new("RGBA", (max(int(w) + 6, 1), h + 8), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im); x = 0
    for word, col in tokens:
        dd.text((x, 0), word, font=font, fill=col)
        x += dd.textlength(word, font=font) + sp
    return im


# высота глифов ≈ FONT_H_FACTOR * (высота зоны на строку). Единственный тюнинг-коэффициент
# соответствия кегля PSD; если текст мельче/крупнее reference — крутить здесь.
FONT_H_FACTOR = 1.30


def _render_text_zone(base, zone, spec):
    """Рисует зону (1+ строк) ТОЧНО в PSD-bbox: размер от высоты зоны с автоподгоном
    по ширине, цвет/align из zones, жёлтый highlight по словам, италик, многострочность."""
    x1, y1, x2, y2 = zone["bbox"]
    maxw, zh = x2 - x1, y2 - y1
    base_color = tuple(zone.get("color", [255, 255, 255]))
    align = zone.get("align", "left")
    italic = spec.get("italic", True)
    hlset = set((spec.get("highlight", "") or "").upper().split())

    sublines = [s for s in re.split(r"[\r\n]+", spec["text"]) if s != ""] or [spec["text"]]
    n = len(sublines)
    per_h = zh / n
    big = per_h >= 24                          # крупный → Burbank, мелкий → Montserrat
    d = ImageDraw.Draw(base)

    def toks(line):
        ws = (line.upper() if big else line).split()
        return [(w, YELLOW if w.strip(".,!?—-").upper() in hlset else base_color) for w in ws]

    size = max(int(per_h * FONT_H_FACTOR), 14)
    while size > 12:                           # ужимаем, если самая длинная строка не влезла
        font = _font(size, big); sp = d.textlength(" ", font=font)
        widest = max((_tokens_width(d, toks(s), font, sp) for s in sublines), default=0)
        if widest <= maxw:
            break
        size -= 2
    font = _font(size, big); sp = d.textlength(" ", font=font)
    asc, desc = font.getmetrics(); lh = asc + desc
    oy = y1 + max((zh - lh * n) // 2, 0)       # вертикальное центрирование блока в зоне
    for s in sublines:
        line = _line_image(toks(s), font, int(sp))
        if italic:
            line = _italic(line, k=0.20 if big else 0.16)
        if align == "center":  ox = x1 + (maxw - line.width) // 2
        elif align == "right": ox = x2 - line.width
        else:                  ox = x1
        base.alpha_composite(line, (int(ox), int(oy)))
        oy += lh


def render(slug, out_path, hero=None, heroes=None, lines=None, team_logo=None, bg=(12, 16, 30)):
    d = os.path.join(TPL_ROOT, slug)
    frame = Image.open(os.path.join(d, "frame.png")).convert("RGBA")
    zones = json.load(open(os.path.join(d, "zones.json"), encoding="utf-8"))
    W, H = zones["canvas"]

    canvas = Image.new("RGBA", (W, H), bg + (255,))
    # heroes → фото-слоты (слева-направо). Один hero заполняет все слоты (или единственный).
    slots = zones.get("photo_slots") or [zones["photo_bbox"]]
    imgs = list(heroes) if heroes else ([hero] if hero else [])
    for i, slot in enumerate(slots):
        src = imgs[i] if i < len(imgs) else (imgs[-1] if imgs else None)
        if not src:
            continue
        x1, y1, x2, y2 = slot
        try:
            canvas.alpha_composite(_cover(src, x2 - x1, y2 - y1), (x1, y1))
        except Exception:
            pass
    # пиксель-перфект рамка PSD поверх фото
    canvas.alpha_composite(frame, (0, 0))
    # лого команды в слот
    if team_logo and zones.get("team_logo_slot"):
        x1, y1, x2, y2 = zones["team_logo_slot"]
        try:
            tl = Image.open(team_logo).convert("RGBA")
            r = min((x2 - x1) / tl.width, (y2 - y1) / tl.height)
            tl = tl.resize((max(int(tl.width * r), 1), max(int(tl.height * r), 1)))
            canvas.alpha_composite(tl, (x1 + ((x2 - x1) - tl.width) // 2,
                                        y1 + ((y2 - y1) - tl.height) // 2))
        except Exception:
            pass
    # текст в зоны (по порядку сверху вниз)
    for zone, spec in zip(zones.get("texts", []), lines or []):
        if spec and spec.get("text"):
            _render_text_zone(canvas, zone, spec)

    canvas.convert("RGB").save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    import sys
    slug = sys.argv[1] if len(sys.argv) > 1 else "quote"
    out = render(slug, "/tmp/card_psd_test.png",
                 hero=os.path.join(HERE, "assets", "sample_hero.png")
                 if os.path.exists(os.path.join(HERE, "assets", "sample_hero.png")) else None,
                 lines=[{"text": "IS SNUS THE 6TH MAN ON EVERY CS2 ROSTER?", "highlight": "6TH MAN"},
                        {"text": "W  —  PRO SCENE RUNS ON IT"},
                        {"text": "L  —  TOUR HYGIENE, PLEASE"}])
    print("rendered", out)
