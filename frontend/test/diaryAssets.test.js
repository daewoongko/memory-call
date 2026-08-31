import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const payload = JSON.parse(readFileSync(new URL("../../data/gildong_diaries_2026.json", import.meta.url), "utf8"));
const diaries = payload.diaries;

test("최종 시연일은 8월 31일이며 할아버지와 손자의 공놀이 기억을 사용한다", () => {
  assert.equal(payload.demo_date, "2026-08-31");
  const demo = diaries.find((diary) => diary.date === payload.demo_date);
  assert.equal(demo.title, "대웅이와 강가 공놀이");
  assert.match(demo.writing, /할아버지.*손자.*빨간 공/);
  assert.match(demo.insight, /손자 대웅이/);
  assert.equal(demo.memory_id, "mem_016");
});

test("8·9·10월 92일의 근거 연결 규격과 승인 그림 자산이 모두 준비된다", () => {
  assert.equal(diaries.length, 92);
  assert.equal(diaries[0].date, "2026-08-01");
  assert.equal(diaries.at(-1).date, "2026-10-31");
  assert.equal(new Set(diaries.map((diary) => diary.date)).size, 92);
  assert.equal(new Set(diaries.map((diary) => diary.image)).size, 92);

  for (const diary of diaries) {
    assert.ok(diary.title.trim());
    assert.ok(diary.writing.trim());
    assert.ok(diary.insight.trim());
    assert.ok(diary.memory_id.startsWith("mem_"));
    assert.ok(diary.storyline.trim());
    assert.ok(Number.isInteger(diary.chapter) && diary.chapter > 0);
    assert.ok(existsSync(new URL(`../public${diary.image}`, import.meta.url)), `${diary.date} image is missing`);
  }
});

test("각 이야기의 장 번호와 이전 일기 연결이 날짜 순서로 이어진다", () => {
  const latest = new Map();
  for (const diary of diaries) {
    const previous = latest.get(diary.storyline);
    assert.equal(diary.chapter, previous ? previous.chapter + 1 : 1);
    assert.equal(diary.previous_diary_date, previous?.date || null);
    latest.set(diary.storyline, diary);
  }
});

test("화면은 일기 API를 사용하고 프론트 하드코딩 모듈을 두지 않는다", () => {
  const child = readFileSync(new URL("../src/screens/ChildScreen.jsx", import.meta.url), "utf8");
  const clothesline = readFileSync(new URL("../src/screens/FamilyMemoryClothesline.jsx", import.meta.url), "utf8");
  assert.match(child, /latest\?\.diary/);
  assert.match(clothesline, /api\.getDiaries\(elderId\)/);
  assert.ok(!existsSync(new URL("../src/demoDiaryData.js", import.meta.url)));
});
