"""Step 1: normalise brand/generic/misspelled names to RxNorm ingredients (FR-02, FR-03, NFR-07).

Uses the free RxNav REST API (no key) with an on-disk JSON cache so the demo still runs if the
API is down. An offline alias table covers a few common brands for development.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

RXNAV = "https://rxnav.nlm.nih.gov/REST"

OFFLINE_ALIASES = {  # brand/generic -> ingredient name, used only when RxNav is unreachable
    "tylenol": ["acetaminophen"], "paracetamol": ["acetaminophen"], "acetaminophen": ["acetaminophen"],
    "coumadin": ["warfarin"], "jantoven": ["warfarin"], "warfarin": ["warfarin"],
    "advil": ["ibuprofen"], "motrin": ["ibuprofen"], "ibuprofen": ["ibuprofen"],
    "glucophage": ["metformin"], "metformin": ["metformin"],
    "zestril": ["lisinopril"], "prinivil": ["lisinopril"], "lisinopril": ["lisinopril"],
    "neurontin": ["gabapentin"], "gabapentin": ["gabapentin"],
    "zocor": ["simvastatin"], "simvastatin": ["simvastatin"],
    "biaxin": ["clarithromycin"], "clarithromycin": ["clarithromycin"],
    "aspirin": ["aspirin"],
}


@dataclass
class NormalisedDrug:
    query: str
    ingredients: list[str] = field(default_factory=list)   # >1 for combination products (FR-03)
    rxcuis: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)   # "Did you mean…?" when no match
    source: str = "rxnav"

    @property
    def found(self) -> bool:
        return bool(self.ingredients)


class RxNormNormaliser:
    def __init__(self, cache_path: Path | str | None = None, timeout: float = 4.0, offline: bool = False):
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())
        self.client = httpx.Client(timeout=timeout)
        self.offline = offline

    def normalise(self, name: str) -> NormalisedDrug:
        key = name.strip().lower()
        if key in self.cache:
            return NormalisedDrug(**self.cache[key])
        result: Optional[NormalisedDrug] = None
        if not self.offline:
            try:
                result = self._rxnav(key)
            except httpx.HTTPError:
                result = None
        if result is None:
            result = self._offline(key)
        elif result.found:
            self._save(key, result)
        return result

    # ---- RxNav ---------------------------------------------------------------------------

    def _get(self, path: str, **params) -> dict:
        r = self.client.get(f"{RXNAV}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def _rxnav(self, key: str) -> NormalisedDrug:
        ids = self._get("/rxcui.json", name=key, search=2).get("idGroup", {}).get("rxnormId", [])
        if not ids:
            return NormalisedDrug(query=key, suggestions=self._suggest(key))
        related = self._get(f"/rxcui/{ids[0]}/related.json", tty="IN")
        ingredients, rxcuis = [], []
        for group in related.get("relatedGroup", {}).get("conceptGroup", []) or []:
            for c in group.get("conceptProperties", []) or []:
                ingredients.append(c["name"].lower())
                rxcuis.append(c["rxcui"])
        if not ingredients:  # the name is itself an ingredient
            props = self._get(f"/rxcui/{ids[0]}/properties.json").get("properties") or {}
            ingredients, rxcuis = [props.get("name", key).lower()], [ids[0]]
        return NormalisedDrug(query=key, ingredients=ingredients, rxcuis=rxcuis)

    def _suggest(self, key: str) -> list[str]:
        cands = self._get("/approximateTerm.json", term=key, maxEntries=10)
        out: list[str] = []
        for c in cands.get("approximateGroup", {}).get("candidate", []) or []:
            n = (c.get("name") or "").lower()
            if n and n not in out:
                out.append(n)
            if len(out) == 3:
                break
        return out

    # ---- fallback + cache ----------------------------------------------------------------

    def _offline(self, key: str) -> NormalisedDrug:
        if key in OFFLINE_ALIASES:
            return NormalisedDrug(query=key, ingredients=OFFLINE_ALIASES[key], source="offline")
        import difflib
        close = difflib.get_close_matches(key, OFFLINE_ALIASES.keys(), n=3, cutoff=0.6)
        return NormalisedDrug(query=key, suggestions=close, source="offline")

    def _save(self, key: str, result: NormalisedDrug) -> None:
        self.cache[key] = result.__dict__
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1))
