const MIN_SPLIT_TEXT_CHARS = 48;
const MIN_FIRST_CHUNK_CHARS = 12;
const MIN_REMAINING_CHARS = 10;
const PREFERRED_FIRST_CHUNK_CHARS = 54;
const MAX_PREFERRED_FIRST_CHUNK_CHARS = 84;
const MAX_RETRY_AFTER_MS = 5000;
const SHORT_FINAL_GRACE_MS = 1200;

const STRONG_BOUNDARY = new Set([".", "!", "?", "。", "！", "？", "…"]);
const SOFT_BOUNDARY = new Set([",", "，", ";", "；", ":", "："]);
const CLOSING_PUNCTUATION = new Set([
  '"',
  "'",
  ")",
  "]",
  "}",
  "”",
  "’",
  "」",
  "』",
  "】",
]);

const SHORT_FINAL_TURNS = new Set([
  "응",
  "네",
  "아니",
  "그래",
  "맞아",
  "괜찮아",
  "알겠어",
  "고마워",
  "먹었어",
  "안 먹었어",
  "몰라",
]);

export function speechNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

/**
 * Publish timing without including transcript or authentication data.
 * Consumers can observe `memory-call:speech-timing` in development tools.
 */
export function emitSpeechTiming(stage, detail = {}) {
  const payload = { stage, atMs: speechNow(), ...detail };
  const markName = `memory-call:speech:${stage}`;
  try {
    globalThis.performance?.clearMarks?.(markName);
    globalThis.performance?.mark?.(markName, { detail: payload });
  } catch {
    // Older browsers may not support the PerformanceMark detail option.
    try {
      globalThis.performance?.mark?.(markName);
    } catch {
      // Timing is advisory and must never interrupt a call.
    }
  }

  if (
    typeof globalThis.dispatchEvent === "function" &&
    typeof globalThis.CustomEvent === "function"
  ) {
    globalThis.dispatchEvent(
      new globalThis.CustomEvent("memory-call:speech-timing", { detail: payload })
    );
  }
  return payload;
}

/**
 * Detach every element from an object URL before revoking it.
 *
 * A media element that is still fetching a revoked blob fails with
 * ERR_FILE_NOT_FOUND, and `preload="auto"` keeps a hidden copy fetching long
 * after the visible one is done. load() aborts those in-flight requests.
 */
export function detachThenRevoke(elements, revoke) {
  for (const element of elements) {
    if (!element) continue;
    element.pause();
    element.removeAttribute("src");
    element.load();
  }
  revoke();
}

function isNumericSeparator(text, index) {
  return /\d/.test(text[index - 1] ?? "") && /\d/.test(text[index + 1] ?? "");
}

function boundaryEnd(text, index) {
  let end = index + 1;
  while (
    end < text.length &&
    (STRONG_BOUNDARY.has(text[end]) || CLOSING_PUNCTUATION.has(text[end]))
  ) {
    end += 1;
  }
  return end;
}

function collectBoundaries(text) {
  const strong = [];
  const soft = [];
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === "\n") {
      strong.push(index);
      continue;
    }
    if (STRONG_BOUNDARY.has(character)) {
      if ((character === "." || character === "…") && isNumericSeparator(text, index)) {
        continue;
      }
      const end = boundaryEnd(text, index);
      strong.push(end);
      index = end - 1;
      continue;
    }
    if (SOFT_BOUNDARY.has(character) && !isNumericSeparator(text, index)) {
      soft.push(index + 1);
    }
  }
  return { strong, soft };
}

function usableBoundary(text, boundary) {
  const first = text.slice(0, boundary).trim();
  const remaining = text.slice(boundary).trim();
  return (
    first.length >= MIN_FIRST_CHUNK_CHARS &&
    remaining.length >= MIN_REMAINING_CHARS
  );
}

/**
 * Split only at natural Korean sentence/clause punctuation and return at most
 * two chunks. If no safe boundary exists, preserving the complete utterance is
 * preferable to an unnatural split.
 */
