import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8100",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "../static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-query": ["@tanstack/react-query"],
          "vendor-xyflow": ["@xyflow/react"],
          "vendor-chart": ["chart.js", "react-chartjs-2"],
          "vendor-codemirror": ["@codemirror/lang-markdown", "@uiw/react-codemirror"],
          "vendor-syntax": ["react-syntax-highlighter"],
        },
      },
    },
  },
});
