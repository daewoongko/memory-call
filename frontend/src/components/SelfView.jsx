import { useEffect, useRef, useState } from "react";

/**
 * 내 화면.
 *
 * 실제 영상통화처럼 자기 모습이 구석에 보여야 "통화 중"이라는 감각이 산다.
 * 카메라를 못 쓰면 조용히 안내만 남기고 통화는 그대로 진행한다.
 */
export default function SelfView() {
  const videoRef = useRef(null);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    let stream;
    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: "user" }, audio: false })
      .then((s) => {
        stream = s;
        if (videoRef.current) videoRef.current.srcObject = s;
      })
      .catch(() => setDenied(true));

    return () => stream?.getTracks().forEach((t) => t.stop());
  }, []);

  return (
    <div className="selfview">
      {denied ? (
        <span>카메라 꺼짐</span>
      ) : (
        <video ref={videoRef} autoPlay playsInline muted />
      )}
    </div>
  );
}
