import { useEffect, useId, useState } from "react";
import { api } from "../api";

function describe(p) {
  const bits = [p.patient_id];
  if (p.age != null) bits.push(`age ${p.age}`);
  if (p.conditions?.length) bits.push(p.conditions.map((c) => c.replace(/ \((disorder|finding)\)$/, "")).join(", "));
  return bits.join(", ");
}

// Patient picker. Falls back to a plain ID field if the patient list can't be loaded.
export default function PatientSelect({ label, value, onChange }) {
  const [patients, setPatients] = useState(null);
  const id = useId();

  useEffect(() => {
    api.patients().then(setPatients).catch(() => setPatients([]));
  }, []);

  const field = "w-full h-12 px-3 text-lg bg-surface border-2 border-rule rounded-md focus:border-act focus:outline-none";

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-bold text-muted mb-1">{label}</label>
      {patients?.length ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={`${field} truncate`}>
          <option value="" disabled>Choose a patient</option>
          {patients.map((p) => (
            <option key={p.patient_id} value={p.patient_id}>{describe(p)}</option>
          ))}
        </select>
      ) : (
        <input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder="P-1042"
               autoComplete="off" className={field} />
      )}
    </div>
  );
}
