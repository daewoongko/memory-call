import { useEffect, useState } from "react";
import * as api from "../api.js";
import { useSpeech } from "../useSpeech.js";

/**
 * 통화 대상 고르기.
 *
 * 어르신이 손가락으로 누르기 어려울 수 있어 말로도 고를 수 있게 한다.
 * "손녀" 처럼 관계로 부르든 "수아" 처럼 이름으로 부르든 찾아준다.
 *
 * 아직 사진과 영상이 준비되지 않은 가족은 누를 수 없게 두고
 * 목록에는 남긴다. 누가 등록되어 있는지 보이는 편이 덜 혼란스럽다.
 */

// 어르신이 실제로 쓰는 말과 등록된 관계가 다를 수 있어 함께 찾는다
const ALIAS = {
  손자: ["손자", "손주"],
  손녀: ["손녀", "손주"],
  아들: ["아들", "아드님"],
  딸: ["딸", "따님"],
  며느리: ["며느리"],
};

function match(text, personas) {
  const said = text.replace(/\s/g, "");
  return personas.find((p) => {
    if (!p.ready) return false;
    if (said.includes(p.display_name)) return true;
    const words = ALIAS[p.relationship] ?? [p.relationship];
    return words.some((w) => w && said.includes(w));
  });
}

export default function FamilyScreen({ onPick, error }) {
  const [personas, setPersonas] = useState([]);
  const [notice, setNotice] = useState("");
  const [loadError, setLoadError] = useState("");

  const speech = useSpeech({
    silenceMs: 1600,
    onFinal: (text) => {
      const hit = match(text, personas);
      if (hit) onPick(hit);
      else setNotice(`“${text}” — 누구에게 걸까요? 이름을 다시 말씀해 주세요.`);
    },
  });

  useEffect(() => {
    api
      .getPersonas()
      .then((r) => setPersonas(r.personas))
      .catch((e) => setLoadError(e.message));
  }, []);

  const ready = personas.filter((p) => p.ready);

  return (
    <div className="screen family">
      <h1>누구에게 전화할까요?</h1>

      <div className="family-grid">
        {personas.map((p) => (
          <button
            key={p.persona_id}
            className={`family-card${p.ready ? "" : " waiting"}`}
            disabled={!p.ready}
            onClick={() => onPick(p)}
          >
            <span className="family-face">
              {p.face ? (
                <img src={p.face} alt="" />
              ) : (
                <i>{p.display_name.slice(0, 1)}</i>
              )}
            </span>
            <b>{p.display_name}</b>
            <small>{p.ready ? p.relationship : "등록 대기"}</small>
          </button>
        ))}
      </div>

      {speech.supported && ready.length > 0 && (
        <button
          className={`pill voice${speech.listening ? " listening" : ""}`}
          onClick={() => (speech.listening ? speech.stop() : speech.start())}
        >
          {speech.listening ? "듣고 있어요" : "말로 걸기"}
        </button>
      )}

      {speech.listening && (
        <p className="hint">
          {speech.interim || "‘손녀’ 또는 ‘수아’ 처럼 말씀해 주세요"}
        </p>
      )}
      {!speech.listening && notice && <p className="hint">{notice}</p>}
      {(error || loadError) && <p className="error">{error || loadError}</p>}
    </div>
  );
}
