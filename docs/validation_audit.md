# RxGuard — Validation Audit (Week 9 → Week 10)

**Status on 28 Oct 2026:** the rules engine (step 4) is built and unit-tested, but the ML severity
predictor (step 2 fallback, FR-05) has not been trained and DDInter is not yet loaded. There are
**no test predictions yet**, so Q4 gives the exact computation plan, and the README carries that
plan in place of a results row. The split, leakage tests and interval code are already in the repo
so the numbers can be produced as soon as the model exists.

Scope of this audit: the **ML severity predictor**, because it is the only part of RxGuard that is
learned from data and therefore the only part with a train/test split to audit. The rules engine
and the planned RAG explainer are covered where they affect trust (Q5) and deployment (Q6).

---

## Q1 · Claim

**Claim:** for a drug pair that is *missing* from DDInter, RxGuard's ML predictor assigns the
interaction severity (Minor / Moderate / Major) well enough to be used as the base severity in the
patient risk score — specifically, it misses few Major interactions.

| | |
|---|---|
| Data | DDInter interaction pairs with a known level (Major / Moderate / Minor; "Unknown" rows dropped), keyed by ingredient. Features: PubChem molecular fingerprints of each drug. |
| Metric | **Macro F1** over the three levels (headline), and **recall on Major** (safety, NFR-02). |
| Number | Target from the requirements doc: macro F1 ≥ 0.70 and Major recall ≥ 0.90 on held-out drugs, clearly above a majority-class and a logistic-regression baseline. **No measured number exists yet.** |

What we are *not* claiming: anything about real patients (Synthea only, NFR-06), or that the 0–10
risk score is clinically calibrated. The rule weights in `config/rules.yaml` are a design choice.

## Q2 · Split

**How:** drug-disjoint ("cold-drug") split, in `backend/rxguard/evaluation/split.py`.

1. Canonicalise every pair (A–B = B–A, lowercase, salt words such as "sodium" stripped) and
   de-duplicate across DDInter's per-ATC files, keeping the most severe level.
2. Hold out ~10% of **drugs**. Every pair touching a held-out drug goes to **test** (~20% of
   pairs, matching the plan).
3. From the remaining drugs, hold out another ~10% the same way as **validation**, used for
   threshold tuning, calibration and model selection. Test is scored once, at the end.
4. Fixed seed, so the split is reproducible; the same split is used for the model and both
   baselines.

**Why it supports the claim:** at run time the predictor is only called for pairs DDInter doesn't
have, which usually involve a drug that is new or rarely studied. A random split *by pair* would
let the model see warfarin + 200 other drugs in training and then be tested on warfarin + one more,
so it could score well by memorising "warfarin pairs are usually Major". Holding out whole drugs
tests the situation the claim is about: severity for a drug the model has not seen.

**Limitation:** a pair where *one* drug is unseen is easier than one where *both* are. We will
report the two subsets separately in Q4 so the headline doesn't hide the harder case.

## Q3 · Leakage

| # | Possible leakage path | Check / fix | Where |
|---|---|---|---|
| 1 | Same pair stored as A–B and B–A, or in two DDInter files, ending up in train and test | Canonical key + de-dupe before splitting; test asserts no pair in two sets in either order | `test_no_pair_in_two_sets_in_either_order`, `test_dedupe_merges_order_case_and_salt_keeping_most_severe` |
| 2 | Drug identity: model memorises per-drug severity (the main risk) | Split by drug; tests assert train/val/test share **no drug IDs** and every test pair has an unseen drug | `test_no_drug_shared_between_train_and_test`, `test_no_drug_shared_between_train_and_val`, `test_every_test_pair_has_an_unseen_drug` |
| 3 | Name variants of one drug (warfarin vs warfarin sodium) treated as different drugs, so the "unseen" drug is actually seen | Salt-word stripping now; **real fix is keying by RxNorm ingredient ID** (open gap, Q7) | `canonical_drug()` in `split.py` |
| 4 | Feature scaling / selection fit on all data | Fit any scaler or feature selector on train only (fingerprints are per-drug bits with no label information) | Training script (to write) |
| 5 | Decision threshold for Major recall, calibration, or hyper-parameters tuned on test | All tuning on the validation drugs; test touched once | Split design, Q2 step 3 |
| 6 | Rule weights tuned on the same 50 end-to-end scenarios they are evaluated on | Split scenarios 25 tune / 25 held out before tuning | Planned, Q7 |

**The leakage tests are in `backend/tests/test_leakage.py`.** They run in CI on a synthetic
DDInter-shaped table (seeded with reversed, case-changed, salt-variant and repeated pairs) and run
automatically on the real DDInter CSVs once they are in `backend/data/raw/ddinter/` (skipped until
then). Current result: all pass.

## Q4 · Metric and uncertainty

**Not computed yet.** Plan:

