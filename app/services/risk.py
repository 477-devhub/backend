from app.schemas.model import RiskAxes

def risk_score(a: RiskAxes) -> int | None:
    if not a.is_complete:
        return None
    return round((.35*a.severity + .30*a.imminence + .20*a.exposure + .15*a.persistence)*100)
def risk_level(s: int | None) -> str:
    if s is None: return "UNKNOWN"
    return "CRITICAL" if s >= 85 else "HIGH" if s >= 65 else "MEDIUM" if s >= 40 else "LOW"
