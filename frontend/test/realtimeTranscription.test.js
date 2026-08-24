import assert from "node:assert/strict";
import test from "node:test";

import {
  resampleTo16k,
  voiceConnectionError,
} from "../src/useRealtimeTranscription.js";
import { readFileSync } from "node:fs";

const speechHook = readFileSync(new URL("../src/useSpeech.js", import.meta.url), "utf8");

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

test("the fallback connection message is not duplicated", () => {
  assert.equal(
    voiceConnectionError("음성 인식에 잠시 연결하지 못했습니다."),
    "음성 인식에 잠시 연결하지 못했습니다.",
  );
  assert.equal(
    voiceConnectionError("일시적인 네트워크 오류"),
    "음성 인식에 잠시 연결하지 못했습니다. 일시적인 네트워크 오류",
  );
});

test("Galaxy Chrome uses realtime STT instead of unreliable browser recognition", () => {
  assert.match(
    speechHook,
    /const usesServerStt = serverStt\.supported && \(!Recognition \|\| ANDROID_BROWSER\);/,
  );
});
