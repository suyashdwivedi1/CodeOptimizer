# Launch checklist

Nothing ships until every box is ticked. `npm run build:release` enforces the items marked (auto).

## Blockers you must do

- [ ] **Custom domain.** Point your domain at wherever you host `dist/` and the backend, enable HTTPS, then set `siteUrl` in `src/site.config.js`. (auto: placeholder check)
- [ ] **Operator details.** Set `operatorName`, `contactEmail` and `jurisdiction` in `src/site.config.js`. The privacy policy and terms read from there. (auto)
- [ ] **Legal review.** Have a lawyer read `src/Legal.jsx`. Confirm these statements are true for your deployment, or edit them:
  - access logs are kept only for a limited time,
  - submitted code is not used to train the model,
  - no analytics or cookies are added by your host or proxy.
- [ ] **Sandbox the backend.** The app compiles and runs strangers' code natively. Put it in a container or VM with no network, a read-only filesystem except a scratch dir, CPU, memory and time limits, and a non-root user. Timeouts alone are not isolation.
- [ ] **Serve over HTTPS** and proxy `/api/` to the backend (the Vite dev proxy does not exist in production). Make sure the proxy supports server-sent events on `/api/experiments/*/events` (disable buffering).

## Already done

- [x] Favicon: `public/favicon.svg`, `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png`, linked in `index.html`. (auto)
- [x] No "Made with" badge anywhere in source or build output. (auto)
- [x] Privacy policy at `#/privacy`, terms and conditions at `#/terms`, linked from the sidebar. (auto)
- [x] No gradients, pill buttons, emoji, em dashes, cursor effects or scroll animation. (auto scan of `src/`)
- [x] No invented numbers: every figure and chart is drawn from the API.
- [x] Fonts are bundled, so the site makes no request to a font CDN.

## Build

```
npm install
npm run dev            # local, proxies /api to 127.0.0.1:8000
npm run build          # builds and prints launch warnings
npm run build:release  # builds and fails if anything above is unfinished
```

If you host on a path that is not `/`, set `base` in `vite.config.js`.
