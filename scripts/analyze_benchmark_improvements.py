"""Compare saved real runs; do not alter predictions or contact providers."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from app.models.benchmark_media import assert_output_outside_inputs


def median_seconds(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return statistics.median(values) / 1000 if values else None


def complete_chain(row):
    return bool(row.get('validated') and all(
        row.get('stages', {}).get(name, {}).get('status') == 'ok'
        and row['stages'][name].get('error_code') is None
        and row['stages'][name].get('invoked',
            row['stages'][name].get('metadata', {}).get('stage_invocation_index_in_run') is not None)
        for name in ('local_cv', 'clef_direct', 'general_vlm'))
        and not row.get('upstream_errors'))


def aggregate(rows):
    result = {}
    for condition in sorted({r['condition'] for r in rows}):
        part = [r for r in rows if r['condition'] == condition]
        stages = {k for r in part for k in r.get('stages', {})}
        paid_stages = [s for r in part for k, s in r.get('stages', {}).items()
                       if k in {'clef_direct', 'general_vlm'} and (
                           s.get('paid_requests_reserved', 0) > 0 or
                           'reservation_usd' in s.get('metadata', {}))]
        costs = [s.get('known_partial_usage_cost_estimate_usd',
                       s.get('metadata', {}).get('usage_cost_estimate_usd')) for s in paid_stages]
        result[condition] = {
            'attempts': len(part), 'status_counts': dict(Counter(r['status'] for r in part)),
            'json_structure_pass': sum(r.get('checks', {}).get('prediction_schema') is True for r in part),
            'evidence_reference_pass': sum(r.get('checks', {}).get('canonical_evidence') is True for r in part),
            'validated_final_output': sum(r.get('validated') is True for r in part),
            'complete_chain_and_output': sum(complete_chain(r) for r in part) if condition == 'cv_llm' else None,
            'latency_seconds_p50': median_seconds(r.get('latency_ms') for r in part),
            'decode_seconds_p50': median_seconds(r.get('preprocessing_decode_ms') for r in part),
            'stage_seconds_p50': {k: median_seconds(r.get('stages', {}).get(k, {}).get('latency_ms') for r in part)
                                  for k in sorted(stages)},
            'stage_statuses': {k: dict(Counter(r.get('stages', {}).get(k, {}).get('status', 'not_executed')
                                              for r in part)) for k in sorted(stages)},
            'over_120_seconds': sum(r.get('latency_ms') is not None and r['latency_ms'] > 120000 for r in part),
            'known_paid_usage_cost_estimate_usd': sum(v for v in costs if v is not None)
                if any(v is not None for v in costs) else None,
            'paid_requests_billing_unknown': sum(s.get('unknown_billing_requests',
                int(s.get('metadata', {}).get('usage_cost_estimate_usd') is None)) for s in paid_stages),
            'paid_requests_reserved_total': sum(s.get('paid_requests_reserved', 1) for s in paid_stages),
            'actual_invoice_cost_usd': None, 'semantic_accuracy': None,
        }
    return result


def labels(prediction):
    if not isinstance(prediction, dict):
        return None
    if 'assessments' in prediction:
        return {r['camera']: r['assessment'].get('event_type') for r in prediction['assessments']}
    return prediction.get('event_type')


def artifact_digest(root):
    rows = [[p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()]
            for p in root.rglob('*') if p.is_file()]
    rows.sort(key=lambda row: row[0])
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def cv_observation_projection(run, row):
    path = run/'raw'/f"{row['attempt_id']}-local_cv.json"
    if not path.is_file():
        return None
    outcome = json.loads(path.read_text(encoding='utf8'))
    features = outcome.get('features') or {}
    frames = features.get('frames')
    if not isinstance(frames, list):
        return None
    return [{'frame_index': f['frame_index'], 'camera': f['camera'],
             'timestamp_sec': f['timestamp_sec'],
             'detections': [{key: detection.get(key) for key in
                 ('bbox', 'confidence', 'class_id', 'class_name', 'track_id')}
                 for detection in f.get('detections', [])]}
            for f in frames]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, default=ROOT/'runs/baseline-final')
    parser.add_argument('--improved', type=Path, default=ROOT/'runs/improved-canonical64')
    parser.add_argument('--speed', type=Path, default=ROOT/'runs/improved-pose-off')
    parser.add_argument('--output', type=Path, default=ROOT/'runs/improvement-analysis')
    args = parser.parse_args()
    output = assert_output_outside_inputs(ROOT, args.output)
    output.mkdir(parents=True, exist_ok=True)
    inputs = {name: assert_output_outside_inputs(ROOT, p) for name, p in
              [('baseline', args.baseline), ('improved', args.improved), ('speed', args.speed)]}
    summaries = {name: json.loads((p/'summary.json').read_text(encoding='utf8')) for name, p in inputs.items()}
    rows = {name: s['attempts'] for name, s in summaries.items()}
    by_key = {name: {(r['item_id'], r['repeat'], r['condition']): r for r in part}
              for name, part in rows.items()}
    comparisons, speed_pairs = [], []
    for after in rows['improved']:
        before = by_key['baseline'].get((after['item_id'], after['repeat'], after['condition']))
        if before is None:
            continue
        comparisons.append({'item_id': after['item_id'], 'condition': after['condition'],
            'same_input_digest': before.get('input_digest') == after.get('input_digest'),
            'same_fingerprint': before.get('input_fingerprint') == after.get('input_fingerprint'),
            'baseline_validated': before['validated'], 'improved_validated': after['validated'],
            'baseline_latency_seconds': before['latency_ms']/1000 if before.get('latency_ms') is not None else None,
            'improved_latency_seconds': after['latency_ms']/1000 if after.get('latency_ms') is not None else None,
            'baseline_provider_labels': labels(before.get('prediction')),
            'improved_provider_labels': labels(after.get('prediction')),
            'label_difference_is_not_ground_truth_error': True})
    for after in rows['speed']:
        before = by_key['improved'].get((after['item_id'], after['repeat'], after['condition']))
        if before is None:
            continue
        cv_before = before.get('stages', {}).get('local_cv', {}).get('latency_ms')
        cv_after = after.get('stages', {}).get('local_cv', {}).get('latency_ms')
        observations_before = cv_observation_projection(inputs['improved'], before)
        observations_after = cv_observation_projection(inputs['speed'], after)
        speed_pairs.append({'item_id': after['item_id'],
            'same_input_digest': before.get('input_digest') == after.get('input_digest'),
            'pose_always_cv_seconds': cv_before/1000 if cv_before is not None else None,
            'pose_off_cv_seconds': cv_after/1000 if cv_after is not None else None,
            'cv_reduction_fraction': 1-cv_after/cv_before if cv_before and cv_after is not None else None,
            'pose_always_total_seconds': before['latency_ms']/1000 if before.get('latency_ms') is not None else None,
            'pose_off_total_seconds': after['latency_ms']/1000 if after.get('latency_ms') is not None else None,
            'pose_always_chain_pass': complete_chain(before), 'pose_off_chain_pass': complete_chain(after),
            'same_detection_and_track_observations': observations_before == observations_after
                if observations_before is not None and observations_after is not None else None,
            'semantic_non_regression': None})
    cv_full = [p['pose_always_cv_seconds'] for p in speed_pairs if p['pose_always_cv_seconds'] is not None]
    cv_fast = [p['pose_off_cv_seconds'] for p in speed_pairs if p['pose_off_cv_seconds'] is not None]
    reduction = 1-statistics.median(cv_fast)/statistics.median(cv_full) if cv_full and cv_fast else None
    successful_pairs = [p for p in speed_pairs if p['pose_always_chain_pass'] and p['pose_off_chain_pass']]
    successful_total_reduction = 1-statistics.median(p['pose_off_total_seconds'] for p in successful_pairs) / \
        statistics.median(p['pose_always_total_seconds'] for p in successful_pairs) if successful_pairs else None
    ledger = json.loads((ROOT/'runs/477-paid-budget.json').read_text(encoding='utf8'))
    requests = ledger['requests']
    original_snapshot = json.loads((ROOT/'runs/improvement-baseline-snapshot.json').read_text(encoding='utf8'))
    baseline_digest = artifact_digest(inputs['baseline'])
    result = {'scope': 'Small demonstration: baseline 3 repeats; new conditions 1 repeat; no semantic ground truth.',
        'baseline_artifact_digest': baseline_digest,
        'original_results_unchanged': baseline_digest == original_snapshot['digest'],
        'runs': {name: aggregate(part) for name, part in rows.items()},
        'protected_snapshots_match_each_run': {name: s['protected_inputs_unchanged'] for name, s in summaries.items()},
        'matched_first_repeat_comparisons': comparisons, 'speed_pairs': speed_pairs,
        'speed_cv_median_reduction_fraction': reduction,
        'speed_successful_full_chain_pairs': len(successful_pairs),
        'speed_successful_full_chain_total_median_reduction_fraction': successful_total_reduction,
        'predeclared_speed_target_20_percent_pass': reduction >= .20 if reduction is not None else None,
        'ledger': {'requests': len(requests), 'reserved_usd': sum(r['reserved_usd'] for r in requests),
                   'usage_cost_estimate_usd': sum(r['usage_cost_estimate_usd'] for r in requests)
                        if all(r['usage_cost_estimate_usd'] is not None for r in requests) else None,
                   'known_partial_usage_cost_estimate_usd': sum(r['usage_cost_estimate_usd'] for r in requests
                        if r['usage_cost_estimate_usd'] is not None)
                        if any(r['usage_cost_estimate_usd'] is not None for r in requests) else None,
                   'usage_unknown_requests': sum(r['usage_cost_estimate_usd'] is None for r in requests),
                   'actual_invoice_cost_usd': None},
        'limitations': ['GT and normal negatives absent: accuracy/misses/false alarms/evidence semantics N/A.',
                       'Pose-off loses pose measurements; no semantic non-regression claim.',
                       'Separate sequential requests can differ in caching/server load/output; one repetition is exploratory.',
                       'Input fingerprint covers original frames/prompt/schema, not changed transport instructions; transport metadata records them.']}
    (output/'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')
    for filename, records in [('paired-output.csv', comparisons), ('pose-speed.csv', speed_pairs)]:
        if records:
            with (output/filename).open('w', newline='', encoding='utf8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    if speed_pairs:
        fig, ax = plt.subplots(figsize=(8, 4))
        x = list(range(len(speed_pairs)))
        ax.bar([i-.18 for i in x], [p['pose_always_total_seconds'] or 0 for p in speed_pairs], .36, label='Pose always')
        fast_bars = ax.bar([i+.18 for i in x], [p['pose_off_total_seconds'] if p['pose_off_total_seconds'] is not None
                          else float('nan') for p in speed_pairs], .36, label='Pose off (extra experiment)')
        for i, p in enumerate(speed_pairs):
            if not p['pose_off_chain_pass']:
                fast_bars[i].set_hatch('//')
                if p['pose_off_total_seconds'] is not None:
                    ax.text(i+.18, p['pose_off_total_seconds']+1, 'Clef error fallback', ha='center', fontsize=8)
        ax.set_xticks(x, [p['item_id'] for p in speed_pairs])
        ax.set_ylabel('Whole pipeline seconds')
        ax.set_title('Same 64 frames; one run per condition; event accuracy unmeasured')
        ax.legend()
        fig.tight_layout()
        fig.savefig(output/'pipeline-speed.png', dpi=160)
        plt.close(fig)
    print(json.dumps({'output': str(output), 'speed_cv_reduction': reduction,
                      'ledger': result['ledger'], 'runs': result['runs']}))


if __name__ == '__main__':
    main()
