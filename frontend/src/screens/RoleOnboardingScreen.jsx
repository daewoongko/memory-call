import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api.js";
import { calculateCallStyle, callStylePersonaPatch } from "../callStyle.js";
import BrandMark from "../components/BrandMark.jsx";
import CallStyleQuiz from "../components/CallStyleQuiz.jsx";
import VoiceProfilePanel from "../components/VoiceProfilePanel.jsx";
import { SIZE_MAX, SIZE_MIN, SIZE_STEP, THEMES } from "../theme.js";

const CONSENT_VERSION = "2026-08-24.v1";
export const ONBOARDING_FLOW_VERSION = "2026-08-25.v2";
const DAEWOONG_DEMO_ASSET_ROOT = "/persona-assets/persona_godaewoong/age_candidates";
const DAEWOONG_DEMO_AGE_STAGES = [
  { age: 24, recommended: "age24_selected.png", candidates: ["age24_selected.png", "age24_alt_a.png", "age24_alt_b.png", "age24_alt_c.png"] },
  { age: 20, recommended: "age20_selected.png", candidates: ["age20_selected.png", "age20_alt_a.png", "age20_alt_b.png", "age20_alt_c.png"] },
  { age: 17, recommended: "age17_selected.png", candidates: ["age17_selected.png", "age17_alt_a.png", "age17_alt_b.png", "age17_alt_c.png"] },
  { age: 15, recommended: "age15_selected.png", candidates: ["age15_selected.png", "age15_alt_a.png", "age15_alt_b.png", "age15_alt_c.png"] },
  {
    age: 12,
    recommended: "age12_corrected_v3.png",
    candidates: ["age12_corrected_v3.png", "age12_selected.png", "age12_corrected_v2.png", "age12_alt_a.png"],
  },
  { age: 11, recommended: "age11_route_c.png", candidates: ["age11_route_c.png", "age11_alt_a.png", "age11_alt_b.png", "age11_alt_c.png"] },
  { age: 10, recommended: "age10_route_c.png", candidates: ["age10_route_c.png", "age10_alt_a.png", "age10_alt_b.png", "age10_alt_c.png"] },
  { age: 9, recommended: "age09_route_c.png", candidates: ["age09_route_c.png", "age09_alt_a.png", "age09_alt_b.png", "age09_alt_c.png"] },
  { age: 8, recommended: "age08_selected.png", candidates: ["age08_selected.png", "age08_alt_a.png", "age08_alt_b.png", "age08_alt_c.png"] },
];

const COMMON_CONSENTS = [
  ["basic_profile", "기본 개인정보 수집·이용", "이름, 연락처, 가족 관계를 계정과 연결에 사용해요."],
  ["call_recording", "통화 녹음과 문자 변환", "대화를 이어가고 기록을 만들기 위해 통화 음성과 내용을 저장해요."],
  ["sensitive_care", "건강·인지·정서 관찰정보 이용", "돌봄에 필요한 변화만 허용된 가족과 담당자가 확인해요."],
  ["care_sharing", "가족·담당자에게 기록 공유", "연결 승인을 받은 사람에게만 요약과 확인 항목을 보여줘요."],
  ["overseas_processing", "해외 AI 서비스 처리", "음성·사진 처리에 사용하는 해외 서비스와 전송 항목을 확인했어요."],
  ["retention_deletion", "보유 기간·삭제와 동의 철회", "설정에서 보유 기간을 확인하고 삭제 또는 동의 철회를 요청할 수 있어요."],
];

const ROLE_META = {
  elder: { label: "어르신", title: "함께 확인해요" },
  child: { label: "가족", title: "가족 설정" },
  care: { label: "요양 담당자", title: "돌봄 준비중..." },
};

const STEPS = {
  elder: ["elder_consent", "elder_display", "elder_ready"],
  child: ["family_setup", "family_avatar", "family_voice"],
  care: ["care_setup", "care_assignment", "care_review"],
};

const STEP_LABELS = {
  intro: "시작", consent: "동의", family: "가족 확인", comfort: "보기 편하게",
  practice: "사용 연습", connection: "어르신 연결", relationship: "관계·호칭",
  photo: "얼굴 사진", tone: "말투 카드", voice: "목소리", organization: "기관 확인",
  assignment: "담당 배정", review: "마지막 확인", elder_consent: "안심하고 시작하기",
  elder_display: "가족과 화면 확인", elder_ready: "통화 준비", care_setup: "기관과 동의",
  care_assignment: "담당 어르신", care_review: "설정 완료",
};

function normalizeDisplaySize(value) {
  const numeric = Number(value);
  if (numeric >= 135) return 140;
  if (numeric >= 110) return 120;
  return 100;
}

function Choice({ selected, title, detail, onClick, children }) {
  return <button type="button" className={`journey-choice${selected ? " selected" : ""}`} onClick={onClick}>
    <span className="journey-choice-check" aria-hidden="true">{selected ? "✓" : ""}</span>
    <span><b>{title}</b>{detail && <small>{detail}</small>}</span>
    {children}
  </button>;
}

function ConsentStep({ role, data, update }) {
  const selected = new Set(data.consent_types || []);
  const mode = data.consent_mode || (role === "care" ? "staff" : "self");
  const toggle = (type) => {
    const next = new Set(selected);
    if (next.has(type)) next.delete(type); else next.add(type);
    update({ consent_types: [...next] });
  };
  return <>
    <header className="journey-copy">
      <p className="eyebrow">개인정보 이용 동의</p>
      <h2>무엇을 왜 사용하는지<br />하나씩 확인해 주세요</h2>
      <p>다소니는 통화 음성과 내용을 저장해 대화를 자연스럽게 이어가고, 오늘의 상태 변화를 허용된 가족과 담당자가 확인하도록 돕습니다. 광고·판매·공개·범용 AI 학습에는 사용하지 않습니다.</p>
    </header>
    {role === "elder" && <div className="journey-mode-grid">
      {[
        ["self", "본인이 직접 확인"], ["with_guardian", "보호자와 함께 확인"],
        ["legal_representative", "적법한 대리인이 확인"],
      ].map(([value, label]) => <Choice key={value} selected={mode === value} title={label} onClick={() => update({ consent_mode: value })} />)}
    </div>}
    <div className="consent-list">
      {COMMON_CONSENTS.map(([type, title, detail]) => <label key={type}>
        <input type="checkbox" checked={selected.has(type)} onChange={() => toggle(type)} />
        <span><b>{title}</b><small>{detail}</small></span>
      </label>)}
    </div>
    <button type="button" className="consent-all" onClick={() => update({ consent_types: COMMON_CONSENTS.map(([type]) => type) })}>필수 항목 모두 확인</button>
    <p className="journey-legal">동의를 거부할 수 있지만 얼굴·목소리 기반 통화와 돌봄 기록 기능은 제한될 수 있어요. 상세 처리업체·국가·보유 기간은 개인정보 처리방침에서 확인할 수 있습니다.</p>
  </>;
}

