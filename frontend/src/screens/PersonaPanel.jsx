import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api.js";
import { calculateCallStyle, callStylePersonaPatch } from "../callStyle.js";
import CallStyleQuiz from "../components/CallStyleQuiz.jsx";

/**
 * 가족 페르소나 등록.
 *
 * 명세 FR-02 — 여기 등록한 말투와 호칭이 그대로 대화 규칙이 되고,
 * 올린 사진이 얼굴 모핑 영상의 재료가 된다.
 *
 * 서비스의 입구이므로 보호자가 한 화면에서 끝낼 수 있어야 한다.
 */

/** 줄 단위로 입력받아 배열로 저장한다. 보호자에게는 목록이 자연스럽다. */
const toLines = (arr) => (Array.isArray(arr) ? arr.join("\n") : arr || "");
const fromLines = (text) =>
  text.split("\n").map((s) => s.trim()).filter(Boolean);

const ageOnDate = (birthValue, photoValue) => {
  if (!birthValue || !photoValue) return null;
  const birth = new Date(`${birthValue}T00:00:00Z`);
  const photo = new Date(`${photoValue}T00:00:00Z`);
  if (Number.isNaN(birth.valueOf()) || Number.isNaN(photo.valueOf()) || photo < birth) {
    return null;
  }
  let age = photo.getUTCFullYear() - birth.getUTCFullYear();
  if (
    photo.getUTCMonth() < birth.getUTCMonth()
    || (photo.getUTCMonth() === birth.getUTCMonth() && photo.getUTCDate() < birth.getUTCDate())
  ) age -= 1;
  return age;
};

const validationStatusLabel = (status) => ({
  strong_pass: "강한 통과",
  borderline: "경계 통과",
  human_review: "사람 검토 필요",
  fail: "실패",
}[status] ?? "검증 전");

