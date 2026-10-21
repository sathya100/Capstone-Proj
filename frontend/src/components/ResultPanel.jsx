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

function Refs({ nums }) {
  return (
    <sup className="ml-0.5 text-xs font-bold text-act">
      {nums.map((n, i) => <a key={n} href={`#src-${n}`} className="no-underline">{i > 0 && ","}[{n}]</a>)}
    </sup>
  );
}

function Explanation({ r }) {
  const ex = r.explanation;
  const muted = (text) => <p className="text-base text-muted max-w-prose">{text}</p>;

  if (!ex || ex.status === "demo") {
    return muted(<>The demo link runs without a server, so it has no FDA label index. Run the backend to see an
      explanation quoting the labels for {r.drugs.join(" and ")}. The score above comes from the rules either way.</>);
  }
  if (ex.status === "pending") return muted("Finding the relevant FDA label passages…");
  if (ex.status !== "ok") return muted(ex.message ?? "No explanation is available for this pair.");

  const mech = ex.sentences.filter((s) => s.part === "mechanism");
  const mon = ex.sentences.filter((s) => s.part === "monitoring");
  const quoted = ex.provider === "extractive";

  return (
    <div className="space-y-3 text-base max-w-prose">
      {mech.length > 0 && <p>{mech.map((s) => <span key={s.text}>{s.text}<Refs nums={s.sources} /> </span>)}</p>}
      {mon.length > 0 && (
        <div>
          <h4 className="font-bold">What to monitor</h4>
          <ul className="list-disc pl-5">{mon.map((s) => <li key={s.text}>{s.text}<Refs nums={s.sources} /></li>)}</ul>
        </div>
      )}
      <div>
        <h4 className="font-bold text-sm">Sources</h4>
        <ol className="text-sm text-muted space-y-1">
          {ex.sources.map((s) => (
            <li key={s.n} id={`src-${s.n}`}>
              <details>
                <summary className="cursor-pointer">[{s.n}] {s.citation}</summary>
                <blockquote className="mt-1 pl-3 border-l-2 border-rule">{s.text}</blockquote>
              </details>
            </li>
          ))}
        </ol>
      </div>
      <p className="text-xs text-muted">
        {quoted ? "Sentences quoted directly from the FDA labels." : `Written by ${ex.provider} from the label passages only.`}
        {" "}Every sentence cites its source
        {ex.dropped?.length > 0 && `; ${ex.dropped.length} unsupported ${ex.dropped.length === 1 ? "sentence was" : "sentences were"} removed`}.
      </p>
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
