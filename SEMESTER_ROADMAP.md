# SafeRx — Semester Roadmap & Advisor Alignment

_Last updated: Sep 16, 2026_

## Advisor Outreach Status
- **Advisor:** TBD — matching in progress as of the Sep 16 Advisor Touchpoint.
- **Action:** confirm assigned advisor at/after today's touchpoint; share repo access immediately once assigned.
- **Open questions to raise with advisor:**
  1. Verification layer: threshold-based semantic-similarity check vs. a trained NLI model for flagging unsupported claims?
  2. Is DrugBank DDI viable given its licensing restrictions, or should TWOSIDES/DDI Corpus be primary rather than backup?
  3. Preference on domain-specific pharmacological embeddings vs. general-purpose sentence embeddings for the retrieval index?

## Remaining Course Deliverables

| Week / Date | Milestone | Planned Work | Status |
|---|---|---|---|
| Wk 4 (Sep 16) | Advisor Touchpoint #1 / Code Audit #1 | Review requirements & SDP with advisor; finalize dataset access; begin data cleaning | 🔲 In progress |
| Wk 5–6 (Sep 23–30) | — | Feature engineering; train and validate baseline ML classifier | 🔲 Not started |
| Wk 7 (Oct 7) | Mid-Term Oral Review | Present baseline prediction results and initial architecture | 🔲 Not started |
| Wk 8 (Oct 14) | Code Audit #2 | Build curated knowledge base; implement retrieval (embedding index) module | 🔲 Not started |
| Wk 9–10 (Oct 21–28) | Code Audit #3 (Wk 10) | Integrate RAG explanation generation; connect full pipeline | 🔲 Not started |
| Wk 11 (Nov 4) | Progress Checkpoint #3 | Demonstrate integrated prediction + RAG pipeline end-to-end | 🔲 Not started |
| Wk 12–13 (Nov 11–18) | — | Implement hallucination-detection/verification layer; build web front-end | 🔲 Not started |
| Wk 14 (Nov 25) | — | End-to-end integration testing; run evaluation against baselines | 🔲 Not started |
| Wk 15 (Dec 2) | Public Demo Day & Panel Q&A | Demonstrate final working prototype; answer panel questions | 🔲 Not started |
| Wk 16 (Dec 9) | Final Report due | Submit final written report | 🔲 Not started |

## Immediate Next Steps (this week)
- [ ] Push initial repo structure, `requirements.txt`/`environment.yml`, and this roadmap (this commit)
- [ ] Confirm dataset access (DrugBank DDI licensing check; TWOSIDES as fallback)
- [ ] Get advisor assigned and share repo
- [ ] Begin data cleaning per Wk 4–6 plan