function CompactFamilyConsent({ data, update }) {
  const [expanded, setExpanded] = useState(false);
  const selected = new Set(data.consent_types || []);
  const allSelected = selected.size === COMMON_CONSENTS.length;
  const toggle = (type) => {
    const next = new Set(selected);
    if (next.has(type)) next.delete(type); else next.add(type);
    update({ consent_types: [...next] });
  };
  return <section className="journey-compact-consent">
    <div className="journey-section-heading">
      <div><b>개인정보 확인</b></div>
      <button type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? "접기" : "자세히 보기"}</button>
    </div>
    <label className="journey-consent-main">
      <input
        type="checkbox"
        checked={allSelected}
        onChange={() => update({ consent_types: allSelected ? [] : COMMON_CONSENTS.map(([type]) => type) })}
      />
      <span><b>필수 내용에 모두 동의합니다</b><small>광고·판매·공개·범용 AI 학습에는 사용하지 않아요.</small></span>
    </label>
    {expanded && <div className="consent-list compact">
      {COMMON_CONSENTS.map(([type, title, detail]) => <label key={type}>
        <input type="checkbox" checked={selected.has(type)} onChange={() => toggle(type)} />
        <span><b>{title}</b><small>{detail}</small></span>
      </label>)}
      <p className="journey-legal">동의를 거부할 수 있지만 얼굴·목소리 통화와 돌봄 기록 기능은 제한될 수 있어요. 처리업체·국가·보유 기간은 개인정보 처리방침에서 확인할 수 있습니다.</p>
    </div>}
  </section>;
}

