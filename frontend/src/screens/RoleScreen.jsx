import BrandMark from "../components/BrandMark.jsx";

const ROLES = [
  {
    id: "elder",
    mark: "안심",
    eyebrow: "어르신",
    title: "가족과 이야기할게요",
    description: "익숙한 얼굴을 보고 오늘의 시간과 일정을 편안하게 확인해요.",
    meta: ["큰 글씨", "간단한 선택", "AI 가족 통화"],
  },
  {
    id: "child",
    mark: "마음",
    eyebrow: "가족",
    title: "어르신의 오늘을 볼게요",
    description: "오늘 남긴 말씀과 사진, 가족이 확인할 일을 따뜻하게 받아봐요.",
    meta: ["오늘의 한마디", "가족 기억", "안심 소식"],
  },
  {
    id: "care",
    mark: "분석",
    eyebrow: "요양원 담당자",
    title: "돌봄 기록을 관리할게요",
    description: "발화 변화와 안전·복약 근거를 확인하고 오늘의 업무를 정리해요.",
    meta: ["분석 리포트", "안전 확인", "복약 기록"],
  },
];

export default function RoleScreen({ onPick }) {
  return <main className="role-gateway">
    <header className="role-gateway-brand">
      <BrandMark size={38} />
      <div><b>다소니</b><span>기억과 오늘을 잇는 AI 케어</span></div>
    </header>

    <section className="role-gateway-intro">
      <span className="role-gateway-badge">WELCOME TO DASONI</span>
      <h1>누구의 화면으로<br />시작할까요?</h1>
      <p>각 역할에 꼭 필요한 정보만 보여드려요.<br />선택한 뒤에도 언제든 역할을 바꿀 수 있습니다.</p>
      <div className="role-gateway-promise">
        <span>가족 기반 대화</span><span>근거가 있는 관찰</span><span>안전한 돌봄 연결</span>
      </div>
    </section>

    <section className="role-gateway-grid" aria-label="사용 역할 선택">
      {ROLES.map((role, index) => <button
        key={role.id}
        className={`role-gateway-card ${role.id}`}
        onClick={() => onPick(role.id)}
      >
        <span className="role-card-number">0{index + 1}</span>
        <span className="role-card-mark" aria-hidden="true">{role.mark}</span>
        <span className="role-card-body">
          <small>{role.eyebrow}</small>
          <b>{role.title}</b>
          <p>{role.description}</p>
          <span className="role-card-tags">{role.meta.map((item) => <i key={item}>{item}</i>)}</span>
        </span>
        <span className="role-card-enter">시작하기 <i>↗</i></span>
      </button>)}
    </section>

    <footer className="role-gateway-footer"><span>Connect</span><i /> <span>Orient</span><i /> <span>Care</span></footer>
  </main>;
}
