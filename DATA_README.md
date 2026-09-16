# SafeRx — Datasets

Two complementary, open, academic-use datasets, matching the two things your architecture needs:
the **ML classifier** (structured drug pairs + severity/interaction type) and the **RAG knowledge
base** (real mechanism/effect/advice sentences to ground explanations in).

## 1. `drugbank_ddi/` — structured DDI pairs (for the ML classifier)

- **Files:** `ddis.csv` (191,808 labeled drug pairs, 86 interaction types), `drug_smiles.csv`
  (1,706 drugs with SMILES chemical structure strings).
- **Source:** derived from DrugBank, redistributed via the `jcsun-00/DrugBank` GitHub repo
  (used in the HDN-DDI / DSN-DDI papers): https://github.com/jcsun-00/DrugBank
- **Format of `ddis.csv`:** `d1,d2,type,Neg samples` — `d1`/`d2` are DrugBank IDs, `type` is an
  integer 0–85 identifying the interaction category (not a severity level — see note below),
  `Neg samples` lists sampled non-interacting drugs for negative-example generation.
- **Important note on severity:** this dataset's 86 "types" are DDI *categories* (e.g., "increases
  anticoagulant activity," "decreases metabolism") from the original DeepDDI paper (Ryu et al.,
  2018, PNAS), not a minor/moderate/major severity scale. Your plan calls for severity
  classification, so you'll need to either (a) map these 86 types to a severity scale yourself —
  a reasonable rule of thumb used in prior work is bleeding/cardiac/CNS-depression-related types →
  major, metabolism/absorption-changes → moderate, minor pharmacokinetic shifts → minor — or
  (b) treat "interaction type" as the prediction target instead of severity, and derive a
  recommendation per type. Flag this decision as one of your advisor questions.
- **License:** DrugBank data is restricted to academic/research use; this repo is a
  commonly-cited academic redistribution, consistent with your plan's "no proprietary clinical
  data" and "academic/research-use licenses" scope.

## 2. `ddi_corpus_text/` — mechanism/effect/advice sentences (for the RAG knowledge base)

- **File:** `ddi_corpus_flat.csv` — 34,449 sentence-level rows parsed from the raw XML
  (`DDICorpus/` folder, kept for reference), of which 5,000 are labeled drug-pair interactions.
- **Source:** the SemEval-2013 Task 9 DDI Corpus (Segura-Bedmar et al.), from
  https://github.com/isegura/DDICorpus — 1,025 documents from DrugBank drug labels and MedLine
  abstracts, manually annotated by domain experts.
- **Columns:** `drug1, drug2, ddi (true/false), interaction_type, sentence, source_file, split, source_type`
- **`interaction_type` values** (only set when `ddi=true`):
  - `mechanism` — pharmacokinetic mechanism (e.g. absorption, metabolism changes) — 1,621 rows
  - `effect` — pharmacodynamic/clinical effect of concurrent use — 2,047 rows
  - `advise` — a recommendation or warning about the combination — 1,047 rows
  - `int` — interaction stated without further detail — 284 rows
- **This is your evidence-grounding source**: each row is a real sentence, from a real drug
  label or paper abstract, describing *why* two drugs interact — exactly what your retrieval
  module should index and what your explanation generator should be forced to cite from.
- **License:** Creative Commons Attribution Non-Commercial 4.0 International — consistent with
  your academic/research-use scope.

## Suggested next step
Build your embedding index over `ddi_corpus_flat.csv` (one row = one retrievable document,
filtered to `ddi=true`), keyed by the `(drug1, drug2)` pair. When `drugbank_ddi/ddis.csv` gives
you a predicted interaction type/severity for a queried pair, retrieve the matching sentence(s)
from `ddi_corpus_flat.csv` for that pair (or the closest drug-class match) to ground the LLM
explanation.

## Attribution
- DrugBank: Wishart et al., "DrugBank 5.0," *Nucleic Acids Research*, 2018.
- DDI Corpus: Herrero-Zazo et al., "The DDI corpus: An annotated corpus with pharmacological
  substances and drug-drug interactions," *Journal of Biomedical Informatics*, 46(5), 2013.
