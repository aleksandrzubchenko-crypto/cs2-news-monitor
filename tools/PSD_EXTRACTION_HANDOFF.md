# Handoff: пиксель-в-пиксель карточки из PSD (для Claude Code, на хосте)

Принцип (память проекта): делаем **именно так, пиксель-в-пиксель, без подгонки**. Рамка
карточки — реальные пиксели PSD, не реконструкция «на глаз». Реконструкция `card.py`
остаётся только как fallback.

## Что уже готово (в репо)
- `farmskins_tg_monitor/tools/extract_psd.py` — экстрактор (psd-tools).
- `farmskins_tg_monitor/card_psd.py` — рендер из `frame.png` + `zones.json`.

## Почему на хосте
В Cowork-сэндбоксе нет PyPI, а Pillow тянет слои PSD ненадёжно (blend-режимы/оффсеты →
пустая рамка, слой `light` не читается). `psd-tools` корректно уважает порядок слоёв и
эффекты — но ставится только на хосте. Поэтому экстракция = здесь, у тебя.

## Шаги
1. Установить зависимости:
   ```bash
   pip install psd-tools pillow
   ```
2. Найти и распаковать исходные PSD (пользователь загрузил `PSD.zip`):
   ```bash
   # PSD.zip лежит в uploads текущей сессии; распакуй в рабочую папку
   mkdir -p /tmp/fs_psd && unzip -o "<путь к PSD.zip>" -d /tmp/fs_psd
   ```
   (16 файлов: База, Цитата, Апдейт, Графики, Обложка, «N фото» и т.д.)
3. Прогнать экстракцию (выход по умолчанию — `farmskins_tg_monitor/assets/templates/`):
   ```bash
   python farmskins_tg_monitor/tools/extract_psd.py /tmp/fs_psd
   ```
   На каждый шаблон появится `assets/templates/<slug>/{frame.png, zones.json, reference.png}`.

## Сверка (обязательно, до коммита)
Для каждого шаблона отрендерить нашей рамкой и сравнить с `reference.png`:
```bash
python - <<'PY'
from farmskins_tg_monitor.card_psd import render
render("quote","/tmp/check_quote.png",
       hero="/tmp/fs_psd_hero.png",   # любое фото игрока для теста
       lines=[{"text":"IS SNUS THE 6TH MAN ON EVERY CS2 ROSTER?","highlight":"6TH MAN"},
              {"text":"W  —  PRO SCENE RUNS ON IT"},
              {"text":"L  —  TOUR HYGIENE, PLEASE"}])
PY
```
Открыть `/tmp/check_quote.png` рядом с `assets/templates/quote/reference.png`. Проверить
пиксель-в-пиксель: панель/полоса/кавычка-кружок/вотермарки/лого совпадают по позиции и
цвету; зона фото — прозрачная (просвечивает hero); текст стоит ровно в PSD-зонах.

Если рамка расходится — правки в `extract_psd.py`:
- **фото определилось не тем слоем** → поправь `pick_photo` / `PHOTO_KW`.
- **в зоне фото остаётся фон (не прозрачно)** → проверь z-split (`above`), список
  `dynamic`; убедись, что bg-слой под фото не попал в «above».
- **лого команды не скрылось/не нашёлся слот** → дополни `TEAM_KW`.
- **шрифт/кегль текста не тот** → `zones.json` даёт `font_px`/`color`/`align`; `card_psd`
  берёт Burbank для крупного (≥40px), Montserrat для мелкого — если PSD использует другой
  шрифт семейства, подставь его в `card_psd._font`.

## Интеграция в монитор
В `monitor.build_and_post` заменить путь генерации картинки на `card_psd.render(slug, …)`,
выбирая `slug` по типу поста (quote/news/update/stats/…). Маппинг «тип новости → шаблон +
раскладка строк» вынести в небольшой конфиг. `card.py` оставить как fallback, если для
типа нет PSD-шаблона.

## Коммит
```bash
git add farmskins_tg_monitor/tools/extract_psd.py farmskins_tg_monitor/card_psd.py \
        farmskins_tg_monitor/tools/PSD_EXTRACTION_HANDOFF.md \
        farmskins_tg_monitor/assets/templates
git commit -m "cards: pixel-perfect PSD templates (extract_psd + card_psd + frame/zones assets)"
git push
```
> Исходные `.psd` (тяжёлые, 620 МБ) в репо НЕ коммитим — только `frame.png`/`zones.json`/
> `reference.png`. При желании добавь `*.psd` в `.gitignore`.
