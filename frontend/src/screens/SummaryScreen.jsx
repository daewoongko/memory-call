import BrandMark from "../components/BrandMark.jsx";

export default function SummaryScreen({ summary, onRestart }) {
  return (
    <div className="screen summary-screen">
      <BrandMark size={168} />
      <div className="who">통화를 잘 마쳤어요</div>

      <div className="summary">
        <div className="summary-thanks">오늘도 따뜻한 이야기를 나눠주셔서 고마워요.</div>
        <div className="summary-duration">통화 시간 <b>{summary.duration_sec}초</b></div>
      </div>

      <button className="pill" onClick={onRestart}>홈으로 돌아가기</button>
    </div>
  );
}
