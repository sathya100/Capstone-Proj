"""Step 5: cited plain-language explanation from FDA label passages (FR-11, FR-12, FR-13, NFR-04, NFR-06).

  1. Retrieve the label passages for both drugs (retriever.py).
  2. Ask the LLM for mechanism, monitoring points and affected body systems, where every item must
     cite passage ids from the numbered list it was given — or, with no LLM configured, pick the
     sentences straight from the passages ("extractive" mode).
  3. Citation check (FR-13): any item with no citation, or citing an id that was not retrieved, is
     dropped and recorded under explanation.dropped. What remains is 100% cited (NFR-04).

The LLM never sees patient data (NFR-06) and never decides severity or score: it gets only the two
ingredient names, the database severity for context, and the passages.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from rxguard.explain.labels import INTERACTION_SECTIONS, Passage, read_passages, split_sentences
from rxguard.explain.llm import LLM, LLMError, make_llm
from rxguard.explain.retriever import Retriever, load_retriever

ROOT = Path(__file__).resolve().parents[2]
PARTS = ("mechanism", "monitoring", "affected_systems")
SYSTEMS = ["blood clotting", "liver", "kidneys", "stomach", "heart", "brain / nervous system"]

SYSTEM_PROMPT = """You explain drug-drug interactions to pharmacists and clinicians.

Rules:
- Use ONLY the numbered FDA label passages you are given. Do not use outside knowledge.
- Every item you write must cite the passage ids that support it, e.g. "cites": ["P2"].
- If the passages do not describe an interaction between the two drugs, return empty lists.
- Plain language, one sentence per item, no dosing advice, no statement of how severe the
  interaction is (severity comes from a database, not from you).

