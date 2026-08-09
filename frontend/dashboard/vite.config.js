import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Proxies /api and /health to the real platform process in dev so the
// browser never needs the backend to send CORS headers -- same pattern
// this repo's own Compose topology uses (one trusted origin), just for a
// local dev server instead of a container network.
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