export default function PersonaPanel() {
  const [data, setData] = useState(null);
  const [personaTargets, setPersonaTargets] = useState([]);
  const [selectedPersonaId, setSelectedPersonaId] = useState("");
  const [persona, setPersona] = useState({});
  const [elder, setElder] = useState({});
  const [agePlan, setAgePlan] = useState({
    current_age: "",
    current_photo: null,
    birth_date: "",
    current_photo_date: "",
    biological_sex: "unspecified",
    population_group: "unspecified",
    stages: [],
  });
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [quizAnswers, setQuizAnswers] = useState({});
  const fileRef = useRef(null);
  const personaType = useMemo(() => calculateCallStyle(quizAnswers), [quizAnswers]);

  const load = (personaId = selectedPersonaId) =>
    Promise.all([api.getPersonas(), api.getPersona(personaId || undefined)])
      .then(([targetData, r]) => {
        setPersonaTargets(targetData.personas.filter((target) => target.ready));
        setData(r);
        setPersona(r.persona ?? {});
        setQuizAnswers(r.persona?.call_style_answers ?? {});
        setSelectedPersonaId(r.persona?.persona_id ?? "");
        setElder(r.elder ?? {});
        setAgePlan(r.age_plan ?? { current_age: "", current_photo: null, stages: [] });
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  async function guard(fn, message) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      await fn();
      setNote(message);
      await load(selectedPersonaId);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const savePersona = () =>
    guard(
      () =>
        api.patchPersona({
          display_name: persona.display_name,
          relationship_type: persona.relationship_type,
          elder_calls_family: persona.elder_calls_family,
          family_calls_elder: persona.family_calls_elder,
          tone: persona.tone,
          frequent_phrases: fromLines(toLines(persona.frequent_phrases)),
          forbidden_phrases: fromLines(toLines(persona.forbidden_phrases)),
          call_style_code: persona.call_style_code,
          call_style_name: persona.call_style_name,
          call_style_scores: persona.call_style_scores,
          call_style_answers: persona.call_style_answers,
        }, selectedPersonaId),
      "페르소나를 저장했어요."
    );

  const applyPersonaType = () => {
    if (!personaType) return;
    const stylePatch = callStylePersonaPatch(personaType, quizAnswers);
    setPersona({
      ...persona,
      ...stylePatch,
    });
    setNote(`${personaType.code} · ${personaType.name} 말투 초안을 적용했어요. 저장하면 실제 통화에 반영됩니다.`);
  };

  const saveElder = () =>
    guard(
      () =>
        api.patchElder({
          name: elder.name,
          preferred_call_name: elder.preferred_call_name,
          speech_wait_time_ms: Number(elder.speech_wait_time_ms) || 2000,
          hearing_support: Boolean(elder.hearing_support),
          anxiety_triggers: fromLines(toLines(elder.anxiety_triggers)),
          calming_phrases: fromLines(toLines(elder.calming_phrases)),
        }),
      "프로필을 저장했어요."
    );

  const upload = (files) =>
    files?.length &&
    guard(() => api.uploadFaces(files, selectedPersonaId), `사진 ${files.length}장을 올렸어요.`);

  const uploadIdentity = (files) => {
    if (!files?.length) return;
    const remaining = (data.identity_photos?.maximum ?? 6) -
      (data.identity_photos?.count ?? 0);
    if (files.length > remaining) {
      setError(`지금은 ${remaining}장만 더 올릴 수 있어요.`);
      return;
    }
    guard(async () => {
      const result = await api.uploadIdentityPhotos(files, selectedPersonaId);
      if (result.errors?.length) {
        await load();
        throw new Error(
          result.errors.map((item) => `${item.file}: ${item.error}`).join(" / ")
        );
      }
      if (fileRef.current) fileRef.current.value = "";
    }, `얼굴 사진 ${files.length}장을 검사했어요.`);
  };

  const prepare = () =>
    guard(async () => {
      const r = await api.prepareFaces(selectedPersonaId);
      if (!r.ok) throw new Error("정렬에 실패했어요. 사진 형식을 확인해 주세요.");
    }, "사진을 정렬했어요.");

  const saveAgePlan = () => {
    const hasBirthDate = Boolean(agePlan.birth_date);
    const hasPhotoDate = Boolean(agePlan.current_photo_date);
    if (hasBirthDate !== hasPhotoDate) {
      setError("생년월일과 현재 사진 촬영일은 함께 입력해 주세요.");
      return;
    }
    const datedAge = ageOnDate(agePlan.birth_date, agePlan.current_photo_date);
    const currentAge = datedAge ?? Number(agePlan.current_age);
    if (!Number.isInteger(currentAge) || currentAge < 18 || currentAge > 100) {
      setError("촬영일 기준 나이를 계산하거나 현재 나이를 18~100세로 입력해 주세요.");
      return;
    }
    if (!agePlan.current_photo) {
      setError("현재 모습을 대표할 정면 사진을 먼저 선택해 주세요.");
      return;
    }
    guard(
      () => api.saveAgePlan({
        current_age: currentAge,
        current_photo: agePlan.current_photo,
        birth_date: agePlan.birth_date || null,
        current_photo_date: agePlan.current_photo_date || null,
        biological_sex: agePlan.biological_sex || "unspecified",
        population_group: agePlan.population_group || "unspecified",
      }, selectedPersonaId),
      "현재 나이와 과거 얼굴 생성 순서를 저장했어요."
    );
  };

  const choosePastCandidate = (stage, candidate) => {
    if (
      candidate.validation
      && !candidate.validation.full_pass
      && !window.confirm(
        "이 후보는 자동 검증을 모두 통과하지 않았습니다. 검증 근거를 확인했고 보호자가 직접 승인합니까?"
      )
    ) return;
    guard(
      () => api.selectAgeCandidate(stage.age, candidate.name, selectedPersonaId),
      `${stage.age}세 후보를 선택했어요.`
    );
  };

  if (!data) return <p className="hint">불러오는 중…</p>;

  const faces = data.faces;
  const identity = data.identity_photos ?? {
    photos: [],
    count: 0,
    usable_count: 0,
    minimum: 3,
    maximum: 6,
    ready: false,
  };
  const statusLabel = {
    good: "좋음",
    warning: "확인 필요",
    rejected: "다시 선택",
  };

  return (
    <>
      <section className="meds">
        <h2>가족 페르소나</h2>
        <p className="hint">
          가족을 선택한 뒤 질문에 답하면, 각자의 말투와 호칭이 따로 통화에 쓰여요.
        </p>

        <div className="family-persona-selector" aria-label="설정할 가족 선택">
          {personaTargets.map((target) => (
            <button
              type="button"
              key={target.persona_id}
              className={selectedPersonaId === target.persona_id ? "selected" : ""}
              onClick={() => {
                setQuizAnswers({});
                setNote("");
                setSelectedPersonaId(target.persona_id);
                load(target.persona_id);
              }}
            >
              {target.face ? <img src={target.face} alt="" /> : <span>{target.display_name.slice(0, 1)}</span>}
              <strong>{target.display_name}</strong>
              <small>{target.relationship}</small>
              <i>{target.call_style_code ? `${target.call_style_code} · ${target.call_style_name}` : "통화 유형 미설정"}</i>
            </button>
          ))}
        </div>

        <div className="field-grid">
          <label>
            이름
            <input
              value={persona.display_name ?? ""}
              onChange={(e) =>
                setPersona({ ...persona, display_name: e.target.value })
              }
            />
          </label>
          <label>
            관계
            <input
              placeholder="손자"
              value={persona.relationship_type ?? ""}
              onChange={(e) =>
                setPersona({ ...persona, relationship_type: e.target.value })
              }
            />
          </label>
          <label>
            할아버지를 부르는 말
            <input
              placeholder="할아버지"
              value={persona.family_calls_elder ?? ""}
              onChange={(e) =>
                setPersona({ ...persona, family_calls_elder: e.target.value })
              }
            />
          </label>
          <label>
            할아버지가 나를 부르는 말
            <input
              placeholder="우리 대웅이"
              value={persona.elder_calls_family ?? ""}
              onChange={(e) =>
                setPersona({ ...persona, elder_calls_family: e.target.value })
              }
            />
          </label>
        </div>

        <CallStyleQuiz answers={quizAnswers} onAnswers={setQuizAnswers} onApply={applyPersonaType} />

        <details className="persona-advanced">
          <summary>적용된 말투와 문장 직접 조정</summary>
          <label className="block">
            말투
            <input
              placeholder="따뜻하고 편안한 반말. 서두르지 않고 천천히."
              value={persona.tone ?? ""}
              onChange={(e) => setPersona({ ...persona, tone: e.target.value })}
            />
          </label>

          <div className="field-grid">
            <label className="block">
              자주 쓰는 말 <span className="hint">한 줄에 하나씩</span>
              <textarea
                value={toLines(persona.frequent_phrases)}
                onChange={(e) =>
                  setPersona({ ...persona, frequent_phrases: e.target.value.split("\n") })
                }
              />
            </label>
            <label className="block">
              쓰면 안 되는 말 <span className="hint">한 줄에 하나씩</span>
              <textarea
                value={toLines(persona.forbidden_phrases)}
                onChange={(e) =>
                  setPersona({ ...persona, forbidden_phrases: e.target.value.split("\n") })
                }
              />
            </label>
          </div>
        </details>

        <button className="save" onClick={savePersona} disabled={busy}>
          페르소나 저장
        </button>
      </section>

      <section className="meds">
        <h2>현재 얼굴 사진 준비</h2>
        <p className="hint">
          같은 사람의 현재 사진을 3~6장 올려주세요. 정면 사진을 중심으로
          살짝 좌우를 본 사진과 미소 사진을 함께 올리면 얼굴을 더 안정적으로
          유지할 수 있어요. 사진은 외부 서비스로 전송되지 않습니다.
        </p>

        <div className="build-status">
          <span className={identity.ready ? "tag ok" : "tag warn"}>
            사용 가능 {identity.usable_count}/{identity.minimum}장
          </span>
          <span className="tag">최대 {identity.maximum}장</span>
          {identity.ready && <span className="tag ok">나이 변환 준비 완료</span>}
        </div>

        {identity.photos.length > 0 && (
          <div className="quality-grid">
            {identity.photos.map((photo) => (
              <article className="quality-card" key={photo.name}>
                <img className="quality-thumb" src={photo.url} alt="업로드한 얼굴" />
                <div className="quality-body">
                  <div className="quality-head">
                    <span className={`quality-status ${photo.quality.status}`}>
                      {statusLabel[photo.quality.status] ?? photo.quality.status}
                    </span>
                    <b>{photo.quality.score}점</b>
                    {photo.recommended && <span className="tag ok">대표 추천</span>}
                  </div>
                  <p className="row-meta">
                    {photo.quality.width}×{photo.quality.height} · 얼굴 {photo.quality.face_count}명
                  </p>
                  {photo.quality.issues?.length ? (
                    <ul className="quality-issues">
                      {photo.quality.issues.map((issue) => (
                        <li key={issue.code}>{issue.message}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="quality-good">선명도와 얼굴 위치가 적절해요.</p>
                  )}
                  <button
                    disabled={busy}
                    onClick={() => guard(
                      () => api.deleteIdentityPhoto(photo.name, selectedPersonaId),
                      "사진을 지웠어요."
                    )}
                  >
                    이 사진 지우기
                  </button>
                  <button
                    className={agePlan.current_photo === photo.name ? "master selected" : "master"}
                    disabled={busy || !photo.quality.usable}
                    onClick={() => setAgePlan({ ...agePlan, current_photo: photo.name })}
                  >
                    {agePlan.current_photo === photo.name ? "현재 기준으로 선택됨" : "현재 기준 사진으로 선택"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        <div className="med-form">
          <input
            ref={fileRef}
            type="file"
            accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
            multiple
            disabled={busy || identity.count >= identity.maximum}
            onChange={(event) => uploadIdentity(event.target.files)}
          />
        </div>
        <p className="hint">
          한 사람만 나오고, 얼굴이 크고 선명하며, 밝은 곳에서 찍은 사진이 좋아요.
          AI가 만든 사진이 아니라 실제 본인 사진을 올려주세요.
        </p>

        <div className="age-plan-box">
          <label>
            생년월일
            <input
              type="date"
              value={agePlan.birth_date ?? ""}
              onChange={(event) => setAgePlan({ ...agePlan, birth_date: event.target.value })}
            />
          </label>
          <label>
            현재 사진 촬영일
            <input
              type="date"
              value={agePlan.current_photo_date ?? ""}
              onChange={(event) => setAgePlan({ ...agePlan, current_photo_date: event.target.value })}
            />
          </label>
          <label>
            현재 나이 {ageOnDate(agePlan.birth_date, agePlan.current_photo_date) !== null ? "(자동 계산)" : ""}
            <input
              type="number"
              min="18"
              max="100"
              value={ageOnDate(agePlan.birth_date, agePlan.current_photo_date) ?? agePlan.current_age ?? ""}
              onChange={(event) => setAgePlan({ ...agePlan, current_age: event.target.value })}
              placeholder="예: 32"
              disabled={ageOnDate(agePlan.birth_date, agePlan.current_photo_date) !== null}
            />
          </label>
          <label>
            성장 통계 성별
            <select
              value={agePlan.biological_sex ?? "unspecified"}
              onChange={(event) => setAgePlan({ ...agePlan, biological_sex: event.target.value })}
            >
              <option value="unspecified">지정 안 함</option>
              <option value="male">남성 성장 기준</option>
              <option value="female">여성 성장 기준</option>
            </select>
          </label>
          <label>
            인구집단 기준
            <select
              value={agePlan.population_group ?? "unspecified"}
              onChange={(event) => setAgePlan({ ...agePlan, population_group: event.target.value })}
            >
              <option value="unspecified">지정 안 함</option>
              <option value="korean">한국인</option>
              <option value="east_asian">동아시아인</option>
              <option value="other">기타</option>
            </select>
          </label>
          <button className="save" onClick={saveAgePlan} disabled={busy || !identity.ready}>
            과거 얼굴 순서 저장
          </button>
        </div>

        <p className="hint">
          생년월일과 촬영일이 있으면 실제 촬영 당시 나이를 계산합니다. 입력한 현재 나이부터
          8세까지 성인은 넓게, 성장 변화가 큰 아동·청소년은
          촘촘하게 기준 사진을 배치합니다. 한 구간이 기준을 통과하지 못하면 합격선을
          낮추지 않고 그 구간에 중간 나이를 추가합니다.
        </p>

        {agePlan.stages?.length > 0 && (
          <>
            <p className="hint">
              생성 사진 {Math.max(0, agePlan.stages.length - 1)}장 + 현재 원본 1장
            </p>
            <div className="age-anchor-grid" aria-label="과거에서 현재까지 선택된 얼굴 순서">
              {agePlan.stages.map((stage) => {
                const selectedCandidate = stage.candidates?.find((candidate) => candidate.name === stage.selected);
                const preview = stage.kind === "current" ? stage.url : selectedCandidate?.url;
                return <article className={`age-anchor ${stage.kind === "current" ? "current" : ""} ${preview ? "selected" : "empty"}`} key={`${stage.kind}-${stage.age}`}>
                  <div className="age-anchor-image">
                    {preview ? <img src={preview} alt={`${stage.age}세 ${stage.kind === "current" ? "현재 얼굴" : "선택 얼굴"}`} /> : <span>?</span>}
                    <b>{stage.age}세</b>
                  </div>
                  <strong>{stage.kind === "current" ? "현재 원본" : stage.selected ? "선택 완료" : "선택 필요"}</strong>
                  <small>{stage.kind === "current" ? "변경하지 않음" : `후보 ${stage.candidates?.length || 0}개`}</small>
                </article>;
              })}
            </div>
          </>
        )}
        {agePlan.stages?.some((stage) => stage.candidates?.length) && (
          <div className="candidate-groups">
            {agePlan.stages
              .filter((stage) => stage.kind === "generated" && stage.candidates?.length)
              .map((stage) => (
                <section className="candidate-group" key={`candidates-${stage.age}`}>
                  <h3>{stage.age}세 후보 — 과거의 나와 가장 닮은 사진을 선택하세요</h3>
                  <div className="candidate-grid">
                    {stage.candidates.map((candidate, candidateIndex) => (
                      <button
                        className={stage.selected === candidate.name ? "candidate selected" : "candidate"}
                        disabled={busy}
                        key={candidate.name}
                        onClick={() => choosePastCandidate(stage, candidate)}
                      >
                        <div className="candidate-image">
                          <img
                            src={candidate.url}
                            alt={`${stage.age}세 얼굴 후보 ${candidateIndex + 1}`}
                            onError={(event) => {
                              event.currentTarget.style.display = "none";
                              event.currentTarget.parentElement.classList.add("failed");
                            }}
                          />
                          <i>후보 {candidateIndex + 1}</i>
                          {stage.selected === candidate.name && <em>✓ 현재 선택</em>}
                        </div>
                        <span>{stage.selected === candidate.name ? "이 사진을 사용 중" : "이 사진 선택"}</span>
                        {candidate.validation && (
                          <small className={`candidate-metrics ${candidate.validation.review_status ?? "legacy"}`}>
                            외관 나이 {candidate.validation.estimated_age}세 · 신원 {candidate.validation.identity_pass ? "통과" : "실패"}
                            {candidate.validation.age_estimation && (
                              <>
                                <br />
                                InsightFace 목표 범위 {Math.round(candidate.validation.age_estimation.target_range_vote_share * 100)}%
                              </>
                            )}
                            {candidate.validation.mivolo_raw_age_estimation?.status === "available" && (
                              <>
                                <br />
                                MiVOLO 원시 중앙값 {candidate.validation.mivolo_raw_age_estimation.median.toFixed(1)}세
                                · 목표 범위 {Math.round(candidate.validation.mivolo_raw_age_estimation.target_range_vote_share * 100)}%
                                · 자동 판정 사용
                              </>
                            )}
                            {candidate.validation.mivolo_corrected_age_estimation?.status === "advisory_only" && (
                              <>
                                <br />
                                MiVOLO 현재 나이 보정 참고값 {candidate.validation.mivolo_corrected_age_estimation.median.toFixed(1)}세
                                · 자동 판정 미사용
                              </>
                            )}
                            {candidate.validation.age_consensus && (
                              <>
                                <br />
                                두 모델 합의 · {validationStatusLabel(candidate.validation.review_status)}
                              </>
                            )}
                            {candidate.validation.structure_3d_assessment?.status === "advisory_only" && (
                              <>
                                <br />
                                3D 개인 구조 {candidate.validation.structure_3d_assessment.personal_structure_stable ? "보존" : "확인 필요"}
                                · 성장 방향 {Math.round(candidate.validation.structure_3d_assessment.growth_direction_score * 100)}%
                                · 보조 지표
                              </>
                            )}
                            {candidate.validation.structure_assessment && (
                              <>
                                <br />2D 구조 변화 방향 {Math.round(candidate.validation.structure_assessment.score * 100)}% · 보조 지표
                              </>
                            )}
                          </small>
                        )}
                      </button>
                    ))}
                  </div>
                </section>
              ))}
          </div>
        )}
        <p className="hint">
          현재보다 어린 얼굴 후보만 만듭니다. 마지막 현재 얼굴은 AI로 생성하지 않고 선택한 원본을 그대로 사용해요.
        </p>
      </section>

      <section className="meds legacy-faces">
        <h2>기존 나이 변화 자료</h2>
        <p className="hint">
          어릴 때부터 지금까지 순서대로 올려주세요. 파일 이름 앞에 번호를
          붙이면 그 순서로 이어집니다 (예: 01_여덟살.png).
        </p>

        {faces.raw.length > 0 && (
          <ul className="med-list">
            {faces.raw.map((f) => (
              <li key={f.name}>
                <div>
                  <b>{f.name}</b>
                  <span className="row-meta"> {f.size_kb}KB</span>
                </div>
                <div className="med-right">
                  <button
                    disabled={busy}
                    onClick={() =>
                      guard(() => api.deleteFace(f.name, selectedPersonaId), "사진을 지웠어요.")
                    }
                  >
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {faces.aligned.length > 0 && (
          <div className="face-strip">
            {faces.aligned.map((f) => (
              <img key={f.name} src={f.url} alt={f.name} />
            ))}
          </div>
        )}

        <div className="med-form">
          <input
            type="file"
            accept="image/*"
            multiple
            onChange={(e) => upload(e.target.files)}
          />
          <button onClick={prepare} disabled={busy || !faces.raw.length}>
            사진 정렬하기
          </button>
        </div>

        <div className="build-status">
          <span className={faces.morph.exists ? "tag ok" : "tag"}>
            모핑 영상 {faces.morph.exists ? `있음 ${faces.morph.size_kb}KB` : "없음"}
          </span>
          <span className={faces.loops.length ? "tag ok" : "tag"}>
            표정 {faces.loops.length ? faces.loops.join(", ") : "없음"}
          </span>
        </div>
        <p className="hint">
          정렬까지 마쳤으면 터미널에서 영상을 만듭니다.
          <br />
          <code>python tools/make_morph.py --model wan-video/wan-2.7-i2v --seconds 5</code>
        </p>
      </section>

      <section className="meds">
        <h2>할아버지 프로필</h2>
        <div className="field-grid">
          <label>
            이름
            <input
              value={elder.name ?? ""}
              onChange={(e) => setElder({ ...elder, name: e.target.value })}
            />
          </label>
          <label>
            불러드릴 호칭
            <input
              value={elder.preferred_call_name ?? ""}
              onChange={(e) =>
                setElder({ ...elder, preferred_call_name: e.target.value })
              }
            />
          </label>
          <label>
            말이 끝났다고 볼 때까지 기다리는 시간
            <input
              type="number"
              step="100"
              min="500"
              max="8000"
              value={elder.speech_wait_time_ms ?? 2000}
              onChange={(e) =>
                setElder({ ...elder, speech_wait_time_ms: e.target.value })
              }
            />
            <span className="hint">
              천천히 말씀하시면 길게 (기본 2000, 단위 밀리초)
            </span>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={Boolean(elder.hearing_support)}
              onChange={(e) =>
                setElder({ ...elder, hearing_support: e.target.checked })
              }
            />
            귀가 어두우심 (자막을 크게)
          </label>
        </div>

        <div className="field-grid">
          <label className="block">
            불안해하시는 상황 <span className="hint">한 줄에 하나씩</span>
            <textarea
              value={toLines(elder.anxiety_triggers)}
              onChange={(e) =>
                setElder({ ...elder, anxiety_triggers: e.target.value.split("\n") })
              }
            />
          </label>
          <label className="block">
            안심하시는 말 <span className="hint">한 줄에 하나씩</span>
            <textarea
              value={toLines(elder.calming_phrases)}
              onChange={(e) =>
                setElder({ ...elder, calming_phrases: e.target.value.split("\n") })
              }
            />
          </label>
        </div>

        <button className="save" onClick={saveElder} disabled={busy}>
          프로필 저장
        </button>
      </section>

      {note && <p className="note">{note}</p>}
      {error && <p className="error">{error}</p>}
    </>
  );
}
