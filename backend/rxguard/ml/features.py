"""Molecular features for the severity predictor (offline pipeline 2).

Each drug becomes a Morgan fingerprint (radius 2) computed from its PubChem SMILES with RDKit.
A drug pair becomes fp_a + fp_b: each position is 0 (neither drug has the substructure),
1 (one drug has it) or 2 (both have it). The sum is symmetric, so (A, B) and (B, A) always get
the same prediction, and it encodes both the union and the overlap of the two structures.

RDKit is needed only to build fingerprints (training time). The saved model carries the
fingerprints of every drug it knows, so the API runs without RDKit.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

DEFAULT_BITS = 1024
DEFAULT_RADIUS = 2


def morgan_fingerprint(smiles: str, n_bits: int = DEFAULT_BITS, radius: int = DEFAULT_RADIUS) -> Optional[np.ndarray]:
    """Bit vector (uint8, 0/1) for one molecule, or None if RDKit cannot parse the SMILES."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdFingerprintGenerator

    RDLogger.DisableLog("rdApp.*")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
    return gen.GetFingerprintAsNumPy(mol).astype(np.uint8)


def fingerprints_for(smiles_by_drug: dict[str, str], n_bits: int = DEFAULT_BITS,
                     radius: int = DEFAULT_RADIUS) -> dict[str, np.ndarray]:
    """Fingerprints keyed by lower-case drug name; drugs whose SMILES fail to parse are skipped."""
    out = {}
    for name, smi in smiles_by_drug.items():
        if not smi:
            continue
        fp = morgan_fingerprint(smi, n_bits, radius)
        if fp is not None:
            out[name.strip().lower()] = fp
    return out


def pair_features(fp_a: np.ndarray, fp_b: np.ndarray) -> np.ndarray:
    """Symmetric pair vector: fp_a + fp_b, values 0/1/2."""
    return (fp_a.astype(np.uint8) + fp_b.astype(np.uint8)).astype(np.uint8)
