"""Runtime severity predictor (FR-05): plugs into the `predictor` hook of the pipeline.

Loads the bundle written by scripts/train_predictor.py. It only answers for drugs whose
fingerprint is in the bundle; anything else is (None, 0.0), which the pipeline turns into
"Unknown — consult a pharmacist" (NFR-03). The confidence floor itself is applied by
interactions.store.base_severity using rules.yaml (ml.min_confidence).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np

from rxguard.ml.features import pair_features
from rxguard.ml.train import decide


class MLPredictor:
    def __init__(self, bundle: dict[str, Any]):
        self.model = bundle["model"]
        self.classes = list(bundle["classes"])
        self.major_guard = bundle.get("major_guard")
        self.n_bits = bundle["n_bits"]
        self._packed = bundle["fingerprints"]
        self.metrics = bundle.get("metrics", {})

    @classmethod
    def load(cls, path: Path | str) -> "MLPredictor":
        import joblib
        return cls(joblib.load(path))

    def save(self, path: Path | str) -> None:  # convenience for tests
        import joblib
        joblib.dump({"model": self.model, "classes": self.classes, "major_guard": self.major_guard,
                     "n_bits": self.n_bits, "fingerprints": self._packed, "metrics": self.metrics,
                     "version": 1}, path)

    def knows(self, drug: str) -> bool:
        return drug.strip().lower() in self._packed

    def _fp(self, drug: str) -> Optional[np.ndarray]:
        packed = self._packed.get(drug.strip().lower())
        return None if packed is None else np.unpackbits(packed)[: self.n_bits]

    def predict(self, a: str, b: str) -> tuple[Optional[str], float]:
        fa, fb = self._fp(a), self._fp(b)
        if fa is None or fb is None:
            return None, 0.0
        proba = self.model.predict_proba(pair_features(fa, fb)[None, :])
        labels, conf = decide(proba, self.classes, self.major_guard)
        if labels[0] == "Unknown":   # cannot rule out Major -> "Unknown — consult a pharmacist"
            return None, round(float(conf[0]), 3)
        return str(labels[0]), round(float(conf[0]), 3)
