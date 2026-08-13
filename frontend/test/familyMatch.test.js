import test from "node:test";
import assert from "node:assert/strict";
import { familyMatchPrompt, matchFamily, readyFamilyHint } from "../src/familyMatch.js";

const personas = [
  { persona_id: "minjun", display_name: "민준", relationship: "손자", ready: true },
  { persona_id: "yujin", display_name: "유진", relationship: "손녀", ready: true },
  { persona_id: "father", display_name: "정훈", relationship: "아버지", ready: true },
  { persona_id: "waiting", display_name: "미영", relationship: "딸", ready: false },
];

test("가족 이름을 정확히 찾는다", () => {
  assert.equal(matchFamily("민준", personas).persona.persona_id, "minjun");
});

test("이름 뒤 조사를 제거해 찾는다", () => {
  assert.equal(matchFamily("민준이한테 전화해줘", personas).persona.persona_id, "minjun");
});

test("관계어를 정확히 찾는다", () => {
  assert.equal(matchFamily("손자에게 전화해줘", personas).persona.persona_id, "minjun");
});

test("중의적인 관계어는 후보를 모두 돌려준다", () => {
  const result = matchFamily("손주에게 전화해줘", personas);
  assert.equal(result.status, "many");
  assert.deepEqual(result.candidates.map((item) => item.persona_id), ["minjun", "yujin"]);
  assert.match(familyMatchPrompt(result), /민준.*유진/);
});

test("부분 문자열은 가족으로 오인하지 않는다", () => {
  assert.equal(matchFamily("할아버지", personas).status, "none");
});

test("등록 대기 가족은 선택하지 않는다", () => {
  assert.equal(matchFamily("미영에게 전화", personas).status, "none");
});

test("빈 목록과 무관한 발화는 매칭하지 않는다", () => {
  assert.equal(matchFamily("오늘 날씨", []).status, "none");
  assert.equal(matchFamily("오늘 날씨", personas).status, "none");
});

test("힌트는 실제 통화 가능한 가족 이름으로 만든다", () => {
  const hint = readyFamilyHint(personas);
  assert.match(hint, /민준/);
  assert.doesNotMatch(hint, /미영/);
});
