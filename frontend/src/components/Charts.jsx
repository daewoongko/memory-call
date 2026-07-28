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
