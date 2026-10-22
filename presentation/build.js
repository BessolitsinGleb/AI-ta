// Сборка презентации: node build.js → Amba_Travel_AI.pptx + ../docs/SPEECH.md (текст выступления с таймингом).
// Регламент: 8 минут на рассказ. Слайдов 12, суммарно ~7:35 — запас на переходы.
// Метрики берутся из ../eval/results (реальный прогон).
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");
const QRCode = require("qrcode");

const ROOT = path.resolve(__dirname, "..");
const IMG = path.join(ROOT, "docs", "img");
const OUT = path.join(__dirname, "Amba_Travel_AI.pptx");
const DEMO_URL = "https://amba-production-3ab7.up.railway.app";
// Финальный QR — пасхалка: прямой mp4 из Internet Archive, открывается во встроенном плеере телефона, без рекламы.
const FINAL_QR_URL = "https://archive.org/download/Rick_Astley_Never_Gonna_Give_You_Up/Rick_Astley_Never_Gonna_Give_You_Up.mp4";
const REPO_URL = "github.com/BessolitsinGleb/AI-ta";

const THEME = {
  name: "Amba Primorye",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0F2D3A", lt1: "FFFFFF", dk2: "0F2D3A", lt2: "E9EFF1",
    accent1: "F0641E", accent2: "F5A15F", accent3: "2E6B62", accent4: "2F5D8A", accent5: "2E6B62", accent6: "3D5A66",
    hlink: "2F5D8A", folHlink: "6B3FA0",
  },
};
const H = THEME.colors;

function loadEval() {
  const dir = path.join(ROOT, "eval", "results");
  return ["v1", "v2", "v3"].map((v) => {
    const p = path.join(dir, `${v}_core10.json`);
    return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null;
  }).filter(Boolean);
}

