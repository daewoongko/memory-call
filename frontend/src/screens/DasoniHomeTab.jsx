import BrandMark from "../components/BrandMark.jsx";

function HomeGlyph() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 8v5" /><path d="M12 17h.01" /><path d="M10.3 3.7 2.6 17a2 2 0 0 0 1.8 3h15.2a2 2 0 0 0 1.8-3L13.7 3.7a2 2 0 0 0-3.4 0z" /></svg>;
}

const ATTENTION_EXAMPLE = {
  id: "attention-preview",
  label: "약 복용 확인",
  evidence: "오늘 약을 먹었는지 잘 기억이 안 나.",
  action: "약을 챙겨 드셨는지 전화로 확인해 주세요.",
  example: true,
};

export default function DasoniHomeTab({
  elderCallName,
  dateLabel,
  callCount = 0,
  totalDurationText = "0초",
  attentionItems = [],
}) {
  const visibleAttentionItems = attentionItems.length ? attentionItems : [ATTENTION_EXAMPLE];
  const homeTitle = `${elderCallName}의 오늘`;
  const titleLength = homeTitle.replace(/\s/g, "").length;
  const titleFit = Math.min(1, 5 / Math.max(titleLength, 1));

  return <section className="dasoni-home" aria-labelledby="dasoni-home-title">
    <header className="dasoni-home-hero">
      <div className="dasoni-home-copy">
        <span>{dateLabel}</span>
        <h1 id="dasoni-home-title" style={{ "--home-title-fit": titleFit }}>{homeTitle}</h1>
        <p>중요한 소식만 한눈에 모았어요.</p>
      </div>
      <BrandMark size={92} />
    </header>

    <div className="dasoni-home-status" aria-label="오늘의 핵심 수치">
      <article><small>오늘 통화</small><b>{callCount}통</b></article>
      <article><small>총 통화 시간</small><b>{totalDurationText}</b></article>
      <article className={attentionItems.length ? "attention" : ""}><small>직접 확인</small><b>{attentionItems.length ? `${attentionItems.length}건` : "없음"}</b></article>
    </div>

    <section className="dasoni-attention" aria-label="직접 확인 상세">

      <div className="dasoni-attention-list">
        {visibleAttentionItems.map((item) => <article className={`dasoni-attention-item${item.example ? " example" : ""}`} key={item.id}>
          <span className="dasoni-attention-icon"><HomeGlyph /></span>
          <div>
            <small>{item.example ? "표시 예시" : "통화에서 발견"}</small>
            <h3>{item.label || "가족 확인이 필요해요"}</h3>
            <blockquote>“{item.evidence}”</blockquote>
            <p>{item.action || "현재 상태를 직접 확인해 주세요."}</p>
          </div>
        </article>)}
      </div>
    </section>
  </section>;
}
