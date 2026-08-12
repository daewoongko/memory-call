import test from "node:test";
import assert from "node:assert/strict";
import {
  CALL_STYLE_DIMENSIONS,
  CALL_STYLE_TOTAL_QUESTIONS,
  calculateCallStyle,
  callStylePersonaPatch,
  getDefaultCallStyle,
} from "../src/callStyle.js";

function answersFor(side) {
  return Object.fromEntries(CALL_STYLE_DIMENSIONS.flatMap((dimension) =>
    dimension.questions.map(([id]) => [id, side === "left" ? dimension.left : dimension.right])
  ));
}

test("the call-style survey has seven questions on each of four dimensions", () => {
  assert.equal(CALL_STYLE_DIMENSIONS.length, 4);
  assert.equal(CALL_STYLE_TOTAL_QUESTIONS, 28);
  assert.deepEqual(CALL_STYLE_DIMENSIONS.map((item) => item.questions.length), [7, 7, 7, 7]);
});

test("all left and all right answers map to the expected endpoint types", () => {
  assert.equal(calculateCallStyle(answersFor("left")).code, "CEML");
  assert.equal(calculateCallStyle(answersFor("right")).code, "BPOG");
});

test("incomplete answers never produce a type", () => {
  assert.equal(calculateCallStyle({ tone_1: "C" }), null);
});

test("the skip action produces the conservative CPOG default with complete evidence", () => {
  const { answers, result } = getDefaultCallStyle();
  assert.equal(result.code, "CPOG");
  assert.equal(Object.keys(answers).length, 28);
  assert.deepEqual(
    CALL_STYLE_DIMENSIONS.map((dimension) => result.scores[dimension.id].selected),
    ["C", "P", "O", "G"],
  );
});

test("persona patch stores evidence and keeps a safety override", () => {
  const answers = answersFor("left");
  const result = calculateCallStyle(answers);
  const patch = callStylePersonaPatch(result, answers);
  assert.equal(patch.call_style_code, "CEML");
  assert.equal(Object.keys(patch.call_style_answers).length, 28);
  assert.match(patch.tone, /안전 규칙을 우선/);
});
