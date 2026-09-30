import { levelStyle, systemsFor } from "../risk";

const ORGANS = {
  brain: { name: "Brain / nervous system", d: "M66 20c0-9 7-14 14-14s14 5 14 14c0 6-4 9-7 9H73c-3 0-7-3-7-9z" },
  heart: { name: "Heart", d: "M92 86c3-5 11-4 11 3 0 6-7 10-11 14-4-4-11-8-11-14 0-7 8-8 11-3z" },
  blood: { name: "Blood clotting", d: "M80 60v120M80 100h-28M80 100h28", stroke: true },
  liver: { name: "Liver", d: "M50 116c6-6 26-8 36-4 2 5-2 12-10 15-9 3-20 3-26-1-3-3-3-7 0-10z" },
  stomach: { name: "Stomach", d: "M92 118c7-3 15 1 15 9 0 9-7 15-14 14-5-1-5-6-2-9 3-3 1-8 1-14z" },
  kidneys: {
    name: "Kidneys",
    d: "M60 146c-5 0-7 6-6 11s4 9 8 8 4-5 3-8 1-5 1-7-2-4-6-4zM100 146c5 0 7 6 6 11s-4 9-8 8-4-5-3-8-1-5-1-7 2-4 6-4z",
  },
};

// Body map (FR-15): systems touched by the fired rules, plus any from the FDA-label explanation.
export default function BodyMap({ result }) {
  const found = systemsFor(result);
  const color = levelStyle(result.risk_level).color;
  const list = [...found.entries()];

  return (
    <div className="flex gap-5 items-start">
      <svg viewBox="30 0 100 250" className="w-24 shrink-0" role="img"
           aria-label={list.length ? `Affected: ${list.map(([k]) => ORGANS[k].name).join(", ")}` : "No body systems flagged"}>
        <g fill="none" stroke="var(--color-rule)" strokeWidth="2.5" strokeLinejoin="round">
          <circle cx="80" cy="24" r="19" />
          <path d="M72 43v8M88 43v8M56 56c-10 3-14 12-15 24l-5 60M104 56c10 3 14 12 15 24l5 60" />
          <path d="M56 54h48c6 0 9 6 9 14l-2 80c0 16-6 24-14 30l1 66M56 54c-6 0-9 6-9 14l2 80c0 16 6 24 14 30l-1 66M80 178v66" />
        </g>
        {Object.entries(ORGANS).map(([key, o]) => {
          const on = found.has(key);
          if (key === "blood" && !on) return null;
          return o.stroke ? (
            <path key={key} d={o.d} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" opacity="0.9" />
          ) : (
            <path key={key} d={o.d} fill={on ? color : "var(--color-blister)"}
                  stroke={on ? color : "var(--color-rule)"} strokeWidth="1.5" />
          );
        })}
      </svg>
      <div className="text-base">
        {list.length ? (
          <ul className="space-y-2">
            {list.map(([key, why]) => (
              <li key={key}>
                <span className="font-bold">{ORGANS[key].name}</span>
                <span className="block text-sm text-muted">{why}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">No organ-specific risk factors for this patient.</p>
        )}
      </div>
    </div>
  );
}
