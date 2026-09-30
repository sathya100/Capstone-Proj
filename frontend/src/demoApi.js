// Demo mode (VITE_DEMO=1): runs the RxGuard pipeline in the browser so the UI can be shared as a
// link with no server. Mirrors backend/config/rules.yaml, drug_flags.yaml and the three demo
// patients from backend/scripts/make_dev_data.py. The real app always uses the FastAPI backend.

const RULES = {
  base: { Major: 6, Moderate: 4, Minor: 2, None: 0 },
  caution: 2,
  age: { threshold: 65, points: 1 },
  kidney: { below: 60, points: 2 },
  liver: { uln: 40, multiple: 3, points: 2 },
  alcohol: { atLeast: 3, drug: "acetaminophen", points: 2 },
  max: 10,
};

const FLAGS = {
  acetaminophen: { liver: true, kidney: false, cautions: [] },
  warfarin: { liver: true, kidney: false, cautions: ["peptic_ulcer"] },
  ibuprofen: { liver: true, kidney: false, cautions: ["heart_failure", "hypertension", "peptic_ulcer"] },
  aspirin: { liver: true, kidney: false, cautions: ["peptic_ulcer"] },
  metformin: { liver: false, kidney: true, cautions: ["heart_failure"] },
  lisinopril: { liver: false, kidney: true, cautions: [] },
  gabapentin: { liver: false, kidney: true, cautions: [] },
  simvastatin: { liver: true, kidney: false, cautions: [] },
  clarithromycin: { liver: true, kidney: false, cautions: [] },
};

const GROUPS = {
  liver_disease: { keywords: ["liver", "hepat", "cirrhosis"], organ: "liver" },
  chronic_kidney_disease: { keywords: ["chronic kidney disease", "renal failure", "renal insufficiency"], organ: "kidney" },
  heart_failure: { keywords: ["heart failure"] },
  hypertension: { keywords: ["hypertension"] },
  peptic_ulcer: { keywords: ["peptic ulcer", "gastric ulcer", "duodenal ulcer", "gastrointestinal hemorrhage"] },
};

const ALIASES = {
  tylenol: ["acetaminophen"], paracetamol: ["acetaminophen"], acetaminophen: ["acetaminophen"],
  coumadin: ["warfarin"], jantoven: ["warfarin"], warfarin: ["warfarin"],
  advil: ["ibuprofen"], motrin: ["ibuprofen"], ibuprofen: ["ibuprofen"],
  glucophage: ["metformin"], metformin: ["metformin"],
  zestril: ["lisinopril"], prinivil: ["lisinopril"], lisinopril: ["lisinopril"],
  neurontin: ["gabapentin"], gabapentin: ["gabapentin"],
  zocor: ["simvastatin"], simvastatin: ["simvastatin"],
  biaxin: ["clarithromycin"], clarithromycin: ["clarithromycin"],
  aspirin: ["aspirin"],
};

// Seed interaction: the design document's own example. Everything else is "not in database".
const INTERACTIONS = { "acetaminophen|warfarin": "Moderate" };

const PATIENTS = {
  "P-1042": { patient_id: "P-1042", age: 68, conditions: ["Chronic liver disease"], egfr: 72, alt: 55, alcohol_drinks_per_day: 4 },
  "P-2210": { patient_id: "P-2210", age: 30, conditions: [], egfr: 105, alt: 22, alcohol_drinks_per_day: 0 },
  "P-3301": {
    patient_id: "P-3301", age: 73,
    conditions: ["Chronic kidney disease stage 3 (disorder)", "Essential hypertension (disorder)"],
    egfr: 42, alt: 31, alcohol_drinks_per_day: 1,
  },
};

class DemoError extends Error {
  constructor(status, detail) { super(detail.error); this.status = status; this.detail = detail; }
}

function similarity(a, b) {
  const m = a.length, n = b.length, d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
  for (let j = 1; j <= n; j++) d[0][j] = j;
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return 1 - d[m][n] / Math.max(m, n);
}

function normalise(name) {
  const key = name.trim().toLowerCase();
  if (ALIASES[key]) return { query: key, ingredients: ALIASES[key], suggestions: [] };
  const suggestions = Object.keys(ALIASES)
    .map((k) => [k, similarity(key, k)]).filter(([, s]) => s >= 0.6)
    .sort((x, y) => y[1] - x[1]).slice(0, 3).map(([k]) => k);
  return { query: key, ingredients: [], suggestions };
}

