from pathlib import Path
import pytest
from app.models.budget import PaidBudget
from app.models.execution import execute_benchmark
from app.schemas.benchmark import BenchmarkInput, BenchmarkOutcome, BenchmarkError, CanonicalFrame


def test_budget_reservations_survive_failures_and_restart(tmp_path: Path):
    budget = PaidBudget(tmp_path / "ledger.json", 0.10)
    token = budget.reserve("test", 0.06)
    budget.settle(token, {}, None, "transport_unknown")
    restarted = PaidBudget(tmp_path / "ledger.json", 0.10)
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        restarted.reserve("test", 0.06)
    assert restarted.summary()["reserved_usd"] == 0.06
    assert restarted.summary()["actual_invoice_cost_usd"] is None


def test_cost_bound_violation_halts_further_requests(tmp_path: Path):
    budget = PaidBudget(tmp_path / "ledger.json")
    token = budget.reserve("test", 0.01)
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        budget.settle(token, {}, 0.02, "ok")
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        budget.reserve("test", 0.01)


def test_unknown_budget_is_not_refunded(tmp_path: Path):
    budget = PaidBudget(tmp_path / "ledger.json", 0.1)
    budget.reserve("test", 0.1)
    with pytest.raises(BenchmarkError):
        budget.reserve("test", 0.001)


@pytest.mark.asyncio
async def test_benchmark_execution_sanitizes_provider_exception():
    pixels = b"\0" * (1920 * 1080 * 3)
    request = BenchmarkInput("fixture", "single", "Frozen JSON prompt.", "{}", "{}",
        tuple(CanonicalFrame("CAM_01", float(i), pixels) for i in range(64)))

    class Failing:
        name = "test_fixture"
        model = "test_fixture"
        async def evaluate_benchmark(self, model_input):
            raise RuntimeError("Authorization: Bearer SECRET_DO_NOT_RETURN")

    result = await execute_benchmark(Failing(), request)
    assert result.status == "error"
    assert result.error_code == "provider_error"
    assert result.prediction is None
    assert "SECRET" not in repr(result)


def test_canonical_input_rejects_non64_visual_budget():
    with pytest.raises(ValueError, match="64 total"):
        BenchmarkInput("fixture", "single", "prompt", "{}", "{}", ())
