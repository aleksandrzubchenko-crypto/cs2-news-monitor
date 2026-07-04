#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_psd.py — пиксель-перфект экстракция шаблонов карточек из PSD.

ЗАПУСКАТЬ НА ХОСТЕ (Claude Code), где ставится psd-tools:
    pip install psd-tools pillow
    python farmskins_tg_monitor/tools/extract_psd.py "/path/to/PSD_folder"

Для каждого <name>.psd кладёт в assets/templates/<slug>/:
  • frame.png     — рамка-оверлей ПИКСЕЛЬ-В-ПИКСЕЛЬ из PSD (реальные пиксели панели/
                    полосы/акцентов/вотермарков/лого), ПРОЗРАЧНАЯ в зоне фото →
                    кладётся ПОВЕРХ нашего hero. Динамический текст и лого команды скрыты.
  • zones.json    — координаты зон: photo_bbox, текст-зоны (bbox + font_px + color +
                    align), слот лого команды. Всё в пикселях 1080-холста.
  • reference.png — полный оригинальный композит PSD (с сэмпл-контентом) для сверки.

Принцип рамки (без подгонки): FRAME = полный композит (скрыты фото/текст/лого) →
в зоне фото заменяем на композит ТОЛЬКО слоёв НАД фото (прозрачный там, где над фото
ничего не рисуется). Итог: панель/глоу/вотермарки за пределами фото — целиком из PSD;
внутри зоны фото — только то, что PSD рисует поверх фото (верхняя полоса, кавычка-кружок),
остальное прозрачно → просвечивает наш hero.
"""
import os, sys, json, re, unicodedata
from psd_tools import PSDImage
from PIL import Image

# ── имя файла → устойчивый slug ──────────────────────────────────────────────
_TRANSLIT = {                                    # семантические слаги для известных типов
    "база": "base", "цитата": "quote", "апдейт": "update", "графики": "stats",
    "обложка": "cover", "новость": "news", "вето": "veto", "матч": "match",
    "воркшоп": "workshop", "мем": "meme", "тир": "tierlist", "опрос": "poll",
    "трансфер": "transfer", "результат": "results", "скин": "skins", "факт": "fact",
}
_CYR = {  # посимвольная транслитерация для неизвестных имён (уникальность вместо «tpl»)
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i",
    "й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t",
    "у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"",
    "э":"e","ю":"yu","я":"ya",
}
def slugify(name):
    base = os.path.splitext(os.path.basename(name))[0].strip().lower()
    m = re.match(r"(\d+)\s*фото", base)          # «2 фото» → photo2
    if m: return f"photo{m.group(1)}"
    for ru, en in _TRANSLIT.items():
        if ru in base: return en
    lat = "".join(_CYR.get(c, c) for c in base)  # кириллица → латиница
    lat = unicodedata.normalize("NFKD", lat).encode("ascii", "ignore").decode()
    lat = re.sub(r"[^a-z0-9]+", "_", lat).strip("_")
    return lat or "tpl"

# ── эвристики классификации слоёв ────────────────────────────────────────────
PHOTO_KW  = ("screenshot", "photo", "фото", "hero", "player", "image", "img")
TEAM_KW   = ("falcons", "navi", "vitality", "faze", "g2", "spirit", "mouz",
             "astralis", "liquid", "aurora", "team", "лого команд", "logo_team")
BRAND_KW  = ("farmskins", "t.me", "t.ме", "watermark", "esports", "news")

def is_type(l):   return getattr(l, "kind", "") == "type"
def is_raster(l): return getattr(l, "kind", "") in ("pixel", "smartobject", "shape")

# статичный бренд-текст, который ПЕЧЁМ в рамку (не выносим в зоны).
# ВАЖНО: имя type-слоя в PSD = его текст, поэтому НЕЛЬЗЯ фильтровать по словам вроде
# "news"/"cologne"/"esports" — они встречаются в реальных заголовках. Детектим по ПОЗИЦИИ:
# вотермарк живёт в верхней/нижней полосе, контентные заголовки — в середине/панели.
def is_static_text(l, H):
    b = l.bbox
    if b == (0, 0, 0, 0): return False
    y1, y2 = b[1], b[3]
    if y2 <= H * 0.06: return True                       # верхняя вотермарк-полоса
    if y1 >= H * 0.95: return True                       # нижняя подпись (t.me / farmskins)
    txt = (getattr(l, "text", "") or "").strip().lower()
    if "farmskins" in txt or "t.me" in txt: return True  # бренд-хэндл (в заголовках не бывает)
    if txt and len(txt) <= 2 and not any(c.isalnum() for c in txt): return True   # глиф « " „ »
    return False

def flatten(node):
    """Плоский список листьев в порядке отрисовки (низ→верх)."""
    out = []
    for ch in node:                      # psd-tools: снизу вверх
        if ch.is_group(): out += flatten(ch)
        else: out.append(ch)
    return out

def bbox_of(l):
    b = l.bbox
    return (int(b[0]), int(b[1]), int(b[2]), int(b[3]))

def area(b): return max(0, b[2]-b[0]) * max(0, b[3]-b[1])

def pick_photo(leaves, W, H):
    """Фото = крупный растровый слой в верхней части холста (или по имени)."""
    named = [l for l in leaves if is_raster(l) and any(k in (l.name or "").lower() for k in PHOTO_KW)]
    # фолбэк — только настоящие картинки (pixel/smartobject), НЕ shape (это рамки-Rectangle)
    cand = named or [l for l in leaves if getattr(l, "kind", "") in ("pixel", "smartobject")]
    best, best_score = None, -1
    for l in cand:
        b = bbox_of(l); a = area(b)
        cy = (b[1]+b[3]) / 2
        if a < W*H*0.15: continue                 # слишком мелкий — не фото
        score = a - (cy > H*0.6) * W*H            # приоритет верхним крупным
        if score > best_score: best, best_score = l, score
    return best

def photo_slots(leaves, W, H):
    """Список фото-слотов (1 или N), слева-направо/сверху-вниз. Сигналы по надёжности:
    клип-фото (скруглённые карточки) → named (photo_*/img) → доминантные растры в полосе."""
    A = W * H
    clipped = [l for l in leaves if getattr(l, "clipping_layer", False)
               and getattr(l, "kind", "") in ("pixel", "smartobject")]
    named = [l for l in leaves if is_raster(l)
             and any(k in (l.name or "").lower() for k in PHOTO_KW)]
    slots = clipped or named
    if not slots:
        cand = [l for l in leaves if getattr(l, "kind", "") in ("pixel", "smartobject")
                and not any(k in (l.name or "").lower() for k in BRAND_KW)]
        band = [l for l in cand if 0.06 * A <= area(bbox_of(l)) <= 0.78 * A]
        slots = band or ([max(cand, key=lambda l: area(bbox_of(l)))] if cand else [])
    slots = list(dict.fromkeys(slots))
    slots.sort(key=lambda l: ((bbox_of(l)[0] + bbox_of(l)[2]) // 2,
                              (bbox_of(l)[1] + bbox_of(l)[3]) // 2))
    return slots

def type_info(l):
    """font_px, (r,g,b), align из type-слоя. Best-effort; bbox всегда надёжен."""
    font_px = rgb = None; align = "left"
    try:
        d = l.engine_dict
        tf = getattr(l, "transform", None)
        scale = (tf[0]**2 + tf[1]**2) ** 0.5 if tf else 1.0
        runs = d["StyleRun"]["RunArray"]
        lens = d["StyleRun"].get("RunLengthArray", [1] * len(runs))
        sizes = []; colors = {}                               # цвет → суммарная длина прогонов
        for r, ln in zip(runs, lens):
            sdd = r["StyleSheet"]["StyleSheetData"]
            sz = sdd.get("FontSize")
            if sz: sizes.append(float(sz) * scale)
            fc = (sdd.get("FillColor") or {}).get("Values")   # [a,r,g,b] 0..1
            if fc and len(fc) >= 4:
                c = tuple(int(round(x * 255)) for x in fc[1:4])
                colors[c] = colors.get(c, 0) + max(int(ln), 1)
        if sizes:  font_px = int(round(max(sizes)))           # заголовок = крупнейший прогон
        if colors: rgb = max(colors, key=colors.get)          # ДОМИНИРУЮЩИЙ цвет (не первый)
        just = d.get("ParagraphRun", {}).get("RunArray", [{}])[0] \
                .get("ParagraphSheet", {}).get("Properties", {}).get("Justification", 0)
        align = {0: "left", 1: "right", 2: "center", 3: "center", 4: "center"}.get(just, "left")
    except Exception:
        pass
    return font_px, rgb, align

def composite_with_visible(psd, visible_leaves, W, H):
    """Композит, где видимы ТОЛЬКО leaves из набора. Возвращает RGBA 1080×1080."""
    all_leaves = flatten(psd)
    saved = {id(l): l.visible for l in all_leaves}
    keep = {id(l) for l in visible_leaves}
    for l in all_leaves:
        l.visible = id(l) in keep
    img = psd.composite(force=True, viewport=(0, 0, W, H))
    for l in all_leaves:
        l.visible = saved[id(l)]
    return img.convert("RGBA")

BRAND_DARK = [32, 34, 43]           # #20222B — бренд-тёмный для текста на светлом фоне
def _lum(c): return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
def _dist(a, b): return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5

def frame_zone_bg(frame, bbox, W, H):
    """Доминантный НЕПРОЗРАЧНЫЙ цвет зоны из FRAME — это реальная подложка, на которую
    композитится наш текст (панель/полоса). None → зона над фото-дырой (фон = будущий hero)."""
    x1, y1, x2, y2 = bbox
    reg = frame.crop((max(x1, 0), max(y1, 0), min(x2, W), min(y2, H)))
    if reg.width < 2 or reg.height < 2:
        return None
    px = list(reg.getdata())
    op = [p[:3] for p in px if len(p) > 3 and p[3] > 128]
    if len(op) < 0.2 * len(px):          # в основном прозрачно → над фото
        return None
    im = Image.new("RGB", (len(op), 1)); im.putdata(op)
    im = im.quantize(colors=8).convert("RGB")
    hist = {}
    for p in im.getdata():
        hist[p] = hist.get(p, 0) + 1
    return max(hist, key=hist.get)

def resolve_text_color(rgb, bg):
    """Цвет текста по КОНТРАСТУ с реальной подложкой (frame). PSD-цвет уважаем, если он
    цветово контрастен к подложке (жёлтый счёт и т.п.); иначе — бренд-контраст (тёмный на
    светлом, белый на тёмном). None-подложка (над фото) → белый (безопасно на фото)."""
    if bg is None:
        return [255, 255, 255]
    if rgb is not None and _dist(rgb, bg) >= 45:
        return list(rgb)
    return list(BRAND_DARK) if _lum(bg) > 140 else [255, 255, 255]

def composite_hiding(psd, hidden_leaves, W, H):
    all_leaves = flatten(psd)
    saved = {id(l): l.visible for l in all_leaves}
    hide = {id(l) for l in hidden_leaves}
    for l in all_leaves:
        if id(l) in hide: l.visible = False
    img = psd.composite(force=True, viewport=(0, 0, W, H))
    for l in all_leaves:
        l.visible = saved[id(l)]
    return img.convert("RGBA")

def extract_one(psd_path, out_root, slug=None):
    psd = PSDImage.open(psd_path)
    W, H = psd.width, psd.height
    slug = slug or slugify(psd_path)
    out_dir = os.path.join(out_root, slug); os.makedirs(out_dir, exist_ok=True)
    leaves = flatten(psd)

    # reference (оригинал как есть) — держим в памяти для сэмплинга цвета текста
    ref_img = psd.composite(force=True, viewport=(0, 0, W, H)).convert("RGB")
    ref_img.save(os.path.join(out_dir, "reference.png"))

    from PIL import ImageChops, ImageFilter, ImageDraw as _ID
    slots = photo_slots(leaves, W, H)
    photo = slots[0] if slots else pick_photo(leaves, W, H)
    photo_bbox = bbox_of(photo) if photo else [0, 0, W, int(H*0.62)]

    texts_all  = [l for l in leaves if is_type(l)]
    static_txt = [l for l in texts_all if is_static_text(l, H)]   # печём в рамку
    dyn_txt    = [l for l in texts_all if l not in static_txt]    # выносим в зоны
    team_logos = [l for l in leaves if is_raster(l) and l not in slots
                  and any(k in (l.name or "").lower() for k in TEAM_KW)
                  and not any(k in (l.name or "").lower() for k in BRAND_KW)]
    # прячем из рамки ТОЛЬКО динамику (все фото-слоты + дин.текст + лого); статик — запечён
    dynamic = set(slots) | set(dyn_txt) | set(team_logos)
    comp_full = composite_hiding(psd, dynamic, W, H)

    # над-фото оверлей: z-направление psd-tools авто-детектим — верный набор «над фото»
    # даёт НИЗКУЮ alpha в центре зоны фото (эти элементы центр фото не закрывают).
    pi = leaves.index(photo) if photo in leaves else 0
    cx, cy = (photo_bbox[0]+photo_bbox[2])//2, (photo_bbox[1]+photo_bbox[3])//2
    def _ca(img):
        p = img.crop((max(cx-30, 0), max(cy-30, 0), cx+30, cy+30)).split()[-1]
        return sum(p.getdata()) / max(p.width * p.height, 1)
    ov_a = composite_with_visible(psd, [l for l in leaves[pi+1:] if l not in dynamic], W, H)
    ov_b = composite_with_visible(psd, [l for l in leaves[:pi]  if l not in dynamic], W, H)
    overlay = ov_a if _ca(ov_a) <= _ca(ov_b) else ov_b

    # FRAME: пробиваем дыры под фото, возвращаем над-фото элементы оверлеем.
    frame = comp_full.copy()
    slot_bboxes = []
    if len(slots) <= 1:
        # ОДИН слот: сплошная прямоугольная дыра по видимому фото (чисто, без просветов).
        with_photo = composite_hiding(psd, set(dyn_txt) | set(team_logos), W, H)
        diff = ImageChops.difference(with_photo.convert("RGB"), comp_full.convert("RGB")).convert("L")
        mbox = diff.point(lambda v: 255 if v > 12 else 0).getbbox()
        pb = list(mbox) if mbox else photo_bbox
        slot_bboxes = [pb]; photo_bbox = pb
        alpha = frame.split()[-1].copy()
        _ID.Draw(alpha).rectangle([pb[0], pb[1], pb[2]-1, pb[3]-1], fill=0)
        frame.putalpha(alpha)
    else:
        # N слотов: per-slot diff-маска (диагональ/скругления сохраняются сами),
        # лёгкое закрытие мелких дыр (MaxFilter), чтобы тёмные зоны фото не просвечивали.
        knock = Image.new("L", (W, H), 0)
        for s in slots:
            with_s = composite_hiding(psd, dynamic - {s}, W, H)   # показать только этот слот
            d = ImageChops.difference(with_s.convert("RGB"), comp_full.convert("RGB")).convert("L")
            m = d.point(lambda v: 255 if v > 8 else 0).filter(ImageFilter.MaxFilter(5))
            knock = ImageChops.lighter(knock, m)
            slot_bboxes.append(list(m.getbbox() or bbox_of(s)))
        frame.putalpha(ImageChops.subtract(frame.split()[-1], knock))
        photo_bbox = slot_bboxes[0]
    frame = Image.alpha_composite(frame, overlay)                # вернуть над-фото
    frame.save(os.path.join(out_dir, "frame.png"))

    # zones.json — ТОЛЬКО динамические текст-зоны (заголовок/W-L/саб)
    zt = []
    for l in sorted(dyn_txt, key=lambda t: bbox_of(t)[1]):     # сверху вниз
        fp, rgb, align = type_info(l)
        b = bbox_of(l)
        sample = (getattr(l, "text", "") or "").strip()
        nlines = max(sample.count("\n") + 1, sample.count("\r") + 1, 1)
        if fp is None:                                         # оценка кегля из высоты зоны
            fp = max(int((b[3] - b[1]) / nlines * 1.15), 20)
        color = resolve_text_color(rgb, frame_zone_bg(frame, b, W, H))   # контраст с реальной подложкой
        zt.append({"name": l.name, "bbox": b, "font_px": fp, "nlines": nlines,
                   "color": color, "align": align, "sample": sample[:80]})
    tl_slot = bbox_of(team_logos[0]) if team_logos else None
    zones = {"canvas": [W, H], "photo_bbox": list(photo_bbox),
             "photo_slots": slot_bboxes, "texts": zt, "team_logo_slot": tl_slot,
             "slug": slug, "source_psd": os.path.basename(psd_path)}
    with open(os.path.join(out_dir, "zones.json"), "w", encoding="utf-8") as f:
        json.dump(zones, f, ensure_ascii=False, indent=2)

    print(f"✓ {slug:12s} photo={photo_bbox} texts={len(zt)} teamlogo={'yes' if tl_slot else 'no'}")
    return slug

def main():
    if len(sys.argv) < 2:
        print("usage: extract_psd.py <psd_folder> [out_dir]"); sys.exit(1)
    src = sys.argv[1]
    out_root = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "templates")
    os.makedirs(out_root, exist_ok=True)
    psds = [os.path.join(src, f) for f in sorted(os.listdir(src)) if f.lower().endswith(".psd")]
    if not psds: print("no .psd in", src); sys.exit(1)
    print(f"→ {len(psds)} PSD → {out_root}\n")
    used, mapping = {}, []
    for p in psds:
        s = slugify(p)
        if s in used:                              # гарантия уникальной папки
            used[s] += 1; s = f"{s}_{used[s]}"
        else:
            used[s] = 1
        mapping.append((os.path.basename(p), s))
        try: extract_one(p, out_root, slug=s)
        except Exception as e:
            print(f"✗ {os.path.basename(p)} [{s}]: {e}")
    print("\nfile → slug:")
    for f, s in mapping:
        print(f"  {f:40s} → {s}")
    print("\ndone.")

if __name__ == "__main__":
    main()
