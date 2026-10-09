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
    def __post_init__(self):
        if not math.isfinite(self.model_timeout_sec) or self.model_timeout_sec <= 0:
            raise ValueError("MODEL_TIMEOUT_SEC must be positive and finite")
    @classmethod
    def from_env(cls):
        mode = os.getenv("APP_MODE", "demo")
        if mode not in {"demo", "development"}: raise ValueError("unsupported APP_MODE; production needs persistence/auth")
        return cls(mode=mode,origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", ",".join(cls.origins)).split(",") if x.strip()),
            media_root=Path(os.getenv("MEDIA_ROOT","media")),
            model_adapter=os.getenv("MODEL_ADAPTER", "local_cv"),
            model_timeout_sec=float(os.getenv("MODEL_TIMEOUT_SEC", "5")),
            asset_map_path=Path(os.environ["ASSET_MAP"]) if os.getenv("ASSET_MAP") else None,
            asset_root=Path(os.environ["ASSET_ROOT"]) if os.getenv("ASSET_ROOT") else None)
