"""Step 4: transparent, config-driven risk scoring (FR-08, FR-09, FR-10, NFR-03, NFR-05).

This is the only place patient data changes the result. Every point added here comes from one
named rule in config/rules.yaml, and every line is returned in the breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from rxguard.models import Condition, PatientContext, RiskScore, ScoreLine, SeverityResult

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
UNKNOWN_LEVEL = "Unknown — consult a pharmacist"


@dataclass
class DrugFlags:
    liver_metabolised: bool = False
    kidney_cleared: bool = False
    condition_cautions: tuple[str, ...] = ()
    known: bool = True


class RulesEngine:
    def __init__(self, rules: dict[str, Any], drug_flags: dict[str, Any]):
        self.rules = rules
        self.drugs: dict[str, Any] = {k.lower(): v for k, v in (drug_flags.get("drugs") or {}).items()}
        self.condition_groups: dict[str, Any] = drug_flags.get("condition_groups") or {}

    @classmethod
    def from_config(cls, config_dir: Path = CONFIG_DIR) -> "RulesEngine":
        rules = yaml.safe_load((config_dir / "rules.yaml").read_text())
        flags = yaml.safe_load((config_dir / "drug_flags.yaml").read_text())
        return cls(rules, flags)

    # ---- lookups -------------------------------------------------------------------------

    def flags_for(self, drug: str) -> DrugFlags:
        entry = self.drugs.get(drug.lower())
        if entry is None:
            return DrugFlags(known=False)
        return DrugFlags(
            liver_metabolised=bool(entry.get("liver_metabolised")),
            kidney_cleared=bool(entry.get("kidney_cleared")),
            condition_cautions=tuple(entry.get("condition_cautions") or ()),
        )

    def groups_for(self, condition: Condition) -> list[str]:
        """Return the condition-group keys a patient condition belongs to."""
        matched = []
        text = condition.display.lower()
        for key, group in self.condition_groups.items():
            codes = {str(c) for c in group.get("snomed", []) or []}
            if condition.code and condition.code in codes:
                matched.append(key)
            elif any(kw.lower() in text for kw in group.get("keywords", []) or []):
                matched.append(key)
        return matched

    def _organ_rule(self, group_key: str) -> Optional[str]:
        return (self.condition_groups.get(group_key) or {}).get("organ_rule")

    def band(self, score: int) -> str:
        for b in sorted(self.rules["bands"], key=lambda b: -b["min"]):
            if score >= b["min"]:
                return b["name"]
        return self.rules["bands"][-1]["name"]

    # ---- scoring -------------------------------------------------------------------------

    def score(self, drugs: list[str], severity: SeverityResult, patient: PatientContext) -> RiskScore:
        r = self.rules
        drugs = [d.lower() for d in drugs]
        flags = {d: self.flags_for(d) for d in drugs}
        lines: list[ScoreLine] = []
        missing = patient.missing_fields()
        missing += [f"drug_flags:{d}" for d, f in flags.items() if not f.known]

        # Base severity
        if severity.severity is not None:
            label = severity.severity
            src = f" ({severity.source}, confidence {severity.confidence:.2f})" if severity.source == "predicted" else ""
            lines.append(ScoreLine(f"Base interaction: {label}{src}", r["base_severity_points"][label], "base_severity"))

        # Patient conditions: organ-rule conditions vs. caution conditions
        patient_groups: dict[str, Condition] = {}
        for cond in patient.conditions:
            for g in self.groups_for(cond):
                patient_groups.setdefault(g, cond)

        # Condition cautions: each patient condition group counted once, even if both drugs list it
        for g, cond in patient_groups.items():
            if self._organ_rule(g):
                continue
            cautioned_by = [d for d in drugs if g in flags[d].condition_cautions]
            if cautioned_by:
                lines.append(ScoreLine(
                    f"{cond.display} is a caution for {', '.join(cautioned_by)}",
                    r["condition_caution_points"], "condition_caution"))

        # Age
        if patient.age is not None and patient.age >= r["age"]["threshold"]:
            lines.append(ScoreLine(f"Age {patient.age}", r["age"]["points"], "age"))

        # Kidney
        kidney_drugs = [d for d in drugs if flags[d].kidney_cleared]
        if kidney_drugs and patient.egfr is not None and patient.egfr < r["kidney"]["egfr_below"]:
            lines.append(ScoreLine(
                f"eGFR {patient.egfr:g} + kidney-cleared {', '.join(kidney_drugs)}",
                r["kidney"]["points"], "kidney"))

        # Liver: disease OR ALT > multiple x ULN, and a liver-metabolised drug
        liver_drugs = [d for d in drugs if flags[d].liver_metabolised]
        if liver_drugs:
            liver_cond = next((c for g, c in patient_groups.items() if self._organ_rule(g) == "liver"), None)
            alt_limit = r["liver"]["alt_uln"] * r["liver"]["alt_multiple"]
            high_alt = patient.alt is not None and patient.alt > alt_limit
            if liver_cond or high_alt:
                cause = liver_cond.display if liver_cond else f"ALT {patient.alt:g} (> {alt_limit:g})"
                lines.append(ScoreLine(f"{cause} + {', '.join(liver_drugs)}", r["liver"]["points"], "liver"))

        # Alcohol + acetaminophen
        a = r["alcohol"]
        if (a["drug"] in drugs and patient.alcohol_drinks_per_day is not None
                and patient.alcohol_drinks_per_day >= a["drinks_per_day_at_least"]):
            lines.append(ScoreLine(
                f"Alcohol {patient.alcohol_drinks_per_day:g} drinks/day + {a['drug']}", a["points"], "alcohol"))

        # NFR-03: unknown severity never becomes Low
        if severity.severity is None:
            return RiskScore(None, UNKNOWN_LEVEL, lines, missing)

        raw = sum(l.points for l in lines)
        total = min(raw, r["max_score"])
        return RiskScore(total, self.band(total), lines, missing, capped=raw > total)
