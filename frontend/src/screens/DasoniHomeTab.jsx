import BrandMark from "../components/BrandMark.jsx";

function AttentionGlyph() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 8v5" /><path d="M12 17h.01" /><path d="M10.3 3.7 2.6 17a2 2 0 0 0 1.8 3h15.2a2 2 0 0 0 1.8-3L13.7 3.7a2 2 0 0 0-3.4 0z" /></svg>;
}

export default function DasoniHomeTab({
  elderCallName,
  elderName,
  dateLabel,
  summary,
  baselineSummary,
  attentionItems = [],
}) {
  const homeTitle = `${elderCallName}의 오늘`;
  const titleLength = homeTitle.replace(/\s/g, "").length;
  const titleFit = Math.min(1, 5 / Math.max(titleLength, 1));
  const dailyReports = baselineSummary?.daily_reports || [];
  const baselineDays = Math.max(1, dailyReports.length || baselineSummary?.days || 1);
  const observations = (summary?.daily_reports || []).reduce((total, day) => total + (day.observation_count || 0), 0);
  const unreadSafety = (summary?.risks || []).filter((risk) => !risk.acknowledged).length;
  const metrics = [
    {
      label: "오늘 통화", value: summary?.calls || 0, unit: "통",
      average: dailyReports.reduce((total, day) => total + (day.calls || 0), 0) / baselineDays,
    },
    {
      label: "통화 시간", value: Math.round((summary?.total_seconds || 0) / 60), unit: "분",
      average: dailyReports.reduce((total, day) => total + (day.seconds || 0) / 60, 0) / baselineDays,
    },
    {
      label: "대화 중 변화 신호", value: observations, unit: "건",
      status: `발화 100건당 ${Math.round(summary?.normalized_rates?.observation_per_100_utterances || 0)}건`,
    },
    {
      label: "반복 발화", value: summary?.repeat_total || 0, unit: "회",
      average: dailyReports.reduce((total, day) => total + (day.repeated_total || day.repeat_total || 0), 0) / baselineDays,
    },
    {
      label: "안전 신호", value: (summary?.risks || []).length, unit: "건",
      status: unreadSafety ? `미확인 ${unreadSafety}건` : "모두 확인",
    },
  ];

  return <section className="dasoni-home" aria-labelledby="dasoni-home-title">
    <header className="dasoni-home-hero">
      <div className="dasoni-home-copy">
        <span>{dateLabel}</span>
        <h1 id="dasoni-home-title" style={{ "--home-title-fit": titleFit }}>{homeTitle}</h1>
        <p>오늘의 통화와 확인할 소식을 한눈에 모았어요.</p>
      </div>
      <BrandMark size={92} />
    </header>

    <section className="dasoni-observation-summary" aria-labelledby="dasoni-observation-title">
      <header>
        <h2 id="dasoni-observation-title">{elderName} 어르신의 오늘 관찰</h2>
        <p>통화에서 확인된 기억·언어·정서·생활 관련 신호이며, 진단 결과가 아닙니다.</p>
      </header>
      <div className="dasoni-observation-grid">
        {metrics.map((item) => {
          const delta = item.value - (item.average || 0);
          return <article key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}<small>{item.unit}</small></strong>
            <em>{item.status || `평균 대비 ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`}</em>
          </article>;
        })}
      </div>
    </section>

    {attentionItems.length > 0 && <section className="dasoni-attention" aria-label="직접 확인 상세">
      <div className="dasoni-attention-list">
        {attentionItems.map((item) => <article className="dasoni-attention-item" key={item.id}>
          <span className="dasoni-attention-icon"><AttentionGlyph /></span>
          <div>
            <small>실제 통화에서 발견</small>
            <h3>{item.label || "가족 확인이 필요해요"}</h3>
            <blockquote>“{item.evidence}”</blockquote>
            <p>{item.action || "현재 상태를 직접 확인해 주세요."}</p>
          </div>
        </article>)}
      </div>
    </section>}
  </section>;
}
