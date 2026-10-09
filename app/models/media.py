from pathlib import Path
import json
class MediaResolver:
    """Trusted local lookup, injected by MAIN into adapters. Never serialize this mapping to a model."""
    def __init__(self, root: Path, mapping: dict[str,str], *, assets: dict[str, bytes] | None = None):
        if not isinstance(mapping, dict) or any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in mapping.items()
        ):
            raise ValueError("asset map must contain nonempty token/path strings")
        self.root=Path(root).resolve();self.mapping=dict(mapping)
        self.assets = dict(assets or {})
        if any(not isinstance(key, str) or not key or not isinstance(value, bytes)
               for key, value in self.assets.items()):
            raise ValueError("memory assets must contain token/bytes pairs")
        if self.mapping.keys() & self.assets.keys():
            raise ValueError("duplicate asset token")

    @classmethod
    def from_asset_map(cls, asset_map: Path, root: Path | None = None):
        asset_map = Path(asset_map)
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate asset token")
                result[key] = value
            return result
        mapping = json.loads(asset_map.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        return cls(root if root is not None else asset_map.parent, mapping)

    def with_assets(self, assets: dict[str, bytes]):
        combined = dict(self.assets)
        for key, value in assets.items():
            if key in combined and combined[key] != value:
                raise ValueError("asset token content conflict")
            combined[key] = value
        return type(self)(self.root, self.mapping, assets=combined)

    def read(self, opaque_ref: str, *, max_bytes: int | None = None) -> bytes:
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if opaque_ref in self.assets:
            value = self.assets[opaque_ref]
            if max_bytes is not None and len(value) > max_bytes:
                raise ValueError("media exceeds byte budget")
            return value
        relative=self.mapping[opaque_ref]
        path=(self.root/relative).resolve()
        if not path.is_relative_to(self.root):raise ValueError("media escapes root")
        with path.open("rb") as stream:
            value = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        if max_bytes is not None and len(value) > max_bytes:
            raise ValueError("media exceeds byte budget")
        return value
