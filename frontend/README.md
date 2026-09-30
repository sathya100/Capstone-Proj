# RxGuard frontend

React + Vite + Tailwind CSS. One results screen with the score gauge, points breakdown, body map
and explanation (FR-14, FR-15), side-by-side two-patient compare (FR-16), and the disclaimer on
every screen (FR-17).

## Run

Start the backend first (see `../backend/README.md`), then:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The dev server forwards `/api/*` to the backend at `http://localhost:8000`. To point at another
backend, set `RXGUARD_API=http://host:port` for `npm run dev`, or `VITE_API_URL` at build time.

`npm run build` writes a static site to `dist/` (e.g. for Vercel).

`npm run build:demo` builds a server-free demo into `dist-demo/`: `src/demoApi.js` runs the same
rules, drug flags and three demo patients in the browser, so the UI can be shared as a link. Keep
it in step with `backend/config/` if you change the rules.

## Layout

| File | What it is |
|---|---|
| `src/App.jsx` | Page: check form, compare toggle, errors, results |
| `src/components/DrugInput.jsx` | Medicine field with autocomplete (`GET /drugs`) |
| `src/components/PatientSelect.jsx` | Patient picker (`GET /patients`) |
| `src/components/ScoreStrip.jsx` | The gauge: 10 cells, each filled by the rule that earned it |
| `src/components/Breakdown.jsx` | Points table, missing-data notes, unknown-severity message |
| `src/components/BodyMap.jsx` | Body systems flagged by the fired rules and the explanation |
| `src/components/ResultPanel.jsx` | One patient's result; compact version for compare |
| `src/risk.js` | Risk colours, band edges, rule → body-system mapping |
| `src/api.js` | Backend client |

## Design

- Colour is reserved for risk: green Low, amber Moderate, red High, hatched violet Unknown.
  Base severity is always navy, so the patient-specific points stand out in the gauge.
- Typeface: Atkinson Hyperlegible (designed for low-vision legibility).
- Keyboard accessible (autocomplete supports arrow keys), respects reduced motion, works at phone width.

The "Why these drugs interact" panel shows a placeholder until the RAG explainer is built; it
renders `mechanism`, `monitoring` and `citations` from the API as soon as they are returned.
