"""Fail-closed, persistent sequential paid-request reservation ledger."""
from decimal import Decimal
from pathlib import Path
import json
import uuid
from app.schemas.benchmark import BenchmarkError


class PaidBudget:
    def __init__(self, path: Path, limit_usd: float = 5.0):
        self.path = Path(path)
        self.limit = Decimal(str(limit_usd))
        if not self.limit.is_finite() or not 0 < self.limit <= 5:
            raise ValueError("budget must be positive and at most $5")
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            if Decimal(str(self.state["limit_usd"])) != self.limit:
                raise ValueError("cannot change an existing run budget")
        else:
            self.state = {"limit_usd": float(self.limit), "requests": []}
            self._save()

    @property
    def reserved_usd(self):
        return sum((Decimal(str(r["reserved_usd"])) for r in self.state["requests"]), Decimal(0))

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def reserve(self, provider: str, upper_usd: float):
        amount = Decimal(str(upper_usd))
        if any(r["status"] == "cost_bound_exceeded" for r in self.state["requests"]):
            raise BenchmarkError("budget_exhausted")
        if not amount.is_finite() or amount <= 0 or self.reserved_usd + amount > self.limit:
            raise BenchmarkError("budget_exhausted")
        token = uuid.uuid4().hex
        self.state["requests"].append({"id": token, "provider": provider,
            "reserved_usd": float(amount), "usage_cost_estimate_usd": None,
            "status": "reserved_or_unknown", "usage": {}})
        # Never release a reservation: failed/timeout requests might have been billed.
        self._save()
        return token

    def settle(self, token: str, usage: dict, estimated_cost_usd: float | None, status: str):
        row = next(r for r in self.state["requests"] if r["id"] == token)
        if estimated_cost_usd is not None:
            cost = Decimal(str(estimated_cost_usd))
            if not cost.is_finite() or cost < 0:
                raise BenchmarkError("provider_schema_error")
            if cost > Decimal(str(row["reserved_usd"])):
                row["status"] = "cost_bound_exceeded"
                row["usage_cost_estimate_usd"] = float(cost)
                self._save()
                # Exhaust remaining requests, rather than hide a violated assumption.
                raise BenchmarkError("budget_exhausted")
        row.update(usage=usage, usage_cost_estimate_usd=estimated_cost_usd, status=status)
        self._save()

    def summary(self):
        costs = [r["usage_cost_estimate_usd"] for r in self.state["requests"]]
        return {"limit_usd": float(self.limit), "reserved_usd": float(self.reserved_usd),
            "requests": len(costs), "usage_cost_estimate_usd": sum(c for c in costs if c is not None),
            "usage_cost_known_requests": sum(c is not None for c in costs),
            "actual_invoice_cost_usd": None}
