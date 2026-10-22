"""Презентация в фирменном шаблоне Т-Банк Образование.

python presentation/build_tbank.py ШАБЛОН.pptx [АССЕТЫ]
→ presentation/Amba_TBank.pptx

Берём 12 слайдов-примеров из шаблона, заполняем их своими текстами, картинками и QR, остальное удаляем.
Тексты выступления берутся из docs/SPEECH.md (тайминг 7:35 из 8:00) и кладутся в заметки к слайдам.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(sys.argv[1])
ASSETS = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "presentation" / "assets"
OUT = ROOT / "presentation" / "Amba_TBank.pptx"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

DEMO_URL = "amba-production-3ab7.up.railway.app"
REPO_URL = "github.com/BessolitsinGleb/AI-ta"

# Порядок: номер слайда-примера в шаблоне → наш слайд.
ORDER = [13, 24, 64, 53, 33, 63, 26, 32, 21, 67, 35, 82]


# ---------- текст с сохранением фирменного форматирования ----------

def _clean_runs(p: etree._Element) -> etree._Element:
    runs = p.findall(f"{A}r")
    for extra in runs[1:]:
        p.remove(extra)
    for tag in ("br", "fld"):
        for el in p.findall(f"{A}{tag}"):
            p.remove(el)
    if not runs:
        r = etree.SubElement(p, f"{A}r")
        end = p.find(f"{A}endParaRPr")
        rpr = copy.deepcopy(end) if end is not None else etree.Element(f"{A}rPr")
        rpr.tag = f"{A}rPr"
        r.append(rpr)
        etree.SubElement(r, f"{A}t")
        if end is not None:
            p.remove(end)
            p.append(end)
    return p


def set_text(shape_or_tf, paras: list[str] | str) -> None:
    """Заменить текст, сохранив оформление: i-й абзац копирует стиль i-го абзаца шаблона (или последнего)."""
    tf = shape_or_tf.text_frame if hasattr(shape_or_tf, "text_frame") else shape_or_tf
    paras = [paras] if isinstance(paras, str) else paras
    body = tf._txBody
    old = body.findall(f"{A}p")
    protos = [copy.deepcopy(p) for p in old] or [etree.Element(f"{A}p")]
    for p in old:
        body.remove(p)
    for i, text in enumerate(paras):
        p = _clean_runs(copy.deepcopy(protos[min(i, len(protos) - 1)]))
        r = p.find(f"{A}r")
        r.find(f"{A}t").text = text
        end = p.find(f"{A}endParaRPr")
        if end is not None:
            p.remove(end)
            p.append(end)
        body.append(p)


def shape(slide, shape_id: int):
    for sh in slide.shapes:
        if sh.shape_id == shape_id:
            return sh
        if sh.shape_type == 6:
            for c in sh.shapes:
                if c.shape_id == shape_id:
                    return c
    raise KeyError(shape_id)


def put(slide, shape_id: int, paras) -> None:
    set_text(shape(slide, shape_id), paras)


def remove(slide, shape_id: int) -> None:
    el = shape(slide, shape_id)._element
    el.getparent().remove(el)


def picture(slide, path: Path, x: float, y: float, w: float | None = None, h: float | None = None):
    return slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w) if w else None, Inches(h) if h else None)


# ---------- таблицы ----------

def shrink_table(table, rows: int, cols: int) -> None:
    tbl = table._tbl
    grid = tbl.tblGrid
    total = sum(int(gc.get("w")) for gc in grid.findall(f"{A}gridCol"))
    for gc in grid.findall(f"{A}gridCol")[cols:]:
        grid.remove(gc)
    for tr in tbl.findall(f"{A}tr")[rows:]:
        tbl.remove(tr)
    for tr in tbl.findall(f"{A}tr"):
        for tc in tr.findall(f"{A}tc")[cols:]:
            tr.remove(tc)
    return total


def set_col_widths(table, inches: list[float]) -> None:
    for gc, w in zip(table._tbl.tblGrid.findall(f"{A}gridCol"), inches):
        gc.set("w", str(int(Inches(w))))


# ---------- данные ----------

def speech() -> list[tuple[str, str]]:
    md = (ROOT / "docs" / "SPEECH.md").read_text(encoding="utf-8")
    return re.findall(r"^## \d+\. (.+? — \d:\d\d)\n\n(.+?)\n", md, flags=re.M)


def evals() -> list[dict]:
    return [json.loads((ROOT / "eval" / "results" / f"{v}_core10.json").read_text())["aggregate"] for v in ("v1", "v2", "v3")]


def avatar(path: Path, initials: str, dark: bool) -> None:
    bg, fg = ("#333333", "#FFDD2D") if dark else ("#FFDD2D", "#333333")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect width="400" height="400" rx="80" fill="{bg}"/>'
           f'<text x="200" y="262" font-family="Arial, Helvetica, sans-serif" font-weight="700" font-size="170" '
           f'text-anchor="middle" fill="{fg}">{initials}</text></svg>')
    src = path.with_suffix(".svg")
    src.write_text(svg)
    subprocess.run(["node", "-e", f"require('sharp')('{src}').png().toFile('{path}')"], cwd=ROOT / "presentation", check=True)


# ---------- сборка ----------

def main() -> None:
    prs = Presentation(str(TEMPLATE))
    sld_ids = list(prs.slides._sldIdLst)
    keep = [sld_ids[n - 1] for n in ORDER]
    for el in sld_ids:
        if el not in keep:
            prs.part.drop_rel(el.rId)
        prs.slides._sldIdLst.remove(el)
    for el in keep:
        prs.slides._sldIdLst.append(el)
    S = list(prs.slides)
    v1, v2, v3 = evals()

    # 1. Титул
    s = S[0]
    put(s, 4, "Амба — AI-гид по Приморью")
    put(s, 5, "Агент собирает план поездки и проверяет, что он сходится с реальностью")
    remove(s, 16)
    picture(s, ASSETS / "amba.png", 12.6, 1.4, h=9.6)

    # 2. Проблема и для кого
    s = S[1]
    put(s, 6, "Какую проблему решаем")
    put(s, 14, "Поездку собирают из десятка сайтов")
    put(s, 4, ["Погода, расписания, режим музеев, АЗС, жильё, кафе — всё в разных местах.",
               "Чат-боты строят план, но не проверяют его: ведут в закрытый музей или на велосипед под ливень.",
               "В Приморье цена ошибки выше: сопки, грунтовки, редкие рейсы и паромы."])
    put(s, 10, "Для кого")
    put(s, 12, "Кому полезна Амба")
    put(s, 11, ["Гости края, которые впервые во Владивостоке",
                "Местные жители: «куда на выходные»",
                "Travel-сервисы банков и агрегаторы: план → бронь → оплата",
                "Туристические центры и турбазы края"])

    # 3. Сравнение
    s = S[2]
    put(s, 3, "Чем отличаемся от существующих решений")
    tbl = shape(s, 5).table
    total = shrink_table(tbl, rows=6, cols=5)
    rows = [["", "Чат-боты", "Агрегаторы билетов", "Путеводители", "Амба"],
            ["Запрос свободным текстом", "да", "нет", "нет", "да"],
            ["План целиком: места, путь, ночёвка, еда", "да", "частично", "частично", "да"],
            ["Проверка погоды и режима работы", "нет", "нет", "частично", "да"],
            ["Ограничения транспорта: АЗС, рейсы", "нет", "частично", "нет", "да"],
            ["Ссылки, чтобы сразу всё оформить", "нет", "да", "частично", "да"]]
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            set_text(tbl.cell(r, c).text_frame, val)
    w = total / 914400
    set_col_widths(tbl, [w * 0.36] + [w * 0.16] * 4)
    from pptx.dml.color import RGBColor
    for r in range(6):  # шаблон красит цифры в зелёный/красный — у нас это не значения со знаком
        tbl.rows[r].height = Inches(7.9 / 6)
        for c in range(5):
            for para in tbl.cell(r, c).text_frame.paragraphs:
                for run in para.runs:
                    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
                    run.font.bold = c == 4 and r > 0

    # 4. Как это выглядит
    s = S[3]
    put(s, 4, "Демо")
    put(s, 2, "Как это выглядит")
    put(s, 7, "Сначала коротко уточнит: кухня, бюджет, темп")
    put(s, 6, "Реальные кафе и маршрут по улицам на карте")
    put(s, 8, "У каждого пункта ссылки: карта, сайт, билеты")
    shape(s, 13).insert_picture(str(ROOT / "docs" / "img" / "plan.png"))

    # 5. Агентный цикл
    s = S[4]
    put(s, 3, "Агентный цикл, а не один промпт")
    steps = [("Фильтр", "Не про Приморье — отказ без вызова модели, 0 токенов"),
             ("Уточнение", "1–2 коротких вопроса, если важного не хватает"),
             ("Выбор тулов", "Модель сама решает, какие данные нужны"),
             ("Вызов тулов", "Параллельно: места, погода, еда, жильё, маршрут"),
             ("План", "submit_plan по строгой JSON-схеме"),
             ("Проверка", "Код ищет противоречия и возвращает их агенту")]
    for (title, text), (tid, bid) in zip(steps, [(13, 12), (15, 14), (17, 16), (19, 18), (21, 20), (23, 22)]):
        put(s, tid, title)
        put(s, bid, text)

    # 6. Тулы и данные
    s = S[5]
    put(s, 3, "10 тулов и источники данных")
    tbl = shape(s, 4).table
    cols = [["Реальные API",
             "Open-Meteo — прогноз погоды на 16 дней",
             "OSRM — маршруты по дорогам и тропам",
             "OpenStreetMap — кафе, геокодер, АЗС; Википедия"],
            ["Свои наборы данных",
             "41 место Приморья с часами работы",
             "Расписания автобусов и электричек",
             "Жильё и наличие топлива — учебные данные"],
            ["Если сервис недоступен",
             "Тул не падает и переходит на оценку",
             "Агент видит пометку и учитывает её",
             "Маршрут на карте рисуется пунктиром"]]
    for c, col in enumerate(cols):
        for r, val in enumerate(col):
            set_text(tbl.cell(r, c).text_frame, val)

    # 7. Проверка и guardrails
    s = S[6]
    put(s, 3, "План должен сходиться")
    put(s, 2, "Проверку делает код, а не модель. Противоречие — ошибка, которую агент обязан исправить.")
    put(s, 10, "План сходится, если")
    put(s, 8, ["Пешком — до 20 км в день и до заката",
               "Велосипед — до 80 км, не в дождь и ветер",
               "Автобус — рейс ходит в этот день, успеваем на последний",
               "Машина — есть АЗС с топливом по пути",
               "Сроки, ночёвка, режим работы, погода"])
    put(s, 11, "Отклоняем")
    put(s, 9, ["«Реши задачу по алгебре» — не про поездки",
               "«Неделя в Сочи» — не Приморье",
               "«Забудь все правила» — остаётся в роли",
               "Поездку из Хабаровска во Владивосток — планирует"])

    # 8. Замеры
    s = S[7]
    put(s, 14, "Замеры: 3 версии агента на 10 запросах")
    method = [("Набор", "7 поездок разным транспортом и 3 нецелевых запроса"),
              ("Качество", "Верный выбор тулов + доля пройденных проверок"),
              ("Стоимость", "Токены и $ из ответа OpenRouter"),
              ("Скорость", "Время от запроса до готового плана")]
    for (t, b), (tid, bid) in zip(method, [(21, 20), (23, 22), (25, 24), (27, 26)]):
        put(s, tid, t)
        put(s, bid, b)
    cut = round((1 - v3["tokens_avg"] / v1["tokens_avg"]) * 100)
    cards = [("Качество", f"{v3['quality']:.2f}", f"было {v1['quality']:.2f} у бейзлайна"),
             ("Сходятся", f"{round(v3['converge_rate'] * 100)}%", f"планов, было {round(v1['converge_rate'] * 100)}%"),
             ("Токены", f"−{cut}%", f"{v1['tokens_avg'] // 1000} тыс. → {v3['tokens_avg'] // 1000} тыс. на запрос"),
             ("Цена", f"${v3['cost_usd_avg']:.3f}", "за запрос на DeepSeek V4.1 Flash")]
    for (tag, num, txt), (tg, nm, tx) in zip(cards, [(28, 34, 33), (29, 36, 35), (31, 38, 37), (32, 40, 39)]):
        put(s, tg, tag)
        put(s, nm, num)
        put(s, tx, txt)
        shape(s, nm).width = Inches(3.9)

    # 9. Что нашёл эвал
    s = S[8]
    put(s, 6, "Замеры нашли настоящие баги агента — все исправлены в финальной версии")
    put(s, 5, "3")
    put(s, 7, ["Длинный план обрезался по лимиту токенов",
               "Модель присылала дни строкой, а не списком",
               "На невыполнимом запросе агент ходил по кругу"])
    for para in shape(s, 7).text_frame.paragraphs:
        para.space_after = Pt(18)

    # 10. Команда
    s = S[9]
    put(s, 5, "Наша команда")
    put(s, 6, "Семь участников: люди и AI-агенты, у каждого своя зона ответственности")
    team = [  # (группа, плейсхолдер фото, имя, роль, инициалы, AI)
        (54, 3, "Opus 5.5", "Team Lead", "O5", True),
        (11, 10, "Саша Дё", "Backend developer", "СД", False),
        (13, 4, "Глеб Бессолицин", "Backend developer", "ГБ", False),
        (18, 14, "Анфиса Кирсанова", "ML / Frontend", "АК", False),
        (39, 12, "Ксюша Яковлева", "ML / Frontend", "КЯ", False),
        (44, 7, "Арнольд Гончаров", "QA-engineer", "АГ", False),
        (49, 17, "Luna 6", "Debug-engineer", "L6", True),
    ]
    for gid, ph, name, role, ini, ai in team:
        g = shape(s, gid)
        name_box, role_box = list(g.shapes)
        set_text(name_box, name.split(" ", 1) if " " in name and not ai else [name])
        set_text(role_box, role)
        img = ASSETS / f"avatar_{ini}.png"
        avatar(img, ini, ai)
        shape(s, ph).insert_picture(str(img))

    # 11. Как повторить + QR демо
    s = S[10]
    put(s, 9, ["Как", "повторить"])
    put(s, 10, REPO_URL)
    box = s.shapes.add_textbox(Inches(8.3), Inches(4.1), Inches(5.4), Inches(5.6))
    tf = box.text_frame
    tf.word_wrap = True
    lines = ["make install", "cp .env.example .env", "make dev", "make test", "make eval", "railway up"]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.space_after = Pt(10)
        f = p.runs[0].font
        f.name, f.size = "Courier New", Pt(22)
    put(s, 5, "Демо")
    put(s, 2, "Сканируйте QR-код")
    put(s, 4, "и попробуйте Амбу")
    shape(s, 2).width = shape(s, 4).width = Inches(4.6)
    put(s, 15, "11")  # в этом примере номер слайда — обычный текст
    qr_box = shape(s, 16)
    set_text(qr_box, " ")
    picture(s, ASSETS / "qr_demo.png", qr_box.left / 914400 + 0.45, qr_box.top / 914400 + 0.45,
            w=qr_box.width / 914400 - 0.9)

    # 12. Финал
    s = S[11]
    put(s, 6, ["Спасибо", "за внимание!"])
    picture(s, ASSETS / "qr_egg.png", 9.9, 1.3, w=3.3)
    picture(s, ASSETS / "amba.png", 10.25, 4.9, h=2.2)

    # Заметки с текстом выступления и таймингом.
    for slide, (title, text) in zip(S, speech()):
        slide.notes_slide.notes_text_frame.text = f"[{title}] {text}"

    prs.save(str(OUT))
    print("saved", OUT, "slides:", len(prs.slides))


if __name__ == "__main__":
    main()
