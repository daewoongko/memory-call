import { useEffect, useRef, useState } from "react";
import * as api from "../api.js";

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

export default function PersonaPanel() {
  const [data, setData] = useState(null);
  const [persona, setPersona] = useState({});
  const [elder, setElder] = useState({});
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef(null);

  const load = () =>
    api
      .getPersona()
      .then((r) => {
        setData(r);
        setPersona(r.persona ?? {});
        setElder(r.elder ?? {});
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
      await load();
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
        }),
      "페르소나를 저장했어요."
    );

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
    guard(() => api.uploadFaces(files), `사진 ${files.length}장을 올렸어요.`);

  const prepare = () =>
    guard(async () => {
      const r = await api.prepareFaces();
      if (!r.ok) throw new Error("정렬에 실패했어요. 사진 형식을 확인해 주세요.");
    }, "사진을 정렬했어요.");

  if (!data) return <p className="hint">불러오는 중…</p>;

  const faces = data.faces;

  return (
    <>
      <section className="meds">
        <h2>가족 페르소나</h2>
        <p className="hint">
          여기 적은 말투와 호칭이 그대로 통화에 쓰여요.
        </p>

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

        <button className="save" onClick={savePersona} disabled={busy}>
          페르소나 저장
        </button>
      </section>

      <section className="meds">
        <h2>얼굴 사진</h2>
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
                      guard(() => api.deleteFace(f.name), "사진을 지웠어요.")
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
            ref={fileRef}
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
