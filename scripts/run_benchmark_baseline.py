"""Reproducible baseline entry point; all paid calls share one persistent ledger."""
import argparse
import asyncio
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from dotenv import load_dotenv
from app.models.benchmark_media import assert_output_outside_inputs, snapshot_protected
from app.models.budget import PaidBudget
from app.models.registry import get_benchmark_adapter


def public_budget_status(budget):
    status = budget.summary()
    known = status['usage_cost_known_requests']
    status['known_partial_usage_cost_estimate_usd'] = status['usage_cost_estimate_usd'] if known else None
    if known < status['requests']:
        status['usage_cost_estimate_usd'] = None
    return status


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['suite', 'local_cv', 'clef', 'vlm', 'pipeline'], default='suite')
    parser.add_argument('--items', nargs='+', default=[f'ITEM_{i:02d}' for i in range(1,8)])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cv-profile', choices=['pose-always', 'pose-off'], default='pose-always',
        help='pose-off is a separate speed experiment; detector resolution and 64 frames are unchanged.')
    parser.add_argument('--vlm-transport',
        choices=['deepseek_timestamp_copy_v2', 'deepseek_json_labels_v3'],
        default='deepseek_timestamp_copy_v2',
        help='v3 is a separate JSON-label experiment with a 4096 output-token cap.')
    parser.add_argument('--output', type=Path,
        default=ROOT/'runs'/('baseline-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
    args = parser.parse_args()
    if (not 1 <= args.repeats <= 3 or len(set(args.items)) != len(args.items)
            or any(i not in {f'ITEM_{n:02d}' for n in range(1,8)} for i in args.items)):
        parser.error('Use one to three repetitions and unique ITEM_01 through ITEM_07.')
    output = assert_output_outside_inputs(ROOT, args.output)
    if output.exists() and any(output.iterdir()):
        parser.error('Output directory already contains results; choose a new directory.')
    load_dotenv(ROOT/'.env', override=False)
    for name in ('httpx', 'httpcore'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    budget = PaidBudget(ROOT/'runs/477-paid-budget.json', limit_usd=5)
    adapters = {name: get_benchmark_adapter(name, root=ROOT, budget=budget,
        **({'pose_enabled': args.cv_profile == 'pose-always'} if name == 'local_cv' else
           {'transport_profile': args.vlm_transport} if name == 'general_vlm' else {}))
        for name in ('local_cv', 'clef_direct', 'general_vlm')}
    from decimal import Decimal
    from app.models.adapters.clef_benchmark import RESERVATION_USD as CLEF_RESERVE
    from app.models.adapters.deepseek_benchmark import RESERVATION_USD as VLM_RESERVE
    counts = len(args.items) * args.repeats
    planned_vlm = counts * (2 if args.mode == 'suite' else 1 if args.mode in {'vlm', 'pipeline'} else 0)
    planned_clef = counts if args.mode in {'suite', 'clef', 'pipeline'} else 0
    vlm_reserve = getattr(adapters['general_vlm'], 'reservation_upper_usd', VLM_RESERVE)
    planned_reserve = Decimal(str(CLEF_RESERVE)) * planned_clef + Decimal(str(vlm_reserve)) * planned_vlm
    if budget.reserved_usd + planned_reserve > budget.limit:
        parser.error('Planned worst-case calls exceed the remaining shared $5 reservation budget; '
                     'reduce items/repeats. Never reset the ledger to continue.')
    before = snapshot_protected(ROOT)
    balance_before = await adapters['general_vlm'].get_balance() if args.mode in {'suite','vlm','pipeline'} else None
    from app.eval.benchmark_baseline import run_baseline
    summary = await run_baseline(root=ROOT, output=output, adapters=adapters,
        budget=budget, items=tuple(args.items), repeats=args.repeats, mode=args.mode)
    balance_after = await adapters['general_vlm'].get_balance() if balance_before is not None else None
    dependencies = {}
    for name in ('torch','torchvision','ultralytics','numpy','opencv-python','httpx','jsonschema','lap','scipy'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    metadata = {'python': sys.version.split()[0], 'dependencies': dependencies,
        'mode': args.mode, 'items': args.items, 'repeats': args.repeats,
        'cv_profile': args.cv_profile,
        'vlm_transport': args.vlm_transport,
        'supplemental_speed_experiment': args.cv_profile == 'pose-off',
        'planned_reservation_usd': float(planned_reserve),
        'balance_before': balance_before, 'balance_after': balance_after,
        'balance_caveat': 'Balance change can include concurrent account activity and rounding; not a per-request invoice.',
        'budget_including_separate_provider_probe': public_budget_status(budget),
        'protected_inputs_unchanged': before == snapshot_protected(ROOT),
        'protected_snapshot_before': before}
    (output/'execution_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False,
        indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps({'output': str(output), 'protected_inputs_unchanged': metadata['protected_inputs_unchanged'],
        'budget': public_budget_status(budget), 'summary_file': str(output/'summary.json')}))
    if not metadata['protected_inputs_unchanged']:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
