const SAMPLE_RATE = 16000;
const BYTES_PER_SAMPLE = 2;
const PLAYBACK_TAIL_MS = 350;

const wait = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true }
    );
  });

/**
 * One Anam WebRTC session per AI call. The permanent key remains on the
 * backend; this object only sees a short-lived session token.
 */
export function createAnamTransport({
  callId,
  personaId,
  videoElementId,
  fetchImpl = fetch,
  createClientImpl = null,
  onStateChange = () => {},
  playbackTailMs = PLAYBACK_TAIL_MS,
}) {
  let client = null;
  let connectPromise = null;
  let state = "idle";
  let generation = 0;

  const setState = (next, detail = null) => {
    state = next;
    onStateChange(next, detail);
  };

  const connect = async () => {
    if (state === "connected" && client) return;
    if (connectPromise) return connectPromise;
    const attempt = ++generation;
    setState("connecting");
    connectPromise = (async () => {
      const response = await fetchImpl("/api/anam/session-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          call_id: callId,
          ...(personaId ? { persona_id: personaId } : {}),
        }),
      });
      if (!response.ok) throw new Error(`Anam token ${response.status}`);
      const payload = await response.json();
      if (!payload.session_token) throw new Error("Anam token missing");

      const createAnamClient = createClientImpl ?? (
        await import("@anam-ai/js-sdk")
      ).createClient;
      const nextClient = createAnamClient(payload.session_token, {
        disableInputAudio: true,
      });
      await nextClient.streamToVideoElement(videoElementId);
      if (attempt !== generation) {
        await nextClient.stopStreaming().catch(() => {});
        throw new DOMException("Aborted", "AbortError");
      }
      client = nextClient;
      setState("connected");
    })()
      .catch((error) => {
        if (attempt === generation) setState("failed", error);
        throw error;
      })
      .finally(() => {
        connectPromise = null;
      });
    return connectPromise;
  };

  const interrupt = () => {
    try {
      client?.interruptPersona();
    } catch {
      // The provider may already have closed the data channel.
    }
  };

  const speakPcmResponse = async (response, { signal, onFirstChunk } = {}) => {
    await connect();
    if (!client || state !== "connected") throw new Error("Anam not connected");
    if (!response.ok || !response.body) {
      throw new Error(`PCM stream ${response.status}`);
    }

    const audioInput = client.createAgentAudioInputStream({
      encoding: "pcm_s16le",
      sampleRate: SAMPLE_RATE,
      channels: 1,
    });
    const reader = response.body.getReader();
    let bytes = 0;
    let firstChunkAt = null;
    try {
      while (true) {
        if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
        const { done, value } = await reader.read();
        if (done) break;
        if (!value?.byteLength) continue;
        if (firstChunkAt == null) {
          firstChunkAt = performance.now();
          onFirstChunk?.();
        }
        bytes += value.byteLength;
        audioInput.sendAudioChunk(value);
      }
      audioInput.endSequence();
    } catch (error) {
      await reader.cancel().catch(() => {});
      interrupt();
      throw error;
    }

    const durationMs = (bytes / (SAMPLE_RATE * BYTES_PER_SAMPLE)) * 1000;
    const elapsedMs = firstChunkAt == null ? 0 : performance.now() - firstChunkAt;
    await wait(Math.max(0, durationMs - elapsedMs) + playbackTailMs, signal);
    return { bytes, durationMs };
  };

  const disconnect = async () => {
    generation += 1;
    interrupt();
    const active = client;
    client = null;
    if (active) await active.stopStreaming().catch(() => {});
    setState("idle");
  };

  return {
    connect,
    disconnect,
    interrupt,
    speakPcmResponse,
    getState: () => state,
  };
}
