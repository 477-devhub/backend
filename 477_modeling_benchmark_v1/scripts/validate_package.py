"""Validate the portable public input contract and actual RGB frame stream."""
import sys
sys.dont_write_bytecode = True
import ast
import hashlib
import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path
from jsonschema import Draft202012Validator
from benchmark_common import read, sha, probe
from load_model_input import load_item, iter_model_frames
from validate_prediction import schemas

ROOT = Path(__file__).resolve().parents[1]
VERSION = '477-reasoning-v1'
PROTOCOL = 'uniform_total64_v1'
MEDIA = {f'media/asset_{i:02d}.mp4' for i in range(1, 7)}
REQUIRED = MEDIA | {
    'README.md', 'QUICKSTART.md', 'PIPELINE_ASSIGNMENT.md', 'public_manifest.json',
    'model_input/scenarios.json', 'model_input/prompt_v1.txt',
    'schemas/prediction.schema.json', 'schemas/result.schema.json',
    'scripts/load_model_input.py', 'scripts/validate_prediction.py',
    'scripts/benchmark_common.py', 'scripts/validate_package.py', 'scripts/inspect_item.py',
    'docs/INPUT_PROTOCOL.md', 'docs/OUTPUT_PROTOCOL.md', 'docs/EXPERIMENT_RULES.md',
    'submissions/README.md',
}
SUBMISSION_DIRS = {'p0_cv_only', 'p1_clef_flash', 'p2_jev', 'p3_clef', 'p4_strong_vlm'}

# Assemble audit terms without planting those exact hints into public source text.
TEXT_TERMS = [('sw', 'oon'), ('tres', 'pass'), ('fi', 'ght'), ('S', '14'),
              ('T', '03'), ('T', '06'), ('F', '01'), ('MV', '05'), ('fall', 'down'),
              ('climb', 'wall'), ('pun', 'ching'), ('private_', 'ground_truth'),
              ('AI Hub ', 'ground truth'), ('expected ', 'ranking')]
PATH_TERMS = [('private_', 'ground_truth'), ('candidate_', 'report'),
              ('contact_', 'sheet'), ('annot', 'ation'), ('BENCHMARK_', 'LOCK'),
              ('score_', 'results.py')]

def require(condition, message):
    if not condition:
        raise ValueError(message)

def local_path(relative):
    p = ROOT / relative
    require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,
            'Unsafe package-relative path')
    require(p.resolve().is_relative_to(ROOT), 'Path escapes package')
    require(p.is_file() and not p.is_symlink(), 'Missing regular package file: ' + relative)
    return p

def leakage_audit(paths):
    for p in paths:
        rel = p.relative_to(ROOT).as_posix()
        lower = rel.lower()
        require(p.suffix.lower() != '.xml', 'Excluded file type found')
        require(not any(''.join(t).lower() in lower for t in PATH_TERMS), 'Excluded path found')
        if p.suffix == '.mp4':
            continue
        text = p.read_text(encoding='utf-8-sig')
        for pieces in TEXT_TERMS:
            token = ''.join(pieces)
            pattern = (r'(?<![A-Za-z0-9])' + re.escape(token) + r'(?![A-Za-z0-9])'
                       if len(token) <= 4 else re.escape(token))
            require(re.search(pattern, text, re.I) is None, 'Public text leakage in ' + rel)

