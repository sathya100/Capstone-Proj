# RxGuard — Validation Audit (Week 9 → Week 10)

EGN 6933 / CAI 6826 · Sathya · Updated 28 Oct 2026

**What is audited:** the **ML severity predictor** (FR-05), the one part of RxGuard learned from
data. It gives a base severity (Major / Moderate / Minor) for a drug pair that is missing from
DDInter; the rules engine then adjusts it for the patient. The rules engine and the RAG explainer
come in where they affect trust (Q5) and deployment (Q6). § numbers refer to Handout 1.

**Results row:** `Macro F1 = 0.65 [0.62, 0.68] · Δ vs. baseline = +0.22 [+0.19, +0.26] · 1 run`
(Random Forest vs. logistic regression, held-out-drug test set, 5,524 pairs, 52 unseen drugs.
How the interval was computed, and why it is probably too narrow, is in Q4.)

---

## Q1 · Claim (§1)

**Claim:** for a pair of drugs not in DDInter, RxGuard predicts the interaction severity well
enough to use as the base of the patient risk score, and rarely shows a Major interaction as
something milder.

| | |
|---|---|
| Data | DDInter pairs with a known level ("Unknown" rows dropped), restricted to 261 drugs (the 300 with the most DDInter interactions plus the demo drugs, keeping those with a PubChem structure): **16,073 pairs**. Features: Morgan fingerprints of both drugs (RDKit), combined symmetrically. |
| Metric | **Macro F1** over the three levels; **Major recall** and **Major safe recall** (share of true Majors shown as Major or as "Unknown — consult a pharmacist", never as Moderate/Minor) for safety, NFR-02. |
| Number that first supported the claim | Random Forest macro F1 **0.685** on unseen drugs vs. **0.272** for a majority-class baseline (README, 21 Oct). |
| Targets (requirements doc) | Macro F1 ≥ 0.70; Major recall ≥ 0.90. |

That first number is the model *without* the Major guard, against the *weakest* baseline. The
deployed model uses the guard, and the fair comparison is logistic regression on the same features.
On that basis the numbers are lower (Q4), and **neither target is met** (`meets_targets` is false
for all three in `docs/results/severity_metrics_rf.json`).

## Q2 · Split (§2)

**How:** drug-level split in `backend/rxguard/ml/train.py::drug_split` (seed 42).

- 20% of the 261 drugs (52) are held out as **test drugs**; every pair touching one goes to test.
- 10% of drugs (26) are held out as **validation drugs**, taken from the non-test drugs. The Major
  guard is tuned here, so test is used only for the final numbers.
- Train = pairs where both drugs are training drugs.
- Result: **8,286 train · 2,263 validation · 5,524 test pairs** (34% of pairs in test, because each
  held-out drug takes all its pairs with it).

**Does it support the claim?** Mostly yes. The predictor is only used for pairs missing from
DDInter, which usually involve a drug it hasn't seen. A random split by *pair* would let it learn
"warfarin pairs are often Major" from training and reuse that at test time; holding out whole drugs
tests the real situation. Two limits:

1. **Test drugs aren't like the drugs that will actually need predictions.** All 261 drugs were
   chosen because they have the *most* DDInter interactions. Pairs missing from DDInter tend to
   involve new or rarely studied drugs, which these are not. The test set is "unseen but common"
   drugs; real use is "unseen and uncommon". Performance in use is likely lower.
2. Most test pairs have one unseen drug and one training drug; pairs with *both* drugs unseen are
   harder and are not reported separately.

## Q3 · Leakage (§3)

