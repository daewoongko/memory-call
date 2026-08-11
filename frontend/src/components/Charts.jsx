/**
 * 리포트용 그래프.
 *
 * 데이터 성격에 맞는 형태만 쓴다.
 *   비율      → 도넛
 *   날짜별 유무 → 고정 칸 스트립 (빈 날도 칸으로 남겨야 규칙이 보인다)
 *   항목 비교  → 가로 막대
 *
 * 라이브러리를 쓰지 않고 SVG 로 그린다. 종류가 셋뿐이라 의존성을 늘릴 이유가 없다.
 */

/** 비율 도넛. 가운데에 핵심 숫자를 놓는다. */
export function Donut({ value, total, label, unit = "회" }) {
  const size = 132;
  const stroke = 15;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const ratio = total > 0 ? value / total : 0;
  const percent = Math.round(ratio * 100);

  return (
    <div className="donut">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
           aria-label={`${label} ${percent}%`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none"
                stroke="var(--line)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={percent >= 80 ? "#57c98a" : percent >= 50 ? "var(--brand-soft)" : "var(--alert)"}
          strokeWidth={stroke}
          strokeDasharray={`${c * ratio} ${c}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text x="50%" y="46%" textAnchor="middle" className="donut-num">
          {total > 0 ? `${percent}%` : "—"}
        </text>
        <text x="50%" y="64%" textAnchor="middle" className="donut-sub">
          {value}/{total}{unit}
        </text>
      </svg>
      <span className="donut-label">{label}</span>
    </div>
  );
}

/** 날짜별 통화. 통화가 없던 날도 칸을 남겨 공백이 드러나게 한다. */
export function DayStrip({ byDay, days }) {
  const today = new Date();
  const slots = [];
  for (let i = days - 1; i >= 0; i -= 1) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const hit = byDay.find((x) => x.date === key);
    slots.push({ key, day: d.getDate(), calls: hit?.calls ?? 0 });
  }
  const peak = Math.max(1, ...slots.map((s) => s.calls));

  return (
    <div className={`daystrip${days > 10 ? " dense" : ""}`}>
      {slots.map((s) => (
        <div key={s.key} className="dayslot" title={`${s.key} · ${s.calls}통화`}>
          <div className="col">
            <div
              className={`fill${s.calls ? "" : " empty"}`}
              style={{ height: `${s.calls ? (s.calls / peak) * 100 : 6}%` }}
            />
          </div>
          {days <= 10 && <span>{s.day}</span>}
        </div>
      ))}
    </div>
  );
}

/** 날짜별 추이를 한눈에 보는 꺾은선. 점을 누르지 않아도 값이 툴팁으로 보인다. */
export function LineChart({ byDay, days, label = "통화" }) {
  const width = 640;
  const height = 190;
  const margin = { top: 18, right: 18, bottom: 32, left: 28 };
  const slots = (byDay || []).map((item) => ({
    key: item.date,
    day: Number(String(item.date).slice(8, 10)),
    value: item.calls || 0,
  }));
  if (!slots.length) slots.push({ key: "선택 기간", day: "-", value: 0 });
  const peak = Math.max(1, ...slots.map((slot) => slot.value));
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const x = (index) => margin.left + (slots.length === 1 ? innerWidth / 2 : index * innerWidth / (slots.length - 1));
  const y = (value) => margin.top + innerHeight - value / peak * innerHeight;
  const points = slots.map((slot, index) => `${x(index)},${y(slot.value)}`).join(" ");
  const area = `${margin.left},${margin.top + innerHeight} ${points} ${margin.left + innerWidth},${margin.top + innerHeight}`;

  return <figure className="line-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`선택한 ${days}일의 ${label} 추이`}>
      <defs><linearGradient id="line-area-gradient" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="var(--brand-soft)" stopOpacity="0.35" />
        <stop offset="100%" stopColor="var(--brand-soft)" stopOpacity="0" />
      </linearGradient></defs>
      {[0, 0.5, 1].map((ratio) => <g key={ratio}>
        <line x1={margin.left} x2={width - margin.right} y1={margin.top + innerHeight * ratio} y2={margin.top + innerHeight * ratio} className="line-grid" />
        <text x={margin.left - 7} y={margin.top + innerHeight * ratio + 3} textAnchor="end" className="line-axis-value">{Math.round(peak * (1 - ratio))}</text>
      </g>)}
      <polygon points={area} className="line-area" />
      <polyline points={points} className="line-path" />
      {slots.map((slot, index) => <g key={slot.key}>
        <circle cx={x(index)} cy={y(slot.value)} r={slot.value ? 4 : 2.5} className={slot.value ? "line-dot" : "line-dot empty"}><title>{slot.key} · {slot.value}{label}</title></circle>
        {days <= 7 && slot.value > 0 && <text x={x(index)} y={y(slot.value) - 9} textAnchor="middle" className="line-value">{slot.value}</text>}
        {(days <= 10 || index === 0 || index === slots.length - 1 || index % 5 === 0) && <text x={x(index)} y={height - 8} textAnchor="middle" className="line-label">{slot.day}</text>}
      </g>)}
    </svg>
  </figure>;
}

/** 여러 관찰 영역의 구성비. 비율과 실제 건수를 동시에 보여준다. */
export function DistributionDonut({ items, label = "전체 관찰" }) {
  const size = 150;
  const stroke = 19;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = items.reduce((sum, item) => sum + Math.max(0, item.value || 0), 0);
  let offset = 0;

  return <div className="distribution-donut">
    <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${label} ${total}건`}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--line)" strokeWidth={stroke} />
      {items.map((item) => {
        const length = total ? circumference * item.value / total : 0;
        const circle = <circle key={item.label} cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={item.color} strokeWidth={stroke} strokeDasharray={`${length} ${circumference - length}`} strokeDashoffset={-offset} transform={`rotate(-90 ${size / 2} ${size / 2})`} />;
        offset += length;
        return circle;
      })}
      <text x="50%" y="47%" textAnchor="middle" className="distribution-total">{total}</text>
      <text x="50%" y="62%" textAnchor="middle" className="distribution-sub">관찰 건수</text>
    </svg>
    <div className="distribution-legend">{items.map((item) => <div key={item.label}>
      <i style={{ background: item.color }} /><span>{item.label}</span><b>{item.value}</b>
    </div>)}</div>
  </div>;
}

/** 항목별 횟수 비교. */
export function BarRows({ items, unit = "번" }) {
  const peak = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="barrows">
      {items.map((it, i) => (
        <div key={i} className="barrow">
          <span className="barrow-label" title={it.label}>{it.label}</span>
          <div className="barrow-track">
            <div className="barrow-fill" style={{ width: `${(it.value / peak) * 100}%` }} />
          </div>
          <b>{it.value}{unit}</b>
        </div>
      ))}
    </div>
  );
}

