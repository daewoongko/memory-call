import { useEffect } from "react";
import BrandMark from "../components/BrandMark.jsx";

/** 앱을 열 때 잠깐 보이는 화면. */
export default function SplashScreen({ onDone, ms = 1800 }) {
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