| Pattern | Risk here | Check | Result |
|---|---|---|---|
| **Duplicate rows across the split** (same pair stored as A–B and B–A, or in two DDInter ATC files) | Real: DDInter ships one CSV per ATC group, so the same pair appears more than once | Loader keys pairs by sorted lowercase names and keeps the most severe level; test feeds reversed, re-cased and cross-file duplicates through the real loader | ✅ Pass |
| **Group / entity leakage** (same drug in train and test) — the main risk | Real: per-drug severity patterns are easy to memorise | Drug-level split; tests assert train, validation and test share **no drug IDs**, no pair is in two sets, and every test pair has an unseen drug | ✅ Pass |
| **Name-variant leakage** (warfarin vs. warfarin sodium counted as two drugs) | Possible: pairs are keyed by name, not by RxNorm ingredient ID | Not yet checked on the real data | ⚠️ Open |
| **Tuning on test** (threshold, model choice) | The Major guard is a tuned threshold | Guard tuned on validation drugs only (`train_and_evaluate`) | ✅ By design |
| **Preprocessing fit on all data** | Low: fingerprints are computed per molecule and carry no label information | — | ✅ None found |
| **Selection on the full dataset** | The 261-drug set was chosen by interaction count across *all* pairs, including test pairs | Uses counts, not severity labels, so it's not label leakage, but it shapes the test set (Q2, limit 1) | ⚠️ Noted |
| **Model selection on test** | RF was picked as best of four models by *test* macro F1 (`model_comparison.json`) | Should be picked on validation | ⚠️ Mild optimism |

**Leakage tests: `backend/tests/test_leakage.py`** (7 tests). They run the real loader
(`rxguard/interactions/store.py`) and the real split (`rxguard/ml/train.py::drug_split`, same seed as
training) on a synthetic DDInter-shaped table in CI, and on the real store automatically when
`backend/data/interactions.sqlite` is loaded. All pass.

## Q4 · Metric and uncertainty (§4–6, §8)

**Is the metric right for the decision?** Partly. Macro F1 weighs the rare Minor class equally,
which suits a three-level label with 2% Minor pairs. But the decision that matters clinically is
"is this a Major?", and the worst error is showing a Major as milder. So the deciding metric is
**Major safe recall**, with macro F1 secondary. Accuracy would be misleading (69% of test pairs are
Moderate; a majority-class model scores 0.69 accuracy but 0.27 macro F1).

**Results** (deployed setting: Major guard on; "Unknown" counts as wrong for F1; test set = 5,524
pairs, 52 unseen drugs; computed with `backend/scripts/audit_intervals.py`):

| | Random Forest | Logistic regression (baseline) | Majority class |
|---|---|---|---|
| Macro F1 | **0.65** [0.62, 0.68] | 0.43 [0.41, 0.45] | 0.27 |
| Major recall | 0.56 [0.54, 0.58] | 0.60 [0.57, 0.62] | 0 |
| Major safe recall | 0.87 | 0.88 | — |
| Coverage (confident predictions) | 62% | 63% | — |

**Paired comparison:** Δ macro F1 (RF − logistic regression) = **+0.22 [+0.19, +0.26]**.

**Decision rule.** The interval of Δ excludes 0 and the gain is far above the smallest gain that
would matter (+0.05 macro F1, below which a transparent linear model would be preferable), so the
claim "RF beats logistic regression on macro F1" holds. But **RF does not beat it where safety is
concerned**: its Major recall is slightly *lower* (0.56 vs 0.60), and both miss the 0.90 target.

**How the intervals were made, and their limits.** The training run saved only confusion matrices,
not per-pair predictions, and the data (DDInter, PubChem) isn't in the repo, so the run couldn't be
repeated for this audit. The intervals are a 2,000-resample percentile bootstrap over **test pairs**
drawn from the saved confusion matrices (`confusion_bootstrap` in
`backend/rxguard/evaluation/metrics.py`). Three consequences:

- **Too narrow, most likely.** Pairs sharing a test drug aren't independent, and there are only 52
  test drugs. The handout's rule for several rows per group is to resample the groups. With 52
  clusters the true interval will be noticeably wider.
- **Unpaired.** Model and baseline were resampled separately, which usually makes the Δ interval
  *wider* than a paired one.
- **One run.** No seed-to-seed variation is included.

