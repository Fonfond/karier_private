# -*- coding: utf-8 -*-
"""Одностраничная презентация для руководства: итоги проекта «Карьер»."""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

NAVY = RGBColor(0x0F, 0x27, 0x40)
NAVY2 = RGBColor(0x15, 0x3A, 0x5C)
ACCENT = RGBColor(0x4C, 0x9A, 0xFF)
RED = RGBColor(0xF0, 0x44, 0x38)
GREEN = RGBColor(0x22, 0xC5, 0x5E)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
INK = RGBColor(0x1B, 0x2B, 0x3A)
MUTED = RGBColor(0x5B, 0x6B, 0x7A)
CARD = RGBColor(0xF4, 0xF7, 0xFB)
LINE = RGBColor(0xDD, 0xE4, 0xEC)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
slide = prs.slides.add_slide(prs.slide_layouts[6])


def box(x, y, w, h, fill=None, line=None, radius=False):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(0.75)
    shp.shadow.inherit = False
    return shp


def text(x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0):
    """runs: list of (text, size, bold, color, space_before) tuples."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    first = True
    for item in runs:
        txt, size, bold, color = item[0], item[1], item[2], item[3]
        space_before = item[4] if len(item) > 4 else 0
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.space_before = Pt(space_before)
        p.space_after = Pt(0)
        p.line_spacing = spacing
        run = p.add_run()
        run.text = txt
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = "Segoe UI"
    return tb


# --- шапка ---
box(0, 0, 13.333, 1.18, fill=NAVY)
text(0.45, 0.16, 9.6, 0.55, [
    ("Карьер: цифровая однолинейная схема и учёт оборудования", 19.5, True, WHITE),
])
text(0.45, 0.76, 10.4, 0.3, [
    ("Итоги разработки · ноябрь 2026 · рабочая версия на стенде", 11.5, False, RGBColor(0xB9, 0xCB, 0xE0)),
])
text(10.2, 0.28, 2.7, 0.5, [
    ("234 + 112", 20, True, ACCENT),
    ("автотестов", 9.5, False, RGBColor(0xB9, 0xCB, 0xE0)),
], align=PP_ALIGN.RIGHT)

# --- карточки ---
card_y, card_h, card_w, gap = 1.38, 4.28, 2.95, 0.22
xs = [0.45 + i * (card_w + gap) for i in range(4)]
titles = ["Проблема", "Решение", "Результат", "Экономический эффект"]
for x, title in zip(xs, titles):
    box(x, card_y, card_w, card_h, fill=CARD, line=LINE, radius=True)
    bar = box(x, card_y, card_w, 0.07, fill=ACCENT if title != "Экономический эффект" else GREEN)
    text(x + 0.18, card_y + 0.2, card_w - 0.36, 0.3, [(title.upper(), 12.5, True, NAVY)])

# 1. Проблема
text(xs[0] + 0.18, card_y + 0.58, card_w - 0.36, 3.4, [
    ("Схема и реестр — в Excel, Visio и на бумаге", 11, True, INK, 0),
    ("Двойной ввод: сначала тип, потом объект; ошибки и потеря времени", 10.5, False, MUTED, 7),
    ("Статус «под напряжением» не виден на месте", 10.5, False, MUTED, 6),
    ("Связи рисуют «на глаз», без привязки к оборудованию", 10.5, False, MUTED, 6),
    ("На объекте нет сети — данные теряются", 10.5, False, MUTED, 6),
])

# 2. Решение
text(xs[1] + 0.18, card_y + 0.58, card_w - 0.36, 3.4, [
    ("Единая модель оборудования", 11, True, INK, 0),
    ("Типы и паспортные поля один раз, создание — по классам", 10.5, False, MUTED, 7),
    ("Шаблоны ПС 35/6 и БКРУ", 10.5, True, INK, 6),
    ("6 ячеек БКРУ, 17 на секцию ПС, КТП с разъединителем", 10.5, False, MUTED, 4),
    ("Живая схема", 10.5, True, INK, 6),
    ("Ресайз блоков, перетаскивание ячеек, связи с ячейками, автосейв", 10.5, False, MUTED, 4),
    ("Безопасность и офлайн", 10.5, True, INK, 6),
    ("Красный/зелёный статус, аудит, работа без сети", 10.5, False, MUTED, 4),
])

# 3. Результат (метрики)
text(xs[2] + 0.18, card_y + 0.58, card_w - 0.36, 3.5, [
    ("234 + 112", 22, True, NAVY, 0),
    ("автотестов: backend + frontend", 9.5, False, MUTED, 0),
    ("p95 15,5 мс", 18, True, NAVY, 12),
    ("сохранение раскладки (20/20 без ошибок)", 9.5, False, MUTED, 0),
    ("2 с", 18, True, NAVY, 12),
    ("автосейв после правки, без кнопки «Сохранить»", 9.5, False, MUTED, 0),
    ("48/48", 18, True, NAVY, 12),
    ("проверок сквозного сценария приёмки", 9.5, False, MUTED, 0),
    ("0", 18, True, GREEN, 12),
    ("блокирующих дефектов на приёмке", 9.5, False, MUTED, 0),
])

# 4. Экономика
text(xs[3] + 0.18, card_y + 0.58, card_w - 0.36, 3.5, [
    ("40–60 ч/мес", 17, True, NAVY, 0),
    ("экономия на сборке схем и двойном вводе", 9.5, False, MUTED, 0),
    ("0,7–1,1 млн ₽/год", 17, True, GREEN, 12),
    ("при 1 500 ₽/ч и 20 объектах/мес — оценка", 9.5, False, MUTED, 0),
    ("меньше аварий и простоев", 11, True, INK, 12),
    ("актуальный статус питания и история — быстрее локализация", 9.5, False, MUTED, 3),
    ("быстрее ввод в эксплуатацию", 11, True, INK, 10),
    ("шаблоны и автосейв вместо ручной отрисовки", 9.5, False, MUTED, 3),
    ("Цифры эффекта — предварительная оценка, требуют подтверждения на пилоте", 8.5, False, RGBColor(0x8A, 0x6D, 0x00), 12),
])

# --- нижняя полоса ---
box(0, 5.9, 13.333, 1.6, fill=NAVY2)
text(0.45, 6.05, 6.2, 0.3, [("Что дальше", 13, True, WHITE)])
text(0.45, 6.42, 6.0, 0.9, [
    ("1) пилот на участке 2–3 недели · 2) Docker на сервер · 3) полевой чек-лист на планшете", 10.5, False, RGBColor(0xD7, 0xE3, 0xF0), 0),
])
text(6.9, 6.05, 6.0, 0.3, [("Готово к показу", 13, True, WHITE)])
text(6.9, 6.42, 6.0, 0.9, [
    ("Рабочий стенд, 234+112 тестов, миграции 0015–0017, Docker-поставка и инструкции", 10.5, False, RGBColor(0xD7, 0xE3, 0xF0), 0),
])
text(0.45, 7.18, 12.4, 0.22, [
    ("Источники: docs/team/35-etap3-report.md, 36-demo-guide.md · оценка эффекта консервативная", 8, False, RGBColor(0x9F, 0xB4, 0xC9)),
])

prs.save(r"C:\karier\karier\docs\team\36-management-onepager.pptx")
print("saved")
