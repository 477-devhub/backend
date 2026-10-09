import argparse
import asyncio
import json
from pathlib import Path
from app.models.registry import ADAPTER_NAMES
from app.schemas.model import ModelInput
from app.eval.pipeline import evaluate_input, load_resolver

async def run(adapter_name, path, timeout_sec=5, output=None, *, asset_map=None, asset_root=None):
    mi=ModelInput.model_validate_json(Path(path).read_text(encoding="utf-8"))
    item=await evaluate_input(adapter_name,mi,timeout_sec,
        resolver=load_resolver(asset_map,asset_root))
    item['error']=item['prediction']['metadata']['error_code']
    if output:
        p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(item,ensure_ascii=False)+"\n",encoding="utf-8")
    else: print(json.dumps(item,ensure_ascii=False))
    return item

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--adapter",choices=ADAPTER_NAMES,required=True);p.add_argument("--input",required=True)
    p.add_argument("--timeout-sec",type=float,default=5);p.add_argument("--output")
    p.add_argument('--asset-map');p.add_argument('--asset-root')
    a=p.parse_args();item=asyncio.run(run(a.adapter,a.input,a.timeout_sec,a.output,asset_map=a.asset_map,asset_root=a.asset_root))
    raise SystemExit(2 if item["error"] else 0)
