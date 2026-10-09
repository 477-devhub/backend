"""Inherited ledger plus explicit scoped user authorization; no refund/reset."""
import json
import math
import uuid
from decimal import Decimal
from pathlib import Path

class Budget:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError("existing authorized ledger required")
        self.state = json.loads(self.path.read_text(encoding="utf-8"))
        if not 0 < self.state["limit_usd"] <= 5:
            raise ValueError("existing authorization is at most $5")
        authorization = self.path.parent / "paid_authorization.json"
        self.authorization = json.loads(authorization.read_text(encoding="utf-8")) if authorization.exists() else {}
        self.uncapped = (self.authorization.get("authorized") is True
                        and self.authorization.get("total_cap_usd", 0) is None
                        and self.authorization.get("supersedes_prior_limit_usd") == self.state["limit_usd"])

    @property
    def remaining(self):
        self.state = json.loads(self.path.read_text(encoding="utf-8"))
        if self.uncapped:
            return None
        return float(Decimal(str(self.state["limit_usd"])) - sum(
            (Decimal(str(r["reserved_usd"])) for r in self.state["requests"]), Decimal(0)))

    def reserve(self, provider, upper_usd):
        if not math.isfinite(upper_usd) or upper_usd <= 0 or (self.remaining is not None and self.remaining < upper_usd):
            raise RuntimeError("budget_exhausted")
        if not self.uncapped and any(r["status"] == "cost_bound_exceeded" for r in self.state["requests"]):
            raise RuntimeError("budget_exhausted")
        token = uuid.uuid4().hex
        self.state["requests"].append({"id": token, "provider": provider,
            "reserved_usd": upper_usd, "usage_cost_estimate_usd": None,
            "usage": {}, "status": "reserved_or_unknown"})
        self._save()
        return token

    def settle(self, token, usage, cost, status):
        row = next(r for r in self.state["requests"] if r["id"] == token)
        if cost is not None and (not math.isfinite(cost) or cost < 0):
            raise ValueError("invalid provider cost")
        row.update(usage=usage, usage_cost_estimate_usd=cost, status=status)
        if cost is not None and cost > row["reserved_usd"]:
            row["status"] = "cost_bound_exceeded"
        self._save()

    def _save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(self.path)
