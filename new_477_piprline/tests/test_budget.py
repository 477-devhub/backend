import json

import pytest

from pipeline477.budget import Budget
from pipeline477.io import write_json

def test_inherited_reservations_cannot_reset_or_refund(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"limit_usd": 5, "requests": [{"id": "old", "reserved_usd": 4.99158528,
        "usage_cost_estimate_usd": None, "status": "reserved_or_unknown", "usage": {}}]}))
    budget = Budget(path)
    assert budget.remaining == pytest.approx(.00841472)
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        budget.reserve("clef", .03145728)
    assert len(json.loads(path.read_text())["requests"]) == 1

def test_no_implicit_new_paid_allowance(tmp_path):
    with pytest.raises(ValueError):
        Budget(tmp_path / "missing.json")

def test_explicit_additional_authorization_preserves_prior_reservations(tmp_path):
    path = tmp_path / "ledger.json"
    prior = {"id": "old", "reserved_usd": 4.99158528, "usage_cost_estimate_usd": None,
             "status": "reserved_or_unknown", "usage": {}}
    path.write_text(json.dumps({"limit_usd": 5, "requests": [prior]}))
    (tmp_path / "paid_authorization.json").write_text(json.dumps({"authorized": True,
        "total_cap_usd": None, "supersedes_prior_limit_usd": 5}))
    budget = Budget(path)
    assert budget.remaining is None
    budget.reserve("clef", .03145728)
    saved = json.loads(path.read_text())
    assert saved["requests"][0] == prior and len(saved["requests"]) == 2

def test_sanitized_artifacts_remove_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("VLM_API_KEY", "TEST_ONLY_SENTINEL_SECRET")
    path = tmp_path / "output.json"
    write_json(path, {"message": "echo TEST_ONLY_SENTINEL_SECRET", "Authorization": "Bearer TEST_ONLY_SENTINEL_SECRET"})
    assert "TEST_ONLY_SENTINEL_SECRET" not in path.read_text()
    assert "[REDACTED]" in path.read_text()