/** 좁은 상태 행 안에서 날짜별 증감을 보여주는 미니 영역 그래프. */
export function MiniTrend({ values = [], color = "#7f8cff", label = "추이" }) {
  const width = 180;
  const height = 52;
  const peak = Math.max(1, ...values);
  const points = values.map((value, index) => {
    const x = values.length <= 1 ? width / 2 : index * width / (values.length - 1);
    const y = height - 5 - (value / peak) * (height - 12);
    return `${x},${y}`;
  }).join(" ");
  const area = `0,${height} ${points} ${width},${height}`;

  return <svg className="mini-trend" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
    <polygon points={area} fill={color} opacity="0.18" />
    <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}

/** 실제로 많이 나온 말과 관찰 상태를 크기·농도로 표현하는 버블 지도. */
export function BubbleChart({ items, title = "관찰 버블 지도" }) {
  const width = 420;
  const height = 300;
  const positions = [
    [210, 150], [108, 76], [318, 72], [94, 220], [326, 218],
    [210, 46], [210, 254], [388, 145], [34, 145],
  ];
  const values = items.slice(0, positions.length);
  const peak = Math.max(1, ...values.map((item) => item.value || 0));
  const compact = (label) => label.length > 15 ? `${label.slice(0, 14)}…` : label;
  const lines = (label) => {
    const text = compact(label).replace(/^“|”$/g, "");
    return text.length > 8 ? [text.slice(0, 8), text.slice(8)] : [text];
  };

  if (!values.length) return <figure className="bubble-chart empty">
    <div><span /><b>표시할 관찰이 없습니다</b><small>근거가 확인되면 말과 상태가 원으로 나타납니다.</small></div>
  </figure>;

  return <figure className="bubble-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title}. 원 크기와 색 농도는 통화 안의 확인 횟수입니다.`}>
      {values.map((item, index) => {
        const ratio = Math.max(0, item.value || 0) / peak;
        const radius = 22 + Math.sqrt(ratio) * 25;
        const [cx, cy] = positions[index];
        const labelLines = lines(item.label);
        return <g key={`${item.kind}-${item.label}`} className="bubble-item">
          <title>{item.kind} · {item.label} · {item.value}회{item.detail ? ` · ${item.detail}` : ""}</title>
          <circle cx={cx} cy={cy} r={radius} fill={item.color} fillOpacity={0.3 + ratio * 0.7} stroke={item.color} />
          <text x={cx} y={cy - (labelLines.length - 1) * 5} textAnchor="middle" className="bubble-label">
            {labelLines.map((line, lineIndex) => <tspan key={lineIndex} x={cx} dy={lineIndex ? 11 : 0}>{line}</tspan>)}
            <tspan x={cx} dy="13" className="bubble-value">{item.value}회</tspan>
          </text>
        </g>;
      })}
    </svg>
    <figcaption><i className="speech" />많이 한 말 <i className="state" />관찰 상태 <i className="risk" />안전 신호</figcaption>
  </figure>;
}

/** 두 시간 단위 통화 분포. 가장 붐비는 시간만 강조한다. */
export function RhythmBars({ blocks = [], peakStart = null }) {
  const peak = Math.max(1, ...blocks.map((block) => block.calls || 0));
  const total = blocks.reduce((sum, block) => sum + (block.calls || 0), 0);

  return <figure className="rhythm-chart">
    <div
      className="rhythm-bars"
      role="img"
      aria-label={`시간대별 통화 분포. 총 ${total}회 통화 중 가장 많은 시간은 ${String(peakStart ?? 0).padStart(2, "0")}시입니다.`}
    >
      {blocks.map((block) => {
        const active = block.start_hour === peakStart;
        const height = block.calls ? Math.max(10, block.calls / peak * 100) : 4;
        return <div className={`rhythm-column ${active ? "peak" : ""}`} key={block.start_hour}>
          <b>{block.calls || 0}</b>
          <div className="rhythm-track">
            <i style={{ height: `${height}%` }} />
          </div>
          <span>{String(block.start_hour).padStart(2, "0")}시</span>
        </div>;
      })}
    </div>
    <figcaption>막대가 높을수록 해당 두 시간 동안 시작한 통화가 많습니다.</figcaption>
  </figure>;
}
