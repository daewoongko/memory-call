import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API와 로컬 얼굴·영상 파일을 FastAPI 로 넘긴다.
// 프록시를 쓰면 브라우저 입장에서는 같은 출처라 CORS 문제가 아예 생기지 않는다.
//
// 포트를 환경변수로 빼둔 이유: Windows 에서 Hyper-V/WSL 이 8000 번을 예약해
// 버리면 (WinError 10013) 백엔드를 다른 포트로 띄울 수밖에 없다. 그때
// 이 파일을 고치는 대신 `set API_PORT=8010` 한 줄로 넘어간다.
const apiTarget = process.env.API_TARGET
  || `http://127.0.0.1:${process.env.API_PORT || 8000}`;

const proxied = [
  "/api",
  "/faces",
  "/identity-faces",
  "/age-candidates",
  "/media",
  "/persona-assets",
  "/memory-photos",
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 터널(cloudflared 등)로 폰에서 볼 때 낯선 호스트를 막지 않도록 한다.
    allowedHosts: true,
    proxy: Object.fromEntries(proxied.map((path) => [path, apiTarget])),
  },
});
