import json

import pytest

from app.config import Settings
from app.main import create_app
from app.models.media import MediaResolver


def test_asset_map_constructor_and_bounded_bytes(tmp_path):
    (tmp_path / "neutral.bin").write_bytes(b"synthetic-unit-bytes")
    mapping = tmp_path / "asset-map.json"
    mapping.write_text(json.dumps({"clip_000001": "neutral.bin"}), encoding="utf-8")
    resolver = MediaResolver.from_asset_map(mapping)
    assert resolver.read("clip_000001") == b"synthetic-unit-bytes"
    with pytest.raises(ValueError, match="byte budget"):
        resolver.read("clip_000001", max_bytes=3)


@pytest.mark.parametrize("contents", [
    '[]', '{"clip_000001": 123}', '{"clip_000001": ""}',
    '{"clip_000001": "a", "clip_000001": "b"}',
])
def test_asset_map_rejects_invalid_or_duplicate_tokens(tmp_path, contents):
    mapping = tmp_path / "asset-map.json"
    mapping.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        MediaResolver.from_asset_map(mapping)


def test_asset_map_cannot_read_outside_root(tmp_path):
    resolver = MediaResolver(tmp_path, {"clip_000001": "../outside.bin"})
    with pytest.raises(ValueError, match="escapes root"):
        resolver.read("clip_000001")


def test_frame_assets_are_isolated_and_conflicts_rejected(tmp_path):
    original = MediaResolver(tmp_path, {})
    prepared = original.with_assets({"media_000001": b"synthetic-jpeg"})
    assert not original.assets
    assert prepared.read("media_000001") == b"synthetic-jpeg"
    with pytest.raises(ValueError, match="byte budget"):
        prepared.read("media_000001", max_bytes=1)
    with pytest.raises(ValueError, match="content conflict"):
        prepared.with_assets({"media_000001": b"different"})
    with pytest.raises(ValueError, match="duplicate asset"):
        MediaResolver(tmp_path, {"media_000001": "file"}, assets={"media_000001": b"x"})


def test_optional_asset_map_is_injected_without_model_fallback(tmp_path):
    (tmp_path / "neutral.bin").write_bytes(b"synthetic")
    mapping = tmp_path / "asset-map.json"
    mapping.write_text('{"clip_000001":"neutral.bin"}', encoding="utf-8")
    app = create_app(Settings(asset_map_path=mapping))
    assert app.state.media_resolver.read("clip_000001") == b"synthetic"
    assert app.state.media_ingestion.resolver is app.state.media_resolver
    assert app.state.model_adapter.name == "local_cv"


async def test_missing_resolver_is_explicitly_unconfigured(mi):
    app = create_app(Settings())
    assert app.state.media_resolver is None and app.state.media_ingestion is None
    with pytest.raises(ValueError, match="not configured"):
        await app.state.prepare_model_input(mi)
