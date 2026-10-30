// Launch gate. `npm run build` prints warnings; `npm run build:release` fails on any problem.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import site from "../src/site.config.js";

const strict = process.argv.includes("--strict");
const problems = [];
const bad = (m) => problems.push(m);

// 1. Placeholders in site.config.js (custom domain, operator, contact)
const placeholders = { siteUrl: "https://example.com", operatorName: "Your Company Name", contactEmail: "contact@example.com", jurisdiction: "Your Jurisdiction" };
for (const [k, v] of Object.entries(placeholders)) if (site[k] === v || !site[k]) bad(`src/site.config.js: "${k}" is still the placeholder. Set your real value.`);
if (!/^https:\/\//.test(site.siteUrl)) bad("src/site.config.js: siteUrl must start with https://");

// 2. Favicon files
for (const f of ["favicon.svg", "favicon.ico", "favicon-32.png", "apple-touch-icon.png"]) if (!existsSync(join("public", f))) bad(`public/${f} is missing.`);

// 3. Legal pages exist and are linked
if (!existsSync("src/Legal.jsx")) bad("src/Legal.jsx (privacy policy and terms) is missing.");
const app = readFileSync("src/App.jsx", "utf8");
if (!app.includes("#/privacy") || !app.includes("#/terms")) bad("App does not link to #/privacy and #/terms.");

// 4. Banned content in source
const walk = (d) => readdirSync(d).flatMap((n) => { const p = join(d, n); return statSync(p).isDirectory() ? walk(p) : [p]; });
const src = [...walk("src"), "index.html"];
for (const f of src) {
  const t = readFileSync(f, "utf8");
  if (new RegExp(String.fromCharCode(0x2014)).test(t)) bad(`${f}: contains an em dash.`);
  if (/gradient\(/i.test(t)) bad(`${f}: contains a CSS gradient.`);
  if (/border-radius:\s*(999|9999|50%|\d{2,}px)/i.test(t) && f.endsWith(".css")) bad(`${f}: contains a pill or circular border-radius.`);
  if (/made with|built with (lovable|bolt|v0)|lovable|bolt\.new|emergent/i.test(t)) bad(`${f}: contains a "made with" or generator badge.`);
  if (/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(t)) bad(`${f}: contains an emoji.`);
  if (/mousemove|IntersectionObserver|ScrollTrigger|framer-motion/.test(t) && !f.endsWith("check-launch.mjs")) bad(`${f}: cursor or scroll animation code found.`);
}

// 5. Built output
if (existsSync("dist")) {
  const html = readFileSync("dist/index.html", "utf8");
  if (/made with|lovable|bolt\.new/i.test(html)) bad('dist/index.html: contains a "made with" badge.');
  if (html.includes("__SITE_")) bad("dist/index.html: site variables were not replaced.");
  if (!html.includes("favicon")) bad("dist/index.html: no favicon link.");
  if (!existsSync("dist/favicon.svg")) bad("dist/favicon.svg missing.");
} else bad("dist/ not found. Run the build first.");

if (!problems.length) { console.log("Launch checks passed."); process.exit(0); }
console.log(`\nLaunch checks: ${problems.length} problem(s)\n` + problems.map((p) => `  - ${p}`).join("\n") + "\n");
if (strict) { console.log("Release build blocked. Fix the items above."); process.exit(1); }
console.log("(Warnings only. Use `npm run build:release` for the strict gate.)");