def check():
    require(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe must be on PATH')
    lock = read(ROOT / 'PACKAGE_LOCK.json')
    require(set(lock) == {'package', 'source_benchmark', 'input_protocol', 'files'}, 'Unexpected lock keys')
    require(lock['package'] == '477-modeling-benchmark-v1' and lock['source_benchmark'] == VERSION
            and lock['input_protocol'] == PROTOCOL, 'Package identity mismatch')
    require(set(lock['files']) == REQUIRED, 'Locked file set mismatch')
    for relative, entry in lock['files'].items():
        require(set(entry) == {'sha256', 'size_bytes'}, 'Unexpected file lock fields')
        p = local_path(relative)
        require(p.stat().st_size == entry['size_bytes'] and sha(p) == entry['sha256'],
                'Package hash/size mismatch: ' + relative)
    # Generated result/code files under assignment directories are user work, not package input.
    immutable = []
    for p in ROOT.rglob('*'):
        require(not p.is_symlink(), 'Package must not contain symbolic links')
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith('submissions/') and rel != 'submissions/README.md':
            require(rel.split('/')[1] in SUBMISSION_DIRS, 'Unknown submission directory')
            continue
        # Frozen copied CLI imports can create harmless bytecode unless launched with -B.
        if '__pycache__' in p.parts and p.suffix == '.pyc':
            continue
        require(rel in REQUIRED | {'PACKAGE_LOCK.json'}, 'Unexpected public package file: ' + rel)
        immutable.append(p)
    require({p.relative_to(ROOT).as_posix() for p in (ROOT/'media').iterdir()} == MEDIA,
            'Exactly six opaque media files required')
    require(all((ROOT/'submissions'/d).is_dir() for d in SUBMISSION_DIRS), 'Missing submission directory')
    leakage_audit(immutable)

    public = read(ROOT/'public_manifest.json')
    require(set(public) == {'benchmark_version', 'media'} and public['benchmark_version'] == VERSION,
            'Public manifest structure/version mismatch')
    require(set(public['media']) == {f'ASSET_{i:02d}' for i in range(1, 7)}, 'Public asset IDs mismatch')
    for i in range(1, 7):
        meta = public['media'][f'ASSET_{i:02d}']
        require(set(meta) == {'path', 'sha256', 'duration', 'fps', 'width', 'height', 'frame_count'},
                'Unexpected asset metadata')
        require(meta['path'] == f'media/asset_{i:02d}.mp4', 'Non-opaque media locator')
        require(meta['sha256'] == lock['files'][meta['path']]['sha256'], 'Media manifest hash mismatch')
        actual = probe(local_path(meta['path']))
        require(actual['width'] == meta['width'] == 1920 and actual['height'] == meta['height'] == 1080,
                'Media dimensions mismatch')
        require(actual['frame_count'] == meta['frame_count'] and abs(actual['fps'] - meta['fps']) < .001
                and meta['fps'] == 30 and abs(actual['duration'] - meta['duration']) < .01,
                'Media timing metadata mismatch')

    scenarios = read(ROOT/'model_input/scenarios.json')
    require(set(scenarios) == {'benchmark_version', 'protocol', 'items'}
            and scenarios['benchmark_version'] == VERSION, 'Scenario structure/version mismatch')
    protocol = scenarios['protocol']
    require(protocol['id'] == PROTOCOL and protocol['total_frames_per_item'] == 64
            and protocol['image_size'] == [1920,1080], 'Input protocol mismatch')
    items = scenarios['items']
    require([i['item_id'] for i in items] == [f'ITEM_{i:02d}' for i in range(1,8)], 'Seven ITEMs required')
    require([i['task'] for i in items] == ['single','single','single','attention','single','single','multi_camera'],
            'Task mapping mismatch')
    expected_cams = [['CAM_01'],['CAM_01'],['CAM_01'],['CAM_01','CAM_02','CAM_03'],
                     ['CAM_01'],['CAM_02'],['CAM_01','CAM_02']]
    expected_assets = [['ASSET_01'],['ASSET_02'],['ASSET_03'],['ASSET_01','ASSET_04','ASSET_02'],
                       ['ASSET_05'],['ASSET_06'],['ASSET_05','ASSET_06']]
    for index, definition in enumerate(items):
        require(set(definition) == {'item_id','task','cameras'}, 'Unexpected ITEM fields')
        require(all(set(c) == {'camera','asset'} for c in definition['cameras']), 'Unexpected camera fields')
        require([c['camera'] for c in definition['cameras']] == expected_cams[index]
                and [c['asset'] for c in definition['cameras']] == expected_assets[index], 'Camera mapping mismatch')

    prediction, result, registry = schemas()
    Draft202012Validator.check_schema(prediction)
    Draft202012Validator.check_schema(result)
    Draft202012Validator(result, registry=registry)
    source = (ROOT/'scripts/load_model_input.py').read_text(encoding='utf-8-sig')
    syntax = ast.parse(source)
    allowed = {'json','math','hashlib','sys','subprocess','pathlib','argparse'}
    for node in ast.walk(syntax):
        if isinstance(node,ast.Import):
            require(all(a.name in allowed for a in node.names), 'Unapproved loader import')
        elif isinstance(node,ast.ImportFrom):
            require(node.module in allowed, 'Unapproved loader import')

    for definition in items:
        item_id = definition['item_id']
        item = load_item(item_id)
        handles = item['media_handles_private_to_harness']
        allocation = [64] if len(handles)==1 else ([22,21,21] if len(handles)==3 else [32,32])
        require([len(h['frame_numbers']) for h in handles] == allocation, 'Frame allocation mismatch')
        require(item['prompt'] == (ROOT/'model_input/prompt_v1.txt').read_text(encoding='utf-8-sig'),
                'Prompt content mismatch')
        fp = item['input_fingerprint']
        require(fp['sampling_protocol_id'] == PROTOCOL and fp['prompt_sha256'] == sha(ROOT/'model_input/prompt_v1.txt')
                and fp['prediction_schema_sha256'] == sha(ROOT/'schemas/prediction.schema.json'), 'Fingerprint mismatch')
        expected = []
        for camera, h, count in zip(definition['cameras'], handles, allocation):
            meta = public['media'][camera['asset']]
            indices = [int(math.floor(j*(meta['frame_count']-1)/(count-1)+.5)) for j in range(count)]
            require(h['frame_numbers'] == fp['frame_numbers'][camera['camera']] == indices, 'Frame indices mismatch')
            require(fp['media_sha256'][camera['camera']] == meta['sha256'], 'Input media hash mismatch')
            require(h['upload_name'] == camera['camera']+'.mp4', 'Non-generic transport name')
            require(Path(h['local_path']).resolve() == local_path(meta['path']).resolve(), 'Broken media handle')
            require(h['frame_timestamps_sec'] == [n/30 for n in indices], 'Timestamp mismatch')
            expected.extend((camera['camera'], n/30) for n in indices)
        observed = Counter()
        count = 0
        for frame in iter_model_frames(item_id):
            require(count < 64, 'Too many decoded frames')
            camera, timestamp = expected[count]
            require(frame['camera'] == camera and abs(frame['timestamp_sec']-timestamp)<1e-9,
                    'Canonical camera/time sequence mismatch')
            require(frame['width']==1920 and frame['height']==1080 and len(frame['rgb24'])==1920*1080*3,
                    'Canonical RGB payload mismatch')
            observed[camera] += 1
            count += 1
        require(count == 64 and list(observed.values()) == allocation, 'Actual RGB frame count mismatch')
        print(item_id + ': 64 canonical RGB frames PASS', flush=True)
    return True

if __name__ == '__main__':
    try:
        check()
        print('PASS')
    except Exception as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
