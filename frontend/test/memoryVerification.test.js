import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const clothesline = readFileSync(new URL("../src/screens/FamilyMemoryClothesline.jsx", import.meta.url), "utf8");
const child = readFileSync(new URL("../src/screens/ChildScreen.jsx", import.meta.url), "utf8");

test("함께 보는 추억에는 통화 사용이 허용된 verified 기억만 건다", () => {
  assert.match(clothesline, /memory\.conversation_allowed && memory\.status === "verified"/);
  assert.doesNotMatch(clothesline, /\["verified", "partial"\]\.includes\(memory\.status\)/);
  assert.match(child, /memory\.status === "verified" && memory\.conversation_allowed/);
});

test("partial과 unverified 기억은 확인 대기에서 검토 후에만 줄로 이동한다", () => {
  assert.match(clothesline, /\["partial", "unverified"\]\.includes\(memory\.status\)/);
  assert.match(clothesline, /beginMemoryReview/);
  assert.match(clothesline, /status: "verified", conversation_allowed: true/);
  assert.match(clothesline, /내용 확인/);
});
