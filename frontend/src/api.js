import { demoApi } from "./demoApi.js";

const BASE = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : detail?.error ?? `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new ApiError(0, "unreachable");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body.detail ?? body);
  return body;
}

const post = (path, body) =>
  request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const realApi = {
  // Score first, without the explanation, so it shows in under a second (NFR-01) …
  check: (drug_a, drug_b, patient_id) => post("/check", { drug_a, drug_b, patient_id, explain: false }),
  // … then the cited FDA-label explanation, which depends only on the drug pair.
  explain: (drug_a, drug_b) => post("/explain", { drug_a, drug_b }),
  suggest: (q) => request(`/drugs?q=${encodeURIComponent(q)}`).then((r) => r.suggestions),
  patients: () => request("/patients").then((r) => r.patients),
};

export const DEMO = import.meta.env.VITE_DEMO === "1";

// Demo mode runs the pipeline in the browser (see demoApi.js); errors are re-thrown as ApiError.
async function demo(fn, ...args) {
  try {
    return await demoApi[fn](...args);
  } catch (e) {
    throw new ApiError(e.status ?? -1, e.detail ?? String(e));
  }
}

export const api = DEMO
  ? {
      check: (...a) => demo("check", ...a),
      explain: async () => ({ explanation: { status: "demo", sentences: [], sources: [], dropped: [] } }),
      suggest: (q) => demo("suggest", q),
      patients: () => demo("patients"),
    }
  : realApi;
