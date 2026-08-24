const SAMPLE_RATE = 24000;
const BYTES_PER_SAMPLE = 2;
const PLAYBACK_TAIL_MS = 350;
const CONNECTION_TIMEOUT_MS = 20000;

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
  performanceStyle = "calm",
  videoElementId,
  fetchImpl = fetch,
  createClientImpl = null,
  onStateChange = () => {},
  playbackTailMs = PLAYBACK_TAIL_MS,
  connectionTimeoutMs = CONNECTION_TIMEOUT_MS,
}) {
  let client = null;
  let connectPromise = null;
  let state = "idle";
  let generation = 0;
  let detachClientListeners = null;
  let pendingClient = null;
  let abortPendingConnection = null;

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
          performance_style: performanceStyle,
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
      pendingClient = nextClient;

      // streamToVideoElement() resolves as soon as the WebRTC connection is
      // requested. It does not mean that an avatar video track is available.
      // Sending PCM in that gap makes Anam reject the turn and forces the
      // caller onto the audio-only fallback, so wait for the real video track.
      let readyTimer = null;
      let readySettled = false;
      let videoReady = false;
      let sessionReady = false;
      let resolveReady;
      let rejectReady;
      const ready = new Promise((resolve, reject) => {
        resolveReady = resolve;
        rejectReady = reject;
      });
      const cleanupReadyListeners = () => {
        clearTimeout(readyTimer);
        nextClient.removeListener?.("VIDEO_STREAM_STARTED", onVideoStarted);
        nextClient.removeListener?.("VIDEO_PLAY_STARTED", onVideoPlayStarted);
        nextClient.removeListener?.("SESSION_READY", onSessionReady);
        nextClient.removeListener?.("DATA_CHANNEL_OPEN", onSessionReady);
      };
      const markReadyWhenComplete = () => {
        if (readySettled || !videoReady || !sessionReady) return;
        readySettled = true;
        cleanupReadyListeners();
        resolveReady();
      };
      const onVideoStarted = (videoStream) => {
        // Mobile browsers can miss media-element events when the WebRTC track
        // arrives while the calling transition is still covering the stage.
        // Re-attach the track defensively and request playback; the SDK already
        // does this in the normal path, so this is harmless when it succeeded.
        const videoElement = globalThis.document?.getElementById?.(videoElementId);
        if (videoElement && videoStream) {
          if (videoElement.srcObject !== videoStream) {
            videoElement.srcObject = videoStream;
          }
          videoElement.play?.().catch(() => {});
        }
        videoReady = true;
        markReadyWhenComplete();
      };
      const onVideoPlayStarted = () => {
        videoReady = true;
        markReadyWhenComplete();
      };
      const onSessionReady = () => {
        sessionReady = true;
        markReadyWhenComplete();
      };
      const onConnectionClosed = (reason, details) => {
        const error = new Error(
          `Anam connection closed${reason ? ` (${reason})` : ""}${details ? `: ${details}` : ""}`
        );
        if (!readySettled) {
          readySettled = true;
          cleanupReadyListeners();
          rejectReady(error);
        }
        if (attempt === generation) {
          client = null;
          setState("failed", error);
        }
      };

      nextClient.addListener?.("VIDEO_STREAM_STARTED", onVideoStarted);
      nextClient.addListener?.("VIDEO_PLAY_STARTED", onVideoPlayStarted);
      nextClient.addListener?.("SESSION_READY", onSessionReady);
      // Older Anam gateways can open the passthrough channel before emitting
      // SESSION_READY. Either event proves that agent-audio signalling is safe.
      nextClient.addListener?.("DATA_CHANNEL_OPEN", onSessionReady);
      nextClient.addListener?.("CONNECTION_CLOSED", onConnectionClosed);
      abortPendingConnection = () => {
        if (readySettled) return;
        readySettled = true;
        cleanupReadyListeners();
        rejectReady(new DOMException("Aborted", "AbortError"));
      };
      detachClientListeners = () => {
        cleanupReadyListeners();
        nextClient.removeListener?.("CONNECTION_CLOSED", onConnectionClosed);
      };
      readyTimer = setTimeout(() => {
        if (readySettled) return;
        readySettled = true;
        cleanupReadyListeners();
        rejectReady(new Error("Anam video connection timed out"));
      }, connectionTimeoutMs);

      try {
        await nextClient.streamToVideoElement(videoElementId);
        await ready;
      } catch (error) {
        if (pendingClient === nextClient) pendingClient = null;
        abortPendingConnection = null;
        detachClientListeners?.();
        detachClientListeners = null;
        await nextClient.stopStreaming().catch(() => {});
        throw error;
      }
      if (attempt !== generation) {
        if (pendingClient === nextClient) pendingClient = null;
        abortPendingConnection = null;
        detachClientListeners?.();
        detachClientListeners = null;
        await nextClient.stopStreaming().catch(() => {});
        throw new DOMException("Aborted", "AbortError");
      }
      pendingClient = null;
      abortPendingConnection = null;
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
        // Fetch is allowed to coalesce server chunks.  Keep every Anam push at
        // roughly 43 ms of PCM so mouth poses are updated frequently.
        for (let offset = 0; offset < value.byteLength; offset += 2048) {
          audioInput.sendAudioChunk(value.subarray(offset, offset + 2048));
        }
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
    const pending = pendingClient;
    pendingClient = null;
    abortPendingConnection?.();
    abortPendingConnection = null;
    detachClientListeners?.();
    detachClientListeners = null;
    const active = client;
    client = null;
    if (pending && pending !== active) {
      await pending.stopStreaming().catch(() => {});
    }
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
