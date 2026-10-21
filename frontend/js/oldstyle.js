// Стилизация под старорусскую рукопись: дореформенная орфография, кириллическая цифирь, даты «отъ сотворенія міра».
// Чистые функции без DOM — покрыты тестами (frontend/tests).

const CONSONANTS = "бвгджзклмнпрстфхцчшщ";
const VOWELS = "аеёиоуыэюяй";
const TITLO = "҃";

// Корни с ятем (ѣ). Ищем в начале слова, регистр сохраняем.
const YAT_ROOTS = [
  ["мест", "мѣст"], ["лес", "лѣс"], ["рек", "рѣк"], ["обед", "обѣд"], ["ветр", "вѣтр"], ["ветер", "вѣтер"],
  ["свет", "свѣт"], ["север", "сѣвер"], ["след", "слѣд"], ["хлеб", "хлѣб"], ["бел", "бѣл"], ["цел", "цѣл"],
  ["снег", "снѣг"], ["звер", "звѣр"], ["дел", "дѣл"], ["где", "гдѣ"], ["здесь", "здѣсь"], ["нет", "нѣт"],
  ["после", "послѣ"], ["лет", "лѣт"], ["путешеств", "путешеств"], ["смотре", "смотрѣ"], ["увиде", "увидѣ"],
  ["успе", "успѣ"], ["тепл", "тепл"], ["вер", "вѣр"], ["пешк", "пѣшк"], ["пеш", "пѣш"], ["сед", "сѣд"],
];
const YAT_STOP = new Set(["белка", "делать", "дела"]); // слова-исключения, где «е» осталось бы
const KEEP_OGO = new Set(["того", "его", "него", "моего", "твоего", "своего", "всего", "ничего", "чего", "кого", "много", "строго", "дорого", "немного", "отого"]);

function matchCase(src, repl) {
  if (src === src.toUpperCase() && src.length > 1) return repl.toUpperCase();
  if (src[0] === src[0].toUpperCase()) return repl[0].toUpperCase() + repl.slice(1);
  return repl;
}

export function oldWord(word) {
  if (!/^[А-Яа-яЁё-]+$/.test(word)) return word;
  if (word.includes("-")) return word.split("-").map(oldWord).join("-");
  let w = word;
  const lower = w.toLowerCase();

  // ѣ в известных корнях.
  if (!YAT_STOP.has(lower)) {
    for (const [root, yat] of YAT_ROOTS) {
      if (lower.startsWith(root) && root !== yat) {
        w = matchCase(w.slice(0, root.length), yat) + w.slice(root.length);
        break;
      }
    }
  }
  // -ого/-его в прилагательных → -аго/-яго (новаго, синяго).
  const l2 = w.toLowerCase();
  if (l2.length > 5 && !KEEP_OGO.has(l2)) {
    if (l2.endsWith("ого")) w = w.slice(0, -3) + matchCase(w.slice(-3), "аго");
    else if (l2.endsWith("его")) w = w.slice(0, -3) + matchCase(w.slice(-3), "яго");
  }
  // і перед гласной (Россія, станція), но не в начале слова.
  w = w.replace(/(?<=[А-Яа-яЁё])и(?=[аеёиоуыэюяй])/g, "і").replace(/(?<=[А-Яа-яЁё])И(?=[АЕЁИОУЫЭЮЯЙ])/g, "І");
  // ъ после конечной согласной.
  const last = w[w.length - 1];
  if (w.length > 1 && CONSONANTS.includes(last.toLowerCase())) {
    w += last === last.toUpperCase() && w === w.toUpperCase() ? "Ъ" : "ъ";
  }
  return w;
}

// Сокращения и единицы, к которым ъ не приписывается.
const ABBR = new Set(["мм", "км", "м", "с", "ч", "мин", "руб", "г", "гг", "дн", "тыс", "ул", "им", "пр", "т", "д", "см", "кг", "млн", "пос", "р", "о", "ж", "жд", "вс", "сб", "пн", "вт", "ср", "чт", "пт", "азс", "мрот"]);

