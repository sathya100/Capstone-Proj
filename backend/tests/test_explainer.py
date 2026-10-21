"""RAG explainer (FR-11, FR-12, FR-13, NFR-04, NFR-06): parsing, retrieval, citation check, fallbacks.

The label text here is written for the tests (set_id "TEST"), not copied from real FDA labels.
"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from rxguard.explain.explainer import RagExplainer, extractive, parse_json, validate
from rxguard.explain.labels import Passage, best_label, chunk, passages_from_label, read_passages, write_passages
from rxguard.explain.llm import LLMError
from rxguard.explain.retriever import TfidfRetriever

LABEL_A = {  # prescription-style label for "warfarin"
    "set_id": "TEST-A", "effective_time": "20250101",
    "openfda": {"generic_name": ["WARFARIN SODIUM"]},
    "drug_interactions": ["7 DRUG INTERACTIONS Drugs may change the anticoagulant effect. "
                          "Regular use of acetaminophen can increase the INR and the risk of bleeding. "
                          "Monitor the INR more often when acetaminophen is started or stopped."],
    "warnings_and_cautions": ["5 WARNINGS AND PRECAUTIONS Serious bleeding can occur. "
                              "Tissue necrosis has been reported in rare cases."],
    "boxed_warning": ["WARNING: BLEEDING RISK Major or fatal bleeding may occur."],
}
LABEL_B = {  # OTC-style label for "acetaminophen"
    "set_id": "TEST-B", "effective_time": "20250101",
    "openfda": {"generic_name": ["ACETAMINOPHEN"]},
    "warnings": ["Liver warning: severe liver damage may occur if you take more than the maximum daily amount "
                 "or have 3 or more alcoholic drinks every day while using this product."],
    "ask_doctor_or_pharmacist": ["Ask a doctor or pharmacist before use if you are taking the blood thinning "
                                 "drug warfarin."],
}
LABEL_C = {"set_id": "TEST-C", "openfda": {"generic_name": ["METFORMIN"]},
           "warnings": ["Lactic acidosis is rare but serious. Assess kidney function before starting."]}


@pytest.fixture
def passages():
    return (passages_from_label(LABEL_A, "warfarin") + passages_from_label(LABEL_B, "acetaminophen")
            + passages_from_label(LABEL_C, "metformin"))


@pytest.fixture
def retriever(passages):
    return TfidfRetriever(passages)


class FakeLLM:
    name, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, system, user):
        self.prompts.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


# --- labels ------------------------------------------------------------------------------------

def test_passages_are_tagged_with_drug_and_section(passages):
    w = [p for p in passages if p.drug == "warfarin"]
    assert {p.section for p in w} == {"drug_interactions", "warnings_and_cautions", "boxed_warning"}
    ix = next(p for p in w if p.section == "drug_interactions")
    assert ix.citation == "FDA label: warfarin, Drug Interactions"
    assert not ix.text.startswith("7 DRUG")        # section heading stripped
    assert ix.id == "warfarin:drug_interactions:0"


def test_chunk_respects_word_limit_with_overlap():
    text = " ".join(f"Sentence number {i} is here." for i in range(40))
    parts = chunk(text, max_words=30)
    assert len(parts) > 1 and all(len(p.split()) <= 35 for p in parts)
    assert parts[0].split(". ")[-1] in parts[1]     # one sentence of overlap


def test_best_label_prefers_single_ingredient_with_interactions():
    combo = {"openfda": {"generic_name": ["ACETAMINOPHEN AND CODEINE"]}, "drug_interactions": ["x"]}
    assert best_label([combo, LABEL_B], "acetaminophen") is LABEL_B


def test_passages_round_trip(tmp_path, passages):
    write_passages(passages, tmp_path / "p.jsonl")
    assert read_passages(tmp_path / "p.jsonl") == passages
    assert read_passages(tmp_path / "missing.jsonl") == []


# --- retrieval (FR-11) -------------------------------------------------------------------------

def test_retrieves_from_both_labels_and_ranks_mentions_first(retriever):
    got = retriever.retrieve("acetaminophen", "warfarin", k=4, min_per_drug=1)
    assert {p.drug for p in got} == {"warfarin", "acetaminophen"}
    assert "acetaminophen" in got[0].text.lower() or "warfarin" in got[0].text.lower()
    assert all(p.drug != "metformin" for p in got)


def test_unknown_drug_returns_only_known_side(retriever):
    got = retriever.retrieve("warfarin", "zzzumab", k=3)
    assert got and all(p.drug == "warfarin" for p in got)


# --- citation check (FR-13) --------------------------------------------------------------------

def test_validate_drops_uncited_and_unretrieved_citations():
    refs = {"P1": object(), "P2": object()}
    raw = {"mechanism": [{"text": "Supported claim.", "cites": ["P1"]},
                         {"text": "Invented claim.", "cites": ["P9"]},
                         {"text": "Claim with no source.", "cites": []},
                         "Inline cited claim [P2]",
                         {"text": "Mixed claim.", "cites": ["P1", "P7"]}],
           "monitoring": [{"text": "Check INR.", "cites": "2"}]}
    kept, dropped = validate(raw, refs)
    assert [k["text"] for k in kept["mechanism"]] == ["Supported claim.", "Inline cited claim"]
    assert kept["monitoring"] == [{"text": "Check INR.", "cites": ["P2"]}]
    assert sorted(d["text"] for d in dropped) == ["Claim with no source.", "Invented claim.", "Mixed claim."]


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"mechanism": []}\n```') == {"mechanism": []}
    with pytest.raises(ValueError):
        parse_json("sorry, I can't")


# --- explainer end to end ----------------------------------------------------------------------

def test_llm_output_is_filtered_and_every_sentence_cited(retriever):
    llm = FakeLLM({
        "mechanism": [{"text": "Acetaminophen can raise the INR, increasing bleeding risk.", "cites": ["P1"]},
                      {"text": "It also causes hair loss.", "cites": ["P42"]}],
        "monitoring": [{"text": "Check the INR more often.", "cites": ["P1"]}],
        "affected_systems": [{"text": "Blood clotting", "cites": ["P1"]}, {"text": "liver", "cites": []}],
    })
    out = RagExplainer(retriever, llm).explain("acetaminophen", "warfarin", "Moderate")
    ex = out["explanation"]
    assert ex["status"] == "ok" and ex["provider"] == "fake"
    assert out["mechanism"] == "Acetaminophen can raise the INR, increasing bleeding risk."
    assert out["monitoring"] == ["Check the INR more often."]
    assert out["affected_systems"] == ["blood clotting"]
    assert len(ex["dropped"]) == 2
    assert all(s["sources"] for s in ex["sentences"])                       # NFR-04
    assert out["citations"] == [ex["sources"][0]["citation"]]
    assert ex["sources"][0]["n"] == 1 and ex["sources"][0]["text"]


def test_prompt_contains_no_patient_data(retriever):
    llm = FakeLLM({"mechanism": [], "monitoring": []})
    RagExplainer(retriever, llm).explain("acetaminophen", "warfarin", "Moderate")
    system, user = llm.prompts[0]
    assert "acetaminophen" in user and "[P1]" in user
    for leak in ("P-1042", "Age ", "eGFR", "ALT ", "drinks/day", "patient", "liver disease"):
        assert leak not in user                                            # NFR-06


def test_extractive_mode_quotes_label_sentences_with_citations(retriever):
    out = RagExplainer(retriever, None).explain("acetaminophen", "warfarin")
    ex = out["explanation"]
    assert ex["status"] == "ok" and ex["provider"] == "extractive"
    assert "acetaminophen" in out["mechanism"].lower() and "inr" in out["mechanism"].lower()
    assert "blood clotting" in out["affected_systems"]
    assert all(s["sources"] for s in ex["sentences"])
    for s in ex["sentences"]:          # every quoted sentence appears in a cited passage
        if s["part"] != "affected_systems":
            assert any(s["text"] in src["text"] for src in ex["sources"])


def test_llm_failure_falls_back_to_extractive(retriever):
    out = RagExplainer(retriever, FakeLLM(LLMError("timeout"))).explain("acetaminophen", "warfarin")
    assert out["explanation"]["provider"] == "extractive"
    assert "timeout" in out["explanation"]["fallback"]
    assert out["mechanism"]


def test_unrelated_pair_says_nothing_unsupported(retriever):
    out = RagExplainer(retriever, None).explain("metformin", "acetaminophen")
    assert out["explanation"]["status"] == "no_supported_sentences"
    assert out["mechanism"] is None and out["citations"] == []


def test_no_passages_tells_user_to_fetch_labels():
    out = RagExplainer(TfidfRetriever([]), None).explain("acetaminophen", "warfarin")
    assert out["explanation"]["status"] == "no_passages"
    assert "fetch_labels.py" in out["explanation"]["message"]


def test_llm_answers_are_cached(retriever, tmp_path):
    llm = FakeLLM({"mechanism": [{"text": "Raises INR.", "cites": ["P1"]}]})
    ex = RagExplainer(retriever, llm, cache_path=tmp_path / "c.json")
    ex.explain("acetaminophen", "warfarin")
    second = ex.explain("warfarin", "acetaminophen")
    assert len(llm.prompts) == 1 and second["explanation"]["cached"]
    again = RagExplainer(retriever, llm, cache_path=tmp_path / "c.json").explain("acetaminophen", "warfarin")
    assert again["explanation"]["cached"] and len(llm.prompts) == 1


# --- pipeline and API --------------------------------------------------------------------------

@pytest.fixture
def pipeline(tmp_path, retriever):
    from scripts.make_dev_data import main as make_dev_data
    from rxguard.interactions.store import InteractionStore
    from rxguard.normalise.rxnorm import RxNormNormaliser
    from rxguard.patients.fhir import FilePatientSource
    from rxguard.pipeline import Pipeline
    from rxguard.rules.engine import RulesEngine

    make_dev_data(tmp_path)
    return Pipeline(RxNormNormaliser(offline=True), InteractionStore(tmp_path / "interactions.sqlite"),
                    FilePatientSource(tmp_path / "patients", today=date(2026, 9, 30)), RulesEngine.from_config(),
                    explainer=RagExplainer(retriever, None))


def test_check_includes_cited_explanation(pipeline):
    out = pipeline.check("Tylenol", "Warfarin", "P-1042")
    assert out["risk_score"] == 9                        # explanation never changes the score
    assert out["mechanism"] and out["citations"]
    assert out["explanation"]["status"] == "ok"


def test_check_without_explanation_then_explain_endpoint(pipeline):
    from rxguard.api import main as api
    api.app.dependency_overrides[api.get_pipeline] = lambda: pipeline
    try:
        c = TestClient(api.app)
        fast = c.post("/check", json={"drug_a": "Tylenol", "drug_b": "Warfarin", "patient_id": "P-1042",
                                      "explain": False}).json()
        assert fast["mechanism"] is None and fast["explanation"]["status"] == "pending"
        ex = c.post("/explain", json={"drug_a": fast["drugs"][0], "drug_b": fast["drugs"][1]}).json()
        assert ex["mechanism"] and ex["disclaimer"]
        h = c.get("/health").json()
        assert h["explainer"]["provider"] == "extractive" and h["explainer"]["labelled_drugs"] == 3
    finally:
        api.app.dependency_overrides.clear()


def test_explainer_crash_does_not_block_score(pipeline):
    class Broken:
        def explain(self, *a):
            raise RuntimeError("boom")
    pipeline.explainer = Broken()
    out = pipeline.check("Tylenol", "Warfarin", "P-1042")
    assert out["risk_score"] == 9 and "explainer error" in out["explanation"]["status"]


# --- LLM providers (HTTP mocked; no network) ----------------------------------------------------

@pytest.mark.parametrize("provider,env,reply", [
    ("gemini", "GEMINI_API_KEY", {"candidates": [{"content": {"parts": [{"text": '{"mechanism": []}'}]}}]}),
    ("groq", "GROQ_API_KEY", {"choices": [{"message": {"content": '{"mechanism": []}'}}]}),
    ("ollama", None, {"message": {"content": '{"mechanism": []}'}}),
])
def test_providers_send_json_requests_and_parse_replies(monkeypatch, provider, env, reply):
    import httpx
    from rxguard.explain import llm as llm_mod

    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers or {})
        return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm_mod.httpx, "post", fake_post)
    if env:
        monkeypatch.setenv(env, "test-key")
    m = llm_mod.make_llm(provider, {})
    assert m.complete("system", "user") == '{"mechanism": []}'
    assert "system" in str(sent["body"]) and "user" in str(sent["body"])
    if env:
        assert "test-key" in str(sent["headers"])


def test_auto_provider_without_keys_is_extractive(monkeypatch):
    from rxguard.explain.llm import make_llm
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert make_llm("auto", {}) is None
    with pytest.raises(LLMError):
        make_llm("gemini", {})
