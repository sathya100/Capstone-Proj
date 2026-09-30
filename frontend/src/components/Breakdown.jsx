import { UNKNOWN, segmentTone } from "../risk";

const FIELD_NAMES = {
  age: "age",
  egfr: "eGFR (kidney function)",
  alt: "ALT (liver enzyme)",
  alcohol_drinks_per_day: "alcohol use",
};

// Points breakdown (FR-09, NFR-05): one row per rule, swatch matches its strip segment.
export default function Breakdown({ result }) {
  const unknown = result.risk_level === UNKNOWN;
  const lines = result.score_breakdown;
  const total = lines.reduce((s, l) => s + l.points, 0);
  const missingRecord = result.missing_fields.filter((f) => !f.startsWith("drug_flags:"));
  const missingFlags = result.missing_fields.filter((f) => f.startsWith("drug_flags:")).map((f) => f.slice(11));

  return (
    <div>
      <table className="w-full text-base">
        <caption className="sr-only">How the score was calculated</caption>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i} className="border-b border-rule last:border-0">
              <td className="py-2 pr-3 w-5 align-top">
                <span className="block w-4 h-4 mt-1 rounded-[3px]"
                      style={{ background: unknown ? "var(--color-rule)" : segmentTone(i, result.risk_level) }} />
              </td>
              <td className="py-2 pr-3">{l.reason}</td>
              <td className="py-2 text-right font-bold whitespace-nowrap">
                {unknown ? <span className="text-muted font-normal">not scored</span> : `+${l.points}`}
              </td>
            </tr>
          ))}
          {lines.length === 0 && (
            <tr><td className="py-2 text-muted" colSpan={3}>No risk factors apply to this patient.</td></tr>
          )}
        </tbody>
        {!unknown && (
          <tfoot>
            <tr className="border-t-2 border-ink">
              <td />
              <td className="py-2 font-bold">Total{result.score_capped ? ` ${total}, capped at 10` : ""}</td>
              <td className="py-2 text-right font-bold">{result.risk_score}</td>
            </tr>
          </tfoot>
        )}
      </table>

      {unknown && (
        <p className="mt-3 text-base">
          This pair isn't in the interaction database and there's no confident prediction for it, so no score is given.
          Check it with a pharmacist before dispensing.
        </p>
      )}
      {missingRecord.length > 0 && (
        <p className="mt-3 text-sm text-muted">
          Not in the patient record, so not scored: {missingRecord.map((f) => FIELD_NAMES[f] ?? f).join(", ")}.
        </p>
      )}
      {missingFlags.length > 0 && (
        <p className="mt-1 text-sm text-muted">
          No kidney, liver or condition data yet for {missingFlags.join(", ")}; only base severity and age apply to it.
        </p>
      )}
    </div>
  );
}
