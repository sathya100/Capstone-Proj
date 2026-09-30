import { BANDS, UNKNOWN, segmentTone } from "../risk";

// The gauge (FR-14): ten cells, each filled by the rule that earned that point, so the strip
// and the breakdown rows beneath it are the same information.
export default function ScoreStrip({ result, compact = false }) {
  const unknown = result.risk_level === UNKNOWN;
  const cells = [];
  if (!unknown) {
    let i = 0;
    result.score_breakdown.forEach((line, seg) => {
      for (let k = 0; k < line.points && i < 10; k++, i++) {
        cells.push({ tone: segmentTone(seg, result.risk_level), seg, start: k === 0 });
      }
    });
  }
  const h = compact ? "h-9" : "h-14";

  return (
    <figure aria-label={unknown ? "Risk unknown" : `Risk score ${result.risk_score} of 10`}>
      <div className="grid grid-cols-10 gap-1">
        {Array.from({ length: 10 }, (_, i) => {
          const c = cells[i];
          return (
            <div key={i}
                 className={`${h} rounded-[3px] ${c ? "cell-fill" : ""} ${!c && !unknown ? "bg-rule/60" : ""}`}
                 style={{
                   background: c ? c.tone : unknown
                     ? "repeating-linear-gradient(135deg, var(--color-unknown) 0 4px, color-mix(in srgb, var(--color-unknown) 25%, white) 4px 9px)"
                     : undefined,
                   animationDelay: c ? `${i * 45}ms` : undefined,
                 }} />
          );
        })}
      </div>
      {!compact && (
        <div className="grid grid-cols-10 gap-1 mt-2 text-xs text-muted" aria-hidden="true">
          {BANDS.map((b) => (
            <div key={b.name} style={{ gridColumn: `${b.from === 0 ? 1 : b.from} / ${b.to + 1}` }}
                 className="border-t-2 border-rule pt-1">
              {b.name} {b.from}–{b.to}
            </div>
          ))}
        </div>
      )}
    </figure>
  );
}
