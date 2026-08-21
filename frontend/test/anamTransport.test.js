import assert from "node:assert/strict";
import test from "node:test";

import { createAnamTransport } from "../src/anamTransport.js";

test("Anam transport exchanges a short-lived token and streams PCM chunks", async () => {
  const requests = [];
  const chunks = [];
  const states = [];
  let streamTarget = null;
  let ended = 0;
  let stopped = 0;
  const listeners = new Map();

  const transport = createAnamTransport({
    callId: "call_12345678",
    personaId: "persona_jeonghun",
    videoElementId: "avatar-video",
    playbackTailMs: 0,
    fetchImpl: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return new Response(JSON.stringify({ session_token: "temporary-token" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
    createClientImpl: (token, options) => {
      assert.equal(token, "temporary-token");
      assert.equal(options.disableInputAudio, true);
      return {
        async streamToVideoElement(target) {
          streamTarget = target;
          queueMicrotask(() => listeners.get("VIDEO_STREAM_STARTED")?.());
        },
        addListener(event, callback) {
          listeners.set(event, callback);
        },
        removeListener(event, callback) {
          if (listeners.get(event) === callback) listeners.delete(event);
        },
        createAgentAudioInputStream(config) {
          assert.deepEqual(config, {
            encoding: "pcm_s16le",
            sampleRate: 16000,
            channels: 1,
          });
          return {
            sendAudioChunk(value) {
              chunks.push([...value]);
            },
            endSequence() {
              ended += 1;
            },
          };
        },
        interruptPersona() {},
        async stopStreaming() {
          stopped += 1;
        },
      };
    },
    onStateChange: (state) => states.push(state),
  });

  const pcmResponse = new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2, 3, 4]));
        controller.enqueue(new Uint8Array([5, 6]));
        controller.close();
      },
    }),
    { status: 200 }
  );
  let started = 0;

  await transport.connect();
  const result = await transport.speakPcmResponse(pcmResponse, {
    onFirstChunk: () => {
      started += 1;
    },
  });

  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0], {
    url: "/api/anam/session-token",
    body: {
      call_id: "call_12345678",
      persona_id: "persona_jeonghun",
      performance_style: "calm",
    },
  });
  assert.equal(streamTarget, "avatar-video");
  assert.deepEqual(chunks, [[1, 2, 3, 4], [5, 6]]);
  assert.equal(result.bytes, 6);
  assert.equal(started, 1);
  assert.equal(ended, 1);
  assert.deepEqual(states.slice(0, 2), ["connecting", "connected"]);

  await transport.disconnect();
  assert.equal(stopped, 1);
  assert.equal(transport.getState(), "idle");
});

test("Anam transport exposes token failures for the caller fallback", async () => {
  const states = [];
  const transport = createAnamTransport({
    callId: "call_12345678",
    personaId: "persona_jeonghun",
    videoElementId: "avatar-video",
    fetchImpl: async () => new Response("unavailable", { status: 503 }),
    createClientImpl: () => {
      throw new Error("must not create a client");
    },
    onStateChange: (state) => states.push(state),
  });

  await assert.rejects(transport.connect(), /Anam token 503/);
  assert.equal(transport.getState(), "failed");
  assert.deepEqual(states, ["connecting", "failed"]);
});

test("Anam transport splits coalesced PCM into low-latency avatar pushes", async () => {
  const chunks = [];
  const listeners = new Map();
  const transport = createAnamTransport({
    callId: "call_12345678",
    personaId: "persona_jeonghun",
    videoElementId: "avatar-video",
    playbackTailMs: 0,
    fetchImpl: async () => new Response(JSON.stringify({ session_token: "token" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
    createClientImpl: () => ({
      async streamToVideoElement() {
        queueMicrotask(() => listeners.get("VIDEO_STREAM_STARTED")?.());
      },
      addListener(event, callback) { listeners.set(event, callback); },
      removeListener(event, callback) {
        if (listeners.get(event) === callback) listeners.delete(event);
      },
      createAgentAudioInputStream() {
        return {
          sendAudioChunk(value) { chunks.push(value.byteLength); },
          endSequence() {},
        };
      },
      interruptPersona() {},
      async stopStreaming() {},
    }),
  });

  const pcm = new Uint8Array(5000);
  await transport.speakPcmResponse(new Response(pcm), {});

  assert.deepEqual(chunks, [2048, 2048, 904]);
});
