import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  // A literal, not a runtime call, so esbuild folds the dev-note branches away
  // and their text never reaches the production bundle.
  const showDevNotes = (env.VITE_ENVIRONMENT ?? mode).toLowerCase().startsWith("dev");
  const appName = env.VITE_APP_NAME || "SaaS Template";

  return {
    plugins: [
      react(),
      {
        // The document title is branding, not a Vite built-in: it needs a
        // default for the common case where VITE_APP_NAME is unset.
        name: "app-name",
        transformIndexHtml: (html: string) =>
          html.replaceAll("%APP_NAME%", () => appName.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")),
      },
    ],
    define: {
      __DEV_NOTES__: JSON.stringify(showDevNotes),
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      host: true,
      port: Number(process.env.WEB_PORT) || 5173,
      allowedHosts: [".coder.munyard.biz"],
      proxy: {
        "/api/": {
          target: `http://localhost:${process.env.API_PORT || 8000}`,
          changeOrigin: true,
          ws: true,
        },
        "/ws": {
          target: `ws://localhost:${process.env.API_PORT || 8000}`,
          ws: true,
          rewrite: (path) => path.replace(/^\/ws/, "/api/v1/ws"),
        },
      },
    },
  };
});
