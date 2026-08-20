import BrandMark from "../components/BrandMark.jsx";

// 아이콘은 파일로 두지 않고 인라인으로 둔다. 세 개뿐이고, 색을 역할 색
// (--role-accent)에서 그대로 물려받아야 해서 currentColor 가 필요하다.
const svg = (paths) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.9"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {paths}
  </svg>
);

const ROLES = [
  {
    id: "elder",
    label: "어르신",
    icon: svg(<path d="M6.2 3.5h3.1l1.5 4-2.1 1.4a12.6 12.6 0 0 0 6.4 6.4l1.4-2.1 4 1.5v3.1a2 2 0 0 1-2.2 2A17.2 17.2 0 0 1 4.2 5.7a2 2 0 0 1 2-2.2Z" />),
  },
  {
    id: "child",
    label: "가족",
    icon: svg(<path d="M12 20.2s-7.4-4.6-7.4-9.6a4.2 4.2 0 0 1 7.4-2.7 4.2 4.2 0 0 1 7.4 2.7c0 5-7.4 9.6-7.4 9.6Z" />),
  },
  {
    id: "care",
    label: "요양원 담당자",
    icon: svg(<>
      <path d="M9 4.5h6M8.4 4.5H6.6a1.6 1.6 0 0 0-1.6 1.6v12.3a1.6 1.6 0 0 0 1.6 1.6h10.8a1.6 1.6 0 0 0 1.6-1.6V6.1a1.6 1.6 0 0 0-1.6-1.6h-1.8" />
      <path d="M9 3.2h6v2.6H9zM9 12.4l2 2 4-4" />
    </>),
  },
];

const CHEVRON = svg(<path d="M9.5 5.5 16 12l-6.5 6.5" />);

export default function RoleScreen({ onPick }) {
  return <main className="role-gateway">
    <header className="role-gateway-brand">
      {/* 캐릭터가 이 화면의 주인공이다. public/logo.png 가 있으면 그것을,
          없으면 BrandMark 가 같은 형태의 도형으로 대신 그린다. */}
      <span className="role-gateway-avatar"><BrandMark size={132} /></span>
      <b>다소니</b>
      <span>누구로 시작할까요?</span>
    </header>

    <section className="role-gateway-grid" aria-label="사용 역할 선택">
      {ROLES.map((role) => <button
        key={role.id}
        className={`role-gateway-card ${role.id}`}
        onClick={() => onPick(role.id)}
        aria-label={`${role.label}(으)로 시작하기`}
      >
        <span className="role-card-mark">{role.icon}</span>
        <span className="role-card-body"><b>{role.label}</b></span>
        <span className="role-card-enter">{CHEVRON}</span>
      </button>)}
    </section>
  </main>;
}
