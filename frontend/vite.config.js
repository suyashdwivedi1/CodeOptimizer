import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import site from "./src/site.config.js";

// Fills the site name and URL in index.html from src/site.config.js.
const siteVars = () => ({
  name: "site-vars",
  transformIndexHtml: (html) => html.replaceAll("__SITE_NAME__", site.siteName).replaceAll("__SITE_URL__", site.siteUrl.replace(/\/$/, "")),
});

export default defineConfig({
  plugins: [react(), siteVars()],
  server: { port: 5173, host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { chunkSizeWarningLimit: 4000 },
});
