from app.models.adapters.local_cv import LocalCVAdapter
from app.models.adapters.unconfigured import UnconfiguredAdapter
from app.models.media import MediaResolver
from app.models.registry import get_adapter


def test_registry_resolver_injection_is_explicit(tmp_path):
    resolver = MediaResolver(tmp_path, {})
    local = get_adapter("local_cv", resolver=resolver)
    assert isinstance(local, LocalCVAdapter) and local.resolver is resolver
    assert isinstance(get_adapter("local_cv"), UnconfiguredAdapter)
    for name in ("clef_direct", "general_vlm"):
        assert isinstance(get_adapter(name, resolver=resolver), UnconfiguredAdapter)
    assert get_adapter("mock_local_cv", resolver=resolver).name == "mock_local_cv"
