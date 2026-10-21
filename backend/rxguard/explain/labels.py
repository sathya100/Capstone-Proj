"""openFDA drug labels → section-tagged passages for retrieval (offline pipeline 3, FR-11).

A label from https://api.fda.gov/drug/label.json has one field per section, each a list of strings.
We keep the sections that describe interactions and risks, split each into passages of about
120 words on sentence boundaries, and tag every passage with its drug and section so a citation
can say exactly where a sentence came from ("FDA label: warfarin, Drug Interactions").
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

# openFDA field -> section title shown in citations. Prescription (PLR) and OTC labels differ.
SECTIONS = {
    "boxed_warning": "Boxed Warning",
    "contraindications": "Contraindications",
    "drug_interactions": "Drug Interactions",
    "warnings_and_cautions": "Warnings and Precautions",
    "warnings": "Warnings",
    "precautions": "Precautions",
    "mechanism_of_action": "Mechanism of Action",
    "do_not_use": "Do Not Use",                                  # OTC
    "ask_doctor_or_pharmacist": "Ask a Doctor or Pharmacist",    # OTC
    "ask_doctor": "Ask a Doctor",                                # OTC
    "stop_use": "Stop Use",                                      # OTC
}
INTERACTION_SECTIONS = {"drug_interactions", "ask_doctor_or_pharmacist", "contraindications", "do_not_use"}

_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(•●\-\d])")
_HEADING = re.compile(r"^\s*(\d+(\.\d+)*\s+)?[A-Z][A-Z &/,\-]{3,}\s+(?=[A-Z][a-z])")


@dataclass
class Passage:
    id: str              # "<drug>:<section>:<n>"
    drug: str            # lower-case ingredient name
    section: str         # openFDA field name
    section_title: str
    text: str
    set_id: str = ""     # openFDA label set_id, for traceability
    effective_time: str = ""

    @property
    def citation(self) -> str:
        return f"FDA label: {self.drug}, {self.section_title}"


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return _HEADING.sub("", text, count=1)  # drop a leading "7 DRUG INTERACTIONS " heading


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]


def chunk(text: str, max_words: int = 120, overlap: int = 1) -> list[str]:
    """Group sentences into passages of at most ~max_words, repeating `overlap` sentences."""
    sents = split_sentences(_clean(text))
    out, cur, words = [], [], 0
    for s in sents:
        n = len(s.split())
        if cur and words + n > max_words:
            out.append(" ".join(cur))
            cur = cur[-overlap:] if overlap else []
            words = sum(len(x.split()) for x in cur)
        cur.append(s)
        words += n
    if cur:
        tail = " ".join(cur)
        if not out or tail not in out[-1]:
            out.append(tail)
    return out


def passages_from_label(label: dict[str, Any], drug: str, max_words: int = 120) -> list[Passage]:
    drug = drug.strip().lower()
    out: list[Passage] = []
    for field, title in SECTIONS.items():
        for block in label.get(field) or []:
            for text in chunk(block, max_words):
                if len(text.split()) < 4:
                    continue
                out.append(Passage(f"{drug}:{field}:{len([p for p in out if p.section == field])}",
                                   drug, field, title, text, label.get("set_id", ""),
                                   label.get("effective_time", "")))
    return out


def label_score(label: dict[str, Any], drug: str) -> tuple:
    """Rank candidate labels for one ingredient: single-ingredient exact match first, then labels
    with an interactions section, then the most recent."""
    names = [n.lower() for n in (label.get("openfda", {}).get("generic_name") or [])]
    exact = any(n == drug for n in names)
    single = exact and all(" and " not in n and "," not in n for n in names)
    has_ix = bool(label.get("drug_interactions") or label.get("ask_doctor_or_pharmacist"))
    has_warn = bool(label.get("warnings") or label.get("warnings_and_cautions") or label.get("boxed_warning"))
    return (single, exact, has_ix, has_warn, label.get("effective_time", ""))


def best_label(results: Iterable[dict[str, Any]], drug: str) -> dict[str, Any] | None:
    results = list(results)
    return max(results, key=lambda r: label_score(r, drug.lower())) if results else None


def write_passages(passages: Iterable[Passage], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for p in passages:
            f.write(json.dumps(asdict(p)) + "\n")
            n += 1
    return n


def read_passages(path: Path) -> list[Passage]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [Passage(**json.loads(line)) for line in f if line.strip()]
