import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from app.eval.dataset import validate_manifest, load_input
from app.eval.metrics import summarize
from app.models.registry import ADAPTER_NAMES
from app.eval.pipeline import evaluate_input, load_resolver

async def run_batch(manifest, adapter_name, split, output, lock=None, run_config=None, allow_test=False,
                    *, asset_map=None, asset_root=None):
    if adapter_name.startswith("mock_"):raise ValueError("mock prohibited in dataset metrics")
    manifest=Path(manifest);rows=validate_manifest(manifest)
    digest=hashlib.sha256(manifest.read_bytes()).hexdigest()
    config_digest=None
    if split=="test":
        if not (allow_test and lock and run_config):raise ValueError("test requires --allow-test, --lock and --run-config")
        frozen=json.loads(Path(lock).read_text(encoding="utf-8"))
        config_digest=hashlib.sha256(Path(run_config).read_bytes()).hexdigest()
        if frozen["manifest_sha256"]!=digest or frozen["run_config_sha256"]!=config_digest:raise ValueError("frozen artifact changed")
        config=json.loads(Path(run_config).read_text(encoding="utf-8"))
        if adapter_name not in config["adapters"]:raise ValueError("adapter absent from frozen run config")
        timeout=config["timeout_sec"]
    else:timeout=5.0
    selected=[r for r in rows if r.split==split]
    if not selected:raise ValueError("no samples for requested split")
    resolver=load_resolver(asset_map,asset_root)
    asset_map_digest=hashlib.sha256(Path(asset_map).read_bytes()).hexdigest() if asset_map else None
    if split=='test':
        map_pinned=config.get('asset_map_sha256') is not None
        preprocessing_pinned=config.get('preprocessing_version') is not None
        if map_pinned!=preprocessing_pinned:
            raise ValueError('asset map and preprocessing version must be frozen together')
        if map_pinned:
            if resolver is None:
                raise ValueError('asset map is required by frozen preprocessing mode')
            if config['asset_map_sha256']!=asset_map_digest:
                raise ValueError('asset map changed from frozen run config')
            if config['preprocessing_version']!='ffmpeg-fixed-grid-v1':
                raise ValueError('preprocessing version does not match fixed sampler')
        elif resolver is not None:
            raise ValueError('asset map cannot be added to frozen supplied-input mode')
    output=Path(output)
    if output.exists():raise ValueError("output exists; choose a new run directory")
    output.mkdir(parents=True)
    records=[]
    with (output/'predictions.jsonl').open('w',encoding='utf-8') as f:
        for row in selected:
            mi=load_input(row,manifest.parent)
            data=await evaluate_input(adapter_name,mi,timeout,resolver=resolver,
                expected_media_sha256=row.media_sha256)
            data.update({"split":split,"asset_map_sha256":asset_map_digest,
                "manifest_sha256":digest,"run_config_sha256":config_digest,
                "ground_truth":{"event_type":row.event_type,"critical":row.critical,
                    "needs_human_review":row.needs_human_review,"risk_axes":row.risk_axes.model_dump() if row.risk_axes else None}})
            # Labels are added only after inference returns; never passed to adapter.
            records.append(data);f.write(json.dumps(data,ensure_ascii=False)+'\n');f.flush()
    metrics=summarize(records)
    (output/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    return metrics
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--adapter',choices=ADAPTER_NAMES,required=True)
    p.add_argument('--split',choices=['validation','test'],default='validation');p.add_argument('--output',required=True)
    p.add_argument('--lock');p.add_argument('--run-config');p.add_argument('--allow-test',action='store_true')
    p.add_argument('--asset-map');p.add_argument('--asset-root')
    a=p.parse_args();m=asyncio.run(run_batch(a.manifest,a.adapter,a.split,a.output,a.lock,a.run_config,a.allow_test,
        asset_map=a.asset_map,asset_root=a.asset_root))
    print(json.dumps(m,indent=2));raise SystemExit(2 if m['error_rate'] else 0)
