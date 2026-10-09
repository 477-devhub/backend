import os
import math
from dataclasses import dataclass
from pathlib import Path
@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    origins: tuple[str,...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    media_root: Path = Path("media")
    model_adapter: str = "local_cv"
    model_timeout_sec: float = 5.0
    asset_map_path: Path | None = None
    asset_root: Path | None = None
    demo_scenario_path: Path | None = None
    analysis_queue_size: int = 8
    analysis_max_jobs: int = 1000
    ai_mode: str = "shadow"
    ai_python: Path | None = None
    ai_cv_python: Path | None = None
    ai_weights: Path | None = None
    ai_stage_timeout_sec: float = 300.0
    ai_total_timeout_sec: float = 1200.0
    def __post_init__(self):
        if not math.isfinite(self.model_timeout_sec) or self.model_timeout_sec <= 0:
            raise ValueError("MODEL_TIMEOUT_SEC must be positive and finite")
        if self.ai_mode not in {"shadow", "frozen_cascade_v1"}:
            raise ValueError("unsupported AI_MODE")
        if self.analysis_queue_size < 1 or self.analysis_max_jobs < self.analysis_queue_size:
            raise ValueError("invalid analysis job limits")
        if any(not math.isfinite(v) or v <= 0 for v in (self.ai_stage_timeout_sec, self.ai_total_timeout_sec)):
            raise ValueError("AI timeouts must be positive and finite")
    @classmethod
    def from_env(cls):
        mode = os.getenv("APP_MODE", "demo")
        if mode not in {"demo", "development"}: raise ValueError("unsupported APP_MODE; production needs persistence/auth")
        return cls(mode=mode,origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", ",".join(cls.origins)).split(",") if x.strip()),
            media_root=Path(os.getenv("MEDIA_ROOT","media")),
            model_adapter=os.getenv("MODEL_ADAPTER", "local_cv"),
            model_timeout_sec=float(os.getenv("MODEL_TIMEOUT_SEC", "5")),
            asset_map_path=Path(os.environ["ASSET_MAP"]) if os.getenv("ASSET_MAP") else None,
            asset_root=Path(os.environ["ASSET_ROOT"]) if os.getenv("ASSET_ROOT") else None,
            demo_scenario_path=Path(os.environ["DEMO_SCENARIO_PATH"]) if os.getenv("DEMO_SCENARIO_PATH") else None,
            analysis_queue_size=int(os.getenv("ANALYSIS_QUEUE_SIZE", "8")),
            analysis_max_jobs=int(os.getenv("ANALYSIS_MAX_JOBS", "1000")),
            ai_mode=os.getenv("AI_MODE", "shadow"),
            ai_python=Path(os.environ["AI_PYTHON"]) if os.getenv("AI_PYTHON") else None,
            ai_cv_python=Path(os.environ["AI_CV_PYTHON"]) if os.getenv("AI_CV_PYTHON") else None,
            ai_weights=Path(os.environ["AI_WEIGHTS"]) if os.getenv("AI_WEIGHTS") else None,
            ai_stage_timeout_sec=float(os.getenv("AI_STAGE_TIMEOUT_SEC", "300")),
            ai_total_timeout_sec=float(os.getenv("AI_TOTAL_TIMEOUT_SEC", "1200")))
