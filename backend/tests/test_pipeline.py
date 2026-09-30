"""End-to-end tests of the orchestrator and API using offline fixtures (no network)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from rxguard.api import main as api
from rxguard.interactions.store import InteractionStore, base_severity
from rxguard.normalise.rxnorm import RxNormNormaliser
from rxguard.patients.fhir import FilePatientSource
from rxguard.pipeline import DISCLAIMER, Pipeline
from rxguard.rules.engine import UNKNOWN_LEVEL, RulesEngine
from scripts.make_dev_data import main as make_dev_data


class FakePredictor:
    def __init__(self, label, conf):
        self.label, self.conf = label, conf

    def predict(self, a, b):
        return self.label, self.conf


@pytest.fixture
def pipeline(tmp_path):
    make_dev_data(tmp_path)
    return Pipeline(
        RxNormNormaliser(offline=True),
        InteractionStore(tmp_path / "interactions.sqlite"),
        FilePatientSource(tmp_path / "patients", today=date(2026, 9, 30)),
        RulesEngine.from_config(),
    )


def test_spec_example_p1042_scores_9_high(pipeline):
    out = pipeline.check("Tylenol", "Warfarin", "P-1042")
    assert out["drugs"] == ["acetaminophen", "warfarin"]
    assert out["base_severity"] == "Moderate" and out["severity_source"] == "DDInter"
    assert out["risk_score"] == 9 and out["risk_level"] == "High"
    assert sorted(l["rule"] for l in out["score_breakdown"]) == ["age", "alcohol", "base_severity", "liver"]
    assert out["disclaimer"] == DISCLAIMER


def test_spec_example_p2210_scores_4_moderate(pipeline):
    out = pipeline.check("Tylenol", "Warfarin", "P-2210")
    assert out["risk_score"] == 4 and out["risk_level"] == "Moderate"


def test_misspelling_returns_suggestions(pipeline):
    from rxguard.pipeline import CheckError
    with pytest.raises(CheckError) as e:
        pipeline.check("warfrin", "Tylenol", "P-1042")
    assert e.value.status == 422
    assert "warfarin" in e.value.detail["unresolved"][0]["suggestions"]


def test_pair_missing_and_no_model_is_unknown(pipeline):
    out = pipeline.check("Advil", "Glucophage", "P-2210")
    assert out["risk_level"] == UNKNOWN_LEVEL and out["risk_score"] is None


def test_low_confidence_prediction_is_unknown(tmp_path):
    store = InteractionStore(tmp_path / "x.sqlite")
    r = base_severity(store, FakePredictor("Minor", 0.55), "a", "b", 0.6)
    assert r.severity is None and r.source == "unknown"
    r = base_severity(store, FakePredictor("Major", 0.8), "a", "b", 0.6)
    assert r.severity == "Major" and r.source == "predicted" and r.confidence == 0.8


def test_ddinter_loader_keeps_most_severe_and_skips_unknown(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text("DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
                   "DDInter1,Warfarin,DDInter2,Aspirin,Moderate\n"
                   "DDInter2,Aspirin,DDInter1,Warfarin,Major\n"
                   "DDInter3,Foo,DDInter4,Bar,Unknown\n")
    store = InteractionStore(tmp_path / "s.sqlite")
    assert store.load_ddinter_csv([csv]) == 1
    assert store.lookup("warfarin", "aspirin") == "Major"
    assert store.lookup("foo", "bar") is None


def test_api_check_and_errors(pipeline):
    api.app.dependency_overrides[api.get_pipeline] = lambda: pipeline
    try:
        c = TestClient(api.app)
        r = c.post("/check", json={"drug_a": "Tylenol", "drug_b": "Coumadin", "patient_id": "P-1042"})
        assert r.status_code == 200 and r.json()["risk_score"] == 9
        assert c.post("/check", json={"drug_a": "Tylenol", "drug_b": "Coumadin", "patient_id": "P-9"}).status_code == 404
        assert c.get("/health").json()["interaction_pairs"] == 1
    finally:
        api.app.dependency_overrides.clear()
