import test from "node:test";
import assert from "node:assert/strict";
import { assessVoiceRecording } from "../src/voiceQuality.js";

test("passes a clear recording of sufficient length", () => {
  const result = assessVoiceRecording({
    durationSeconds: 58,
    averageLevel: 0.08,
    clippedRatio: 0.001,
  });
  assert.equal(result.passed, true);
  assert.deepEqual(result.issues, []);
});

test("rejects a short or nearly silent recording", () => {
  const result = assessVoiceRecording({
    durationSeconds: 18,
    averageLevel: 0.005,
    clippedRatio: 0,
  });
  assert.equal(result.passed, false);
  assert.equal(result.issues.length, 2);
});

test("rejects clipping", () => {
  const result = assessVoiceRecording({
    durationSeconds: 60,
    averageLevel: 0.2,
    clippedRatio: 0.03,
  });
  assert.equal(result.passed, false);
  assert.match(result.issues[0], /찢어질/);
});
