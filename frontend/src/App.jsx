import { useState } from "react";
import { ApiError, DEMO, api } from "./api";
import DrugInput from "./components/DrugInput";
import PatientSelect from "./components/PatientSelect";
import ResultPanel from "./components/ResultPanel";

const DISCLAIMER = "Clinical decision support only. Not medical advice.";

function ErrorNotice({ error, onPick }) {
  const d = error.detail;
  let body;
  if (error.status === 0) {
    body = <>RxGuard can't reach its API. Start the backend with <code className="font-bold">uvicorn rxguard.api.main:app</code> in the <code>backend</code> folder, then check again.</>;
  } else if (d?.error === "unknown_drug_name") {
    body = (
      <ul className="space-y-2">
        {d.unresolved.map((u) => (
          <li key={u.query}>
            No medicine called “{u.query}”.{" "}
            {u.suggestions.length ? (
              <>Did you mean{" "}
                {u.suggestions.map((s, i) => (
                  <span key={s}>
                    {i > 0 && ", "}
                    <button type="button" onClick={() => onPick(u.query, s)}
                            className="font-bold underline underline-offset-2 text-act hover:text-act-dark">{s}</button>
                  </span>
                ))}?
              </>
            ) : "Check the spelling or try the generic name."}
          </li>
        ))}
      </ul>
    );
  } else if (d?.error === "patient_not_found") {
    body = <>No patient with ID {d.patient_id}. Choose one from the list.</>;
  } else if (d?.error === "same_ingredient") {
    body = <>Both names are the same active ingredient. Enter two different medicines.</>;
  } else {
    body = <>The check failed ({error.message}). Try again.</>;
  }
  return <div role="alert" className="bg-surface border-2 border-high rounded-lg p-4 text-base">{body}</div>;
}

function CompareSummary({ a, b }) {
  if (a.risk_score == null || b.risk_score == null) return null;
  const diff = a.risk_score - b.risk_score;
  const rulesA = new Set(a.score_breakdown.map((l) => l.reason));
  const onlyA = a.score_breakdown.filter((l) => !b.score_breakdown.some((m) => m.reason === l.reason));
  const onlyB = b.score_breakdown.filter((l) => !rulesA.has(l.reason));
  const [hi, lo, extra] = diff >= 0 ? [a, b, onlyA] : [b, a, onlyB];
  if (diff === 0) return <p className="text-lg">Both patients score {a.risk_score}.</p>;
  return (
    <p className="text-lg max-w-prose">
      <b>{hi.patient.patient_id}</b> scores {Math.abs(diff)} {Math.abs(diff) === 1 ? "point" : "points"} higher than{" "}
      <b>{lo.patient.patient_id}</b> for the same pair.
      {extra.length > 0 && <> The difference: {extra.map((l) => `${l.reason} (+${l.points})`).join("; ")}.</>}
    </p>
  );
}

export default function App() {
  const [drugA, setDrugA] = useState("");
  const [drugB, setDrugB] = useState("");
  const [patient, setPatient] = useState("");
  const [compare, setCompare] = useState(false);
  const [patient2, setPatient2] = useState("");
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const ready = drugA.trim() && drugB.trim() && patient && (!compare || patient2);

  async function run(a = drugA, b = drugB, p1 = patient, p2 = compare ? patient2 : null) {
    setBusy(true);
    setError(null);
    try {
      const ids = p2 ? [p1, p2] : [p1];
      setResults(await Promise.all(ids.map((id) => api.check(a, b, id))));
    } catch (e) {
      setResults(null);
      setError(e instanceof ApiError ? e : new ApiError(-1, String(e)));
    } finally {
      setBusy(false);
    }
  }

  function tryExample() {
    setDrugA("Tylenol"); setDrugB("Warfarin"); setPatient("P-1042"); setPatient2("P-2210"); setCompare(true);
    run("Tylenol", "Warfarin", "P-1042", "P-2210");
  }

  function pickSuggestion(query, name) {
    const a = drugA.trim().toLowerCase() === query ? name : drugA;
    const b = drugB.trim().toLowerCase() === query ? name : drugB;
    setDrugA(a); setDrugB(b);
    run(a, b);
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-ink text-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-2xl font-bold">RxGuard</h1>
          <p className="text-sm text-white/80">{DISCLAIMER}</p>
        </div>
      </header>

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 py-6 sm:py-10">
        <form onSubmit={(e) => { e.preventDefault(); if (ready) run(); }}
              className="bg-surface rounded-lg border-2 border-rule p-5 sm:p-6">
          <p className="text-lg mb-5 max-w-prose">
            Check how risky two medicines are together for a specific patient.
          </p>
          {DEMO && (
            <p className="text-base mb-5 max-w-prose border-l-4 border-act pl-3">
              Demo version: runs in your browser with three synthetic patients (P-1042, P-2210, P-3301) and one example
              interaction, acetaminophen with warfarin. Try Tylenol, Coumadin, Advil or Glucophage.
            </p>
          )}
          <div className="grid gap-4 md:grid-cols-[1fr_1fr_1.4fr]">
            <DrugInput label="First medicine" value={drugA} onChange={setDrugA} placeholder="Brand or generic name" />
            <DrugInput label="Second medicine" value={drugB} onChange={setDrugB} placeholder="Brand or generic name" />
            <PatientSelect label={compare ? "Patient A" : "Patient"} value={patient} onChange={setPatient} />
          </div>
          {compare && (
            <div className="grid gap-4 md:grid-cols-[1fr_1fr_1.4fr] mt-4">
              <div className="hidden md:block md:col-span-2" />
              <PatientSelect label="Patient B" value={patient2} onChange={setPatient2} />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 mt-5">
            <button type="submit" disabled={!ready || busy}
                    className="h-12 px-6 rounded-md bg-act text-white text-lg font-bold hover:bg-act-dark disabled:opacity-40 disabled:cursor-not-allowed">
              {busy ? "Checking…" : compare ? "Check both patients" : "Check interaction"}
            </button>
            <label className="flex items-center gap-2 text-base cursor-pointer">
              <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)}
                     className="w-5 h-5 accent-act" />
              Compare two patients
            </label>
            <button type="button" onClick={tryExample}
                    className="text-base text-act underline underline-offset-2 hover:text-act-dark">
              Try the example: Tylenol and warfarin for two different patients
            </button>
          </div>
        </form>

        <div className="mt-6 sm:mt-8 space-y-6">
          {error && <ErrorNotice error={error} onPick={pickSuggestion} />}
          {results?.length === 2 && <CompareSummary a={results[0]} b={results[1]} />}
          {results && (
            <div className={results.length === 2 ? "grid gap-6 lg:grid-cols-2" : ""}>
              {results.map((r) => (
                <ResultPanel key={r.patient.patient_id} result={r} compact={results.length === 2} />
              ))}
            </div>
          )}
          {!results && !error && (
            <p className="text-base text-muted max-w-prose">
              The score starts from how serious the interaction is in general, then adds points for this patient's
              age, conditions, kidney and liver results, and alcohol use. Every point is listed with its reason.
            </p>
          )}
        </div>
      </main>

      <footer className="border-t border-rule">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 text-sm text-muted">
          {DISCLAIMER} Synthetic patients only. Interaction data: DDInter. Drug names: NLM RxNorm.
        </div>
      </footer>
    </div>
  );
}
