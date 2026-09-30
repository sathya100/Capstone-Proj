"""Rules engine unit tests: every rule and boundary (evaluation plan: 100% pass rate)."""
import pytest

from rxguard.models import Condition, PatientContext, SeverityResult
from rxguard.rules.engine import UNKNOWN_LEVEL, RulesEngine


@pytest.fixture(scope="module")
def engine():
    return RulesEngine.from_config()


def pt(**kw):
    base = dict(patient_id="T", age=40, egfr=100.0, alt=20.0, alcohol_drinks_per_day=0.0)
    base.update(kw)
    return PatientContext(**base)


MOD = SeverityResult("Moderate", "DDInter")
PAIR = ["acetaminophen", "warfarin"]


def rules_fired(result):
    return [l.rule for l in result.breakdown]


@pytest.mark.parametrize("sev,pts", [("Major", 6), ("Moderate", 4), ("Minor", 2), ("None", 0)])
def test_base_severity_points(engine, sev, pts):
    r = engine.score(PAIR, SeverityResult(sev, "DDInter"), pt())
    assert r.risk_score == pts


@pytest.mark.parametrize("age,fires", [(64, False), (65, True), (66, True)])
def test_age_boundary(engine, age, fires):
    assert ("age" in rules_fired(engine.score(PAIR, MOD, pt(age=age)))) is fires


@pytest.mark.parametrize("egfr,fires", [(59, True), (59.9, True), (60, False), (61, False)])
def test_egfr_boundary_with_kidney_cleared_drug(engine, egfr, fires):
    r = engine.score(["metformin", "lisinopril"], MOD, pt(egfr=egfr))
    assert ("kidney" in rules_fired(r)) is fires


def test_kidney_rule_needs_kidney_cleared_drug(engine):
    assert "kidney" not in rules_fired(engine.score(PAIR, MOD, pt(egfr=30)))


@pytest.mark.parametrize("alt,fires", [(119, False), (120, False), (121, True)])
def test_alt_boundary(engine, alt, fires):  # ULN 40, > 3x -> > 120
    assert ("liver" in rules_fired(engine.score(PAIR, MOD, pt(alt=alt)))) is fires


def test_liver_disease_fires_liver_rule(engine):
    r = engine.score(PAIR, MOD, pt(conditions=[Condition("Chronic liver disease")]))
    assert rules_fired(r).count("liver") == 1
    assert "condition_caution" not in rules_fired(r)  # not double-counted


def test_liver_rule_needs_liver_metabolised_drug(engine):
    r = engine.score(["metformin", "gabapentin"], MOD, pt(conditions=[Condition("Cirrhosis of liver")]))
    assert "liver" not in rules_fired(r)


def test_liver_disease_and_high_alt_count_once(engine):
    r = engine.score(PAIR, MOD, pt(alt=300, conditions=[Condition("Chronic hepatitis C")]))
    assert rules_fired(r).count("liver") == 1


@pytest.mark.parametrize("drinks,fires", [(2, False), (2.9, False), (3, True), (5, True)])
def test_alcohol_boundary(engine, drinks, fires):
    assert ("alcohol" in rules_fired(engine.score(PAIR, MOD, pt(alcohol_drinks_per_day=drinks)))) is fires


def test_alcohol_needs_acetaminophen(engine):
    r = engine.score(["warfarin", "aspirin"], MOD, pt(alcohol_drinks_per_day=6))
    assert "alcohol" not in rules_fired(r)


def test_condition_caution_each_condition_once(engine):
    # peptic ulcer is a caution for both warfarin and aspirin -> +2 once
    r = engine.score(["warfarin", "aspirin"], MOD, pt(conditions=[Condition("Peptic ulcer")]))
    assert rules_fired(r).count("condition_caution") == 1
    assert r.risk_score == 6


def test_multiple_caution_conditions_add_up(engine):
    conds = [Condition("Essential hypertension"), Condition("Chronic congestive heart failure")]
    r = engine.score(["ibuprofen", "lisinopril"], MOD, pt(conditions=conds))
    assert rules_fired(r).count("condition_caution") == 2
    assert r.risk_score == 8


def test_cap_at_10(engine):
    p = pt(age=80, alt=500, alcohol_drinks_per_day=6, conditions=[Condition("Peptic ulcer")])
    r = engine.score(PAIR, SeverityResult("Major", "DDInter"), p)
    assert r.risk_score == 10 and r.capped
    assert sum(l.points for l in r.breakdown) > 10  # breakdown still shows every point


@pytest.mark.parametrize("score,band", [(0, "Low"), (3, "Low"), (4, "Moderate"), (6, "Moderate"),
                                        (7, "High"), (10, "High")])
def test_bands(engine, score, band):
    assert engine.band(score) == band


def test_unknown_severity_is_never_low(engine):
    r = engine.score(PAIR, SeverityResult(None, "unknown"), pt())
    assert r.risk_score is None and r.risk_level == UNKNOWN_LEVEL


def test_missing_fields_flagged_and_skipped(engine):
    p = PatientContext(patient_id="T", age=None, egfr=None, alt=None, alcohol_drinks_per_day=None)
    r = engine.score(PAIR, MOD, p)
    assert r.risk_score == 4
    assert set(r.missing_fields) >= {"age", "egfr", "alt", "alcohol_drinks_per_day"}


def test_unknown_drug_gets_base_severity_only(engine):
    r = engine.score(["acetaminophen", "notadrug"], MOD, pt(age=70, egfr=20))
    assert "drug_flags:notadrug" in r.missing_fields
    assert rules_fired(r) == ["base_severity", "age"]


def test_every_point_traces_to_a_rule(engine):
    p = pt(age=70, alcohol_drinks_per_day=4, conditions=[Condition("Chronic liver disease")])
    r = engine.score(PAIR, MOD, p)
    assert all(l.rule and l.reason for l in r.breakdown)
    assert sum(l.points for l in r.breakdown) == r.risk_score
