// Shared helpers for risk levels and score segments.

export const UNKNOWN = "Unknown — consult a pharmacist";

export const LEVEL = {
  Low: { color: "var(--color-low)", text: "text-low", bg: "bg-low" },
  Moderate: { color: "var(--color-moderate)", text: "text-moderate", bg: "bg-moderate" },
  High: { color: "var(--color-high)", text: "text-high", bg: "bg-high" },
  [UNKNOWN]: { color: "var(--color-unknown)", text: "text-unknown", bg: "bg-unknown" },
};

export const levelStyle = (level) => LEVEL[level] ?? LEVEL[UNKNOWN];

// Band edges on the 0–10 strip (inclusive lower bounds), matching config/rules.yaml.
export const BANDS = [
  { name: "Low", from: 0, to: 3 },
  { name: "Moderate", from: 4, to: 6 },
  { name: "High", from: 7, to: 10 },
];

// Each breakdown line gets its own tone so strip segments and rows can be matched by eye.
// Base severity is always ink; patient factors step through lighter tints of the band colour.
const TINTS = [1, 0.72, 0.5, 0.34, 0.22];

export function segmentTone(index, level) {
  if (index === 0) return "var(--color-ink)";
  const base = levelStyle(level).color;
  const t = TINTS[(index - 1) % TINTS.length];
  return `color-mix(in srgb, ${base} ${Math.round(t * 100)}%, white)`;
}

// Body systems a rule touches, for the body map. Explainer output (affected_systems) adds to these.
const RULE_SYSTEMS = { liver: ["liver"], alcohol: ["liver"], kidney: ["kidneys"] };
const TEXT_SYSTEMS = [
  [/clot|bleed|blood|inr/i, "blood"],
  [/liver|hepat/i, "liver"],
  [/kidney|renal/i, "kidneys"],
  [/stomach|gastro|gi\b|ulcer/i, "stomach"],
  [/heart|cardiac|qt/i, "heart"],
  [/brain|cns|sedat|drows/i, "brain"],
];

export function systemsFor(result) {
  const found = new Map(); // system -> reason
  for (const line of result.score_breakdown ?? []) {
    for (const s of RULE_SYSTEMS[line.rule] ?? []) if (!found.has(s)) found.set(s, line.reason);
  }
  for (const label of result.affected_systems ?? []) {
    for (const [re, s] of TEXT_SYSTEMS) if (re.test(label) && !found.has(s)) found.set(s, `FDA label: ${label}`);
  }
  return found;
}
