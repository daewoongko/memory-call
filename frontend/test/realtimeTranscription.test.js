import assert from "node:assert/strict";
import test from "node:test";

import { resampleTo16k } from "../src/useRealtimeTranscription.js";

test("48 kHz microphone frames are downsampled to 16 kHz", () => {
  const input = Float32Array.from({ length: 4800 }, (_, index) => Math.sin(index / 20));
  const output = resampleTo16k(input, 48000);
  assert.equal(output.length, 1600);
  assert.ok(output.some((sample) => Math.abs(sample) > 0.1));
});

test("native 16 kHz frames are copied without changing length", () => {
  const input = Float32Array.from([0, 0.25, -0.5, 1]);
  const output = resampleTo16k(input, 16000);
  assert.deepEqual([...output], [...input]);
  assert.notEqual(output, input);
});
