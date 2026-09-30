import { UNKNOWN, levelStyle } from "../risk";
import BodyMap from "./BodyMap";
import Breakdown from "./Breakdown";
import ScoreStrip from "./ScoreStrip";

function SeveritySource({ r }) {
  if (r.severity_source === "DDInter") return <>Base interaction <b>{r.base_severity}</b>, from DDInter</>;
  if (r.severity_source === "predicted")
    return <>Base interaction <b>{r.base_severity}</b>, predicted ({Math.round(r.severity_confidence * 100)}% confidence)</>;
  return <>Not in the interaction database</>;
}

function PatientFacts({ p }) {
  const facts = [
    p.age != null && `Age ${p.age}`,
    p.egfr != null && `eGFR ${p.egfr}`,
    p.alt != null && `ALT ${p.alt} U/L`,
    p.alcohol_drinks_per_day != null && `${p.alcohol_drinks_per_day} drinks/day`,
  ].filter(Boolean);
  return (
    <p className="text-sm text-muted">
      {facts.join(", ")}
      {p.conditions.length > 0 && <><br />{p.conditions.map((c) => c.replace(/ \((disorder|finding)\)$/, "")).join(", ")}</>}
    </p>
  );
}

function Explanation({ r }) {
  if (!r.mechanism) {
    return (
      <p className="text-base text-muted">
        A plain-language explanation quoting the FDA labels for {r.drugs.join(" and ")} will appear here once the
        explainer is built. Until then, the score and every point in it come from the rules above.
      </p>
    );
  }
  return (
    <div className="space-y-3 text-base max-w-prose">
      <p>{r.mechanism}</p>
      {r.monitoring?.length > 0 && (
        <div>
          <h4 className="font-bold">What to monitor</h4>
          <ul className="list-disc pl-5">{r.monitoring.map((m) => <li key={m}>{m}</li>)}</ul>
        </div>
      )}
      {r.citations?.length > 0 && (
        <p className="text-sm text-muted">Sources: {r.citations.join("; ")}</p>
      )}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="pt-5 mt-5 border-t border-rule">
      <h3 className="text-lg font-bold mb-3">{title}</h3>
      {children}
    </section>
  );
}

export default function ResultPanel({ result: r, compact = false }) {
  const style = levelStyle(r.risk_level);
  const unknown = r.risk_level === UNKNOWN;

  return (
    <article className="bg-surface rounded-lg border-2 border-rule p-5 sm:p-7" aria-live="polite">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 mb-5">
        <div>
          <p className="text-sm font-bold text-muted">{r.patient.patient_id}</p>
          <h2 className="text-2xl sm:text-3xl font-bold leading-tight">{r.drugs.join(" + ")}</h2>
          <p className="text-base mt-1"><SeveritySource r={r} /></p>
        </div>
        <div className={compact ? "" : "sm:text-right"}>
          {unknown ? (
            <p className={`text-2xl font-bold leading-tight ${style.text}`}>Unknown<br /><span className="text-base">consult a pharmacist</span></p>
          ) : (
            <p className={`leading-none font-bold ${style.text}`}>
              <span className={compact ? "text-6xl" : "text-7xl sm:text-8xl"}>{r.risk_score}</span>
              <span className="text-xl text-muted font-normal">/10</span>
              <span className="block text-2xl mt-1">{r.risk_level} risk</span>
            </p>
          )}
        </div>
      </header>

      <ScoreStrip result={r} compact={compact} />
      <div className="mt-5"><Breakdown result={r} /></div>

      <Section title="Patient record used"><PatientFacts p={r.patient} /></Section>

      {!compact && (
        <div className="grid md:grid-cols-2 md:gap-8">
          <Section title="Body systems at risk"><BodyMap result={r} /></Section>
          <Section title="Why these drugs interact"><Explanation r={r} /></Section>
        </div>
      )}
    </article>
  );
}
