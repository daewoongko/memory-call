const SPEECH_MEDIA_TYPES = new Set(["audio/wav", "video/mp4"]);
const LIPSYNC_FALLBACK_STATUSES = new Set([404, 409, 503]);

/** Strip optional MIME parameters and reject every unexpected media type. */
export function normalizeSpeechMediaType(value) {
  const mediaType = String(value ?? "")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  return SPEECH_MEDIA_TYPES.has(mediaType) ? mediaType : null;
}

/** These statuses mean the optional video path is unavailable, not that TTS failed. */
export function shouldFallbackFromLipSyncStatus(status) {
  return LIPSYNC_FALLBACK_STATUSES.has(Number(status));
}

export function speechMediaKind(mediaType) {
  const normalized = normalizeSpeechMediaType(mediaType);
  if (normalized === "video/mp4") return "video";
  if (normalized === "audio/wav") return "audio";
  return null;
}
