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
SITE_URL = "bessolitsingleb.github.io/AI-ta/site"

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
    put(s, 14, "Данные разбросаны")
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
    put(s, 3, "Чем Амба отличается от аналогов")
    tbl = shape(s, 5).table
    total = shrink_table(tbl, rows=6, cols=5)
    rows = [["", "Чат-боты", "Агрегаторы", "Путеводители", "Амба"],
            ["Запрос свободным текстом", "да", "нет", "нет", "да"],
            ["План целиком: места, путь, ночлег, еда", "да", "частично", "частично", "да"],
            ["Проверка погоды и режима работы", "нет", "нет", "частично", "да"],
            ["Ограничения транспорта: АЗС, рейсы", "нет", "частично", "нет", "да"],
            ["Ссылки, чтобы сразу всё оформить", "нет", "да", "частично", "да"]]
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            set_text(tbl.cell(r, c).text_frame, val)
    w = total / 914400
    set_col_widths(tbl, [w * 0.37, w * 0.13, w * 0.16, w * 0.19, w * 0.15])
    from pptx.dml.color import RGBColor
    # Палитра «положительные / отрицательные значения» из шаблона: да — зелёный, частично — жёлтый, нет — розовый.
    tone = {"да": RGBColor(0xDA, 0xEC, 0xBD), "частично": RGBColor(0xFF, 0xEE, 0x96), "нет": RGBColor(0xFF, 0xE1, 0xD5)}
    for r in range(6):
        tbl.rows[r].height = Inches(7.9 / 6)
        for c in range(5):
            cell = tbl.cell(r, c)
            if r > 0 and c > 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = tone[rows[r][c]]
                for para in cell.text_frame.paragraphs:
                    para.alignment = 2  # по центру: цветные ячейки читаются как значки
            if r == 0 and c == 4:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(0xFF, 0xDD, 0x2D)
            for para in cell.text_frame.paragraphs:
                if c > 0:
                    para.alignment = 2
                for run in para.runs:
                    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
                    run.font.bold = (c == 4) or r == 0

    # 4. Как это выглядит
    s = S[3]
    put(s, 4, "Приложение")
    put(s, 2, "Как это выглядит")
    put(s, 7, "Сначала коротко уточнит: кухня, бюджет, темп")
    put(s, 6, "Реальные кафе, ссылки и маршрут по улицам")
    put(s, 8, "План дорабатывается в чате: «подешевле», «убери музей»")
    shape(s, 13).insert_picture(str(ROOT / "docs" / "img" / "plan.png"))

    # 5. Агентный цикл
    s = S[4]
    put(s, 3, "Агентный цикл, а не один промпт")
    steps = [("Фильтр", "Не про Приморье — отказ без вызова модели, 0 токенов"),
             ("Уточнение", "1–2 вопроса до плана, правки — в чате после"),
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
            ["Надёжность",
             "Сервис недоступен — тул переходит на оценку",
             "Redis: лимиты против спама и история диалогов",
             "Нет Redis — работаем на памяти, не падаем"]]
    from pptx.dml.color import RGBColor
    heads = [RGBColor(0xFF, 0xDD, 0x2D), RGBColor(0xA2, 0xC6, 0xF9), RGBColor(0xB5, 0xB1, 0xEF)]  # основной жёлтый + доп. палитра
    tints = [RGBColor(0xFF, 0xF4, 0xBF), RGBColor(0xE4, 0xEE, 0xFD), RGBColor(0xEC, 0xEA, 0xFC)]
    for c, col in enumerate(cols):
        for r, val in enumerate(col):
            cell = tbl.cell(r, c)
            set_text(cell.text_frame, val)
            cell.fill.solid()
            cell.fill.fore_color.rgb = heads[c] if r == 0 else tints[c]
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
                    run.font.bold = r == 0

    # 7. Проверка и guardrails
    s = S[6]
    put(s, 3, "План должен сходиться")
    put(s, 2, "Проверку делает код, а не модель. Противоречие — ошибка, которую агент обязан исправить. От спама — лимиты запросов в Redis.")
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
    put(s, 14, "Замеры: 3 версии агента")
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
        shape(s, tg).width = Inches(2.6)  # ярлык «Качество»/«Сходятся» не должен переноситься

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
    for sid, w in ((5, 14.0), (6, 17.0)):  # шире, чтобы в любом шрифте оставались в одну строку
        box = shape(s, sid)
        box.left, box.width = Inches((21.65 - w) / 2), Inches(w)
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
        for box, size in ((name_box, 26), (role_box, 16)):  # с запасом под любой шрифт: длинные фамилии и роли
            for para in box.text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(size)
        img = ASSETS / f"avatar_{ini}.png"
        avatar(img, ini, ai)
        shape(s, ph).insert_picture(str(img))

    # 11. Сайт команды + приложение: две одинаковые QR-плашки
    s = S[10]
    put(s, 9, ["Сайт", "команды"])
    for para in shape(s, 9).text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(56)  # было 72: с запасом под широкие шрифты
    host, path = SITE_URL.split("/", 1)
    put(s, 10, [host, "/" + path])  # перенос по слэшу, а не посреди «github.io»
    for para in shape(s, 10).text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(28)
    shape(s, 10).top, shape(s, 10).height = Inches(4.0), Inches(1.1)
    put(s, 5, "Приложение")
    put(s, 2, "Сканируйте QR-код")
    put(s, 4, "и откройте Амбу")
    shape(s, 2).width = shape(s, 4).width = shape(s, 5).width = Inches(4.6)
    put(s, 15, "11")  # в этом примере номер слайда — обычный текст
    plate = shape(s, 16)
    set_text(plate, " ")
    twin = copy.deepcopy(plate._element)  # такая же фирменная плашка под QR, но в белой карточке
    twin_id = max(int(e.get("id")) for e in s.shapes._spTree.iter() if e.tag.endswith("}cNvPr")) + 1
    twin.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr").set("id", str(twin_id))
    twin.find(f".//{A}off").set("x", str(int(Inches(8.3))))
    plate._element.addnext(twin)
    twin_shape = shape(s, twin_id)
    twin_shape.fill.solid()
    from pptx.dml.color import RGBColor
    twin_shape.fill.fore_color.rgb = RGBColor(0xEF, 0xF0, 0xF1)
    for qr_png, left in ((ASSETS / "qr_site.png", 8.3), (ASSETS / "qr_demo.png", plate.left / 914400)):
        picture(s, qr_png, left + 0.45, plate.top / 914400 + 0.45, w=plate.width / 914400 - 0.9)

    # 12. Финал
    s = S[11]
    put(s, 6, ["Спасибо", "за внимание!"])
    thanks = shape(s, 6)
    thanks.top, thanks.height = Inches(6.6), Inches(3.6)
    for para in thanks.text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(92)  # было 115: в широких шрифтах «внимание!» обрезалось
    picture(s, ASSETS / "qr_egg.png", 9.9, 1.3, w=3.3)
    picture(s, ASSETS / "amba.png", 10.25, 4.9, h=2.2)

    # Заметки с текстом выступления и таймингом.
    for slide, (title, text) in zip(S, speech()):
        slide.notes_slide.notes_text_frame.text = f"[{title}] {text}"

    prs.save(str(OUT))
    print("saved", OUT, "slides:", len(prs.slides))
    export_pdf(OUT)


