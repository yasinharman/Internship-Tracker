import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In development Vite serves the front end and forwards /api to the uvicorn
// process, so the browser sees one origin and there is no CORS story to get
// wrong. In production FastAPI serves this build directly and the proxy is
// not involved at all - same-origin either way, deliberately.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_ORIGIN ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    // Chart.js is the only heavy dependency and the board is the only page
    // that draws a chart; splitting it keeps the first paint of the other
    // pages off the critical path.
    rollupOptions: {
      output: {
        manualChunks: {
          chart: ["chart.js", "react-chartjs-2"],
        },
      },
    },
  },
});
