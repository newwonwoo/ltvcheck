import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 로컬 개발 시 /api 호출을 Vercel dev 서버(보통 3000)로 프록시.
// 운영(Vercel)에서는 /api 가 파이썬 서버리스 함수로 자동 매핑되므로 프록시 불필요.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:3000",
        changeOrigin: true,
      },
    },
  },
});
