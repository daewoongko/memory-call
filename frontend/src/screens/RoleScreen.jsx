/**
 * 역할 선택.
 *
 * 같은 앱을 어르신과 보호자가 나눠 쓴다.
 * 고른 역할에 따라 이후 화면이 통째로 달라지므로 처음에 한 번만 묻는다.
 */
export default function RoleScreen({ onPick }) {
  return (
    <div className="screen role">
      <h1>어떤 역할로 함께하시나요?</h1>

      <div className="role-cards">
        <button className="role-card" onClick={() => onPick("elder")}>
          <span className="role-face" aria-hidden="true">
            👴
          </span>
          <b>어르신</b>
          <small>가족과 영상통화를 해요</small>
        </button>

        <button className="role-card" onClick={() => onPick("guardian")}>
          <span className="role-face" aria-hidden="true">
            🧑
          </span>
          <b>보호자</b>
          <small>통화 기록과 상태를 봐요</small>
        </button>
      </div>

      <p className="hint">나중에 화면 설정에서 바꿀 수 있어요</p>
    </div>
  );
}
