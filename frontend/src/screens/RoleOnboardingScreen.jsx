import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api.js";
import BrandMark from "../components/BrandMark.jsx";
import VoiceProfilePanel from "../components/VoiceProfilePanel.jsx";

const CONSENT_VERSION = "2026-08-24.v1";

const COMMON_CONSENTS = [
  ["basic_profile", "기본 개인정보 수집·이용", "이름, 연락처, 가족 관계를 계정과 연결에 사용해요."],
  ["call_recording", "통화 녹음과 문자 변환", "대화를 이어가고 기록을 만들기 위해 통화 음성과 내용을 저장해요."],
  ["sensitive_care", "건강·인지·정서 관찰정보 이용", "돌봄에 필요한 변화만 허용된 가족과 담당자가 확인해요."],
  ["care_sharing", "가족·담당자에게 기록 공유", "연결 승인을 받은 사람에게만 요약과 확인 항목을 보여줘요."],
  ["overseas_processing", "해외 AI 서비스 처리", "음성·사진 처리에 사용하는 해외 서비스와 전송 항목을 확인했어요."],
  ["retention_deletion", "보유 기간·삭제와 동의 철회", "설정에서 보유 기간을 확인하고 삭제 또는 동의 철회를 요청할 수 있어요."],
];

const ROLE_META = {
  elder: { label: "어르신", title: "다소니를 함께 준비할게요" },
  child: { label: "가족", title: "가족 목소리와 얼굴을 준비할게요" },
  care: { label: "요양 담당자", title: "담당 어르신 돌봄 화면을 준비할게요" },
};

const STEPS = {
  elder: ["intro", "consent", "family", "comfort", "practice", "review"],
  child: ["intro", "consent", "connection", "relationship", "photo", "tone", "voice", "review"],
  care: ["intro", "organization", "consent", "assignment", "review"],
};

const STEP_LABELS = {
  intro: "시작", consent: "동의", family: "가족 확인", comfort: "보기 편하게",
  practice: "사용 연습", connection: "어르신 연결", relationship: "관계·호칭",
  photo: "얼굴 사진", tone: "말투 카드", voice: "목소리", organization: "기관 확인",
  assignment: "담당 배정", review: "마지막 확인",
};

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

