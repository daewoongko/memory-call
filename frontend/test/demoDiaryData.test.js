import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";

import { DEMO_DIARIES, DEMO_DIARY_BY_DATE, demoDiaryMemories } from "../src/demoDiaryData.js";

test("7·8·9월의 모든 날짜에 서로 다른 그림일기가 준비된다", () => {
  assert.equal(DEMO_DIARIES.length, 92);
  assert.equal(DEMO_DIARY_BY_DATE.size, 92);
  assert.equal(DEMO_DIARIES[0].date, "2026-07-01");
  assert.equal(DEMO_DIARIES.at(-1).date, "2026-09-30");

  assert.equal(new Set(DEMO_DIARIES.map((diary) => diary.date)).size, 92);
  assert.equal(new Set(DEMO_DIARIES.map((diary) => diary.image)).size, 92);
  assert.equal(new Set(DEMO_DIARIES.map((diary) => diary.title)).size, 92);
  assert.equal(new Set(DEMO_DIARIES.map((diary) => diary.writing)).size, 92);

  for (const diary of DEMO_DIARIES) {
    assert.ok(diary.title.trim());
    assert.ok(diary.writing.trim());
    assert.ok(diary.insight.trim());
    assert.ok(existsSync(new URL(`../public${diary.image}`, import.meta.url)), `${diary.date} image is missing`);
  }
});

test("날짜별 그림일기 92개가 함께 보는 추억의 서로 다른 카드로 이어진다", () => {
  const memories = demoDiaryMemories();

  assert.equal(memories.length, 92);
  assert.equal(new Set(memories.map((memory) => memory.memory_id)).size, 92);
  assert.equal(new Set(memories.map((memory) => memory.photo_url)).size, 92);
  assert.ok(memories.every((memory) => memory.status === "verified"));
  assert.ok(memories.every((memory) => memory.conversation_allowed));
});

test("위험 확인 예시는 날짜별 일기 안에 포함된다", () => {
  const risky = DEMO_DIARIES.filter((diary) => diary.risk);

  assert.ok(risky.length >= 6);
  assert.ok(risky.every((diary) => diary.risk.evidence.trim() && diary.risk.action.trim()));
});