| | |
|---|---|
| Metric | Macro F1 (headline) and Major recall, on the **test** drugs of the split above |
| Baselines | (a) majority class, (b) logistic regression on the same fingerprint features. The paired comparison is against **logistic regression**, the stronger one |
| Runs | 5 training seeds on the one fixed split; each metric averaged over the 5 runs |
| 95% interval | Percentile bootstrap, 2,000 resamples, **resampling held-out drugs, not pairs**, since pairs that share a drug are not independent (the "several rows per group" case in Handout 2). Code: `paired_cluster_bootstrap()` in `backend/rxguard/evaluation/metrics.py` |
| Paired comparison | On each resample, score the model and the baseline on the *same* rows and take the difference; interval of Δ from those differences |
| Also reported | One-unseen vs both-unseen subsets; Major recall with its own interval |
| Data | DDInter, downloaded under its academic licence, loaded with `scripts/load_ddinter.py` |
| Date | **Wed 11 Nov 2026** (week 11, the evaluation week in the project plan) |

**Decision rule.** We will claim the model beats logistic regression only if the 95% interval of
Δ macro F1 excludes 0. The smallest gain worth claiming is **+0.05 macro F1**: below that, a
pharmacist-facing tool gains little from a black-box model over a transparent linear one.
Separately, Major recall below 0.90 fails NFR-02 regardless of F1 — the model would then not be
used, and missing pairs would show "Unknown — consult a pharmacist".

## Q5 · Trust

**Calibration.** The pipeline trusts a prediction only when its confidence is ≥ 0.6 (NFR-03);
below that the pair is "Unknown", never Low. That floor only means something if the confidences
are calibrated, which raw classifier scores usually aren't. Plan: reliability diagram and expected
calibration error on the **validation** drugs; if poorly calibrated, fit isotonic or Platt scaling
on validation, then report ECE on test. Also report what share of test pairs falls below 0.6 —
if most do, the model rarely helps in practice.

**Graders.**

- *Ground truth for the ML model* is DDInter itself — a curated database, not a grader we built.
  It has known gaps (many pairs are "Unknown", levels can differ from other sources), so test
  labels are not perfect. Not validated by us; stated as a limitation.
- *End-to-end scenarios:* the expected risk band for each of the 50 scenarios is set by me, the
  same person who wrote the rules. **Not validated.** Plan: a second rater (a pharmacy student or
  classmate) labels the bands independently from the FDA labels; report agreement (Cohen's κ)
  and settle disagreements before scoring.
- *Explanations (planned RAG step):* RAGAS faithfulness uses an **LLM judge**. **Not validated.**
  Plan: hand-label 30 explanation sentences as supported / unsupported by the cited passage and
  report the judge's agreement with those labels before trusting its scores.

## Q6 · After launch

**What to monitor**

- Share of checks that fall back to the predictor, and share returned as "Unknown" (a jump means
  the drug mix has moved away from DDInter's coverage).
- Confidence distribution of predictions over time, against the validation distribution.
- Pharmacist overrides or "this looks wrong" feedback, especially on predicted (not DDInter) pairs.
- New DDInter releases: re-score previously *predicted* pairs that now have a DDInter level — a free
  live test set for the model.
- Missing patient fields (`missing_fields` in the report) — the score silently drops rules when
  labs are absent.

**What could fail**

- Distribution shift: pairs missing from DDInter differ systematically from those in it (newer
  drugs, biologics, poorly characterised chemistry), so test performance may overstate real use.
- A predicted Moderate for a true Major — the worst error (NFR-02) — gets shown as a confident score.
- Name normalisation errors map a brand to the wrong ingredient, so the right pair is never looked up.
- Seed `drug_flags.yaml` is unverified (all 9 entries `verified: false`); wrong flags shift scores
  for every patient on that drug.
- Synthetic Synthea patients don't reflect real lab distributions; rule thresholds untested on real data.

**Who would be harmed**

Patients — especially older patients, people with liver or kidney disease, and people on many
medicines — if a dangerous combination is scored low. A secondary harm is alert fatigue: if too
many pairs come back High or Unknown, clinicians stop reading the score. Clinicians and caregivers
who over-trust a precise-looking number are also exposed; the report is decision support only.

## Q7 · Verdict

**Biggest gap:** the headline component has never been measured. There is no trained predictor,
no DDInter data loaded and therefore no test predictions — the claim in Q1 currently rests on
targets, not results. (Next gaps: drug identity is keyed by name rather than RxNorm ID, which
weakens leakage check #3; and no grader has been validated.)

**First fix:** load DDInter, run the drug-disjoint split with the leakage tests passing on the real
data, and produce the majority-class and logistic-regression baseline rows with their intervals —
**by Wed 4 Nov 2026**. The trained model, 5 runs and the full results row (Q4) follow by
**Wed 11 Nov 2026**.
