import { useCallback, useEffect, useState } from "react";
import * as api from "../api.js";
import ReportTabs from "./ReportTabs.jsx";

function localDateKey(date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

function rollingRange(end, days = 30) {
  const endDate = new Date(`${end}T12:00:00`);
  const startDate = new Date(endDate);
  startDate.setDate(startDate.getDate() - days + 1);
  return { days, start: localDateKey(startDate), end };
}

function jsonList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [value];
  } catch {
    return [value];
  }
}

function normalizeProfile(profile) {
  if (!profile) return null;
  return {
    ...profile,
    care_baseline: jsonList(profile.care_baseline),
    medical_cautions: jsonList(profile.medical_cautions),
  };
}

export default function FamilyAnalysisReport({ elderId, elderName, date }) {
  const [summary, setSummary] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");
  const [loadingBaseline, setLoadingBaseline] = useState(false);

  const load = useCallback(() => {
    const range = rollingRange(date);
    setSummary(null);
    setBaseline(null);
    setError("");
    return Promise.all([
      api.getPeriodSummary(1, elderId, { start: date, end: date }),
      api.getPersona(undefined, elderId).catch(() => null),
    ]).then(([day, persona]) => {
      setSummary(day);
      setProfile(normalizeProfile(persona?.elder));
      setLoadingBaseline(true);
      return api.getPeriodSummary(range.days, elderId, range)
        .then(setBaseline)
        .catch((reason) => setError(`최근 30일 비교 기준을 불러오지 못했습니다. (${reason.message})`))
        .finally(() => setLoadingBaseline(false));
    }).catch((reason) => setError(`분석 리포트를 불러오지 못했습니다. (${reason.message})`));
  }, [date, elderId]);

  useEffect(() => { load(); }, [load]);

  if (!summary) return <div className="family-analysis-loading" role="status"><p className={error ? "error" : "hint"}>{error || "통화 분석을 불러오는 중…"}</p></div>;

  return <section className="family-analysis-report">
    {error && <p className="error">{error}</p>}
    <ReportTabs
      elderId={elderId}
      elderName={elderName}
      patientProfile={profile}
      summary={summary}
      baselineSummary={baseline || summary}
      comparisonDay={summary}
      period={{ mode: "day", value: date }}
      onReload={load}
    />
    {loadingBaseline && <p className="manager-baseline-loading">최근 30일 비교 기준을 이어서 계산하고 있습니다.</p>}
  </section>;
}
