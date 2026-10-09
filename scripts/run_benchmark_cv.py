"""Read-only canonical CV diagnostic; authored outputs stay outside inputs."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from app.models.benchmark_media import (assert_output_outside_inputs,
    load_benchmark_input, snapshot_protected)
from app.models.execution import execute_benchmark
from app.models.adapters.yolo_benchmark import YoloBenchmarkAdapter


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--item', default='ITEM_01')
    parser.add_argument('--output', type=Path, default=ROOT/'runs/cv-diagnostic')
    args = parser.parse_args()
    assert_output_outside_inputs(ROOT, args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    before = snapshot_protected(ROOT)
    request, decode_ms = await asyncio.to_thread(load_benchmark_input,
        ROOT/'477_modeling_benchmark_v1', args.item)
    adapter = YoloBenchmarkAdapter(ROOT/'artifacts/models/yolo26s.pt',
        ROOT/'artifacts/models/yolo26s-pose.pt', worker_python=Path(sys.executable))
    outcome = await execute_benchmark(adapter, request, timeout_sec=1800)
    result = {'item_id': args.item, 'decode_ms': decode_ms,
        'outcome': asdict(outcome), 'protected_inputs_unchanged':
            before == snapshot_protected(ROOT)}
    (args.output/(args.item+'.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps({'item_id': args.item, 'status': outcome.status,
        'error_code': outcome.error_code, 'decode_ms': decode_ms,
        'latency_ms': outcome.latency_ms,
        'protected_inputs_unchanged': result['protected_inputs_unchanged']}))
    if outcome.status != 'ok' or not result['protected_inputs_unchanged']:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
