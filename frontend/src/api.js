// FastAPI 호출부. Vite 프록시 덕분에 상대 경로만 쓴다.

const TRANSIENT_STATUSES = new Set([502, 503, 504]);

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function request(path, options = {}) {
  let res;
  const attempts = (options.method || "GET") === "GET" ? 3 : 1;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!TRANSIENT_STATUSES.has(res.status) || attempt === attempts - 1) break;
    await wait(700 * (attempt + 1));
  }
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // JSON 이 아니면 상태 코드만 쓴다
    }
    throw new Error(detail);
  }
  return res.json();
}

export const getProfile = (personaId, elderId = "elder_001") => {
  const params = new URLSearchParams({ elder_id: elderId });
  if (personaId) params.set("persona_id", personaId);
  return request(`/api/profile?${params}`);
};

export const getPersonas = (elderId = "elder_001") =>
  request(`/api/personas?elder_id=${elderId}`);

export const getElders = () => request("/api/elders");

export const addElder = (body) =>
  request("/api/elders", { method: "POST", body: JSON.stringify(body) });

export const issueLinkCode = (elderId = "elder_001") =>
  request(`/api/link/code?elder_id=${elderId}`, { method: "POST" });

export const verifyLinkCode = (code) =>
  request("/api/link/verify", {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const startCall = (personaId, elderId = "elder_001") =>
  request("/api/calls", {
    method: "POST",
    body: JSON.stringify({
      elder_id: elderId,
      ...(personaId ? { persona_id: personaId } : {}),
    }),
  });

export const sendTurn = (callId, text) =>
  request(`/api/calls/${callId}/turn`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

/** Android Chrome에서 Web Speech가 응답하지 않을 때 쓰는 짧은 음성 전사. */
export const transcribeSpeech = async (blob, lang = "ko-KR") => {
  const form = new FormData();
  const extension = blob.type.includes("mp4") ? "m4a" : "webm";
  form.append("audio", blob, `utterance.${extension}`);
  const res = await fetch(`/api/stt?lang=${encodeURIComponent(lang)}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // JSON 응답이 아니면 상태 코드만 사용한다.
    }
    throw new Error(detail);
  }
  return res.json();
};

/** Permanent ElevenLabs credentials stay on the API server. */
export const getRealtimeSTTToken = () =>
  request("/api/stt/realtime-token", { method: "POST" });

// ── 기기와 호출 ────────────────────────────────────────────
// 벨은 서버의 상태다. 화면은 그 상태를 읽기만 하고 스스로 판정하지 않는다.

export const registerDevice = (body) =>
  request("/api/devices", { method: "POST", body: JSON.stringify(body) });

export const ringFamily = (body) =>
  request("/api/call-invites", { method: "POST", body: JSON.stringify(body) });

/** 어르신 기기의 폴링. 벨이 끝났는지는 서버가 알려준다. */
export const getInvite = (inviteId) =>
  request(`/api/call-invites/${inviteId}`);

/** 보호자 기기의 수신 폴링. 이 호출이 heartbeat 를 겸한다. */
export const getIncomingInvite = (deviceId) =>
  request(`/api/call-invites?device_id=${encodeURIComponent(deviceId)}`);

export const answerInvite = (inviteId, deviceId) =>
  request(`/api/call-invites/${inviteId}/answer`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId }),
  });

export const declineInvite = (inviteId, deviceId, reason) =>
  request(`/api/call-invites/${inviteId}/decline`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, ...(reason ? { reason } : {}) }),
  });

export const getRecentInvites = (elderId = "elder_001", limit = 20) =>
  request(`/api/call-invites/recent?elder_id=${encodeURIComponent(elderId)}&limit=${limit}`);

export const cancelInvite = (inviteId) =>
  request(`/api/call-invites/${inviteId}/cancel`, { method: "POST" });

/** AI 가 대신 받는다. 응답은 startCall 과 같은 형태다. */
export const takeOverInvite = (inviteId, reason) =>
  request(`/api/call-invites/${inviteId}/ai-takeover`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });

export const endInvite = (inviteId) =>
  request(`/api/call-invites/${inviteId}/end`, { method: "POST" });

/** 실제 사람 통화의 SDP·ICE. 진단 신호와 URL을 분리해 운영 기록과 섞지 않는다. */
export const sendCallSignal = (inviteId, body) =>
  request(`/api/call-invites/${encodeURIComponent(inviteId)}/signal`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const pollCallSignal = (inviteId, sender, since = 0) =>
  request(`/api/call-invites/${encodeURIComponent(inviteId)}/signal`
    + `?sender=${encodeURIComponent(sender)}&since=${since}`);

// ── P2P 진단 ──────────────────────────────────────────────
// 서버는 SDP·ICE 를 방 단위로 전달만 한다. 내용은 보지 않는다.

export const createNetTestRoom = () =>
  request("/api/nettest/room", { method: "POST" });

export const sendSignal = (room, body) =>
  request(`/api/nettest/${encodeURIComponent(room)}/signal`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const pollSignal = (room, sender, since = 0) =>
  request(`/api/nettest/${encodeURIComponent(room)}/signal`
    + `?sender=${encodeURIComponent(sender)}&since=${since}`);

export const saveNetTestResult = (body) =>
  request("/api/nettest/results", { method: "POST", body: JSON.stringify(body) });

export const getNetTestResults = (limit = 20) =>
  request(`/api/nettest/results?limit=${limit}`);

export const getPersona = (personaId, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/persona${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`);

export const patchPersona = (body, personaId, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/persona${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const patchElder = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/profile`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const uploadFaces = async (fileList, personaId) => {
  const form = new FormData();
  [...fileList].forEach((f) => form.append("files", f));
  const query = personaId ? `?persona_id=${encodeURIComponent(personaId)}` : "";
  const res = await fetch(`/api/faces${query}`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`업로드 실패 (${res.status})`);
  return res.json();
};

export const uploadIdentityPhotos = async (fileList, personaId) => {
  const form = new FormData();
  [...fileList].forEach((file) => form.append("files", file));
  const query = personaId ? `?persona_id=${encodeURIComponent(personaId)}` : "";
  const res = await fetch(`/api/identity-photos${query}`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`사진 검사 실패 (${res.status})`);
  return res.json();
};

export const deleteIdentityPhoto = (name, personaId) =>
  request(`/api/identity-photos/${encodeURIComponent(name)}${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`, {
    method: "DELETE",
  });

export const saveAgePlan = (body, personaId) =>
  request(`/api/age-plan${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const selectAgeCandidate = (age, filename, personaId) =>
  request(`/api/age-plan/selection${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`, {
    method: "PUT",
    body: JSON.stringify({ age, filename }),
  });

export const refineAgePlan = (olderAge, youngerAge, personaId) =>
  request(`/api/age-plan/refine${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`, {
    method: "POST",
    body: JSON.stringify({ older_age: olderAge, younger_age: youngerAge }),
  });

export const deleteFace = (name, personaId) =>
  request(`/api/faces/${encodeURIComponent(name)}${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`, { method: "DELETE" });

export const prepareFaces = (personaId) =>
  request(`/api/faces/prepare${personaId ? `?persona_id=${encodeURIComponent(personaId)}` : ""}`, { method: "POST" });

export const getMemories = (elderId = "elder_001") =>
  request(`/api/elders/${elderId}/memories`);

export const addMemory = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/memories`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export async function uploadMemoryPhoto(memoryId, file, elderId = "elder_001") {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/elders/${encodeURIComponent(elderId)}/memories/${encodeURIComponent(memoryId)}/photo`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.json();
}

export const patchMemory = (memoryId, body) =>
  request(`/api/memories/${memoryId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteMemory = (memoryId) =>
  request(`/api/memories/${memoryId}`, { method: "DELETE" });

export const reviewRecall = (utteranceId, body, elderId = "elder_001") =>
  request(`/api/recalls/${utteranceId}/review?elder_id=${encodeURIComponent(elderId)}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getPendingCall = (elderId = "elder_001") =>
  request(`/api/elders/${elderId}/pending-call`);

export const getSchedules = (elderId = "elder_001") =>
  request(`/api/elders/${elderId}/schedules`);

export const addSchedule = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/schedules`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const patchSchedule = (scheduleId, body) =>
  request(`/api/schedules/${scheduleId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteSchedule = (scheduleId) =>
  request(`/api/schedules/${scheduleId}`, { method: "DELETE" });

export const getMedications = (elderId = "elder_001", asOf = "") =>
  request(`/api/elders/${elderId}/medications${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ""}`);

export const addMedication = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/medications`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const addMedicationReview = (scheduleId, body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/medications/${scheduleId}/reviews`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const removeMedication = (scheduleId) =>
  request(`/api/medications/${scheduleId}`, { method: "DELETE" });

export const getReports = (elderId = "elder_001", limit = 120) =>
  request(`/api/elders/${elderId}/reports?limit=${limit}`);

export const getReport = (callId) => request(`/api/calls/${callId}/report`);

export const getTranscript = (callId) => request(`/api/calls/${callId}/log`);

export const getPeriodSummary = (days = 7, elderId = "elder_001", range = {}) => {
  const params = new URLSearchParams({ days: String(days) });
  if (range.start && range.end) {
    params.set("start", range.start);
    params.set("end", range.end);
  }
  return request(`/api/elders/${elderId}/summary?${params}`);
};

export const acknowledgeRisk = (eventId) =>
  request(`/api/risk-events/${eventId}/acknowledge`, { method: "POST" });

export const getCareTasks = (asOf = "") =>
  request(`/api/care-tasks${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ""}`);

export const completeDoseTask = (scheduleId, asOf) =>
  request(`/api/care-tasks/dose/${encodeURIComponent(scheduleId)}/complete`, {
    method: "POST", body: JSON.stringify({ as_of: asOf }),
  });

export const setDoseTaskStatus = (scheduleId, asOf, status) =>
  request(`/api/care-tasks/dose/${encodeURIComponent(scheduleId)}/status`, {
    method: "POST", body: JSON.stringify({ as_of: asOf, status }),
  });

export const getHandovers = (limit = 10) => request(`/api/handovers?limit=${limit}`);

export const closeHandover = (body) => request("/api/handovers", {
  method: "POST", body: JSON.stringify(body),
});

export const endCall = (callId, reason = "user_ended") =>
  request(`/api/calls/${callId}/end`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
