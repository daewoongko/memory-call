import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api 와 /faces 를 FastAPI 로 넘긴다.
// 프록시를 쓰면 브라우저 입장에서는 같은 출처라 CORS 문제가 아예 생기지 않는다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/faces": "http://127.0.0.1:8000",
      "/media": "http://127.0.0.1:8000",
    },
  },
});