PDF_FONTS = {b"T-Sans Medium": b"PT Sans Caption", b"TINKOFFSANS-MEDIUM": b"PT Sans Caption", b"T-Sans": b"PT Sans", b"Tinkoff Sans": b"PT Sans"}


def export_pdf(pptx: Path) -> Path:
    """PDF с зашитым шрифтом: фирменный T-Sans не у всех установлен, в PDF подставляем PT Sans — он есть в macOS и открыт (OFL)."""
    import shutil
    import tempfile
    import zipfile

    work = Path(tempfile.mkdtemp())
    tmp = work / pptx.name
    with zipfile.ZipFile(pptx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".xml"):
                for old, new in PDF_FONTS.items():
                    data = data.replace(b'typeface="' + old + b'"', b'typeface="' + new + b'"')
            zout.writestr(item, data)
    profile = work / "lo"
    (profile / "user" / "fonts").mkdir(parents=True)
    pt_sans = Path("/System/Library/Fonts/Supplemental/PTSans.ttc")
    if pt_sans.exists():
        shutil.copy(pt_sans, profile / "user" / "fonts")  # LibreOffice видит только свои шрифты и шрифты профиля
    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    subprocess.run([soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf", "--outdir", str(work), str(tmp)],
                   check=True, capture_output=True, timeout=600)
    out = pptx.with_suffix(".pdf")
    shutil.copy(work / pptx.with_suffix(".pdf").name, out)
    print("saved", out)
    return out


if __name__ == "__main__":
    main()
