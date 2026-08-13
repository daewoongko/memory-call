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
