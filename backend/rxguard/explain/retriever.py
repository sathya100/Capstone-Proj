"""Retrieve the FDA label passages relevant to a drug pair (FR-11).

Two interchangeable backends:
  ChromaRetriever  — the spec's design: all-MiniLM-L6-v2 embeddings in a local ChromaDB.
                     Needs `pip install -r requirements-rag.txt` and scripts/build_label_index.py.
  TfidfRetriever   — scikit-learn TF-IDF over the same passages. No model download, runs anywhere;
                     used automatically when ChromaDB or the index is missing (NFR-07), and in tests.

Both search each drug's own label (metadata filter on drug) and rerank with the same two signals
that matter most for interactions: the passage names the other drug, and it comes from an
interactions section. At least `min_per_drug` passages are kept from each drug's label.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Protocol

from rxguard.explain.labels import INTERACTION_SECTIONS, Passage

MENTION_BOOST = 1.0     # passage names the other drug
SECTION_BOOST = 0.15    # passage is from an interactions section


class Retriever(Protocol):
    name: str

    def retrieve(self, drug_a: str, drug_b: str, k: int = 6, min_per_drug: int = 2) -> list[Passage]: ...

    def drugs(self) -> set[str]: ...


def _query(drug: str, other: str) -> str:
    return f"{other} interaction with {drug}: increased risk, effect, mechanism, monitoring"


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text, re.I) is not None


def _boost(p: Passage, other: str) -> float:
    return MENTION_BOOST * _mentions(p.text, other) + SECTION_BOOST * (p.section in INTERACTION_SECTIONS)


def _merge(scored: dict[str, list[tuple[float, Passage]]], k: int, min_per_drug: int) -> list[Passage]:
    """Take the top min_per_drug from each drug, then fill to k by score; best first."""
    chosen: list[tuple[float, Passage]] = []
    rest: list[tuple[float, Passage]] = []
    for items in scored.values():
        items = sorted(items, key=lambda t: -t[0])
        chosen += items[:min_per_drug]
        rest += items[min_per_drug:]
    rest.sort(key=lambda t: -t[0])
    chosen += rest[: max(0, k - len(chosen))]
    chosen.sort(key=lambda t: -t[0])
    return [p for _, p in chosen[:max(k, min_per_drug * len(scored))]]


class TfidfRetriever:
    name = "tfidf"

    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self._by_drug: dict[str, list[int]] = {}
        for i, p in enumerate(passages):
            self._by_drug.setdefault(p.drug, []).append(i)
        self._vec = self._matrix = None
        if passages:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, ngram_range=(1, 2), min_df=1)
            self._matrix = self._vec.fit_transform(p.text for p in passages)

    def drugs(self) -> set[str]:
        return set(self._by_drug)

    def retrieve(self, drug_a: str, drug_b: str, k: int = 6, min_per_drug: int = 2) -> list[Passage]:
        a, b = drug_a.lower(), drug_b.lower()
        scored: dict[str, list[tuple[float, Passage]]] = {}
        for drug, other in ((a, b), (b, a)):
            idx = self._by_drug.get(drug)
            if not idx:
                continue
            q = self._vec.transform([_query(drug, other)])
            sims = (self._matrix[idx] @ q.T).toarray().ravel()
            scored[drug] = [(float(s) + _boost(self.passages[i], other), self.passages[i]) for s, i in zip(sims, idx)]
        return _merge(scored, k, min_per_drug)


class ChromaRetriever:
    name = "chroma"
    COLLECTION = "fda_labels"
    MODEL = "all-MiniLM-L6-v2"

    def __init__(self, index_dir: Path | str, candidates: int = 15):
        import chromadb
        from chromadb.utils import embedding_functions

        self.client = chromadb.PersistentClient(path=str(index_dir))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=self.MODEL)
        self.col = self.client.get_collection(self.COLLECTION, embedding_function=ef)
        self.candidates = candidates
        self._drugs: Optional[set[str]] = None

    def drugs(self) -> set[str]:
        if self._drugs is None:
            metas = self.col.get(include=["metadatas"])["metadatas"]
            self._drugs = {m["drug"] for m in metas}
        return self._drugs

    def retrieve(self, drug_a: str, drug_b: str, k: int = 6, min_per_drug: int = 2) -> list[Passage]:
        a, b = drug_a.lower(), drug_b.lower()
        scored: dict[str, list[tuple[float, Passage]]] = {}
        for drug, other in ((a, b), (b, a)):
            res = self.col.query(query_texts=[_query(drug, other)], n_results=self.candidates,
                                 where={"drug": drug}, include=["documents", "metadatas", "distances"])
            items = []
            for pid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
                p = Passage(pid, meta["drug"], meta["section"], meta["section_title"], doc,
                            meta.get("set_id", ""), meta.get("effective_time", ""))
                items.append((1.0 - float(dist) + _boost(p, other), p))
            if items:
                scored[drug] = items
        return _merge(scored, k, min_per_drug)


def build_chroma_index(passages: list[Passage], index_dir: Path | str) -> int:
    """Embed every passage into a fresh ChromaDB collection (cosine distance)."""
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=str(index_dir))
    try:
        client.delete_collection(ChromaRetriever.COLLECTION)
    except Exception:
        pass
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=ChromaRetriever.MODEL)
    col = client.create_collection(ChromaRetriever.COLLECTION, embedding_function=ef,
                                   metadata={"hnsw:space": "cosine"})
    for i in range(0, len(passages), 256):
        batch = passages[i:i + 256]
        col.add(ids=[p.id for p in batch], documents=[p.text for p in batch],
                metadatas=[{"drug": p.drug, "section": p.section, "section_title": p.section_title,
                            "set_id": p.set_id, "effective_time": p.effective_time} for p in batch])
    return col.count()


def load_retriever(passages: list[Passage], index_dir: Path, kind: str = "auto") -> Retriever:
    """kind: auto (Chroma if installed and built, else TF-IDF) | chroma | tfidf."""
    has_index = (Path(index_dir) / "chroma.sqlite3").exists()
    if kind == "chroma":
        if not has_index:
            raise FileNotFoundError(f"no Chroma index in {index_dir}; run scripts/build_label_index.py")
        return ChromaRetriever(index_dir)
    if kind == "auto" and has_index:
        try:
            return ChromaRetriever(index_dir)
        except Exception:  # chromadb / sentence-transformers not installed or model not cached
            pass
    return TfidfRetriever(passages)
