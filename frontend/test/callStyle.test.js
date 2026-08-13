import test from "node:test";
import assert from "node:assert/strict";
import {
  CALL_STYLE_DIMENSIONS,
  CALL_STYLE_SCENES,
  CALL_STYLE_TYPES,
  calculateCallStyle,
  callStylePersonaPatch,
  getDefaultCallStyle,
} from "../src/callStyle.js";

function allAnswerCombinations() {
  let combinations = [{}];
  for (const scene of CALL_STYLE_SCENES) {
    combinations = combinations.flatMap((answers) => scene.choices.map((choice) => ({
      ...answers,
      [scene.id]: choice.id,
    })));
  }
  return combinations;
}

test("the first-style matcher has six scenes and three safe choices each", () => {
  assert.equal(CALL_STYLE_SCENES.length, 6);
  assert.ok(CALL_STYLE_SCENES.every((scene) => scene.choices.length === 3));
  assert.ok(CALL_STYLE_SCENES.flatMap((scene) => scene.choices).every((choice) => /^[abc]$/.test(choice.id)));
});

test("each axis receives exactly five balanced votes", () => {
  for (const dimension of CALL_STYLE_DIMENSIONS) {
    const choicesWithAxis = CALL_STYLE_SCENES.flatMap((scene) => scene.choices)
      .filter((choice) => choice.axes[dimension.id]);
    assert.equal(CALL_STYLE_SCENES.filter((scene) => scene.choices.every((choice) => choice.axes[dimension.id])).length, 5);
    assert.ok(choicesWithAxis.some((choice) => choice.axes[dimension.id] === dimension.left));
    assert.ok(choicesWithAxis.some((choice) => choice.axes[dimension.id] === dimension.right));
  }
});

test("all 729 response combinations reach all 16 types without excessive skew", () => {
  const frequencies = {};
  for (const answers of allAnswerCombinations()) {
    const result = calculateCallStyle(answers);
    assert.ok(result);
    frequencies[result.code] = (frequencies[result.code] || 0) + 1;
  }
  assert.deepEqual(Object.keys(frequencies).sort(), Object.keys(CALL_STYLE_TYPES).sort());
  const shares = Object.values(frequencies).map((count) => count / 729);
  assert.ok(Math.max(...shares) <= 0.12);
  assert.ok(Math.min(...shares) >= 0.02);
});

test("every completed answer has a three-level confidence on every axis", () => {
  for (const answers of allAnswerCombinations()) {
    const result = calculateCallStyle(answers);
    for (const dimension of CALL_STYLE_DIMENSIONS) {
      const score = result.scores[dimension.id];
      assert.equal(score.left_count + score.right_count, 5);
      assert.ok(["strong", "medium", "weak"].includes(score.confidence));
      assert.notEqual(score.left_count, score.right_count);
    }
  }
});

test("type keys, names and API-bound values remain valid", () => {
  assert.equal(Object.keys(CALL_STYLE_TYPES).length, 16);
  assert.equal(new Set(Object.values(CALL_STYLE_TYPES).map(([name]) => name)).size, 16);
  for (const [code, [name]] of Object.entries(CALL_STYLE_TYPES)) {
    assert.match(code, /^[CB][EP][MO][LG]$/);
    assert.ok(name.length <= 40);
  }
});

test("the default path explicitly produces the conservative CPOG start", () => {
  const { answers, result } = getDefaultCallStyle();
  assert.equal(result.code, "CPOG");
  assert.equal(Object.keys(answers).length, 6);
});

test("incomplete and legacy 28-question answers do not produce a new type", () => {
  assert.equal(calculateCallStyle({ scene_1: "a" }), null);
  assert.equal(calculateCallStyle({ tone_1: "C", response_1: "E" }), null);
});

test("persona patch keeps four chosen reusable phrases and a safety override", () => {
  const answers = Object.fromEntries(CALL_STYLE_SCENES.map((scene) => [scene.id, "a"]));
  const result = calculateCallStyle(answers);
  const patch = callStylePersonaPatch(result, answers);
  assert.equal(Object.keys(patch.call_style_answers).length, 6);
  assert.equal(patch.frequent_phrases.length, 4);
  assert.deepEqual(
    patch.frequent_phrases,
    CALL_STYLE_SCENES.filter((scene) => scene.choices[0].phrase).map((scene) => scene.choices[0].phrase),
  );
  assert.match(patch.tone, /안전 규칙을 우선/);
  assert.ok(Object.values(patch.call_style_answers).every((value) => typeof value === "string"));
});
