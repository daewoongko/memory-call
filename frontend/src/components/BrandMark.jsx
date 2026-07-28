import { useState } from "react";

/**
 * 다소니 로고.
 *
 * public/logo.png 가 있으면 그것을 쓰고, 없으면 같은 형태의 도형으로 대신한다.
 * 이미지 파일이 준비되지 않아도 화면이 비어 보이지 않아야 한다.
 */
export default function BrandMark({ size = 132 }) {
  const [failed, setFailed] = useState(false);

  if (!failed) {
    return (
      <img
        className="brandmark"
        src="/logo.png"
        alt=""
        width={size}
        height={size}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <svg
      className="brandmark"
      width={size}
      height={size}
      viewBox="0 0 120 120"
      role="img"
      aria-label="다소니"
    >
      {/* 위가 둥근 몸체와 아래 홈 */}
      <path
        d="M18 62a34 34 0 0 1 68 0v40H60V88H44v14H18V62Z"
        fill="var(--brand)"
      />
      <circle cx="52" cy="55" r="19" fill="#fff" />
      <circle cx="52" cy="55" r="12" fill="var(--brand)" />
      <circle cx="47" cy="50" r="4" fill="#fff" />
      {/* 옆에 떠 있는 점 */}
      <circle cx="100" cy="92" r="12" fill="var(--brand)" />
      <path
        d="M96 92a4 4 0 0 1 8 0c0 3-4 5-4 5s-4-2-4-5Z"
        fill="var(--lilac)"
      />
    </svg>
  );
}
