"""Analyze saved real attempts without changing inputs, predictions or thresholds."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.models.benchmark_media import assert_output_outside_inputs


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    offset = (len(values)-1)*fraction
    lo = int(offset)
    hi = min(lo+1, len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(offset-lo)


def median_seconds(values):
    values = list(values)
    return statistics.median(values)/1000 if values else None


def event_labels(prediction):
    if not isinstance(prediction, dict):
        return None
    if 'assessments' in prediction:
        return {row['camera']: row['assessment'].get('event_type')
            for row in prediction['assessments']}
    return prediction.get('event_type')


def observations(prediction):
    if not isinstance(prediction, dict):
        return []
    if 'assessments' in prediction:
        return [obs for row in prediction['assessments']
            for obs in row['assessment'].get('observations', [])]
    result = list(prediction.get('observations', []))
    result.extend(obs for rows in prediction.get('camera_evidence', {}).values() for obs in rows)
    return result


def track_observations_count(track):
    value = track.get('observations', track.get('evidence_frame_keys', []))
    return value if isinstance(value, int) else len(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, default=ROOT/'runs/baseline-final')
    args = parser.parse_args()
    run = assert_output_outside_inputs(ROOT, args.run)
    records = [json.loads(p.read_text(encoding='utf8'))
        for p in sorted((run/'diagnostics').glob('*.json'))]
    aggregate, examples, cv_quality, raw_labels = {}, [], [], []
    for condition in sorted({r['condition'] for r in records}):
        rows = [r for r in records if r['condition'] == condition]
        times = [r['latency_ms'] for r in rows if r.get('latency_ms') is not None]
        aggregate[condition] = {'attempts': len(rows),
            'status_counts': dict(Counter(r['status'] for r in rows)),
            'prediction_schema_pass': sum(r['checks']['prediction_schema'] for r in rows),
            'canonical_evidence_pass': sum(r['checks']['canonical_evidence'] for r in rows),
            'validated': sum(r['validated'] for r in rows),
            'latency_seconds_p50': percentile(times, .5)/1000 if times else None,
            'latency_seconds_p95': percentile(times, .95)/1000 if times else None,
            'decode_seconds_p50': median_seconds(r['preprocessing_decode_ms'] for r in rows
                if r.get('preprocessing_decode_ms') is not None),
            'stage_latency_seconds_p50': {name: statistics.median(
                r['stages'][name]['latency_ms'] for r in rows
                if r.get('stages', {}).get(name, {}).get('latency_ms') is not None)/1000
                for name in sorted({name for r in rows for name in r.get('stages', {})})
                if any(r.get('stages', {}).get(name, {}).get('latency_ms') is not None for r in rows)},
            'over_120_seconds': sum(t > 120000 for t in times)}
    for row in records:
        for name in row.get('stages', {}):
            path = run/'raw'/f"{row['attempt_id']}-{name}.json"
            outcome = json.loads(path.read_text(encoding='utf8'))
            if name == 'local_cv' and outcome.get('features'):
                features = outcome['features']
                tracks = features.get('tracks', [])
                cv_quality.append({'attempt_id': row['attempt_id'],
                    'quality': features.get('quality'), 'track_count': len(tracks),
                    'short_track_count': sum(track_observations_count(t) <= 1 for t in tracks),
                    'dwell_candidate_count': sum(t.get('person_dwell_candidate', False) for t in tracks),
                    'low_posture_candidate_count': sum(t.get('sustained_low_posture_candidate', False) for t in tracks),
                    'memory': outcome['metadata'].get('memory')})
            if name != 'general_vlm':
                continue
            prediction = outcome.get('prediction')
            raw_labels.append({'item_id': row['item_id'], 'repeat': row['repeat'],
                'condition': row['condition'], 'provider_labels': event_labels(prediction),
                'validated': row['validated'], 'status': row['status']})
            images = outcome.get('metadata', {}).get('images', [])
            for obs in observations(prediction):
                if not isinstance(obs.get('timestamp_sec'), (int, float)):
                    continue
                candidates = [i for i in images if i['camera'] == obs.get('camera')]
                if not candidates:
                    continue
                closest = min(candidates, key=lambda i: abs(i['timestamp_sec']-obs['timestamp_sec']))
                distance = abs(closest['timestamp_sec']-obs['timestamp_sec'])
                if distance > 1/30+1e-9:
                    examples.append({'attempt_id': row['attempt_id'],
                        'camera': obs['camera'], 'provider_timestamp_sec': obs['timestamp_sec'],
                        'closest_input_timestamp_sec': closest['timestamp_sec'],
                        'closest_input_frame_index': closest['frame_index'],
                        'distance_sec': distance, 'provider_observation': obs.get('description'),
                        'failure': 'VLM output references a time outside selected-input tolerance'})
    analysis = {'conditions': aggregate, 'canonical_evidence_failures': examples,
        'cv_quality_proxies_not_accuracy': cv_quality, 'raw_provider_labels_not_ground_truth': raw_labels,
        'event_accuracy': None, 'false_alarm_rate': None, 'event_miss_rate': None,
        'semantic_evidence_correctness': None,
        'limitation': 'Seven demo ITEMs reuse six clips; labels/normal references are absent.'}
    (run/'analysis.json').write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf8')
    with (run/'raw-label-comparison.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['item_id','repeat','condition','provider_labels','validated','status'])
        writer.writeheader()
        writer.writerows(raw_labels)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axis = plt.subplots(figsize=(9,5))
    for condition, label in [('vlm_only','VLM only'),('cv_llm','CV + Clef + VLM')]:
        points = [r for r in records if r['condition'] == condition and r.get('latency_ms') is not None]
        axis.scatter([int(r['item_id'][-2:]) for r in points],
            [r['latency_ms']/1000 for r in points], label=label, alpha=.7)
    axis.axhline(120, color='red', linestyle='--', label='Predeclared 120 s demo target')
    axis.set(xlabel='Demo ITEM (6 unique clips)', ylabel='End-to-end seconds', xticks=range(1,8))
    axis.legend()
    fig.tight_layout()
    fig.savefig(run/'latency.png', dpi=160)
    plt.close(fig)
    print(json.dumps({'attempts':len(records), 'conditions':aggregate,
        'canonical_evidence_failure_refs':len(examples), 'output':str(run/'analysis.json')}))


if __name__ == '__main__':
    main()
