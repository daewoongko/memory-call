/**
 * 리포트용 그래프.
 *
 * 라이브러리를 쓰지 않고 SVG 로 직접 그린다. 화면에 실제로 붙는 그래프가
 * 하나뿐이라 의존성을 늘릴 이유가 없다.
 *
 * 예전에는 도넛·스트립·막대·꺾은선 등 여덟 개를 여기 두었는데, 리포트
 * 화면이 버블 지도 하나로 정리되면서 나머지 일곱 개는 아무 데서도
 * 렌더되지 않는 코드로 남았다. 다시 필요하면 git 기록에서 꺼낸다.
 */

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
