"""One explicitly separate real-media access probe within the shared $5 ledger."""
import asyncio
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from dotenv import load_dotenv
from app.models.benchmark_media import load_benchmark_input, snapshot_protected
from app.models.budget import PaidBudget
from app.models.execution import execute_benchmark
from app.models.registry import get_benchmark_adapter


async def main():
    load_dotenv(ROOT/'.env', override=False)
    output = ROOT/'runs/provider-access-check'
    output.mkdir(parents=True, exist_ok=True)
    if (output/'results.json').exists():
        raise SystemExit('Provider check already exists; inspect it before making another paid call.')
    budget = PaidBudget(ROOT/'runs/477-paid-budget.json', limit_usd=5)
    before = snapshot_protected(ROOT)
    request, decode_ms = await asyncio.to_thread(load_benchmark_input,
        ROOT/'477_modeling_benchmark_v1', 'ITEM_01')
    vlm = get_benchmark_adapter('general_vlm', budget=budget)
    clef = get_benchmark_adapter('clef_direct', budget=budget)
    balance_before = await vlm.get_balance()
    outcomes = {}
    outcomes['vlm'] = asdict(await execute_benchmark(vlm, request, timeout_sec=210))
    features = json.loads((ROOT/'runs/cv-diagnostic/ITEM_01.json').read_text(encoding='utf8'))['outcome']['features']
    outcomes['clef'] = asdict(await execute_benchmark(clef,
        replace(request, features_json=json.dumps(features, ensure_ascii=False)), timeout_sec=150))
    result = {'experiment': 'separate real-media provider access check',
        'item_id': 'ITEM_01', 'decode_ms': decode_ms, 'outcomes': outcomes,
        'balance_before': balance_before, 'balance_after': await vlm.get_balance(),
        'budget': budget.summary(), 'protected_inputs_unchanged': before == snapshot_protected(ROOT)}
    (output/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2,
        allow_nan=False), encoding='utf8')
    print(json.dumps({'outcomes': {name: {'status': row['status'],
        'error_code': row['error_code'], 'http_status': row['metadata'].get('http_status'),
        'latency_ms': row['latency_ms'], 'usage': row['usage']}
        for name, row in outcomes.items()}, 'budget': result['budget'],
        'protected_inputs_unchanged': result['protected_inputs_unchanged']}))


if __name__ == '__main__':
    asyncio.run(main())
