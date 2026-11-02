import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { alphaTab } from "@coderline/alphatab-vite";

export default defineConfig({
  plugins: [vue(), alphaTab()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});

