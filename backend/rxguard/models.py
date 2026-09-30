"""Shared data types passed between pipeline steps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Severity = Literal["Major", "Moderate", "Minor", "None"]
SeveritySource = Literal["DDInter", "predicted", "unknown"]


@dataclass
class Condition:
    display: str
    code: Optional[str] = None  # SNOMED code when available


@dataclass
class PatientContext:
    """Step 3 output. Any field may be None if the record lacks it (FR-07)."""

    patient_id: str
    age: Optional[int] = None
    conditions: list[Condition] = field(default_factory=list)
    egfr: Optional[float] = None          # mL/min/1.73m2, latest
    alt: Optional[float] = None           # U/L, latest
    alcohol_drinks_per_day: Optional[float] = None

    def missing_fields(self) -> list[str]:
        names = ["age", "egfr", "alt", "alcohol_drinks_per_day"]
        return [n for n in names if getattr(self, n) is None]


@dataclass
class SeverityResult:
    """Step 2 output."""

    severity: Optional[Severity]          # None when unknown and ML confidence too low
    source: SeveritySource
    confidence: Optional[float] = None    # only for predicted


@dataclass
class ScoreLine:
    reason: str
    points: int
    rule: str                             # rule id, so every point traces to one rule (NFR-05)


@dataclass
class RiskScore:
    """Step 4 output."""

    risk_score: Optional[int]             # None when severity unknown (NFR-03)
    risk_level: str                       # Low / Moderate / High / Unknown — consult a pharmacist
    breakdown: list[ScoreLine]
    missing_fields: list[str]
    capped: bool = False
