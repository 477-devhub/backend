"""Print public input metadata, without media handles or predictions."""
import sys
sys.dont_write_bytecode = True
import argparse
from load_model_input import load_item

def inspect(item_id):
    item = load_item(item_id)
    frames = item['input_fingerprint']['frame_numbers']
    names = {'single': 'single_camera', 'attention': 'three_camera_attention', 'multi_camera': 'multi_camera'}
    branches = {'single': 'single assessment', 'attention': 'camera assessments and attention queue', 'multi_camera': 'multi-camera assessment'}
    print('Item: ' + item_id)
    print('Task type: ' + names[item['task']])
    print('Cameras: ' + ', '.join(frames))
    print('Total canonical frames: ' + str(sum(len(v) for v in frames.values())))
    print('Allocation: ' + ', '.join(f'{k}={len(v)}' for k, v in frames.items()))
    print('Prompt version: prompt_v1')
    print('Prediction schema: ' + branches[item['task']])

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('item_id', nargs='?', choices=[f'ITEM_{i:02d}' for i in range(1, 8)])
    p.add_argument('--all', action='store_true')
    args = p.parse_args()
    if bool(args.item_id) == args.all:
        p.error('Supply one ITEM ID or --all')
    for item_id in ([f'ITEM_{i:02d}' for i in range(1, 8)] if args.all else [args.item_id]):
        inspect(item_id)