export function toOldOrthography(text) {
  if (!text) return "";
  const s = String(text);
  return s.replace(/[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*/g, (m, offset) => {
    const next = s[offset + m.length] || "";
    if (ABBR.has(m.toLowerCase()) || (next === "." && m.length <= 3) || next === "/" || (m === m.toUpperCase() && m.length > 1 && m.length <= 5)) return m;
    return oldWord(m);
  });
}

const UNITS = ["", "а", "в", "г", "д", "є", "ѕ", "з", "и", "ѳ"];
const TENS = ["", "і", "к", "л", "м", "н", "ѯ", "ѻ", "п", "ч"];
const HUNDREDS = ["", "р", "с", "т", "ѵ", "ф", "х", "ѱ", "ѿ", "ц"];

// Кириллическая цифирь с титлом: 1 → а҃, 21 → к҃а, 7535 → ҂зфл҃є.
// html: true — титло рисуется CSS-ом (у многих шрифтов нет комбинируемого U+0483).
export function cyrillicNumeral(n, { html = false } = {}) {
  if (html) {
    const plain = cyrillicNumeral(n).replace(TITLO, "");
    if (plain === String(Math.floor(Number(n)))) return plain;
    return `<span class="cyr-num" title="${Math.floor(Number(n))}">${plain}</span>`;
  }
  n = Math.floor(Number(n));
  if (!Number.isFinite(n) || n <= 0 || n > 999999) return String(n);
  const thousands = Math.floor(n / 1000);
  let rest = n % 1000;
  let body = "";
  body += HUNDREDS[Math.floor(rest / 100)];
  rest %= 100;
  if (rest > 10 && rest < 20) body += UNITS[rest - 10] + "і"; // 11–19 пишутся «единицы + і»
  else body += TENS[Math.floor(rest / 10)] + UNITS[rest % 10];
  let prefix = "";
  if (thousands) {
    const th = cyrillicNumeral(thousands).replace(TITLO, "");
    prefix = [...th].map((ch) => "҂" + ch).join("");
  }
  const letters = [...body];
  if (letters.length === 0) return prefix;
  const pos = letters.length >= 2 ? letters.length - 1 : 1;
  letters.splice(pos, 0, TITLO);
  return prefix + letters.join("");
}

export const MONTHS_GEN = ["января", "февраля", "марта", "апрѣля", "мая", "іюня", "іюля", "августа", "сентября", "октября", "ноября", "декабря"];
export const WEEKDAYS_OLD = ["недѣля", "понедѣльникъ", "вторникъ", "среда", "четвергъ", "пятница", "суббота"];
export const ORDINALS = ["первый", "второй", "третій", "четвертый", "пятый", "шестой", "седьмой"];

// Год от сотворения мира (византийская эра; новый год — 1 сентября).
export function yearFromCreation(date) {
  const d = date instanceof Date ? date : new Date(date);
  return d.getFullYear() + 5508 + (d.getMonth() >= 8 ? 1 : 0);
}

export function oldDate(iso, { numerals = true, html = false } = {}) {
  const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return html ? "" : String(iso || "");
  const day = numerals ? cyrillicNumeral(d.getDate(), { html }) : String(d.getDate());
  return `${day} ${MONTHS_GEN[d.getMonth()]}, ${WEEKDAYS_OLD[d.getDay()]}`;
}

export function colophon(date = new Date(), { html = false } = {}) {
  const d = date instanceof Date ? date : new Date(date);
  return `Писано тигрёнкомъ Амбою лѣта ${cyrillicNumeral(yearFromCreation(d), { html })}, ` +
    `мѣсяца ${MONTHS_GEN[d.getMonth()]} въ ${cyrillicNumeral(d.getDate(), { html })} день`;
}

export function oldTime(hhmm) {
  const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm || ""));
  if (!m) return "";
  const h = Number(m[1]);
  const part = h < 5 ? "ночи" : h < 12 ? "утра" : h < 17 ? "пополудни" : "вечера";
  return `${m[1].padStart(2, "0")}:${m[2]} ${part}`;
}
