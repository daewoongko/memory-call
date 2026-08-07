import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeSpeechMediaType,
  shouldFallbackFromLipSyncStatus,
  speechMediaKind,
} from "../src/speechMedia.js";

test("speech media accepts only the two server response formats", () => {
  assert.equal(normalizeSpeechMediaType("video/mp4"), "video/mp4");
  assert.equal(
    normalizeSpeechMediaType("Audio/Wav; charset=binary"),
    "audio/wav"
  );
  assert.equal(normalizeSpeechMediaType("text/html"), null);
  assert.equal(normalizeSpeechMediaType("video/webm"), null);
  assert.equal(normalizeSpeechMediaType(""), null);
});

test("speech media maps MP4 to video and WAV fallback to audio", () => {
  assert.equal(speechMediaKind("video/mp4"), "video");
  assert.equal(speechMediaKind("audio/wav"), "audio");
  assert.equal(speechMediaKind("application/octet-stream"), null);
});

test("optional lip-sync endpoint fallback statuses stay explicit", () => {
  for (const status of [404, 409, 503]) {
    assert.equal(shouldFallbackFromLipSyncStatus(status), true);
  }
  for (const status of [200, 400, 429, 500]) {
    assert.equal(shouldFallbackFromLipSyncStatus(status), false);
  }
});