export default function RoleOnboardingScreen({ role, account, elderId = "elder_001", onDone, onCancel }) {
  const steps = STEPS[role];
  const [index, setIndex] = useState(0);
  const [data, setData] = useState({ elder_id: "", consent_types: [], consent_mode: role === "care" ? "staff" : "self" });
  const [elders, setElders] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [photoPreview, setPhotoPreview] = useState("");
  const [issuedLink, setIssuedLink] = useState(null);
  const fileRef = useRef(null);
  const step = steps[index];
  const meta = ROLE_META[role];

  useEffect(() => {
    let alive = true;
    Promise.all([api.getOnboarding(role), api.getElders(), api.getPersonas(elderId)])
      .then(([saved, elderResult, personaResult]) => {
        if (!alive) return;
        const savedIndex = Math.max(0, steps.indexOf(saved.current_step));
        setIndex(saved.complete ? steps.length - 1 : savedIndex);
        setData((current) => ({ ...current, ...(saved.data || {}) }));
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
  const update = (patch) => setData((current) => ({ ...current, ...patch }));

  async function persist(nextIndex, patch = {}, complete = false) {
    const merged = { ...data, ...patch };
    const nextStep = complete ? "review" : steps[nextIndex];
    const saved = await api.saveOnboarding(role, {
      current_step: nextStep,
      data: merged,
      complete,
    });
    setData(saved.data || merged);
    setIndex(nextIndex);
    return saved;
  }

  async function next() {
    setError("");
    setBusy(true);
    try {
      let stepPatch = {};
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
        if (!data.tone) throw new Error("평소 말투와 가장 가까운 카드를 골라 주세요.");
        await api.patchPersona({ tone: data.tone }, data.persona_id, data.elder_id);
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
      }
      if (step === "organization" && (!data.organization_code?.trim() || !data.staff_name?.trim() || !data.job_title?.trim())) {
        throw new Error("기관 코드, 직원 이름과 직무를 모두 입력해 주세요.");
      }
      if (step === "assignment" && !data.elder_id) throw new Error("담당 어르신을 선택해 주세요.");
      if (step === "review") {
        if (role === "child" && data.persona_id) {
          const avatar = await api.getAvatarProfile(data.persona_id, data.elder_id);
          if (avatar.provider_configured && avatar.avatar_status === "creating") {
            throw new Error("얼굴 후보를 아직 만들고 있어요. 잠시 후 다시 확인해 주세요.");
          }
          if (avatar.provider_configured && avatar.avatar_status === "failed") {
            throw new Error("얼굴 생성 상태를 다시 확인해 주세요. 설정에서 사진을 바꿔 다시 시도할 수 있어요.");
          }
          await api.patchPersona({ active: true }, data.persona_id, data.elder_id);
        }
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

  if (loading) return <main className="journey-screen journey-loading"><BrandMark size={86} /><p>완료한 설정을 불러오고 있어요…</p></main>;

  return <main className={`journey-screen journey-${role}`}>
    <header className="journey-header">
      <button type="button" onClick={back} aria-label="이전 단계">←</button>
      <BrandMark size={58} />
      <div><small>{account.display_name}님의 {meta.label} 설정</small><b>{meta.title}</b></div>
      <span>{index + 1}/{steps.length}</span>
    </header>
    <div className="journey-progress" aria-label={`전체 ${steps.length}단계 중 ${index + 1}단계`}><i style={{ width: `${((index + 1) / steps.length) * 100}%` }} /></div>

    <section className="journey-card">
      {step === "intro" && <>
        <header className="journey-copy"><p className="eyebrow">{STEP_LABELS[step]}</p><h2>{meta.title}</h2><p>한 번에 한 가지씩 확인하고, 완료한 단계는 자동으로 저장할게요. 중간에 앱을 닫아도 이 자리에서 다시 시작합니다.</p></header>
        <div className="journey-summary-list">
          {role === "elder" && <><span>1</span><p><b>쉬운 말로 동의 확인</b><small>본인·보호자·대리인 확인을 구분해 기록해요.</small></p><span>2</span><p><b>가족과 보기 설정</b><small>가족 호칭, 글자 크기와 명암을 맞춰요.</small></p><span>3</span><p><b>한 번 연습하고 통화 시작</b><small>누르면 가족에게 전화가 가는지 함께 확인해요.</small></p></>}
          {role === "child" && <><span>1</span><p><b>어르신과 관계 확인</b><small>잘못된 사람에게 얼굴과 목소리가 연결되지 않게 해요.</small></p><span>2</span><p><b>얼굴 생성 중 말투·목소리 설정</b><small>기다리는 시간을 다른 설정에 사용해요.</small></p><span>3</span><p><b>결과 확인 후 연결 승인</b><small>선택한 얼굴·목소리만 통화에 사용해요.</small></p></>}
          {role === "care" && <><span>1</span><p><b>기관과 직원 확인</b><small>관리자 초대와 담당 업무를 기록해요.</small></p><span>2</span><p><b>접근·보안 동의</b><small>허용된 어르신의 요약만 확인해요.</small></p><span>3</span><p><b>담당 어르신 배정</b><small>담당 변경 시 권한을 바로 회수할 수 있어요.</small></p></>}
        </div>
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
        <div className="journey-mode-grid"><Choice selected={Boolean(data.vision_support)} title="글자를 더 크게" detail="버튼과 안내 글자를 크게 표시해요." onClick={() => update({ vision_support: !data.vision_support })} /><Choice selected={Boolean(data.hearing_support)} title="듣기 도움" detail="안내 음성을 더 천천히 또렷하게 재생해요." onClick={() => update({ hearing_support: !data.hearing_support })} /></div>
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
        {(data.photo_candidates || []).length > 0 && <div className="journey-photo-candidates" aria-label="대표 사진 후보">{data.photo_candidates.map((photo) => <button type="button" key={photo.name} className={data.selected_photo === photo.name ? "selected" : ""} onClick={() => { update({ selected_photo: photo.name, face_job: "processing" }); api.confirmAvatarPhoto(data.persona_id, photo.name, data.elder_id).then(() => update({ face_job: "processing" })).catch(() => update({ face_job: "needs_review" })); }}><img src={photo.url} alt="대표 사진 후보" /><span>{data.selected_photo === photo.name ? "선택됨" : "선택"}</span></button>)}</div>}
        {data.photo_ready && <div className={`journey-job ${data.face_job || "waiting_selection"}`}><i /><span><b>{data.face_job === "ready" ? "선택한 얼굴을 통화에 사용할 준비가 됐어요" : data.face_job === "needs_review" ? "사진을 등록했어요 · 생성 상태를 설정에서 다시 확인해 주세요" : data.face_job === "waiting_selection" ? "통화에 사용할 대표 사진을 골라 주세요" : "선택한 사진으로 얼굴을 준비하고 있어요"}</b><small>생성이 시작되면 다음 말투·목소리 설정을 계속 진행해도 됩니다.</small></span></div>}
      </>}

      {step === "tone" && <>
        <header className="journey-copy"><p className="eyebrow">말투 카드</p><h2>평소 가장 가까운<br />말투를 골라 주세요</h2></header>
        <div className="journey-tone-grid">{[
          ["따뜻하고 편안한 반말. 짧고 자연스럽게, 서두르지 않고 천천히 말한다.", "다정하고 편안하게", "“아버지, 오늘은 어땠어요?”"],
          ["차분한 높임말. 한 문장씩 또렷하게 말하고 충분히 기다린다.", "차분하고 또렷하게", "“오늘 식사는 하셨어요?”"],
          ["밝고 친근한 반말. 좋은 감정을 자연스럽게 표현하되 과장하지 않는다.", "밝고 친근하게", "“우리 천천히 얘기해 보자.”"],
          ["담백한 높임말. 사실 확인은 부드럽게 묻고 확인되지 않은 기억은 단정하지 않는다.", "담백하고 조심스럽게", "“같이 한번 확인해 볼까요?”"],
        ].map(([value, title, detail]) => <Choice key={title} selected={data.tone === value} title={title} detail={detail} onClick={() => update({ tone: value })} />)}</div>
      </>}

      {step === "voice" && <>
        <header className="journey-copy"><p className="eyebrow">목소리 등록과 학습</p><h2>AI 통화에 사용할<br />목소리를 등록하세요</h2><p>본인 목소리만 등록할 수 있어요. 두 녹음의 품질이 확인되면 얼굴 후보 생성 상태와 관계없이 다음으로 이동할 수 있습니다.</p></header>
        {data.persona_id && <VoiceProfilePanel elderId={data.elder_id} personaId={data.persona_id} persona={{ display_name: data.display_name }} />}
      </>}

      {step === "organization" && <>
        <header className="journey-copy"><p className="eyebrow">기관·직원 확인</p><h2>소속 기관과 담당 업무를<br />확인해 주세요</h2></header>
        <div className="journey-fields"><label>기관 코드 또는 관리자 초대<input placeholder="기관 코드를 입력해 주세요" value={data.organization_code || ""} onChange={(event) => update({ organization_code: event.target.value })} /></label><label>직원 이름<input value={data.staff_name || account.display_name || ""} onChange={(event) => update({ staff_name: event.target.value })} /></label><label>직무<input placeholder="예: 요양보호사" value={data.job_title || ""} onChange={(event) => update({ job_title: event.target.value })} /></label></div>
      </>}

      {step === "assignment" && <>
        <header className="journey-copy"><p className="eyebrow">담당 어르신 배정</p><h2>관리자가 배정한 어르신만<br />선택할 수 있어요</h2><p>이번 화면에서는 연결 구조를 확인할 수 있도록 현재 등록된 목록을 표시합니다.</p></header>
        <div className="journey-elder-list">{elders.map((elder) => <Choice key={elder.elder_id} selected={data.elder_id === elder.elder_id} title={`${elder.name} 어르신`} detail={elder.diagnosis_label || "진단 정보 미등록"} onClick={() => update({ elder_id: elder.elder_id, elder_name: elder.name })} />)}</div>
      </>}

      {step === "review" && <>
        <header className="journey-copy"><p className="eyebrow">마지막 확인</p><h2>준비가 끝났어요</h2><p>아래 내용은 나중에 설정에서 다시 바꾸거나 동의를 철회할 수 있어요.</p></header>
        <dl className="journey-review"><div><dt>사용 역할</dt><dd>{meta.label}</dd></div><div><dt>연결된 어르신</dt><dd>{data.elder_name || selectedElder?.name || "고길동"} 어르신</dd></div>{role === "child" && <><div><dt>관계·호칭</dt><dd>{data.relationship} · {data.family_calls_elder}</dd></div><div><dt>얼굴·목소리</dt><dd>{data.photo_ready ? "사진 등록" : "기존 사진"} · 목소리 품질 확인</dd></div></>}{role === "care" && <div><dt>기관·직무</dt><dd>{data.organization_code || "기관 확인 대기"} · {data.job_title}</dd></div>}<div><dt>개인정보 동의</dt><dd>{CONSENT_VERSION} · {data.consent_mode}</dd></div></dl>
      </>}

      {error && <p className="error journey-error" role="alert">{error}</p>}
      <footer className="journey-actions"><button type="button" className="journey-secondary" onClick={back} disabled={busy}>{index === 0 ? "역할 다시 선택" : "이전"}</button><button type="button" className="journey-primary" onClick={next} disabled={busy || (step === "family" && !data.family_confirmed) || (step === "practice" && !data.practice_confirmed)}>{busy ? "저장하는 중…" : step === "review" ? `${meta.label} 메인으로` : "계속"}</button></footer>
    </section>
  </main>;
}
