# Quick Start

Run all commands from this extracted package root.

## 1. Environment
Python 3.10+; install ffmpeg/ffprobe and add both to PATH.
```
python -m pip install jsonschema referencing
ffmpeg -version
ffprobe -version
```
Use a suitable current `jsonschema` release with Draft 2020-12 support.
No model frameworks are required to validate or inspect this package.

## 2. Validate package
```
python -B scripts/validate_package.py
```
Expected final output: `PASS`. This streams and checks all 448 canonical RGB frames
across seven ITEMs, without saving frames or accumulating them in memory.

## 3. Inspect items
```
python -B scripts/inspect_item.py --all
python -B scripts/inspect_item.py ITEM_01
```
Only public metadata is printed.

## 4. Load one item
```
python -B scripts/load_model_input.py ITEM_01
```
This prints public harness metadata. Local media handles and fingerprints are for your harness,
not model prompt text. Do not forward filesystem paths or ITEM IDs to a decision model.

## 5. Python API
```python
from scripts.load_model_input import load_item, iter_model_frames

item = load_item("ITEM_01")
count = 0
for frame in iter_model_frames("ITEM_01"):
    rgb = frame["rgb24"]  # packed uint8 RGB bytes, H x W x 3
    camera = frame["camera"]
    timestamp = frame["timestamp_sec"]
    # Feed only these canonical pixels, camera IDs and relative times to your pipeline.
    count += 1
assert count == 64
fingerprint = item["input_fingerprint"]
```
Frames are 1920 x 1080. Stream them rather than materializing a full list (~380 MiB per ITEM).
Use `item["prompt"]` and `item["response_schema"]` for model requests.

## 6. Validate a real measured result
```
python -B scripts/validate_prediction.py submissions/p1_clef_flash/run_ITEM_01.json --result
```
Expected: `Schema and context validation: PASS`.
See `docs/OUTPUT_PROTOCOL.md` for the required frozen field names and metadata.