The proper version — **5 seeds, per-pair predictions saved, resampling held-out drugs, model and
baseline scored on the same resample** — is already written and tested
(`paired_cluster_bootstrap` in the same file). It replaces these numbers in the fix in Q7. A
difference this large (+0.22) is very likely to stay clear of 0; the Major-recall comparison is the
one that could change.

## Q5 · Trust (§7, §9)

**Calibration: not checked.** RxGuard trusts a prediction only when its confidence is ≥ 0.6, and
otherwise shows "Unknown — consult a pharmacist" (NFR-03). The Major guard is also a probability
threshold (P(Major) ≥ 0.30 for RF). Both assume the probabilities mean what they say, but Random
Forest probabilities are typically poorly calibrated (pushed away from 0 and 1). There is also
evidence of drift from validation to test: the guard was tuned to give 0.90 Major safe recall on
validation and gave **0.87** on test. Plan: reliability diagram and expected calibration error on
validation, isotonic calibration fitted on validation if needed, then ECE reported on test.

**Graders.**

- *Labels for the ML model* come from DDInter, a curated database, not a grader we built. It is not
  validated by us; levels can disagree with other sources, so some "errors" are label noise.
- *End-to-end scenarios:* I set the expected risk band for each of the 50 scenarios myself, the same
  person who wrote the rules. **Not validated.** Plan: a second rater (pharmacy student or
  classmate) labels them independently from the FDA labels; report agreement (Cohen's κ).
- *Explanations:* faithfulness is scored with RAGAS, which uses an **LLM judge**. **Not validated.**
  Plan: hand-label 30 explanation sentences as supported / not supported by the cited passage and
  report the judge's agreement with them before trusting its scores.

## Q6 · After launch (§10)

**What to monitor**

- Share of checks that use the predictor, and the share shown as "Unknown" (now 38% of test pairs).
  A rise means the drugs being checked are drifting away from the training set.
- Confidence and P(Major) distributions over time, compared with validation.
- New DDInter releases: pairs RxGuard predicted that now have a real DDInter level are a free,
  ongoing test set — track Major safe recall on them.
- Pharmacist overrides and "this looks wrong" reports, split by DDInter vs. predicted severity.
- How often patient fields are missing (`missing_fields`), since missing labs silently switch rules off.

**What could fail**

- A true Major shown as milder: **13% of test Majors** are shown as Moderate or Minor today. That pair then gets 4 base points
  instead of 6, which can drop a High patient into Moderate.
- Distribution shift: the model was tested on common drugs; real missing pairs involve rare ones (Q2).
- Too many "Unknown" results make the tool unhelpful, and alert fatigue sets in.
- Name normalisation maps a brand to the wrong ingredient, so the real DDInter pair is never found.
- `drug_flags.yaml` entries are unverified (`verified: false`), which shifts every score for that drug.

**Who is harmed:** patients most at risk from interactions — older adults, people with liver or
kidney disease, people taking many medicines — if a dangerous pair is scored low. Clinicians and
caregivers are harmed too if a precise-looking 0–10 score earns more trust than it deserves.

## Q7 · Verdict (§11)

**The checklist item that matters most here is the safety metric with its uncertainty (§4–6).** The
model clearly beats the baselines on macro F1, but on the error that hurts patients — a Major shown
as milder — it misses the target (Major safe recall 0.87 vs. 0.90), it is no better than logistic
regression, and the interval around that number is unknown because the evaluation is a single run
with no per-pair predictions saved.

**The one fix, by Wed 4 Nov 2026:** re-run the evaluation over **5 seeds**, save per-pair test
predictions, and report macro F1 and Major safe recall with **drug-clustered, paired 95% intervals**
(`paired_cluster_bootstrap`), with the model chosen on validation rather than test. If the lower
bound of Major safe recall is below 0.90, raise the guard target on validation until it isn't, and
report the coverage that costs. That updated row replaces the one at the top of this audit.