export default function RoleOnboardingScreen({
  role,
  account,
  elderId = "elder_001",
  theme = "light",
  size = 100,
  onTheme,
  onSize,
  onDone,
  onCancel,
}) {
  const steps = STEPS[role];
  const [index, setIndex] = useState(0);
  const [data, setData] = useState({
    elder_id: "",
    consent_types: [],
    consent_mode: role === "care" ? "staff" : role === "elder" ? "with_guardian" : "self",
    ...(role === "elder" ? {
      setup_mode: "with_family",
      display_theme: theme,
      display_size: normalizeDisplaySize(size),
    } : {}),
  });
  const [elders, setElders] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [photoPreview, setPhotoPreview] = useState("");
  const [ageAdvancing, setAgeAdvancing] = useState(false);
  const [issuedLink, setIssuedLink] = useState(null);
  const [careAddOpen, setCareAddOpen] = useState(false);
  const [careElderName, setCareElderName] = useState("");
  const fileRef = useRef(null);
  const step = steps[index];
  const meta = ROLE_META[role];

  useEffect(() => {
    let alive = true;
    Promise.all([api.getOnboarding(role), api.getElders(), api.getPersonas(elderId)])
      .then(([saved, elderResult, personaResult]) => {
        if (!alive) return;
        const savedIndex = Math.max(0, steps.indexOf(saved.current_step));
        const currentFlowComplete = role === "care"
          ? Boolean(saved.complete)
          : Boolean(saved.complete && saved.data?.onboarding_version === ONBOARDING_FLOW_VERSION);
        setIndex(currentFlowComplete ? steps.length - 1 : saved.complete ? 0 : savedIndex);
        setData((current) => {
          const savedData = saved.data || {};
          const nextData = { ...current, ...savedData };
          if (role === "elder" && savedData.onboarding_version !== ONBOARDING_FLOW_VERSION) {
            nextData.display_size = normalizeDisplaySize(savedData.display_size || size);
          }
          return nextData;
        });
        setElders(elderResult.elders || []);
        setPersonas(personaResult.personas || []);
      })
      .catch((reason) => setError(reason.message))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [role, elderId]);

  useEffect(() => {
    if (!data.elder_id) return;
    let alive = true;
    api.getPersonas(data.elder_id)
      .then(({ personas: rows }) => alive && setPersonas(rows || []))
      .catch(() => {});
    return () => { alive = false; };
  }, [data.elder_id]);

  useEffect(() => () => photoPreview && URL.revokeObjectURL(photoPreview), [photoPreview]);

  const selectedElder = useMemo(
    () => elders.find((item) => item.elder_id === data.elder_id) || elders[0],
    [elders, data.elder_id]
  );
  const selectedPersona = useMemo(
    () => personas.find((item) => item.persona_id === data.persona_id),
    [personas, data.persona_id]
  );
  const isDaewoongDemo = useMemo(
    () => /대웅/.test(`${data.display_name || ""} ${account.display_name || ""}`),
    [data.display_name, account.display_name]
  );
  const update = (patch) => setData((current) => ({ ...current, ...patch }));

  async function persist(nextIndex, patch = {}, complete = false) {
    const merged = {
      ...data,
      ...patch,
      ...(complete && role !== "care" ? { onboarding_version: ONBOARDING_FLOW_VERSION } : {}),
    };
    const nextStep = complete ? steps[steps.length - 1] : steps[nextIndex];
    const saved = await api.saveOnboarding(role, {
      current_step: nextStep,
      data: merged,
      complete,
    });
    setData(saved.data || merged);
    setIndex(nextIndex);
    return saved;
  }

  function applyDisplay({ nextTheme = data.display_theme || theme, nextSize = data.display_size || size } = {}) {
    update({ display_theme: nextTheme, display_size: nextSize });
    onTheme?.(nextTheme);
    onSize?.(nextSize);
  }

  async function checkMediaPermissions() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("이 기기에서는 카메라와 마이크 권한을 확인할 수 없어요.");
      return;
    }
    setBusy(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
      stream.getTracks().forEach((track) => track.stop());
      update({ media_permissions_ready: true });
    } catch {
      update({ media_permissions_ready: false });
      setError("카메라와 마이크 사용을 허용한 뒤 다시 확인해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  function playSoundCheck() {
    setError("");
    if (!("speechSynthesis" in window)) {
      setError("이 기기에서는 소리 확인 안내를 재생할 수 없어요.");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance("다소니 목소리가 잘 들리시나요?");
    utterance.lang = "ko-KR";
    utterance.rate = .82;
    window.speechSynthesis.speak(utterance);
    update({ sound_checked: true });
  }

  async function addCareElder(event) {
    event.preventDefault();
    const name = careElderName.trim();
    if (!name) {
      setError("추가할 어르신 이름을 입력해 주세요.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const created = await api.addElder({
        name,
        preferred_call_name: "어르신",
        persona_name: "가족",
        relationship: "가족",
      });
      const added = { ...created, diagnosis_label: "진단 정보 미등록" };
      setElders((current) => [...current.filter((item) => item.elder_id !== added.elder_id), added]);
      update({ elder_id: added.elder_id, elder_name: added.name });
      setCareElderName("");
      setCareAddOpen(false);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function next() {
    setError("");
    setBusy(true);
    try {
      let stepPatch = {};
      if (step === "family_setup") {
        const displayName = (data.display_name || account.display_name || "").trim();
        if ((data.consent_types || []).length !== COMMON_CONSENTS.length) {
          throw new Error("필수 개인정보 내용을 확인해 주세요.");
        }
        if (!displayName || !data.relationship?.trim() || !data.elder_calls_family?.trim() || !data.family_calls_elder?.trim()) {
          throw new Error("관계와 호칭을 모두 입력해 주세요.");
        }
        const linkedElderId = data.elder_id || elderId || elders[0]?.elder_id;
        const linkedElder = elders.find((item) => item.elder_id === linkedElderId);
        if (!linkedElderId) throw new Error("등록할 어르신 정보를 찾지 못했어요.");
        await api.saveConsents({
          role,
          consent_types: data.consent_types,
          consent_version: CONSENT_VERSION,
          consent_mode: "self",
          elder_id: linkedElderId,
        });
        let personaId = data.persona_id;
        if (!personaId) {
          const result = await api.addPersona(linkedElderId, {
            display_name: displayName,
            relationship: data.relationship.trim(),
            elder_calls_family: data.elder_calls_family.trim(),
            family_calls_elder: data.family_calls_elder.trim(),
          });
          personaId = result.persona.persona_id;
        }
        stepPatch = {
          elder_id: linkedElderId,
          elder_name: data.elder_name || linkedElder?.name || "고길동",
          persona_id: personaId,
          display_name: displayName,
        };
      }
      if (step === "family_avatar") {
        if (!data.selected_photo && !selectedPersona?.face) {
          throw new Error("본인 얼굴 사진을 등록하고 대표 사진을 골라 주세요.");
        }
        if (isDaewoongDemo && !data.demo_age_complete) {
          throw new Error("연령별 얼굴을 마지막 단계까지 확인해 주세요.");
        }
        const callStyleResult = calculateCallStyle(data.call_style_answers || {});
        if (!callStyleResult) throw new Error("말투 질문 6개에 모두 답해 주세요.");
        const callStylePatch = callStylePersonaPatch(callStyleResult, data.call_style_answers);
        await api.patchPersona(callStylePatch, data.persona_id, data.elder_id);
        stepPatch = callStylePatch;
      }
      if (step === "family_voice") {
        const profile = await api.getVoiceProfile(data.persona_id, data.elder_id);
        if (!data.use_default_voice && !profile.active_voice_type && (profile.ivc_prompts_ready || []).length < 2) {
          throw new Error("필수 목소리 녹음 2개를 저장한 뒤 완료해 주세요.");
        }
        await api.patchPersona({ active: true }, data.persona_id, data.elder_id);
        await persist(index, {}, true);
        onDone({ role, ...data, elderId: data.elder_id, personaId: data.persona_id });
        return;
      }
      if (step === "elder_consent") {
        if (!data.setup_mode) throw new Error("설정 방법을 선택해 주세요.");
        if ((data.consent_types || []).length !== COMMON_CONSENTS.length) {
          throw new Error("필수 개인정보 내용을 확인해 주세요.");
        }
        let consentElderId = data.elder_id || elderId || null;
        let elderName = data.elder_name || elders.find((item) => item.elder_id === consentElderId)?.name || "";
        if (!consentElderId) {
          const created = await api.addElder({
            name: account.display_name,
            preferred_call_name: "어르신",
            persona_name: "가족",
            relationship: "가족",
          });
          consentElderId = created.elder_id;
          elderName = created.name;
        }
        const consentMode = data.setup_mode === "with_family" ? "with_guardian" : "self";
        await api.saveConsents({
          role,
          consent_types: data.consent_types,
          consent_version: CONSENT_VERSION,
          consent_mode: consentMode,
          elder_id: consentElderId,
        });
        stepPatch = { elder_id: consentElderId, elder_name: elderName, consent_mode: consentMode };
      }
      if (step === "elder_display") {
        await api.patchElder({
          preferred_call_name: data.preferred_call_name || "어르신",
          hearing_support: Boolean(data.hearing_support),
          vision_support: Number(data.display_size || size) > 100,
        }, data.elder_id);
        stepPatch = {
          display_theme: data.display_theme || theme,
          display_size: data.display_size || size,
        };
      }
      if (step === "elder_ready") {
        await persist(index, {}, true);
        onDone({ role, ...data, elderId: data.elder_id, personaId: data.persona_id });
        return;
      }
      if (step === "care_setup") {
        const staffName = data.staff_name?.trim() || account.display_name?.trim() || "체험 담당자";
        if (!data.organization_code?.trim() || !data.job_title?.trim()) {
          throw new Error("기관 코드와 직무를 입력해 주세요.");
        }
        if ((data.consent_types || []).length !== COMMON_CONSENTS.length) {
          throw new Error("필수 개인정보 내용을 확인해 주세요.");
        }
        await api.saveConsents({
          role,
          consent_types: data.consent_types,
          consent_version: CONSENT_VERSION,
          consent_mode: "staff",
          elder_id: null,
        });
        stepPatch = { consent_mode: "staff", staff_name: staffName };
      }
      if (step === "care_assignment" && !data.elder_id) {
        throw new Error("담당 어르신을 선택해 주세요.");
      }
      if (step === "care_review") {
        await persist(index, {}, true);
        onDone({ role, ...data, elderId: data.elder_id, personaId: data.persona_id });
        return;
      }
      if (step === "intro" && role === "elder") {
        if (!data.setup_mode) throw new Error("설정 방법을 선택해 주세요.");
        stepPatch = {
          setup_mode: data.setup_mode,
          consent_mode: data.setup_mode === "with_family" ? "with_guardian" : "self",
        };
      }
      if (step === "consent") {
        if ((data.consent_types || []).length !== COMMON_CONSENTS.length) throw new Error("필수 동의 항목을 모두 확인해 주세요.");
        let consentElderId = data.elder_id || null;
        if (role === "elder" && !consentElderId) {
          const created = await api.addElder({
            name: account.display_name,
            preferred_call_name: "어르신",
            persona_name: "가족",
            relationship: "가족",
          });
          consentElderId = created.elder_id;
          stepPatch = { elder_id: created.elder_id, elder_name: created.name };
        }
        await api.saveConsents({
          role,
          consent_types: data.consent_types,
          consent_version: CONSENT_VERSION,
          consent_mode: data.consent_mode,
          elder_id: consentElderId,
        });
      }
      if (step === "connection") {
        if (!/^\d{6}$/.test(data.invite_code || "")) throw new Error("어르신 기기에 표시된 연결 번호 6자리를 입력해 주세요.");
        const linked = await api.verifyLinkCode(data.invite_code);
        stepPatch = { elder_id: linked.elder_id, elder_name: linked.name, invite_code: "" };
      }
      if (step === "relationship") {
        if (!data.display_name?.trim() || !data.relationship?.trim() || !data.elder_calls_family?.trim() || !data.family_calls_elder?.trim()) {
          throw new Error("이름, 관계와 서로 부르는 호칭을 모두 입력해 주세요.");
        }
        if (!data.persona_id) {
          const result = await api.addPersona(data.elder_id, {
            display_name: data.display_name.trim(), relationship: data.relationship.trim(),
            elder_calls_family: data.elder_calls_family.trim(), family_calls_elder: data.family_calls_elder.trim(),
          });
          stepPatch.persona_id = result.persona.persona_id;
        }
      }
      if (step === "photo" && !data.selected_photo && !selectedPersona?.face) throw new Error("본인 얼굴 사진을 등록하고 대표 사진을 골라 주세요.");
      if (step === "tone") {
        const callStyleResult = calculateCallStyle(data.call_style_answers || {});
        if (!callStyleResult) throw new Error("말투 질문 6개에 모두 답해 주세요.");
        const callStylePatch = callStylePersonaPatch(callStyleResult, data.call_style_answers);
        await api.patchPersona(callStylePatch, data.persona_id, data.elder_id);
        stepPatch = callStylePatch;
      }
      if (step === "voice") {
        const profile = await api.getVoiceProfile(data.persona_id, data.elder_id);
        if (!profile.active_voice_type && (profile.ivc_prompts_ready || []).length < 2) {
          throw new Error("필수 목소리 녹음 2개를 저장한 뒤 계속해 주세요.");
        }
      }
      if (step === "comfort") {
        await api.patchElder({
          preferred_call_name: data.preferred_call_name || "어르신",
          hearing_support: Boolean(data.hearing_support),
          vision_support: Boolean(data.vision_support),
        }, data.elder_id);
        stepPatch = {
          display_theme: data.display_theme || theme,
          display_size: data.display_size || size,
          media_permissions_ready: Boolean(data.media_permissions_ready),
          sound_checked: Boolean(data.sound_checked),
        };
      }
      if (step === "organization" && (!data.organization_code?.trim() || !data.staff_name?.trim() || !data.job_title?.trim())) {
        throw new Error("기관 코드, 직원 이름과 직무를 모두 입력해 주세요.");
      }
      if (step === "assignment" && !data.elder_id) throw new Error("담당 어르신을 선택해 주세요.");
      if (step === "review") {
        await persist(index, {}, true);
        onDone({ role, ...data, elderId: data.elder_id, personaId: data.persona_id });
        return;
      }
      await persist(Math.min(index + 1, steps.length - 1), stepPatch);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function back() {
    if (index === 0) return onCancel();
    setError("");
    setBusy(true);
    try { await persist(index - 1); } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  async function uploadPhotos(files) {
    if (!files?.length) return;
    const list = [...files].slice(0, 6);
    setError("");
    setBusy(true);
    if (photoPreview) URL.revokeObjectURL(photoPreview);
    setPhotoPreview(URL.createObjectURL(list[0]));
    try {
      const result = await api.uploadIdentityPhotos(list, data.persona_id);
      if (result.errors?.length) throw new Error(result.errors[0].error);
      const candidates = result.identity_photos?.photos || [];
      update({
        photo_ready: true,
        photo_count: result.identity_photos?.count || list.length,
        photo_candidates: candidates,
        selected_photo: "",
        face_job: candidates.length ? "waiting_selection" : "needs_review",
      });
    } catch (reason) {
      setError(reason.message);
      update({ photo_ready: false });
    } finally {
      setBusy(false);
    }
  }

  async function confirmFamilyAvatarPhoto(photo) {
    setError("");
    update({
      selected_photo: photo.name,
      face_job: "requesting",
      demo_age_index: isDaewoongDemo ? 0 : undefined,
      demo_age_complete: false,
      demo_age_selections: {},
    });
    try {
      await api.confirmAvatarPhoto(data.persona_id, photo.name, data.elder_id);
      update({ face_job: "processing" });
    } catch (reason) {
      update({ face_job: "needs_review" });
      setError(reason.message);
    }
  }

  function chooseDemoAgeCandidate(stage, filename) {
    if (ageAdvancing) return;
    const currentIndex = Number(data.demo_age_index || 0);
    const selections = { ...(data.demo_age_selections || {}), [stage.age]: filename };
    const complete = currentIndex >= DAEWOONG_DEMO_AGE_STAGES.length - 1;
    update({ demo_age_selections: selections });
    setAgeAdvancing(true);
    window.setTimeout(() => {
      update({
        demo_age_selections: selections,
        demo_age_index: complete ? DAEWOONG_DEMO_AGE_STAGES.length : currentIndex + 1,
        demo_age_complete: complete,
        face_job: complete ? "ready" : "processing",
      });
      setAgeAdvancing(false);
    }, 420);
  }

  function revisitDemoAgeStage(nextIndex) {
    if (ageAdvancing) return;
    if (nextIndex < 0 || nextIndex >= DAEWOONG_DEMO_AGE_STAGES.length) return;
    const currentIndex = Math.min(Number(data.demo_age_index || 0), DAEWOONG_DEMO_AGE_STAGES.length - 1);
    const wasVisited = nextIndex <= currentIndex || Boolean(data.demo_age_selections?.[DAEWOONG_DEMO_AGE_STAGES[nextIndex].age]);
    if (!wasVisited) return;
    update({ demo_age_index: nextIndex, demo_age_complete: false, face_job: "processing" });
  }

  if (loading) return <main className="journey-screen journey-loading"><BrandMark size={86} /><p>완료한 설정을 불러오고 있어요…</p></main>;

  return <main className={`journey-screen journey-${role}`}>
    <header className="journey-header">
      <button type="button" onClick={back} aria-label="이전 단계">←</button>
      <BrandMark size={58} />
      {role === "child"
        ? <div className="journey-avatar-heading"><small>{account.display_name}님의 가족 설정</small><b><i className={data.face_job === "ready" && (!isDaewoongDemo || data.demo_age_complete) ? "ready" : "waiting"} aria-hidden="true">{data.face_job === "ready" && (!isDaewoongDemo || data.demo_age_complete) ? "✓" : "⌛"}</i> {data.face_job === "ready" && (!isDaewoongDemo || data.demo_age_complete) ? "아바타 준비 완료" : "아바타 생성 중"}</b></div>
        : <div><small>{account.display_name}님의 {meta.label} 설정</small><b>{meta.title}</b></div>}
      <span>{index + 1}/{steps.length}</span>
    </header>
    <div className="journey-progress" aria-label={`전체 ${steps.length}단계 중 ${index + 1}단계`}><i style={{ width: `${((index + 1) / steps.length) * 100}%` }} /></div>

    <section className="journey-card">
      {step === "elder_consent" && <div className="journey-elder-compact">
        <header className="journey-copy journey-elder-consent-title">
          <h2>안심하고 시작할게요</h2>
        </header>
        <section className="journey-family-section">
          <div className="journey-section-heading"><div><b>누구와 확인할까요?</b></div></div>
          <div className="journey-mode-grid compact">
            <Choice
              selected={data.setup_mode === "with_family"}
              title="가족과 함께"
              detail="가족이 옆에서 도와드려요"
              onClick={() => update({ setup_mode: "with_family" })}
            />
            <Choice
              selected={data.setup_mode === "self"}
              title="직접 확인"
              detail="한 단계씩 직접 확인해요"
              onClick={() => update({ setup_mode: "self" })}
            />
          </div>
        </section>
        <CompactFamilyConsent data={data} update={update} />
      </div>}

      {step === "elder_display" && <div className="journey-elder-compact">
        {personas.some((item) => item.ready) && <div className="journey-family-grid compact">{personas.filter((item) => item.ready).map((person) => <article key={person.persona_id}>{person.face ? <img src={person.face} alt="" /> : <span>{person.display_name?.[0]}</span>}<b>{person.display_name}</b><small>{person.relationship}</small></article>)}</div>}
        <div className="journey-fields compact"><label>가족이 나를 부르는 말<input value={data.preferred_call_name || "할아버지"} onChange={(event) => update({ preferred_call_name: event.target.value })} /></label></div>
        <section className="journey-display-setting compact">
          <h3>글씨 크기</h3>
          <div className="journey-display-slider">
            <div><span>작게</span><strong>{Number(data.display_size || size)}%</strong><span>크게</span></div>
            <input
              type="range"
              min={SIZE_MIN}
              max={SIZE_MAX}
              step={SIZE_STEP}
              value={Number(data.display_size || size)}
              aria-label="글씨 크기"
              onChange={(event) => applyDisplay({ nextSize: Number(event.target.value) })}
            />
          </div>
        </section>
        <section className="journey-display-setting compact">
          <h3>화면 보기</h3>
          <div className="journey-display-theme-options">
            {THEMES.map((item) => <button
              type="button"
              key={item.id}
              className={(data.display_theme || theme) === item.id ? "selected" : ""}
              aria-pressed={(data.display_theme || theme) === item.id}
              onClick={() => applyDisplay({ nextTheme: item.id })}
            ><b>{item.label}</b><small>{item.description}</small></button>)}
          </div>
        </section>
      </div>}

      {step === "elder_ready" && <div className="journey-elder-compact">
        <header className="journey-copy journey-elder-ready-title">
          <h2>소리와 통화를 한번 확인해요</h2>
        </header>
        <section className="journey-device-checks journey-device-checks-plain">
          <div><b>안내 목소리를 들어 보세요</b></div>
          <button type="button" className={data.sound_checked ? "ready" : ""} onClick={playSoundCheck}>{data.sound_checked ? "확인 완료" : "소리 듣기"}</button>
          <div><b>영상통화 권한을 확인해요</b></div>
          <button type="button" className={data.media_permissions_ready ? "ready" : ""} disabled={busy} onClick={checkMediaPermissions}>{data.media_permissions_ready ? "확인 완료" : "권한 확인"}</button>
        </section>
        <div className="journey-practice compact journey-family-practice">
          {personas.find((item) => item.ready)?.face
            ? <img src={personas.find((item) => item.ready).face} alt="정훈" />
            : <span>정훈</span>}
          <div><b>가족 얼굴을 누르면 전화해요</b></div>
        </div>
      </div>}

      {step === "family_setup" && <>
        <section className={`journey-family-section${isDaewoongDemo && data.selected_photo && !data.demo_age_complete ? " journey-age-stage" : ""}`}>
          <div className="journey-section-heading"><div><b>관계와 호칭</b></div></div>
          <div className="journey-fields two"><label>내 이름<input value={data.display_name || account.display_name || ""} onChange={(event) => update({ display_name: event.target.value })} /></label><label>어르신과의 관계<input placeholder="예: 아들" value={data.relationship || ""} onChange={(event) => update({ relationship: event.target.value })} /></label><label>어르신이 나를 부르는 말<input placeholder="예: 대웅아" value={data.elder_calls_family || ""} onChange={(event) => update({ elder_calls_family: event.target.value })} /></label><label>내가 어르신을 부르는 말<input placeholder="예: 할아버지" value={data.family_calls_elder || ""} onChange={(event) => update({ family_calls_elder: event.target.value })} /></label></div>
        </section>
        <CompactFamilyConsent data={data} update={update} />
      </>}

      {step === "family_avatar" && <>
        <section className="journey-family-section">
          {!isDaewoongDemo || !data.selected_photo ? <>
            <div className="journey-section-heading"><div><b>현재 28세 얼굴 사진</b><small>먼저 지금 모습을 가장 잘 보여주는 사진을 골라 주세요.</small></div></div>
            <div className="journey-photo-upload compact" onClick={() => fileRef.current?.click()}>{photoPreview || selectedPersona?.face ? <img src={photoPreview || selectedPersona.face} alt="등록한 현재 얼굴 미리보기" /> : <span>＋<small>사진 선택</small></span>}<input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(event) => uploadPhotos(event.target.files)} /></div>
            {(data.photo_candidates || []).length > 0 && <div className="journey-photo-candidates" aria-label="현재 얼굴 사진 후보">{data.photo_candidates.map((photo) => <button type="button" key={photo.name} className={data.selected_photo === photo.name ? "selected" : ""} onClick={() => confirmFamilyAvatarPhoto(photo)}><img src={photo.url} alt="현재 얼굴 사진 후보" /><span>{data.selected_photo === photo.name ? "선택됨" : "이 사진 선택"}</span></button>)}</div>}
            {data.photo_ready && <div className={`journey-job ${data.face_job || "waiting_selection"}`}><i /><span><b>{data.face_job === "needs_review" ? "사진을 다시 확인해 주세요" : data.face_job === "waiting_selection" ? "28세 대표 사진을 골라 주세요" : "현재 얼굴을 확인했어요"}</b><small>선택하면 연령별 얼굴을 차례로 확인해요.</small></span></div>}
          </> : data.demo_age_complete ? <div className="journey-age-complete">
            <div className="journey-age-complete-faces" aria-hidden="true">
              {[24, 17, 12, 8].map((age) => {
                const stage = DAEWOONG_DEMO_AGE_STAGES.find((item) => item.age === age);
                const filename = data.demo_age_selections?.[age] || stage.recommended;
                return <img key={age} src={`${DAEWOONG_DEMO_ASSET_ROOT}/${filename}`} alt="" />;
              })}
            </div>
            <span aria-hidden="true">✓</span>
            <h3>시간 여행 얼굴을 모두 골랐어요</h3>
            <button type="button" onClick={() => update({ demo_age_index: 0, demo_age_complete: false, face_job: "processing" })}>선택 다시 보기</button>
          </div> : (() => {
            const stageIndex = Math.min(Number(data.demo_age_index || 0), DAEWOONG_DEMO_AGE_STAGES.length - 1);
            const stage = DAEWOONG_DEMO_AGE_STAGES[stageIndex];
            const selected = data.demo_age_selections?.[stage.age];
            return <div className="journey-age-picker">
              <div className="journey-age-picker-heading">
                <h3>{stage.age}세 얼굴을 골라 주세요</h3>
              </div>
              <div className="journey-age-candidates">
                {stage.candidates.map((filename, candidateIndex) => <button
                  type="button"
                  key={filename}
                  className={selected === filename ? "selected" : ""}
                  disabled={ageAdvancing}
                  onClick={() => chooseDemoAgeCandidate(stage, filename)}
                >
                  <img src={`${DAEWOONG_DEMO_ASSET_ROOT}/${filename}`} alt={`${stage.age}세 얼굴 후보 ${candidateIndex + 1}`} />
                  {filename === stage.recommended && <em>AI 추천</em>}
                  <span>{selected === filename ? "선택했어요" : `후보 ${candidateIndex + 1}`}</span>
                </button>)}
              </div>
              <nav className="journey-age-arrows" aria-label="연령별 얼굴 이동">
                <button type="button" disabled={stageIndex === 0 || ageAdvancing} onClick={() => revisitDemoAgeStage(stageIndex - 1)} aria-label="이전 연령 얼굴 보기">←</button>
                <button type="button" disabled={stageIndex >= DAEWOONG_DEMO_AGE_STAGES.length - 1 || !data.demo_age_selections?.[DAEWOONG_DEMO_AGE_STAGES[stageIndex + 1]?.age] || ageAdvancing} onClick={() => revisitDemoAgeStage(stageIndex + 1)} aria-label="다음 연령 얼굴 보기">→</button>
              </nav>
            </div>;
          })()}
        </section>
        {(!isDaewoongDemo || data.demo_age_complete) && <section className="journey-family-section">
          <CallStyleQuiz
            answers={data.call_style_answers || {}}
            onAnswers={(answers) => update({ call_style_answers: answers })}
            elderCallName={data.family_calls_elder || "어르신"}
          />
        </section>}
      </>}

      {step === "family_voice" && <>
        <section className="journey-family-section">
          <div className="journey-section-heading"><div><b>목소리 등록</b></div></div>
          {data.persona_id && <VoiceProfilePanel
            elderId={data.elder_id}
            personaId={data.persona_id}
            persona={{ display_name: data.display_name }}
            useDefaultVoice={Boolean(data.use_default_voice)}
            onUseDefaultVoice={() => update({ use_default_voice: true })}
          />}
        </section>
      </>}

      {step === "intro" && <>
        <header className="journey-copy"><p className="eyebrow">{STEP_LABELS[step]}</p><h2>{meta.title}</h2><p>한 번에 한 가지씩 확인하고, 완료한 단계는 자동으로 저장할게요. 중간에 앱을 닫아도 이 자리에서 다시 시작합니다.</p></header>
        <div className="journey-summary-list">
          {role === "elder" && <><span>1</span><p><b>쉬운 말로 동의 확인</b><small>본인·보호자·대리인 확인을 구분해 기록해요.</small></p><span>2</span><p><b>가족과 보기 설정</b><small>가족 호칭, 글자 크기와 명암을 맞춰요.</small></p><span>3</span><p><b>한 번 연습하고 통화 시작</b><small>누르면 가족에게 전화가 가는지 함께 확인해요.</small></p></>}
          {role === "child" && <><span>1</span><p><b>어르신과 관계 확인</b><small>잘못된 사람에게 얼굴과 목소리가 연결되지 않게 해요.</small></p><span>2</span><p><b>얼굴 생성 중 말투·목소리 설정</b><small>기다리는 시간을 다른 설정에 사용해요.</small></p><span>3</span><p><b>결과 확인 후 연결 승인</b><small>선택한 얼굴·목소리만 통화에 사용해요.</small></p></>}
          {role === "care" && <><span>1</span><p><b>기관과 직원 확인</b><small>관리자 초대와 담당 업무를 기록해요.</small></p><span>2</span><p><b>접근·보안 동의</b><small>허용된 어르신의 요약만 확인해요.</small></p><span>3</span><p><b>담당 어르신 배정</b><small>담당 변경 시 권한을 바로 회수할 수 있어요.</small></p></>}
        </div>
        {role === "elder" && <div className="journey-setup-mode">
          <p>누구와 함께 준비할까요?</p>
          <div className="journey-mode-grid">
            <Choice
              selected={data.setup_mode === "with_family"}
              title="가족과 함께 설정할게요"
              detail="동의와 가족 연결을 함께 확인해요 · 추천"
              onClick={() => update({ setup_mode: "with_family" })}
            />
            <Choice
              selected={data.setup_mode === "self"}
              title="직접 설정할게요"
              detail="설명을 한 단계씩 읽고 직접 진행해요"
              onClick={() => update({ setup_mode: "self" })}
            />
          </div>
        </div>}
      </>}

      {step === "consent" && <ConsentStep role={role} data={data} update={update} />}

      {step === "family" && <>
        <header className="journey-copy"><p className="eyebrow">연결된 가족 확인</p><h2>전화할 가족을<br />함께 확인해 볼까요?</h2><p>얼굴과 이름이 맞는지 보호자와 함께 확인해 주세요.</p></header>
        {personas.some((item) => item.ready) ? <div className="journey-family-grid">{personas.filter((item) => item.ready).map((person) => <article key={person.persona_id}>{person.face ? <img src={person.face} alt="" /> : <span>{person.display_name?.[0]}</span>}<b>{person.display_name}</b><small>{person.relationship}</small></article>)}</div> : <div className="journey-empty-family"><BrandMark size={66} /><p><b>아직 통화 준비를 마친 가족이 없어요</b><small>아래 연결 번호를 가족 휴대전화에 입력하면 얼굴·목소리 설정을 시작할 수 있어요.</small></p></div>}
        <label className="journey-confirm"><input type="checkbox" checked={Boolean(data.family_confirmed)} onChange={(event) => update({ family_confirmed: event.target.checked })} />현재 연결된 가족 상태를 확인했어요</label>
        <div className="journey-link-issue"><div><b>새 가족을 연결하려면</b><small>가족 휴대전화에서 입력할 6자리 번호를 만들어 주세요.</small></div>{issuedLink ? <strong>{issuedLink.code}</strong> : <button type="button" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { setIssuedLink(await api.issueLinkCode(data.elder_id)); } catch (reason) { setError(reason.message); } finally { setBusy(false); } }}>연결 번호 만들기</button>}</div>
      </>}

      {step === "comfort" && <>
        <header className="journey-copy"><p className="eyebrow">보기·듣기 설정</p><h2>어르신께 편한 화면으로<br />맞춰 드릴게요</h2></header>
        <div className="journey-fields"><label>가족이 나를 부르는 말<input value={data.preferred_call_name || "할아버지"} onChange={(event) => update({ preferred_call_name: event.target.value })} /></label></div>
        <section className="journey-comfort-group">
          <h3>글자 크기</h3>
          <div className="journey-size-grid">
            {[[100, "보통"], [120, "크게"], [140, "아주 크게"]].map(([value, label]) => <Choice
              key={value}
              selected={Number(data.display_size || size) === value}
              title={label}
              detail={`${value}%`}
              onClick={() => {
                update({ vision_support: value > 100 });
                applyDisplay({ nextSize: value });
              }}
            />)}
          </div>
        </section>
        <section className="journey-comfort-group">
          <h3>화면 명암</h3>
          <div className="journey-theme-grid">
            {[
              ["light", "편안하게", "따뜻한 밝은 화면"],
              ["contrast", "선명하게", "글자와 경계를 또렷하게"],
              ["soft", "눈부심 줄이기", "밝은 색과 강한 빛을 줄여요"],
            ].map(([value, title, detail]) => <Choice
              key={value}
              selected={(data.display_theme || theme) === value}
              title={title}
              detail={detail}
              onClick={() => applyDisplay({ nextTheme: value })}
            />)}
          </div>
        </section>
        <section className="journey-device-checks">
          <div><b>소리 확인</b><small>{data.sound_checked ? "안내 음성을 재생했어요" : "통화 안내가 잘 들리는지 확인해요"}</small></div>
          <button type="button" onClick={playSoundCheck}>소리 듣기</button>
          <div><b>카메라·마이크</b><small>{data.media_permissions_ready ? "사용할 준비가 됐어요" : "영상통화에 필요한 권한을 확인해요"}</small></div>
          <button type="button" className={data.media_permissions_ready ? "ready" : ""} disabled={busy} onClick={checkMediaPermissions}>{data.media_permissions_ready ? "확인 완료" : "권한 확인"}</button>
        </section>
        <label className="journey-confirm"><input type="checkbox" checked={Boolean(data.hearing_support)} onChange={(event) => update({ hearing_support: event.target.checked })} />안내 음성을 천천히 또렷하게 들을게요</label>
      </>}

      {step === "practice" && <>
        <header className="journey-copy"><p className="eyebrow">한 번만 연습해요</p><h2>얼굴 카드를 누르면<br />바로 가족에게 전화해요</h2><p>20~30초 이상 기다리게 되면 연결 상태를 사실대로 알려 드리고, 다소니와 먼저 이야기할 수 있게 도와드려요.</p></header>
        <div className="journey-practice"><span>정훈</span><div><b>아들 정훈</b><small>카드 전체를 눌러 전화하기</small></div><i>☎</i></div>
        <label className="journey-confirm"><input type="checkbox" checked={Boolean(data.practice_confirmed)} onChange={(event) => update({ practice_confirmed: event.target.checked })} />직접 눌러 보는 방법을 확인했어요</label>
      </>}

      {step === "connection" && <>
        <header className="journey-copy"><p className="eyebrow">어르신 연결</p><h2>누구를 위해 준비하는지<br />먼저 확인할게요</h2><p>어르신 기기에서 만든 연결 번호를 입력하면 얼굴·목소리가 다른 분에게 잘못 연결되는 것을 막을 수 있어요.</p></header>
        <label className="journey-code journey-code-large"><span>어르신 기기의 연결 번호 6자리</span><input inputMode="numeric" maxLength={6} placeholder="000000" value={data.invite_code || ""} onChange={(event) => update({ invite_code: event.target.value.replace(/\D/g, "").slice(0, 6) })} /></label>
      </>}

      {step === "relationship" && <>
        <header className="journey-copy"><p className="eyebrow">관계와 호칭</p><h2>서로 평소에 부르는 말을<br />그대로 알려 주세요</h2></header>
        <div className="journey-fields two"><label>내 이름<input value={data.display_name || account.display_name || ""} onChange={(event) => update({ display_name: event.target.value })} /></label><label>어르신과의 관계<input placeholder="예: 아들" value={data.relationship || ""} onChange={(event) => update({ relationship: event.target.value })} /></label><label>어르신이 나를 부르는 말<input placeholder="예: 정훈아" value={data.elder_calls_family || ""} onChange={(event) => update({ elder_calls_family: event.target.value })} /></label><label>내가 어르신을 부르는 말<input placeholder="예: 아버지" value={data.family_calls_elder || ""} onChange={(event) => update({ family_calls_elder: event.target.value })} /></label></div>
      </>}

      {step === "photo" && <>
        <header className="journey-copy"><p className="eyebrow">얼굴 사진 등록</p><h2>통화에서 보여 드릴<br />본인 사진을 골라 주세요</h2><p>정면 얼굴이 선명한 사진을 1~3장 고르면 후보 생성을 시작합니다. 생성하는 동안 다음 말투·목소리 설정을 계속할 수 있어요.</p></header>
        <div className="journey-photo-upload" onClick={() => fileRef.current?.click()}>{photoPreview || selectedPersona?.face ? <img src={photoPreview || selectedPersona.face} alt="등록한 얼굴 미리보기" /> : <span>＋<small>사진 선택</small></span>}<input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(event) => uploadPhotos(event.target.files)} /></div>
        {(data.photo_candidates || []).length > 0 && <div className="journey-photo-candidates" aria-label="대표 사진 후보">{data.photo_candidates.map((photo) => <button type="button" key={photo.name} className={data.selected_photo === photo.name ? "selected" : ""} onClick={() => confirmFamilyAvatarPhoto(photo)}><img src={photo.url} alt="대표 사진 후보" /><span>{data.selected_photo === photo.name ? "선택됨" : "선택"}</span></button>)}</div>}
        {data.photo_ready && <div className={`journey-job ${data.face_job || "waiting_selection"}`}><i /><span><b>{data.face_job === "ready" ? "선택한 얼굴을 통화에 사용할 준비가 됐어요" : data.face_job === "needs_review" ? "사진을 등록했어요 · 생성 상태를 설정에서 다시 확인해 주세요" : data.face_job === "waiting_selection" ? "통화에 사용할 대표 사진을 골라 주세요" : "선택한 사진으로 얼굴을 준비하고 있어요"}</b><small>생성이 시작되면 다음 말투·목소리 설정을 계속 진행해도 됩니다.</small></span></div>}
      </>}

      {step === "tone" && <>
        <CallStyleQuiz
          answers={data.call_style_answers || {}}
          onAnswers={(answers) => update({ call_style_answers: answers })}
          elderCallName={data.family_calls_elder || "어르신"}
        />
      </>}

      {step === "voice" && <>
        <header className="journey-copy"><p className="eyebrow">목소리 등록과 학습</p><h2>AI 통화에 사용할<br />목소리를 등록하세요</h2><p>본인 목소리만 등록할 수 있어요. 두 녹음의 품질이 확인되면 얼굴 후보 생성 상태와 관계없이 다음으로 이동할 수 있습니다.</p></header>
        {data.persona_id && <VoiceProfilePanel elderId={data.elder_id} personaId={data.persona_id} persona={{ display_name: data.display_name }} />}
      </>}

      {(step === "organization" || step === "care_setup") && <>
        <header className="journey-copy"><p className="eyebrow">기관·직원 확인</p></header>
        <div className="journey-fields"><label>기관 코드 또는 관리자 초대<input placeholder="기관 코드를 입력해 주세요" value={data.organization_code || ""} onChange={(event) => update({ organization_code: event.target.value })} /></label><label>직원 이름<input value={data.staff_name || account.display_name || ""} onChange={(event) => update({ staff_name: event.target.value })} /></label><label>직무<input placeholder="예: 요양보호사" value={data.job_title || ""} onChange={(event) => update({ job_title: event.target.value })} /></label></div>
        {step === "care_setup" && <CompactFamilyConsent data={data} update={update} />}
      </>}

      {(step === "assignment" || step === "care_assignment") && <>
        <header className="journey-copy"><p className="eyebrow">담당 어르신 배정</p></header>
        <div className="journey-elder-list journey-care-elder-list">
          {elders.map((elder) => <Choice key={elder.elder_id} selected={data.elder_id === elder.elder_id} title={`${elder.name} 어르신`} detail={elder.diagnosis_label || "진단 정보 미등록"} onClick={() => update({ elder_id: elder.elder_id, elder_name: elder.name })} />)}
          {careAddOpen ? <form className="journey-care-add-form" onSubmit={addCareElder}>
            <input autoFocus aria-label="추가할 어르신 이름" placeholder="어르신 이름" value={careElderName} onChange={(event) => setCareElderName(event.target.value)} />
            <button type="submit" disabled={busy}>추가</button>
            <button type="button" className="journey-care-add-cancel" onClick={() => { setCareAddOpen(false); setCareElderName(""); }}>취소</button>
          </form> : <button type="button" className="journey-care-add" onClick={() => setCareAddOpen(true)}>+ 추가하기</button>}
        </div>
      </>}

      {(step === "review" || step === "care_review") && <>
        {role === "care" && <header className="journey-copy journey-review-heading"><h2>최종 확인</h2></header>}
        <dl className="journey-review">
          <div><dt>사용 역할</dt><dd>{meta.label}</dd></div>
          <div><dt>연결된 어르신</dt><dd>{data.elder_name || selectedElder?.name || "고길동"} 어르신</dd></div>
          {role === "elder" && <><div><dt>화면 설정</dt><dd>글자 {data.display_size || size}% · {data.display_theme === "contrast" ? "선명하게" : data.display_theme === "soft" ? "눈부심 줄이기" : "편안하게"}</dd></div><div><dt>통화 준비</dt><dd>{data.media_permissions_ready ? "카메라·마이크 확인" : "권한은 통화 전에 확인"}</dd></div></>}
          {role === "child" && <><div><dt>관계·호칭</dt><dd>{data.relationship} · {data.family_calls_elder}</dd></div><div><dt>얼굴·목소리</dt><dd>{data.photo_ready ? "사진 등록" : "기존 사진"} · 목소리 품질 확인</dd></div></>}
          {role === "care" && <><div><dt>기관</dt><dd>{data.organization_code || "기관 확인 대기"}</dd></div><div><dt>직무</dt><dd>{data.job_title}</dd></div></>}
          <div><dt>개인정보 동의</dt><dd>{CONSENT_VERSION}{role !== "care" ? ` · ${data.consent_mode}` : ""}</dd></div>
        </dl>
      </>}

      {error && <p className="error journey-error" role="alert">{error}</p>}
      <footer className={`journey-actions${step === "care_review" ? " journey-care-review-actions" : ""}`}><button type="button" className="journey-secondary" onClick={back} disabled={busy}>{index === 0 ? "역할 다시 선택" : "이전"}</button><button type="button" className={`journey-primary${step === "care_review" ? " journey-care-complete" : ""}`} onClick={next} disabled={busy || (step === "family" && !data.family_confirmed) || (step === "practice" && !data.practice_confirmed)}>{busy ? "저장하는 중…" : step === "care_review" ? "메인으로" : step === "review" || step === "family_voice" || step === "elder_ready" ? `${meta.label} 메인으로` : "계속"}</button></footer>
    </section>
  </main>;
}