function groupsFor(display) {
  const t = display.toLowerCase();
  return Object.entries(GROUPS).filter(([, g]) => g.keywords.some((k) => t.includes(k))).map(([k]) => k);
}

function score(drugs, severity, p) {
  const lines = [];
  const flags = Object.fromEntries(drugs.map((d) => [d, FLAGS[d]]));
  const missing = drugs.filter((d) => !FLAGS[d]).map((d) => `drug_flags:${d}`);
  const f = (d) => flags[d] ?? { liver: false, kidney: false, cautions: [] };

  if (severity) lines.push({ reason: `Base interaction: ${severity}`, points: RULES.base[severity], rule: "base_severity" });

  const groups = new Map();
  for (const c of p.conditions) for (const g of groupsFor(c)) if (!groups.has(g)) groups.set(g, c);
  for (const [g, c] of groups) {
    if (GROUPS[g].organ) continue;
    const by = drugs.filter((d) => f(d).cautions.includes(g));
    if (by.length) lines.push({ reason: `${c} is a caution for ${by.join(", ")}`, points: RULES.caution, rule: "condition_caution" });
  }
  if (p.age >= RULES.age.threshold) lines.push({ reason: `Age ${p.age}`, points: RULES.age.points, rule: "age" });
  const kd = drugs.filter((d) => f(d).kidney);
  if (kd.length && p.egfr < RULES.kidney.below)
    lines.push({ reason: `eGFR ${p.egfr} + kidney-cleared ${kd.join(", ")}`, points: RULES.kidney.points, rule: "kidney" });
  const ld = drugs.filter((d) => f(d).liver);
  if (ld.length) {
    const liverCond = [...groups].find(([g]) => GROUPS[g].organ === "liver")?.[1];
    const limit = RULES.liver.uln * RULES.liver.multiple;
    if (liverCond || p.alt > limit)
      lines.push({ reason: `${liverCond ?? `ALT ${p.alt} (> ${limit})`} + ${ld.join(", ")}`, points: RULES.liver.points, rule: "liver" });
  }
  if (drugs.includes(RULES.alcohol.drug) && p.alcohol_drinks_per_day >= RULES.alcohol.atLeast)
    lines.push({ reason: `Alcohol ${p.alcohol_drinks_per_day} drinks/day + ${RULES.alcohol.drug}`, points: RULES.alcohol.points, rule: "alcohol" });

  if (!severity) return { risk_score: null, risk_level: "Unknown — consult a pharmacist", lines, missing, capped: false };
  const raw = lines.reduce((s, l) => s + l.points, 0);
  const total = Math.min(raw, RULES.max);
  const level = total >= 7 ? "High" : total >= 4 ? "Moderate" : "Low";
  return { risk_score: total, risk_level: level, lines, missing, capped: raw > total };
}

const delay = (v) => new Promise((r) => setTimeout(() => r(v), 120));

export const demoApi = {
  async suggest(q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    const names = Object.keys(ALIASES);
    return [...names.filter((n) => n.startsWith(q)).sort(), ...names.filter((n) => n.includes(q) && !n.startsWith(q)).sort()].slice(0, 8);
  },
  async patients() {
    return Object.values(PATIENTS).map(({ patient_id, age, conditions }) => ({ patient_id, age, conditions }));
  },
  async check(drugA, drugB, patientId) {
    const na = normalise(drugA), nb = normalise(drugB);
    const unresolved = [na, nb].filter((n) => !n.ingredients.length).map(({ query, suggestions }) => ({ query, suggestions }));
    if (unresolved.length) throw new DemoError(422, { error: "unknown_drug_name", unresolved });
    const a = na.ingredients[0], b = nb.ingredients[0];
    if (a === b) throw new DemoError(422, { error: "same_ingredient" });
    const p = PATIENTS[patientId];
    if (!p) throw new DemoError(404, { error: "patient_not_found", patient_id: patientId });
    const pair = [a, b].sort();
    const severity = INTERACTIONS[pair.join("|")] ?? null;
    const r = score(pair, severity, p);
    return delay({
      drugs: pair, input_names: [drugA, drugB],
      base_severity: severity ?? "Unknown", severity_source: severity ? "DDInter" : "unknown", severity_confidence: null,
      risk_score: r.risk_score, risk_level: r.risk_level,
      score_breakdown: r.lines, score_capped: r.capped, missing_fields: r.missing,
      patient: p, mechanism: null, affected_systems: [], monitoring: [], citations: [],
      disclaimer: "Clinical decision support only. Not medical advice.",
    });
  },
};