export function splitKoreanSpeech(value) {
  const text = String(value ?? "").replace(/[ \t]+/g, " ").trim();
  if (text.length < MIN_SPLIT_TEXT_CHARS) return text ? [text] : [];

  const { strong, soft } = collectBoundaries(text);
  const safeStrong = strong.filter((boundary) => usableBoundary(text, boundary));
  const safeSoft = soft.filter((boundary) => usableBoundary(text, boundary));

  let boundary = safeStrong.find(
    (candidate) => candidate <= MAX_PREFERRED_FIRST_CHUNK_CHARS
  );
  if (!boundary && safeSoft.length) {
    boundary = safeSoft.reduce((best, candidate) =>
      Math.abs(candidate - PREFERRED_FIRST_CHUNK_CHARS) <
      Math.abs(best - PREFERRED_FIRST_CHUNK_CHARS)
        ? candidate
        : best
    );
  }
  if (!boundary && safeStrong.length) boundary = safeStrong[0];
  if (!boundary) return [text];

  return [text.slice(0, boundary).trim(), text.slice(boundary).trim()];
}

export function retryAfterDelayMs(value, nowMs = Date.now()) {
  if (value == null || String(value).trim() === "") return null;
  const raw = String(value).trim();
  const seconds = Number(raw);
  let delay;
  if (Number.isFinite(seconds)) {
    delay = Math.max(0, seconds * 1000);
  } else {
    const date = Date.parse(raw);
    if (!Number.isFinite(date)) return null;
    delay = Math.max(0, date - nowMs);
  }
  return Math.min(delay, MAX_RETRY_AFTER_MS);
}

/** Keep the elderly-user pause unchanged except for reliable short final turns. */
export function adaptiveSilenceDelay({
  configuredMs,
  finalizedText,
  hasFinalResult,
  hasInterim,
}) {
  const base = Number(configuredMs);
  if (!Number.isFinite(base) || base <= 0) return configuredMs;
  if (!hasFinalResult || hasInterim) return base;

  const normalized = String(finalizedText ?? "")
    .trim()
    .replace(/[.!?。！？…]+$/u, "")
    .trim();
  const explicitShortTurn = SHORT_FINAL_TURNS.has(normalized);
  const terminalShortTurn =
    String(finalizedText ?? "").trim().length <= 18 &&
    /[.!?。！？…]$/u.test(String(finalizedText ?? "").trim());

  return explicitShortTurn || terminalShortTurn
    ? Math.min(base, SHORT_FINAL_GRACE_MS)
    : base;
}

function settled(promise) {
  return promise.then(
    (value) => ({ value }),
    (error) => ({ error })
  );
}

/**
 * Fetch the first chunk immediately. The next (and only next) chunk begins
 * when playChunk reports that current audio is actually playing. Playback is
 * always awaited, so audio can never overlap or reorder.
 */
export async function runSequentialAudioQueue(
  chunks,
  { fetchChunk, playChunk, shouldContinue = () => true, onChunkComplete = () => {} }
) {
  if (!chunks.length || !shouldContinue()) return;

  let current = await fetchChunk(chunks[0], 0);
  for (let index = 0; index < chunks.length; index += 1) {
    if (!shouldContinue()) return;
    let nextFetch = null;
    const prefetchNext = () => {
      if (
        nextFetch === null &&
        index + 1 < chunks.length &&
        shouldContinue()
      ) {
        nextFetch = settled(fetchChunk(chunks[index + 1], index + 1));
      }
    };

    await playChunk(current, index, prefetchNext);
    onChunkComplete(index);
    if (!shouldContinue() || index + 1 >= chunks.length) return;

    // A browser that never fires `playing` remains correct, just not prefetched.
    prefetchNext();
    const next = await nextFetch;
    if (next.error) throw next.error;
    current = next.value;
  }
}