async function png(file, width) {
  const buf = await sharp(file).resize({ width }).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

const SPEECH = []; // [{n, title, sec, text}]
const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

(async () => {
  const evals = loadEval();
  if (evals.length < 3) throw new Error("нет eval/results/v{1,2,3}_core10.json — сначала прогоните эвал");
  const [a1, a2, a3] = evals.map((e) => e.aggregate);
  const team = JSON.parse(fs.readFileSync(path.join(__dirname, "team.json"), "utf8"));
  const mascot = await png(path.join(ROOT, "frontend", "assets", "amba.svg"), 900);
  const qrOf = async (url) => "image/png;base64," + (await QRCode.toBuffer(url, { width: 600, margin: 1, color: { dark: "#0F2D3A", light: "#FFFFFF" } })).toString("base64");
  const qr = await qrOf(DEMO_URL);
  const qrFinal = await qrOf(FINAL_QR_URL);

  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9"; // 10 × 5.625 in
  pres.title = "Амба — AI-гид по Приморью";
  pres.author = "Команда «Амба»";
  pres.company = "Т-Банк × Сириус";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  pres.defineSlideMaster({
    title: "DARK",
    background: { color: H.dk2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.0, w: 5.6, h: 2.0, fontFace: THEME.headFontFace, fontSize: 36, bold: true, color: C.background2, align: "left", valign: "bottom", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.6, y: 3.25, w: 5.6, h: 1.2, fontFace: THEME.bodyFontFace, fontSize: 16, color: "CFE6E3", align: "left", valign: "top", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "LIGHT",
    background: { color: H.lt1 },
    margin: [0.5, 0.5, 0.5, 0.5],
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9.0, h: 0.7, fontFace: THEME.headFontFace, fontSize: 28, bold: true, color: C.text2, valign: "middle", margin: 0 }, text: "" } },
      { text: { text: "Амба · Т-Банк × Сириус", options: { x: 0.5, y: 5.25, w: 5, h: 0.25, fontSize: 9, color: "6B8590", margin: 0 } } },
    ],
    slideNumber: { x: 9.1, y: 5.22, w: 0.4, h: 0.25, fontSize: 9, color: "6B8590", align: "right" },
  });

  let currentSection = "";
  const slide = (master, sec) => {
    if (sec !== currentSection) { pres.addSection({ title: sec }); currentSection = sec; }
    return pres.addSlide({ masterName: master, sectionTitle: sec });
  };
  const speak = (s, title, sec, text) => {
    SPEECH.push({ n: SPEECH.length + 1, title, sec, text });
    const until = SPEECH.reduce((t, x) => t + x.sec, 0);
    s.addNotes(`[${fmt(sec)} · к концу слайда ${fmt(until)}] ${text}`);
  };
  const card = (s, x, y, w, h, fill = C.background2, name = "card") =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: name });
  const badge = (s, x, y, n, fill = C.accent1, d = 0.42) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill }, objectName: `num-${n}` });
    s.addText(String(n), { x, y, w: d, h: d, align: "center", valign: "middle", fontSize: 14, bold: true, color: C.background1, margin: 0, isTextBox: true });
  };
  const txt = (s, text, o) => s.addText(text, { margin: 0, isTextBox: true, valign: "top", color: C.text1, ...o });
  const addImg = async (s, file, x, y, w, maxH) => {
    const meta = await sharp(file).metadata();
    let h = (w * meta.height) / meta.width;
    if (maxH && h > maxH) { w = (w * maxH) / h; h = maxH; }
    s.addImage({ data: await png(file, 1800), x, y, w, h, objectName: path.basename(file) });
    return { w, h };
  };

  // 1. Титул — 0:20
  {
    const s = slide("DARK", "Начало");
    txt(s, "Т-Банк × Сириус · командный проект", { x: 0.6, y: 0.55, w: 5.6, h: 0.3, fontSize: 12, color: H.accent2, bold: true, charSpacing: 2 });
    s.addText("Амба — AI-гид по Приморью", { placeholder: "title" });
    s.addText("Пишете поездку обычными словами — агент собирает план и проверяет, что он сходится с реальностью", { placeholder: "body" });
    s.addImage({ data: mascot, x: 6.5, y: 0.75, w: 3.0, h: 3.25, objectName: "mascot" });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 6.6, y: 4.2, w: 2.8, h: 0.55, rectRadius: 0.12, fill: { color: C.background2 }, line: { color: H.accent1, width: 1.5 }, objectName: "speech" });
    txt(s, "Привет! Куда поедем?", { x: 6.6, y: 4.2, w: 2.8, h: 0.55, align: "center", valign: "middle", italic: true, fontSize: 13 });
    speak(s, "Титул", 20, "Здравствуйте! Мы команда «Амба». Амба — это амурский тигрёнок и наш AI-гид по Приморскому краю: вы пишете поездку обычными словами, а агент собирает план и проверяет, что он сходится с реальностью.");
  }

  // 2. Проблема и для кого — 0:50
  {
    const s = slide("LIGHT", "Задача");
    s.addText("Какую проблему решаем", { placeholder: "title" });
    [["Данные разбросаны", "Погода, расписания, режим музеев, АЗС, жильё, кафе — десяток сайтов на одну поездку"],
     ["Чат-боты ошибаются", "Ведут в закрытый музей, на велосипед под ливень, предлагают 3 дня вместо двух"],
     ["Приморье — особый случай", "Сопки, грунтовки, редкие рейсы и паромы, туманы и тайфуны с моря"]].forEach(([h, t], i) => {
      const y = 1.2 + i * 1.25;
      badge(s, 0.5, y + 0.05, i + 1);
      txt(s, h, { x: 1.1, y, w: 4.2, h: 0.4, fontSize: 16, bold: true });
      txt(s, t, { x: 1.1, y: y + 0.4, w: 4.2, h: 0.7, fontSize: 13, color: C.accent6 });
    });
    card(s, 5.7, 1.15, 3.8, 3.85, C.background2, "audience");
    txt(s, "Для кого", { x: 5.95, y: 1.3, w: 3.3, h: 0.4, fontSize: 18, bold: true, color: C.accent1 });
    s.addText([
      { text: "Гости края — впервые во Владивостоке", options: { bullet: true, breakLine: true } },
      { text: "Местные — «куда на выходные»", options: { bullet: true, breakLine: true } },
      { text: "Travel-сервисы банков и агрегаторы: план → бронь → оплата", options: { bullet: true, breakLine: true } },
      { text: "Туристические центры и турбазы края", options: { bullet: true } },
    ], { x: 5.95, y: 1.8, w: 3.35, h: 3.0, fontSize: 14, color: C.text1, valign: "top", paraSpaceAfter: 8, margin: 0 });
    speak(s, "Проблема", 50, "Чтобы спланировать даже выходные, нужно открыть десяток сайтов: погода, расписания автобусов, часы работы музеев, заправки, жильё, кафе. Обычный чат-бот быстро выдаёт план, но не проверяет его — и ведёт в закрытый музей или на велосипед под ливень. А в Приморье цена ошибки выше: сопки, грунтовки, редкие рейсы. Наши пользователи — гости края, местные жители, которые ищут, куда поехать на выходные, и travel-сервисы, например банковские, где из плана можно сразу перейти к брони и оплате.");
  }

  // 3. Сравнение — 0:35
  {
    const s = slide("LIGHT", "Задача");
    s.addText("Чем отличаемся от существующих решений", { placeholder: "title" });
    const yes = "✓", no = "—", part = "≈";
    const rows = [
      ["", "Чат-боты", "Агрегаторы билетов", "Путеводители", "Амба"],
      ["Запрос свободным текстом", yes, no, no, yes],
      ["План целиком: места, путь, ночёвка, еда", yes, part, part, yes],
      ["Проверка погоды и режима работы", no, no, part, yes],
      ["Ограничения транспорта: АЗС, рейсы", no, part, no, yes],
      ["Ссылки, чтобы сразу всё оформить", no, yes, part, yes],
    ];
    const data = rows.map((r, i) => r.map((cell, j) => {
      if (i === 0) return { text: cell, options: { bold: true, color: H.lt1, fill: { color: H.dk2 }, fontSize: 12, align: j === 0 ? "left" : "center", valign: "middle" } };
      const amba = j === 4;
      return { text: cell, options: { fontSize: j === 0 ? 13 : 16, align: j === 0 ? "left" : "center", valign: "middle", bold: amba,
        color: amba ? H.accent1 : H.dk1, fill: { color: amba ? "FFF0E7" : (i % 2 ? "FFFFFF" : "F3F6F7") } } };
    }));
    s.addTable(data, { x: 0.5, y: 1.2, w: 9.0, colW: [3.4, 1.3, 1.6, 1.4, 1.3], rowH: 0.52, border: { type: "solid", pt: 0.5, color: "D5E0E3" }, margin: 0.08 });
    txt(s, "≈ — частично. Амба сфокусирован на одном регионе, зато знает его ограничения.", { x: 0.5, y: 4.55, w: 9, h: 0.35, fontSize: 12, italic: true, color: C.accent6 });
    speak(s, "Сравнение", 35, "Чат-боты понимают свободный текст, но ничего не проверяют. Агрегаторы продают билеты, но поездку не строят. Путеводители надёжны, но статичны. Амба соединяет всё: свободный запрос, полный план, проверку по реальным данным и ссылки, чтобы сразу всё оформить.");
  }

  // 4. Демо — 0:50
  {
    const s = slide("LIGHT", "Решение");
    s.addText("Как это выглядит", { placeholder: "title" });
    await addImg(s, path.join(IMG, "plan.png"), 0.5, 1.1, 5.9, 3.9);
    const notes = [
      ["Сначала уточнит", "1–2 коротких вопроса с вариантами: кухня, бюджет, темп"],
      ["Реальные кафе", "из OpenStreetMap: кухня, часы, сайт"],
      ["Ссылки у каждого пункта", "карта, сайт, расписание и билеты, гостиницы рядом"],
      ["Маршрут по улицам", "карта по дням; вид «Бортовой журнал» — в морском стиле"],
    ];
    notes.forEach(([h, t], i) => {
      const y = 1.12 + i * 0.98;
      txt(s, h, { x: 6.7, y, w: 2.8, h: 0.32, fontSize: 14, bold: true, color: C.accent1 });
      txt(s, t, { x: 6.7, y: y + 0.32, w: 2.8, h: 0.6, fontSize: 11.5 });
    });
    speak(s, "Демо", 50, "Вот как это выглядит. Человек пишет: «на три дня на машине в Хасанский район». Если чего-то не хватает, Амба коротко уточняет, например какую кухню вы любите. Дальше видно, что агент понял из запроса, статус проверки, дни таймлайном и маршрут на карте — по улицам, а не напрямик. Обеды — реальные кафе из OpenStreetMap. У каждого пункта есть ссылки: карта, сайт, расписание и билеты, гостиницы рядом. Демо открыто по ссылке на последнем слайде.");
  }

  // 5. Как работает — 0:50
  {
    const s = slide("LIGHT", "Решение");
    s.addText("Агентный цикл, а не один промпт", { placeholder: "title" });
    const steps = [
      ["Фильтр", "не про Приморье — отказ за 0 токенов", C.accent3],
      ["Уточнение", "1–2 вопроса, если важного не хватает", C.accent4],
      ["Выбор тулов", "модель решает, какие данные нужны", C.accent1],
      ["Вызов тулов", "параллельно: места, погода, еда, жильё", C.accent1],
      ["План", "submit_plan по JSON-схеме", C.accent1],
      ["Проверка", "противоречия → агенту на исправление", C.accent5],
    ];
    steps.forEach(([h, t, col], i) => {
      const x = 0.5 + i * 1.53;
      card(s, x, 1.25, 1.4, 2.0, C.background2, `step-${i + 1}`);
      badge(s, x + 0.49, 1.37, i + 1, col);
      txt(s, h, { x: x + 0.08, y: 1.9, w: 1.24, h: 0.4, fontSize: 12.5, bold: true, align: "center", valign: "middle" });
      txt(s, t, { x: x + 0.08, y: 2.3, w: 1.24, h: 0.9, fontSize: 10, color: C.accent6, align: "center" });
    });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.55, y: 3.45, w: 4.5, h: 0.45, rectRadius: 0.22, fill: { color: "E3F0EC" }, line: { color: H.accent3, width: 1 }, objectName: "loop" });
    txt(s, "↻ шаги 3–5 повторяются, пока данных не хватит", { x: 3.55, y: 3.45, w: 4.5, h: 0.45, fontSize: 12, bold: true, color: C.accent3, align: "center", valign: "middle" });
    txt(s, "FastAPI + OpenRouter tool calling, цикл написан с нуля, без агентных фреймворков. Модель — DeepSeek V4.1 Flash. Шаги агента стримятся в интерфейс. Карту и ссылки достраивает сервер — модель на них токены не тратит.", { x: 0.5, y: 4.1, w: 9, h: 0.9, fontSize: 12.5 });
    speak(s, "Агентный цикл", 50, "Это не один промпт, а агентный цикл. Сначала фильтр: всё, что не про Приморье, отклоняется без вызова модели. Если важного не хватает, агент задаёт один-два вопроса. Дальше модель сама выбирает тулы, мы вызываем их параллельно и возвращаем данные, и так по кругу, пока данных не хватит. Готовый план проходит проверку; если есть противоречия, агент их исправляет. Цикл написан с нуля на FastAPI, модель — DeepSeek через OpenRouter.");
  }

  // 6. Данные — 0:35
  {
    const s = slide("LIGHT", "Решение");
    s.addText("10 тулов и источники данных", { placeholder: "title" });
    const rows = [
      ["get_weather", "Open-Meteo", "реальный"], ["build_route", "OSRM: машина, велосипед, пешком", "реальный"],
      ["find_food", "OpenStreetMap: кафе, кухня, сайт", "реальный"], ["geocode", "Nominatim (OSM)", "реальный"],
      ["find_fuel_stations", "OSM Overpass + наличие топлива", "реальный + мок"], ["place_info", "Википедия", "реальный"],
      ["search_places", "41 место Приморья, часы и выходные", "датасет"], ["find_lodging", "по мотивам Островка / Tvil", "мок"],
      ["public_transport", "по мотивам Яндекс Расписаний", "датасет"], ["find_events", "ярмарки, театр, кормление тигров", "датасет"],
    ];
    const hd = { bold: true, color: H.lt1, fill: { color: H.dk2 } };
    const data = [[{ text: "Тул", options: hd }, { text: "Источник", options: hd }, { text: "Тип", options: hd }]].concat(rows.map((r, i) => {
      const fill = { color: i % 2 ? "FFFFFF" : "F3F6F7" };
      return [{ text: r[0], options: { fontFace: "Courier New", fontSize: 11, color: H.dk1, fill } }, { text: r[1], options: { fontSize: 12, color: H.dk1, fill } },
        { text: r[2], options: { fontSize: 12, bold: true, color: r[2].startsWith("реальный") ? H.accent3 : H.accent6, fill } }];
    }));
    s.addTable(data, { x: 0.5, y: 1.15, w: 6.4, colW: [1.9, 3.15, 1.35], rowH: 0.33, fontSize: 12, border: { type: "solid", pt: 0.5, color: "D5E0E3" }, margin: 0.06, valign: "middle" });
    card(s, 7.2, 1.15, 2.3, 3.6, C.background2, "sources");
    txt(s, "5", { x: 7.2, y: 1.3, w: 2.3, h: 0.9, fontSize: 54, bold: true, color: C.accent1, align: "center" });
    txt(s, "реальных источников из интернета", { x: 7.35, y: 2.2, w: 2.0, h: 0.6, fontSize: 12, align: "center" });
    txt(s, "API недоступен — тул не падает, а переходит на офлайн-оценку и сообщает об этом агенту", { x: 7.35, y: 2.95, w: 2.0, h: 1.6, fontSize: 11, italic: true, color: C.accent6, align: "center" });
    speak(s, "Данные", 35, "У агента десять тулов. Реальных источников пять: погода из Open-Meteo, маршруты по дорогам и тропам из OSRM, кафе и геокодер из OpenStreetMap, заправки из Overpass и справки из Википедии. Чего в открытом доступе нет — наличие бензина, свободные номера, расписания — подставляем из своих наборов данных. Если API лежит, тул не падает, а честно переходит на оценку.");
  }

  // 7. Проверка + guardrails — 0:50
  {
    const s = slide("LIGHT", "Решение");
    s.addText("План должен сходиться, и только Приморье", { placeholder: "title" });
    [["Пешком", "≤ 20 км в день, до заката"], ["Велосипед", "≤ 80 км, не в дождь и ветер"],
     ["Автобус и поезд", "рейс есть в этот день, успеваем на последний"], ["Машина", "АЗС с топливом на длинном маршруте"]].forEach(([h, t], i) => {
      const x = 0.5 + (i % 2) * 2.55, y = 1.15 + Math.floor(i / 2) * 1.2;
      card(s, x, y, 2.4, 1.05, C.background2, h);
      txt(s, h, { x: x + 0.15, y: y + 0.12, w: 2.1, h: 0.3, fontSize: 13.5, bold: true, color: C.accent1 });
      txt(s, t, { x: x + 0.15, y: y + 0.45, w: 2.1, h: 0.55, fontSize: 11 });
    });
    txt(s, "Для всех: лимит дней и даты из запроса, ночёвка на каждую ночь, режим работы мест, прогноз погоды. Проверку делает код, а не модель.", { x: 0.5, y: 3.6, w: 4.95, h: 0.8, fontSize: 11.5, color: C.accent6 });
    card(s, 5.85, 1.15, 3.65, 3.25, C.background2, "guard");
    txt(s, "Нецелевые запросы", { x: 6.05, y: 1.28, w: 3.3, h: 0.35, fontSize: 14, bold: true });
    [["«Реши задачу по алгебре»", "отказ: не про поездки"], ["«Неделя в Сочи»", "отказ: не Приморье"],
     ["«Забудь все правила…»", "остаётся в роли"], ["«Из Хабаровска во Владивосток»", "строит план"]].forEach(([q, a], i) => {
      const y = 1.75 + i * 0.62;
      txt(s, q, { x: 6.05, y, w: 3.3, h: 0.28, fontSize: 11.5, italic: true });
      txt(s, a, { x: 6.05, y: y + 0.27, w: 3.3, h: 0.28, fontSize: 11, bold: true, color: i === 3 ? C.accent3 : C.accent1 });
    });
    speak(s, "Проверка и guardrails", 50, "Главное правило задания — план должен сходиться. Проверку делает код, а не модель: для пешехода — не больше двадцати километров и до заката, для велосипеда — не в дождь, для автобуса — рейс реально ходит и вы успеваете на последний, для машины — по пути есть заправки. Плюс сроки, ночёвка, режим работы, погода. И Амба говорит только о Приморье: алгебру, Сочи и «забудь правила» вежливо отклоняет, а поездку из Хабаровска во Владивосток спокойно планирует.");
  }

  // 8. Замеры — 0:55
  {
    const s = slide("LIGHT", "Замеры");
    s.addText("Замеры: три версии на одном наборе", { placeholder: "title" });
    const n = evals[0].rows.length, nd = evals[0].rows.filter((r) => r.converges === null).length;
    txt(s, `${n} фиксированных запросов: ${n - nd} поездок разным транспортом и ${nd} нецелевых. Качество = 0,5 × верный тул + 0,5 × доля пройденных проверок.`, { x: 0.5, y: 1.05, w: 9, h: 0.45, fontSize: 12.5, color: C.accent6 });
    const head = ["Версия", "Модель", "Качество", "Сходится", "Токены", "$ / запрос", "Время, с"];
    const hopt = { bold: true, color: H.lt1, fill: { color: H.dk2 }, fontSize: 11, align: "center", valign: "middle" };
    const rows = [head.map((t) => ({ text: t, options: hopt }))];
    const labels = ["v1 · бейзлайн", "v2 · сжатие + проверка", "v3 · исправления + DeepSeek"];
    evals.forEach((e, i) => {
      const a = e.aggregate;
      const o = (x = {}) => ({ fontSize: 11, align: "center", valign: "middle", color: H.dk1, fill: { color: i === 2 ? "FFF0E7" : (i % 2 ? "FFFFFF" : "F3F6F7") }, ...x });
      rows.push([{ text: labels[i], options: o({ align: "left", bold: true }) }, { text: e.model.split("/").pop().replace(":free", " (free)"), options: o({ fontSize: 10 }) },
        { text: a.quality.toFixed(2), options: o({ bold: true, color: i === 2 ? H.accent1 : H.dk1 }) }, { text: `${Math.round(a.converge_rate * 100)}%`, options: o() },
        { text: a.tokens_avg.toLocaleString("ru-RU"), options: o() }, { text: a.cost_usd_avg ? `$${a.cost_usd_avg.toFixed(4)}` : "$0", options: o() },
        { text: String(a.latency_p50_s).replace(".", ","), options: o() }]);
    });
    s.addTable(rows, { x: 0.5, y: 1.55, w: 9.0, colW: [2.45, 1.75, 0.95, 0.95, 0.95, 0.95, 1.0], rowH: 0.4, border: { type: "solid", pt: 0.5, color: "D5E0E3" }, margin: 0.05 });
    const chart = (x, title, values, color, fmtCode, max) => s.addChart(pres.charts.BAR, [{ name: title, labels: ["v1", "v2", "v3"], values }], {
      x, y: 3.25, w: 4.4, h: 1.95, barDir: "col", showTitle: true, title, titleFontSize: 12, titleColor: H.dk1, titleFontFace: "+mn-lt",
      chartColors: [color], showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelColor: H.dk1, dataLabelFontFace: "+mn-lt",
      dataLabelFormatCode: fmtCode, catAxisLabelColor: H.accent6, catAxisLabelFontFace: "+mn-lt", catAxisLabelFontSize: 10, valAxisHidden: true,
      valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, ...(max ? { valAxisMinVal: 0, valAxisMaxVal: max } : {}),
    });
    chart(0.5, "Токены на запрос", evals.map((e) => e.aggregate.tokens_avg), H.accent3, "# ##0");
    chart(5.1, "Качество (0–1)", evals.map((e) => e.aggregate.quality), H.accent1, "0.00", 1.15);
    speak(s, "Замеры", 55, `Замеряли три версии на одном наборе из ${n} запросов: ${n - nd} поездок разным транспортом и ${nd} нецелевых. Качество — это верно ли выбраны тулы плюс доля пройденных проверок плана. Бейзлайн — короткий промпт и сырые ответы тулов. Вторая версия — сжатие контекста, фильтр и цикл исправлений. Третья — исправления, найденные эвалом, и модель DeepSeek. Качество выросло с ${a1.quality.toFixed(2)} до ${a3.quality.toFixed(2)}, токенов стало почти втрое меньше, а запрос стоит меньше цента.`);
  }

  // 9. Выводы — 0:40
  {
    const s = slide("LIGHT", "Замеры");
    s.addText("Что дали улучшения", { placeholder: "title" });
    const cut = Math.round((1 - a3.tokens_avg / a1.tokens_avg) * 100);
    [[`−${cut}%`, "токенов на запрос: модели уходит только нужное"], [`${Math.round(a1.converge_rate * 100)} → ${Math.round(a3.converge_rate * 100)}%`, "планов проходят все проверки"],
     [`$${a3.cost_usd_avg.toFixed(3)}`, "за запрос на DeepSeek V4.1 Flash"]].forEach(([n, t], i) => {
      const x = 0.5 + i * 3.05;
      card(s, x, 1.15, 2.85, 1.75, C.background2, `stat-${i + 1}`);
      txt(s, n, { x, y: 1.25, w: 2.85, h: 0.9, fontSize: 36, bold: true, color: C.accent1, align: "center", valign: "middle" });
      txt(s, t, { x: x + 0.2, y: 2.15, w: 2.45, h: 0.7, fontSize: 12, align: "center" });
    });
    txt(s, "Эвал нашёл три бага агента — все исправлены в v3:", { x: 0.5, y: 3.15, w: 9, h: 0.35, fontSize: 14, bold: true });
    s.addText([
      { text: "длинный план не влезал в лимит токенов и обрезался", options: { bullet: true, breakLine: true } },
      { text: "модель присылала дни плана строкой вместо списка", options: { bullet: true, breakLine: true } },
      { text: "на невыполнимом запросе («170 км на велосипеде за день») агент собирал данные по кругу", options: { bullet: true } },
    ], { x: 0.5, y: 3.55, w: 9, h: 1.4, fontSize: 13, color: C.text1, valign: "top", paraSpaceAfter: 5, margin: 0 });
    speak(s, "Выводы", 40, "Что дали улучшения. Сжатие контекста срезало токены больше чем вдвое: геометрию маршрутов и почасовую погоду модели видеть не нужно. Доля планов, которые проходят все проверки, выросла с сорока трёх до ста процентов. И самое ценное: эвал нашёл три настоящих бага агента — обрезанный план, дни строкой и зацикливание на невыполнимом запросе. Все исправлены.");
  }

  // 10. Команда — 0:30
  {
    const s = slide("LIGHT", "Команда");
    s.addText("Команда", { placeholder: "title" });
    const colors = [H.accent1, H.accent3, H.accent4, "8A5A00", "6B3FA0", H.dk2, "9C2F6B"];
    const initials = (nm) => nm.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
    team.slice(0, 8).forEach((m, i) => {
      const row = i < 4 ? 0 : 1;
      const inRow = row === 0 ? Math.min(team.length, 4) : team.length - 4;
      const w = 2.1, gap = 0.2;
      const x = 0.5 + (9 - (inRow * w + (inRow - 1) * gap)) / 2 + (row === 0 ? i : i - 4) * (w + gap);
      const y = 1.15 + row * 2.0;
      card(s, x, y, w, 1.8, C.background2, `member-${i + 1}`);
      s.addShape(pres.shapes.OVAL, { x: x + 0.15, y: y + 0.18, w: 0.55, h: 0.55, fill: { color: colors[i % colors.length] }, line: { color: H.lt1, width: 1.5 }, objectName: `avatar-${i + 1}` });
      txt(s, initials(m.name), { x: x + 0.15, y: y + 0.18, w: 0.55, h: 0.55, fontSize: 13, bold: true, color: C.background1, align: "center", valign: "middle" });
      txt(s, m.name, { x: x + 0.8, y: y + 0.12, w: w - 0.9, h: 0.7, fontSize: 13, bold: true, valign: "middle" });
      txt(s, m.role, { x: x + 0.15, y: y + 0.85, w: w - 0.3, h: 0.3, fontSize: 11, bold: true, color: C.accent1 });
      txt(s, m.work, { x: x + 0.15, y: y + 1.15, w: w - 0.3, h: 0.6, fontSize: 10, color: C.accent6 });
    });
    speak(s, "Команда", 30, "Нас семеро: двое бэкенд-разработчиков отвечали за агента, тулы и деплой, два ML-инженера — за промпты, версии агента, эвал и интерфейс, QA — за тесты и guardrails, тимлид — за архитектуру, инженер по отладке — за поиск и разбор багов.");
  }

  // 11. Как повторить — 0:30
  {
    const s = slide("LIGHT", "Итоги");
    s.addText("Как повторить самостоятельно", { placeholder: "title" });
    [["make install", "окружение и зависимости"], ["cp .env.example .env", "вписать OPENROUTER_API_KEY"], ["make dev", "приложение на localhost:8000"],
     ["make test", "108 тестов: бэкенд, фронт, браузер"], ["make eval", "замеры трёх версий → таблица"], ["railway up", "деплой: Docker, одна команда"]].forEach(([c, t], i) => {
      const y = 1.12 + i * 0.6;
      badge(s, 0.5, y, i + 1, C.accent3, 0.4);
      card(s, 1.05, y - 0.03, 3.6, 0.46, C.text2, `cmd-${i + 1}`);
      txt(s, c, { x: 1.2, y: y - 0.03, w: 3.4, h: 0.46, fontFace: "Courier New", fontSize: 13, color: C.background2, valign: "middle" });
      txt(s, t, { x: 4.85, y: y - 0.03, w: 2.6, h: 0.46, fontSize: 12, valign: "middle" });
    });
    txt(s, REPO_URL, { x: 0.5, y: 4.85, w: 6.8, h: 0.3, fontSize: 12, bold: true, color: C.accent4 });
    s.addImage({ data: qr, x: 7.55, y: 1.12, w: 1.95, h: 1.95, objectName: "qr" });
    txt(s, "Живое демо", { x: 7.55, y: 3.12, w: 1.95, h: 0.3, fontSize: 12, bold: true, align: "center" });
    txt(s, DEMO_URL.replace("https://", ""), { x: 7.3, y: 3.42, w: 2.45, h: 0.5, fontSize: 9, color: C.accent6, align: "center" });
    speak(s, "Как повторить", 30, "Повторить можно за пять минут: установить зависимости, вписать ключ, запустить, прогнать тесты и замеры. Деплой — одна команда, приложение собирается в Docker. Новый тул — это файл с описанием, схемой и функцией. Код открыт на GitHub, а по QR-коду можно попробовать Амбу прямо сейчас.");
  }

  // 12. Финал — 0:10
  {
    const s = slide("DARK", "Итоги");
    s.addText("Вопросы? И в путь!", { placeholder: "title" });
    s.addText("Попробуйте Амбу по QR-коду — план поездки по Приморью за минуту", { placeholder: "body" });
    s.addImage({ data: mascot, x: 6.4, y: 0.6, w: 2.0, h: 2.17, objectName: "mascot-final" });
    s.addImage({ data: qrFinal, x: 7.65, y: 2.95, w: 1.75, h: 1.75, objectName: "qr-final" });
    txt(s, "Хорошей дороги!", { x: 6.2, y: 4.85, w: 3.2, h: 0.35, italic: true, fontSize: 13, color: H.accent2, align: "right" });
    speak(s, "Финал", 10, "Спасибо! Готовы ответить на вопросы. Хорошей дороги!");
  }

  await pres.writeFile({ fileName: OUT });
  const { applyTheme } = require(path.join(__dirname, "apply_theme.js"));
  await applyTheme(OUT, THEME);

  const total = SPEECH.reduce((t, x) => t + x.sec, 0);
  let acc = 0;
  const md = [`# Текст выступления (${fmt(total)} из 8:00)`, "",
    "Темп спокойный — около 85 слов в минуту, с паузами на показ. Запас ~25 секунд на переходы. Вопросы из зала — отдельные 3 минуты.", "",
    "| # | Слайд | Время | Конец слайда |", "|---|---|---|---|",
    ...SPEECH.map((x) => { acc += x.sec; return `| ${x.n} | ${x.title} | ${fmt(x.sec)} | ${fmt(acc)} |`; }), "",
    ...SPEECH.map((x) => `## ${x.n}. ${x.title} — ${fmt(x.sec)}\n\n${x.text}\n`)].join("\n");
  fs.writeFileSync(path.join(ROOT, "docs", "SPEECH.md"), md);
  console.log("saved", OUT, `слайдов: ${SPEECH.length}, хронометраж ${fmt(total)}`);
  SPEECH.forEach((x) => console.log(`  ${x.n}. ${x.title}: ${fmt(x.sec)}, слов ${x.text.split(/\s+/).length} (${Math.round(x.text.split(/\s+/).length / x.sec * 60)} сл/мин)`));
})();
