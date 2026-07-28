// FastAPI 호출부. Vite 프록시 덕분에 상대 경로만 쓴다.

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
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

export const getProfile = (personaId) =>
  request(`/api/profile${personaId ? `?persona_id=${personaId}` : ""}`);

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

export const startCall = (personaId) =>
  request("/api/calls", {
    method: "POST",
    body: JSON.stringify(personaId ? { persona_id: personaId } : {}),
  });

export const sendTurn = (callId, text) =>
  request(`/api/calls/${callId}/turn`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const getPersona = (elderId = "elder_001") =>
  request(`/api/elders/${elderId}/persona`);

export const patchPersona = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/persona`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const patchElder = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/profile`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const uploadFaces = async (fileList) => {
  const form = new FormData();
  [...fileList].forEach((f) => form.append("files", f));
  const res = await fetch("/api/faces", { method: "POST", body: form });
  if (!res.ok) throw new Error(`업로드 실패 (${res.status})`);
  return res.json();
};

export const deleteFace = (name) =>
  request(`/api/faces/${encodeURIComponent(name)}`, { method: "DELETE" });

export const prepareFaces = () =>
  request("/api/faces/prepare", { method: "POST" });

export const getMemories = (elderId = "elder_001") =>
  request(`/api/elders/${elderId}/memories`);

export const addMemory = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/memories`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const patchMemory = (memoryId, body) =>
  request(`/api/memories/${memoryId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteMemory = (memoryId) =>
  request(`/api/memories/${memoryId}`, { method: "DELETE" });

export const reviewRecall = (utteranceId, body) =>
  request(`/api/recalls/${utteranceId}/review`, {
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

export const getMedications = (elderId = "elder_001") =>
  request(`/api/elders/${elderId}/medications`);

export const addMedication = (body, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/medications`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const removeMedication = (scheduleId) =>
  request(`/api/medications/${scheduleId}`, { method: "DELETE" });

export const getReports = (elderId = "elder_001") =>
  request(`/api/elders/${elderId}/reports`);

export const getReport = (callId) => request(`/api/calls/${callId}/report`);

export const getTranscript = (callId) => request(`/api/calls/${callId}/log`);

export const getPeriodSummary = (days = 7, elderId = "elder_001") =>
  request(`/api/elders/${elderId}/summary?days=${days}`);

export const acknowledgeRisk = (eventId) =>
  request(`/api/risk-events/${eventId}/acknowledge`, { method: "POST" });

export const endCall = (callId, reason = "user_ended") =>
  request(`/api/calls/${callId}/end`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
