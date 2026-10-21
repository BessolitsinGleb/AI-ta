import assert from "node:assert/strict";
import { test } from "node:test";
import { colophon, cyrillicNumeral, oldDate, oldTime, oldWord, toOldOrthography, yearFromCreation } from "../js/oldstyle.js";

test("ъ после конечной согласной, но не после гласной и й", () => {
  assert.equal(oldWord("маршрут"), "маршрутъ");
  assert.equal(oldWord("Владивосток"), "Владивостокъ");
  assert.equal(oldWord("море"), "море");
  assert.equal(oldWord("май"), "май");
});

test("і перед гласной, ѣ в корнях, -аго в прилагательных", () => {
  assert.equal(oldWord("станция"), "станція");
  assert.equal(oldWord("место"), "мѣсто");
  assert.equal(oldWord("Нового"), "Новаго");
  assert.equal(oldWord("синего"), "синяго");
  assert.equal(oldWord("его"), "его");
});

test("сокращения, единицы и аббревиатуры не трогаем", () => {
  assert.equal(toOldOrthography("2 дн. 10 км, 5 м/с, АЗС и ДВФУ"), "2 дн. 10 км, 5 м/с, АЗС и ДВФУ");
  assert.equal(toOldOrthography("Open-Meteo 12:00"), "Open-Meteo 12:00");
});

test("регистр сохраняется", () => {
  assert.equal(oldWord("Лес"), "Лѣсъ");
  assert.equal(toOldOrthography("Мост через пролив"), "Мостъ черезъ проливъ");
});

test("кириллическая цифирь", () => {
  assert.equal(cyrillicNumeral(1), "а҃");
  assert.equal(cyrillicNumeral(11), "а҃і");
  assert.equal(cyrillicNumeral(21), "к҃а");
  assert.equal(cyrillicNumeral(100), "р҃");
  assert.equal(cyrillicNumeral(7535), "҂зфл҃є");
  assert.equal(cyrillicNumeral(0), "0");
  assert.match(cyrillicNumeral(24, { html: true }), /<span class="cyr-num" title="24">кд<\/span>/);
});

test("год от сотворения мира и дата", () => {
  assert.equal(yearFromCreation(new Date("2026-08-31T12:00:00")), 7534);
  assert.equal(yearFromCreation(new Date("2026-10-21T12:00:00")), 7535);
  assert.equal(oldDate("2026-10-24"), "к҃д октября, суббота");
  assert.match(colophon(new Date("2026-10-21T12:00:00")), /лѣта ҂зфл҃є/);
  assert.equal(oldTime("09:05"), "09:05 утра");
  assert.equal(oldTime("19:30"), "19:30 вечера");
});
