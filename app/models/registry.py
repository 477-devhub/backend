from app.models.adapters.mock_local_cv import MockLocalCVAdapter
from app.models.adapters.mock_clef import MockClefDirectAdapter
from app.models.adapters.mock_vlm import MockGeneralVLMAdapter
from app.models.adapters.unconfigured import UnconfiguredAdapter
from app.models.media import MediaResolver

ADAPTER_NAMES = ("local_cv", "clef_direct", "general_vlm", "mock_local_cv", "mock_clef", "mock_vlm")
def get_adapter(name: str, *, resolver: MediaResolver | None = None):
    mocks = {"mock_local_cv": MockLocalCVAdapter, "mock_clef": MockClefDirectAdapter, "mock_vlm": MockGeneralVLMAdapter}
    if name in mocks:
        return mocks[name]()
    if name == "local_cv" and resolver is not None:
        from app.models.adapters.local_cv import LocalCVAdapter
        return LocalCVAdapter(resolver)
    if name in ADAPTER_NAMES:
        return UnconfiguredAdapter(name)
    raise ValueError(f"unknown adapter: {name}")


def get_benchmark_adapter(name: str, *, budget=None, root=None, **options):
    """Explicit benchmark entry point; preserve existing backend configuration."""
    from pathlib import Path
    workspace = Path(root or Path(__file__).resolve().parents[2])
    if name == 'local_cv':
        from app.models.adapters.yolo_benchmark import YoloBenchmarkAdapter
        pose_enabled = options.pop('pose_enabled', True)
        if not isinstance(pose_enabled, bool):
            raise ValueError('pose_enabled must be a boolean')
        adapter = YoloBenchmarkAdapter(workspace/'artifacts/models/yolo26s.pt',
            workspace/'artifacts/models/yolo26s-pose.pt' if pose_enabled else None, **options)
        adapter.name = name
        return adapter
    if budget is None:
        raise ValueError('paid benchmark adapters require the persistent shared budget')
    if name == 'clef_direct':
        from app.models.adapters.clef_benchmark import ClefBenchmarkAdapter
        adapter = ClefBenchmarkAdapter(budget=budget, **options)
        adapter.name = name
        return adapter
    if name == 'general_vlm':
        from app.models.adapters.deepseek_benchmark import DeepSeekBenchmarkAdapter
        adapter = DeepSeekBenchmarkAdapter(budget=budget, **options)
        adapter.name = name
        return adapter
    raise ValueError(f'unknown benchmark adapter: {name}')