Return only this JSON object:
{
  "mechanism": [{"text": "<how or why the two drugs interact>", "cites": ["P1"]}],
  "monitoring": [{"text": "<what to monitor or review>", "cites": ["P3"]}],
  "affected_systems": [{"text": "<one of: blood clotting, liver, kidneys, stomach, heart, brain / nervous system>", "cites": ["P1"]}]
}
Give at most 3 mechanism items, 4 monitoring items and 4 affected systems."""

_INTERACT = re.compile(r"increas|decreas|risk|enhanc|potentiat|inhibit|reduc|prolong|bleed|toxic|effect|interact|level|concentration", re.I)
_MONITOR = re.compile(r"monitor|\bINR\b|prothrombin|check|measure|blood test|laborator|observe|ask a doctor|consult|adjust|evaluat", re.I)
_SYSTEM_WORDS = [
    ("blood clotting", re.compile(r"bleed|hemorrh|haemorrh|\bINR\b|prothrombin|anticoagul|clot|platelet", re.I)),
    ("liver", re.compile(r"hepat|liver", re.I)),
    ("kidneys", re.compile(r"renal|kidney|nephro", re.I)),
    ("stomach", re.compile(r"gastro|\bGI\b|stomach|ulcer", re.I)),
    ("heart", re.compile(r"cardi|\bQT|arrhythm|heart", re.I)),
    ("brain / nervous system", re.compile(r"\bCNS\b|sedat|drows|seizure|serotonin|respiratory depression|dizz", re.I)),
]


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text, re.I) is not None


def _norm_ref(c: Any) -> str:
    s = str(c).strip().strip("[]").upper()
    return f"P{s}" if s.isdigit() else s


def parse_json(text: str) -> dict[str, Any]:
    """Model output → dict; tolerates ```json fences and text around the object."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model output")
    return json.loads(t[start:end + 1])


def validate(raw: dict[str, Any], refs: dict[str, Passage]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Citation check (FR-13). Keeps items whose citations are non-empty and all in the retrieved
    set. Inline markers like "[P2]" in the text count as citations and are stripped."""
    kept: dict[str, list[dict]] = {p: [] for p in PARTS}
    dropped: list[dict] = []
    for part in PARTS:
        items = raw.get(part) or []
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if isinstance(item, str):
                item = {"text": item, "cites": []}
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            cites = item.get("cites") or item.get("citations") or []
            if isinstance(cites, (str, int)):
                cites = [cites]
            inline = re.findall(r"\[(P?\d+)\]", text, re.I)
            text = re.sub(r"\s*\[(P?\d+)\]", "", text, flags=re.I).strip()
            refs_used = list(dict.fromkeys(_norm_ref(c) for c in [*cites, *inline]))
            if not text:
                continue
            if not refs_used:
                dropped.append({"part": part, "text": text, "reason": "no citation"})
            elif any(r not in refs for r in refs_used):
                bad = [r for r in refs_used if r not in refs]
                dropped.append({"part": part, "text": text, "reason": f"cites passage not retrieved: {', '.join(bad)}"})
            else:
                kept[part].append({"text": text, "cites": refs_used})
    return kept, dropped


def extractive(a: str, b: str, numbered: list[tuple[str, Passage]]) -> dict[str, Any]:
    """No-LLM explanation: label sentences that name the other drug, quoted with their passage id."""
    mech, mon, seen = [], [], set()
    for ref, p in numbered:
        other = b if p.drug == a else a
        names_other = _mentions(p.text, other)
        for s in split_sentences(p.text):
            if s in seen or len(s.split()) > 60:
                continue
            if _mentions(s, other) and _INTERACT.search(s) and len(mech) < 2:
                mech.append({"text": s, "cites": [ref]})
                seen.add(s)
            elif names_other and _MONITOR.search(s) and len(mon) < 3:
                mon.append({"text": s, "cites": [ref]})
                seen.add(s)
    systems, used = [], {}
    for item in mech + mon:
        for name, rx in _SYSTEM_WORDS:
            if rx.search(item["text"]) and name not in used:
                used[name] = item["cites"]
    systems = [{"text": n, "cites": c} for n, c in used.items()]
    return {"mechanism": mech, "monitoring": mon, "affected_systems": systems}


def user_prompt(a: str, b: str, severity: Optional[str], numbered: list[tuple[str, Passage]]) -> str:
    lines = [f"Drugs: {a} and {b}",
             f"Database severity (context only): {severity or 'not in database'}", "", "Passages:"]
    for ref, p in numbered:
        lines.append(f"[{ref}] ({p.citation}) {p.text}")
    return "\n".join(lines)


class RagExplainer:
    def __init__(self, retriever: Retriever, llm: Optional[LLM] = None, top_k: int = 6, min_per_drug: int = 2,
                 cache_path: Optional[Path] = None, llm_note: Optional[str] = None):
        self.retriever, self.llm = retriever, llm
        self.top_k, self.min_per_drug = top_k, min_per_drug
        self.cache_path = Path(cache_path) if cache_path else None
        self.llm_note = llm_note
        self._cache: dict[str, Any] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text())
            except ValueError:
                self._cache = {}

    def explain(self, drug_a: str, drug_b: str, severity: Optional[str] = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        a, b = drug_a.lower(), drug_b.lower()
        passages = self.retriever.retrieve(a, b, self.top_k, self.min_per_drug)
        numbered = [(f"P{i}", p) for i, p in enumerate(passages, 1)]
        refs = dict(numbered)
        meta = {"provider": self.llm.name if self.llm else "extractive",
                "model": self.llm.model if self.llm else None, "retriever": self.retriever.name}
        if self.llm_note:
            meta["note"] = self.llm_note

        if not passages:
            missing = [d for d in (a, b) if d not in self.retriever.drugs()]
            return self._result(a, b, {p: [] for p in PARTS}, [], numbered, t0, meta,
                                status="no_passages",
                                message=f"No FDA label passages indexed for {', '.join(missing) or 'these drugs'}. "
                                        "Run scripts/fetch_labels.py to add them.")

        key = self._key(a, b, meta, passages)
        if key in self._cache:
            out = self._cache[key]
            out["explanation"]["cached"] = True
            return out

        raw, fallback = None, None
        if self.llm is not None:
            try:
                raw = parse_json(self.llm.complete(SYSTEM_PROMPT, user_prompt(a, b, severity, numbered)))
            except (LLMError, ValueError) as e:
                fallback = f"LLM unavailable ({str(e)[:120]}); showing label sentences instead"
        kept, dropped = validate(raw, refs) if raw is not None else ({p: [] for p in PARTS}, [])
        if raw is not None and not kept["mechanism"] and not kept["monitoring"]:
            fallback = fallback or "LLM returned no cited sentences; showing label sentences instead"
        if raw is None or fallback:
            ex_kept, ex_dropped = validate(extractive(a, b, numbered), refs)
            if fallback and raw is not None:
                dropped += ex_dropped
            else:
                dropped = ex_dropped
            kept = ex_kept
            if fallback:
                meta = {**meta, "provider": "extractive", "fallback": fallback}

        if not kept["mechanism"] and not kept["monitoring"]:
            out = self._result(a, b, kept, dropped, numbered, t0, meta, status="no_supported_sentences",
                               message=f"The FDA label passages retrieved do not describe an interaction between "
                                       f"{a} and {b}. The score above still comes from the interaction database "
                                       f"and the patient rules.")
        else:
            out = self._result(a, b, kept, dropped, numbered, t0, meta, status="ok")
        if self.llm is not None and not fallback:
            self._remember(key, out)
        return out

    # -- helpers -------------------------------------------------------------------------------

    def _result(self, a, b, kept, dropped, numbered, t0, meta, status, message=None) -> dict[str, Any]:
        refs = dict(numbered)
        order: list[str] = []
        for part in PARTS:
            for item in kept[part]:
                for r in item["cites"]:
                    if r not in order:
                        order.append(r)
        cite_no = {r: i for i, r in enumerate(order, 1)}            # P-ref -> source number shown in UI
        citations = list(dict.fromkeys(refs[r].citation for r in order))
        sentences = [{"part": part, "text": it["text"], "sources": [cite_no[r] for r in it["cites"]]}
                     for part in PARTS for it in kept[part]]
        systems = []
        for it in kept["affected_systems"]:
            name = it["text"].strip().lower()
            systems.append(next((s for s in SYSTEMS if s.split(" /")[0] in name), it["text"].strip()))
        return {
            "mechanism": " ".join(it["text"] for it in kept["mechanism"]) or None,
            "affected_systems": list(dict.fromkeys(systems)),
            "monitoring": [it["text"] for it in kept["monitoring"]],
            "citations": citations,
            "explanation": {
                "status": status,
                **({"message": message} if message else {}),
                **meta,
                "sentences": sentences,
                "sources": [{"n": cite_no[r], "ref": r, "citation": refs[r].citation, "drug": refs[r].drug,
                             "section": refs[r].section_title, "text": refs[r].text, "passage_id": refs[r].id}
                            for r in order],
                "retrieved": [{"ref": r, "passage_id": p.id, "citation": p.citation} for r, p in numbered],
                "dropped": dropped,
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "cached": False,
            },
        }

    @staticmethod
    def _key(a, b, meta, passages) -> str:
        ids = "|".join(p.id for p in passages)
        raw = f"{'|'.join(sorted((a, b)))}|{meta['provider']}|{meta['model']}|{hashlib.sha1(ids.encode()).hexdigest()[:12]}"
        return raw

    def _remember(self, key: str, out: dict[str, Any]) -> None:
        self._cache[key] = out
        if self.cache_path:
            try:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(self._cache))
            except OSError:
                pass


def load_config(path: Path = ROOT / "config" / "explainer.yaml") -> dict[str, Any]:
    cfg = yaml.safe_load(Path(path).read_text()) if Path(path).exists() else {}
    cfg.setdefault("provider", "auto")
    cfg.setdefault("models", {})
    cfg.setdefault("retriever", "auto")
    cfg.setdefault("top_k", 6)
    cfg.setdefault("min_per_drug", 2)
    cfg.setdefault("timeout_seconds", 20)
    cfg.setdefault("cache", True)
    if os.getenv("RXGUARD_LLM_PROVIDER"):
        cfg["provider"] = os.environ["RXGUARD_LLM_PROVIDER"]
    if os.getenv("RXGUARD_LLM_MODEL"):
        cfg["models"][cfg["provider"]] = os.environ["RXGUARD_LLM_MODEL"]
    return cfg


def build_explainer(data: Path, cfg: Optional[dict[str, Any]] = None) -> RagExplainer:
    cfg = cfg or load_config()
    passages = read_passages(Path(data) / "labels" / "passages.jsonl")
    retriever = load_retriever(passages, Path(data) / "labels" / "chroma", cfg["retriever"])
    note = None
    try:
        llm = make_llm(cfg["provider"], cfg["models"], cfg["timeout_seconds"])
    except LLMError as e:
        llm, note = None, f"{e}; using extractive mode"
    cache = Path(data) / "cache" / "explanations.json" if cfg["cache"] else None
    return RagExplainer(retriever, llm, cfg["top_k"], cfg["min_per_drug"], cache, note)
