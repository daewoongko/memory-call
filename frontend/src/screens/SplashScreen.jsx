import { useEffect } from "react";
import BrandMark from "../components/BrandMark.jsx";

/** 앱을 열 때 잠깐 보이는 화면. */
// 900ms. 바로 다음 화면(역할 선택)이 같은 캐릭터를 크게 보여주므로
// 1.8초를 두면 같은 그림을 두 번 기다리는 꼴이 된다.
export default function SplashScreen({ onDone, ms = 900 }) {
  useEffect(() => {
    const id = setTimeout(onDone, ms);
    return () => clearTimeout(id);
  }, [onDone, ms]);

  return (
    <div className="screen splash" onClick={onDone}>
      <BrandMark size={144} />
      <div className="wordmark">
        다소니
        <small>에이닷</small>
      </div>
    </div>
  );
}
