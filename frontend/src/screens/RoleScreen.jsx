import BrandMark from "../components/BrandMark.jsx";

const ICONS = {
  elder: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" /></svg>,
  child: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" /></svg>,
  care: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1M9 12h6M9 16h6" /></svg>,
};

const ROLES = [
  {
    id: "elder",
    eyebrow: "어르신",
    title: "가족과 이야기할게요",
  },
  {
    id: "child",
    eyebrow: "가족",
    title: "어르신의 오늘을 볼게요",
  },
  {
    id: "care",
    eyebrow: "요양원 담당자",
    title: "돌봄 기록을 관리할게요",
  },
];

export default function RoleScreen({ account, onPick, onLogout }) {
  return <main className="role-gateway role-gateway-simple">
    <header className="role-gateway-brand">
      <BrandMark size={162} />
      <div><b>다소니</b><p className="role-gateway-subtitle">누구로 시작할까요?</p></div>
    </header>

    {account && <div className="role-account-line"><span><b>{account.display_name}</b>님, 어떤 역할로 시작할까요?</span>{onLogout && <button type="button" onClick={onLogout}>로그아웃</button>}</div>}

    <section className="role-list" aria-label="사용 역할 선택">
      {ROLES.map((role) => <button
        key={role.id}
        className={`role-list-item ${role.id}`}
        onClick={() => onPick(role.id)}
      >
        <span className="role-list-icon" aria-hidden="true">{ICONS[role.id]}</span>
        <span className="role-list-body">
          <small>{role.eyebrow}</small>
          <b>{role.title}</b>
        </span>
        <span className="role-list-chevron" aria-hidden="true">›</span>
      </button>)}
    </section>
  </main>;
}
