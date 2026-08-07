import assert from "node:assert/strict";
import test from "node:test";

import {
  adaptiveSilenceDelay,
  retryAfterDelayMs,
  runSequentialAudioQueue,
  splitKoreanSpeech,
} from "../src/speechPipeline.js";

test("short replies and text without a safe boundary stay in one chunk", () => {
  assert.deepEqual(splitKoreanSpeech("응, 알겠어."), ["응, 알겠어."]);
  const unbroken = "가".repeat(100);
  assert.deepEqual(splitKoreanSpeech(unbroken), [unbroken]);
});

test("Korean speech splits at a natural boundary and never exceeds two chunks", () => {
  const text =
    "할아버지 오늘 많이 힘들었지? 지금은 천천히 숨을 쉬면서 그대로 앉아 있어. 내가 가족에게 바로 알려줄게.";
  const chunks = splitKoreanSpeech(text);
  assert.deepEqual(chunks, [
    "할아버지 오늘 많이 힘들었지?",
    "지금은 천천히 숨을 쉬면서 그대로 앉아 있어. 내가 가족에게 바로 알려줄게.",
  ]);
  assert.equal(chunks.join(" "), text);
  assert.equal(chunks.length, 2);
});

test("numeric punctuation does not create an unsafe split", () => {
  const text =
    "약은 3.14처럼 숫자로 들은 내용을 추측해서 말하면 안 돼 오늘 복용 기록은 가족에게 확인해볼게";
  assert.deepEqual(splitKoreanSpeech(text), [text]);
});

test("a long Korean sentence may split at one safe clause boundary", () => {
  const text =
    "많이 놀랐겠지만 지금은 천천히 숨을 쉬고 그대로 앉아 있어, 움직이지 말고 기다리면 내가 가족에게 바로 알려줄게";
  const chunks = splitKoreanSpeech(text);
  assert.deepEqual(chunks, [
    "많이 놀랐겠지만 지금은 천천히 숨을 쉬고 그대로 앉아 있어,",
    "움직이지 말고 기다리면 내가 가족에게 바로 알려줄게",
  ]);
  assert.equal(chunks.length, 2);
});

test("sequential queue prefetches only the next chunk after playback starts", async () => {
  const events = [];
  await runSequentialAudioQueue(["첫 문장", "둘째 문장"], {
    fetchChunk: async (chunk, index) => {
      events.push(`fetch:${index}`);
      return chunk;
    },
    playChunk: async (_chunk, index, onPlaying) => {
      events.push(`play-start:${index}`);
      onPlaying();
      events.push(`play-end:${index}`);
    },
  });

  assert.deepEqual(events, [
    "fetch:0",
    "play-start:0",
    "fetch:1",
    "play-end:0",
    "play-start:1",
    "play-end:1",
  ]);
});

test("sequential queue does not fetch a third chunk before its predecessor", async () => {
  const events = [];
  await runSequentialAudioQueue(["하나", "둘", "셋"], {
    fetchChunk: async (_chunk, index) => {
      events.push(`fetch:${index}`);
      return index;
    },
    playChunk: async (_value, index, onPlaying) => {
      events.push(`play:${index}`);
      onPlaying();
      assert.equal(events.includes(`fetch:${index + 2}`), false);
    },
  });
  assert.deepEqual(events, [
    "fetch:0",
    "play:0",
    "fetch:1",
    "play:1",
    "fetch:2",
    "play:2",
  ]);
});

test("Retry-After parsing is capped and rejects invalid values", () => {
  assert.equal(retryAfterDelayMs("3"), 3000);
  assert.equal(retryAfterDelayMs("60"), 5000);
  assert.equal(retryAfterDelayMs("invalid"), null);
  assert.equal(
    retryAfterDelayMs("Thu, 01 Jan 2026 00:00:04 GMT", Date.UTC(2026, 0, 1)),
    4000
  );
});

test("adaptive silence only shortens reliable final short turns", () => {
  assert.equal(
    adaptiveSilenceDelay({
      configuredMs: 2000,
      finalizedText: "응",
      hasFinalResult: true,
      hasInterim: false,
    }),
    1200
  );
  assert.equal(
    adaptiveSilenceDelay({
      configuredMs: 2000,
      finalizedText: "오늘 아침에 할 이야기가 있는데",
      hasFinalResult: true,
      hasInterim: false,
    }),
    2000
  );
  assert.equal(
    adaptiveSilenceDelay({
      configuredMs: 2000,
      finalizedText: "오늘 아침에 약을 먹었는지 잘 모르겠어.",
      hasFinalResult: true,
      hasInterim: false,
    }),
    2000
  );
  assert.equal(
    adaptiveSilenceDelay({
      configuredMs: 2000,
      finalizedText: "응",
      hasFinalResult: true,
      hasInterim: true,
    }),
    2000
  );
});
