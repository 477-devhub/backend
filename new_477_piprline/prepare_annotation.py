"""Prepare existing fixed frames for offline candidate annotation and visual review."""
from pathlib import Path
import argparse
import json
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["prepare", "overlay", "zoom"], default="prepare")
    args = parser.parse_args()
    output = HERE / "ground_truth" / "ai_review_v1"
    output.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare":
        frames = []
        for number in range(1, 7):
            item = f"P{number:03d}"
            data = json.loads((HERE / "data/frames" / item / "manifest.json").read_text(encoding="utf-8"))
            for index in (0, 21, 42, 63):
                frame = dict(data["frames"][index])
                frame["image_path"] = str(HERE / frame["image_path"])
                frames.append(frame)
            # All 64 chronological thumbnails, solely for annotation review.
            rows = []
            for start in range(0, 64, 4):
                tiles = []
                for frame in data["frames"][start:start + 4]:
                    image = cv2.imread(str(HERE / frame["image_path"]))
                    tile = np.full((224, 384, 3), 255, dtype=np.uint8)
                    tile[:216] = cv2.resize(image, (384, 216))
                    label = f"F{frame['frame_number']} t={frame['timestamp_sec']:.2f}"
                    cv2.putText(tile, label, (3, 223), cv2.FONT_HERSHEY_SIMPLEX, .32, (0, 0, 0), 1)
                    tiles.append(tile)
                rows.append(np.concatenate(tiles, axis=1))
            cv2.imwrite(str(output / f"SRC{number:02d}_sequence.jpg"), np.concatenate(rows, axis=0))
        (output / "candidate_frames.json").write_text(json.dumps(frames, indent=2), encoding="utf-8")
        print(json.dumps({"selected_frames": len(frames), "sequence_sheets": 6, "paid_calls": 0}))
    elif args.mode == "zoom":
        regions = {1: (0, 200, 1500, 950), 2: (400, 250, 1500, 1000),
                   3: (0, 200, 1200, 1000), 4: (1050, 300, 1920, 950),
                   5: (0, 100, 1450, 1080), 6: (250, 150, 1850, 1080)}
        for number in range(1, 7):
            data = json.loads((HERE / "data/frames" / f"P{number:03d}" / "manifest.json").read_text(encoding="utf-8"))
            tiles = []
            x1, y1, x2, y2 = regions[number]
            for index in list(range(0, 60, 4)) + [63]:
                frame = data["frames"][index]
                image = cv2.imread(str(HERE / frame["image_path"]))[y1:y2, x1:x2]
                tile = np.full((344, 480, 3), 255, dtype=np.uint8)
                tile[:320] = cv2.resize(image, (480, 320))
                cv2.putText(tile, f"{frame['frame_id']} {frame['timestamp_sec']:.2f}s", (4, 339),
                            cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
                tiles.append(tile)
            rows = [np.concatenate(tiles[i:i+4], axis=1) for i in range(0, 16, 4)]
            cv2.imwrite(str(output / f"SRC{number:02d}_zoom.jpg"), np.concatenate(rows, axis=0))
        print(json.dumps({"annotation_only_zoom_sheets": 6, "inference_input_changed": False}))
    else:
        candidates = json.loads((output / "rtdetr_candidates.json").read_text(encoding="utf-8"))
        # Candidate keys follow the independently implemented detector artifact.
        for frame in candidates["frames"]:
            image = cv2.imread(frame["image_path"])
            for index, obj in enumerate(frame["detections"]):
                if obj["confidence"] < .35:
                    continue  # Display filter only; raw candidates retain all predictions.
                box = obj.get("bbox_xyxy", obj.get("bbox"))
                x1, y1, x2, y2 = [int(round(v)) for v in box]
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 80, 255), 2)
                cv2.putText(image, f"{index}:{obj['class_name']} {obj['confidence']:.2f}",
                            (x1, max(18, y1)), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 30, 255), 2)
            cv2.imwrite(str(output / (frame["frame_id"] + "_boxes.jpg")), image)
        print(json.dumps({"overlay_frames": len(candidates["frames"]), "paid_calls": 0}))


if __name__ == "__main__":
    main()
