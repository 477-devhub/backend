"""Materialize explicit MAIN visual decisions; never auto-accept model proposals."""
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from pipeline477.metrics import validate_ground_truth

HERE = Path(__file__).resolve().parent
REVIEW = HERE / "ground_truth/ai_review_v1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    candidates = read(REVIEW / "rtdetr_candidates.json")
    decisions = read(REVIEW / "box_review_decisions.json")
    events = read(REVIEW / "visual_event_review.json")
    truth = read(HERE / "ground_truth/sources.json")
    if candidates["inference_kind"] != "local_rtdetr" or candidates["reviewed"]:
        raise ValueError("Real unpromoted independent candidates required")
    mapping = {f["frame_id"]: f for f in candidates["frames"]}
    if set(mapping) != set(decisions["frames"]):
        raise ValueError("Every candidate frame needs an explicit review decision")
    for sid, source in truth.items():
        event = events["sources"][sid]
        source.update(reviewer=events["reviewer"], reviewed_at=events["reviewed_at"],
                      reference_quality=events["quality"], revision=events["revision"])
        source["clef"] = {"invoke_vlm": event["invoke_vlm"], "reviewed": True,
                          "rationale": event["routing_rationale"], "policy": events["routing_policy"]}
        source["vlm"].update(label=event["label"], reviewed=True,
                             observation=event["observations"],
                             support_frame_interval=event["support_frame_interval"],
                             support_interval_precision="coarse_visual_support_not_exact_boundary",
                             review_artifacts=event["review_artifacts"])
        source["yolo"].update(frames=[], class_scope=decisions["class_scope"][sid],
                              note="AI visual-reviewed sparse reference. Complete means exhaustive only within declared class scope; partial frames unscored.")
    for fid, decision in decisions["frames"].items():
        frame = mapping[fid]
        objects = []
        for index in decision["accept"]:
            candidate = frame["detections"][index]
            box = decision.get("replace", {}).get(str(index), candidate["bbox_xyxy"])
            box = [int(round(x)) for x in box]
            if candidate["class_name"] not in decisions["class_scope"][frame["source_id"]]:
                raise ValueError("Accepted object outside declared class scope")
            objects.append({"class_name": candidate["class_name"], "bbox": box,
                            "candidate_index": index,
                            "review_action": "corrected" if str(index) in decision.get("replace", {}) else "visually_accepted"})
        objects.extend({**obj, "review_action": "manual_addition"} for obj in decision.get("add", []))
        truth[frame["source_id"]]["yolo"]["frames"].append({
            "frame_number": frame["frame_number"], "frame_id": fid,
            "timestamp_sec": frame["timestamp_sec"], "sha256": frame["sha256"],
            "complete": decision["complete"], "objects": objects, "review_note": decision["note"]})
    Draft202012Validator(read(HERE / "schemas/ground_truth.schema.json")).validate(truth)
    validation = validate_ground_truth(truth, read(HERE / "data/sources.json"))
    if not validation["valid"]:
        raise ValueError(validation)
    payload = (json.dumps(truth, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path = REVIEW / "sources.json"
    path.write_bytes(payload)
    lock_paths = [path, REVIEW / "box_review_decisions.json", REVIEW / "visual_event_review.json", REVIEW / "rtdetr_candidates.json"]
    lock = {str(p.relative_to(HERE)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in lock_paths}
    (REVIEW / "ground_truth.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sources": len(truth), "reviewed_frames": len(mapping),
                      "complete_frames": sum(d["complete"] for d in decisions["frames"].values()),
                      "objects": sum(len(f["objects"]) for s in truth.values() for f in s["yolo"]["frames"]),
                      "quality": events["quality"], "sha256": lock[str(path.relative_to(HERE)).replace("\\", "/")]}))


if __name__ == "__main__":
    main()
