export function assessVoiceRecording({ durationSeconds, averageLevel, clippedRatio }) {
  const issues = [];
  if (durationSeconds < 40) issues.push("40초 이상 읽어주세요.");
  if (averageLevel < 0.015) issues.push("목소리가 너무 작아요. 휴대폰을 조금 가까이 두세요.");
  if (averageLevel > 0.45 || clippedRatio >= 0.02) {
    issues.push("소리가 찢어질 만큼 커요. 휴대폰과 거리를 조금 늘려주세요.");
  }
  return {
    passed: issues.length === 0,
    issues,
    duration_seconds: Math.round(durationSeconds * 10) / 10,
    average_level: Math.round(averageLevel * 10000) / 10000,
    clipped_ratio: Math.round(clippedRatio * 100000) / 100000,
  };
}

export function recordingMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  return ["audio/webm;codecs=opus", "audio/mp4", "audio/webm", "audio/ogg;codecs=opus"]
    .find((type) => MediaRecorder.isTypeSupported?.(type)) || "";
}
