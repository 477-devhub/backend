"""Portable, label-only evaluation for the frozen 64-frame pipeline benchmark.

This module deliberately imports no application schemas or provider SDKs. MAIN
copies this file into the handoff package. Pending references are never promoted
to reviewed truth, and incomplete box annotations are never treated as negatives.
"""
from __future__ import annotations

import math
from collections import defaultdict

LABELS = {
    "normal", "fall_ground_posture", "boundary_crossing",
    "gate_entry_authorization_unknown", "physical_conflict", "loitering", "uncertain",
}
SYNONYMS = {
    "collapse": "fall_ground_posture", "fall": "fall_ground_posture",
    "ground posture": "fall_ground_posture", "fight": "physical_conflict",
    "conflict": "physical_conflict", "boundary crossing": "boundary_crossing",
    "gate entry": "gate_entry_authorization_unknown",
}
CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
AXES = {"severity", "imminence", "exposure", "persistence"}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _unit(value):
    return _number(value) and 0 <= value <= 1


def _box_valid(box, width=None, height=None):
    if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(map(_number, box)):
        return False
    x1, y1, x2, y2 = box
    return (0 <= x1 < x2 and 0 <= y1 < y2
            and (width is None or x2 <= width) and (height is None or y2 <= height))


def _source_metadata(metadata):
    if isinstance(metadata, dict):
        return metadata
    return {entry["source_id"]: entry for entry in metadata}


def validate_ground_truth(ground_truth_by_source, source_metadata):
    """Return structural errors and pending review; never fill missing labels.

    ``complete`` means exhaustive annotation within the declared ``class_scope``
    (the frozen six classes by default). Metadata must identify genuine sources;
    absent dimensions prevent a bounds check and remain a review requirement.
    """
    metadata = _source_metadata(source_metadata)
    errors, pending = [], []
    if not isinstance(ground_truth_by_source, dict):
        return {"valid": False, "errors": ["ground_truth must be a source mapping"],
                "review_required": []}
    for source in metadata:
        if source not in ground_truth_by_source:
            pending.append(f"{source}: ground truth absent")
    for source, truth in ground_truth_by_source.items():
        if source not in metadata:
            errors.append(f"{source}: unknown ground-truth source")
            continue
        if not isinstance(truth, dict):
            errors.append(f"{source}: source truth must be an object")
            continue
        meta = metadata[source]
        width, height = meta.get("width"), meta.get("height")
        if not (_number(width) and width > 0 and _number(height) and height > 0):
            width = height = None
            pending.append(f"{source}: dimensions unavailable for box bounds checking")
        yolo = truth.get("yolo") or {}
        if not isinstance(yolo, dict):
            errors.append(f"{source}: yolo truth must be an object")
            yolo = {}
        scope = yolo.get("class_scope", sorted(CLASSES))
        if not isinstance(scope, list) or not scope or not all(isinstance(c, str) and c in CLASSES for c in scope) or len(scope) != len(set(scope)):
            errors.append(f"{source}: invalid yolo class_scope")
            scope = []
        frames = yolo.get("frames", [])
        if not isinstance(frames, list):
            errors.append(f"{source}: yolo frames must be a list")
            frames = []
        seen = set()
        for frame in frames:
            if not isinstance(frame, dict):
                errors.append(f"{source}: annotation frame must be an object")
                continue
            number = frame.get("frame_number")
            if type(number) is not int or number < 0 or number in seen:
                errors.append(f"{source}: invalid/duplicate annotation frame_number")
            else:
                seen.add(number)
                if type(meta.get("frame_count")) is int and number >= meta["frame_count"]:
                    errors.append(f"{source}: annotation frame outside video")
            if type(frame.get("complete")) is not bool:
                errors.append(f"{source}: annotation complete must be boolean")
            objects = frame.get("objects")
            if not isinstance(objects, list):
                errors.append(f"{source}: annotation objects must be a list")
                continue
            for obj in objects:
                if not isinstance(obj, dict) or not isinstance(obj.get("class_name"), str) or obj.get("class_name") not in scope:
                    errors.append(f"{source}: annotation object outside class scope")
                elif not _box_valid(obj.get("bbox"), width, height):
                    errors.append(f"{source}: invalid/out-of-bounds annotation bbox")
        if not frames:
            pending.append(f"{source}: no object annotations")
        for stage, field in (("clef", "invoke_vlm"), ("vlm", "label")):
            entry = truth.get(stage) or {}
            if not isinstance(entry, dict):
                errors.append(f"{source}: {stage} truth must be an object")
                entry = {}
            if type(entry.get("reviewed", False)) is not bool:
                errors.append(f"{source}: {stage}.reviewed must be boolean")
            reviewed = entry.get("reviewed") is True
            value = entry.get(field)
            if stage == "clef":
                if value is not None and type(value) is not bool:
                    errors.append(f"{source}: clef invoke_vlm must be boolean or null")
                if reviewed and type(value) is not bool:
                    errors.append(f"{source}: reviewed clef truth needs a decision")
                if reviewed and not isinstance(entry.get("rationale"), str):
                    errors.append(f"{source}: reviewed clef truth needs routing rationale")
            else:
                if value is not None and (not isinstance(value, str) or value not in LABELS):
                    errors.append(f"{source}: invalid canonical VLM truth label")
                if reviewed and value is None:
                    errors.append(f"{source}: reviewed vlm truth needs a label")
            if not reviewed:
                pending.append(f"{source}: {stage} semantic truth pending review")
    return {"valid": not errors, "errors": errors, "review_required": pending}


def _frames(model_input):
    rows = model_input.get("frames", [])
    sources = model_input.get("sources", [])
    if len(rows) != 64 or len({f.get("frame_id") for f in rows}) != 64:
        raise ValueError("benchmark input requires 64 unique frame IDs")
    if len(sources) != len(set(sources)) or not 1 <= len(sources) <= 6:
        raise ValueError("benchmark input requires unique known sources")
    if set(f.get("source_id") for f in rows) != set(sources):
        raise ValueError("benchmark input has missing/unknown source mapping")
    mapping = {row["frame_id"]: row for row in rows}
    for source in sources:
        selected = [f for f in rows if f["source_id"] == source]
        numbers = [f.get("frame_number") for f in selected]
        if any(type(n) is not int or n < 0 for n in numbers) or numbers != sorted(set(numbers)):
            raise ValueError("benchmark input has invalid source frame order")
    active = model_input.get("active_sources", sources)
    if len(active) != len(set(active)) or not set(active) <= set(sources):
        raise ValueError("benchmark input has invalid active sources")
    return mapping


def _iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0.0


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _ap101(matches, total):
    if not total:
        return None
    points, tp = [], 0
    for index, matched in enumerate(matches, 1):
        tp += matched
        points.append((tp / total, tp / index))
    return sum(max((p for r, p in points if r >= threshold / 100), default=0.0)
               for threshold in range(101)) / 101


def detection_metrics(model_input, ground_truth_by_source, stage_record):
    """IoU .5 greedy matching, per-class 101-point AP on complete input frames.

    Missing predictions on an eligible frame are omissions, including execution
    failures. Classes outside that frame's annotated scope are not evaluated.
    """
    mapping = _frames(model_input)
    eligible, objects, scopes = {}, defaultdict(list), {}
    skipped_partial, noncanonical, absent = 0, 0, 0
    for source in model_input["sources"]:
        annotated = {f["frame_number"]: f for f in (ground_truth_by_source.get(source, {}).get("yolo") or {}).get("frames", [])}
        canonical = {f["frame_number"] for f in mapping.values() if f["source_id"] == source}
        noncanonical += len(set(annotated) - canonical)
        scope = set((ground_truth_by_source.get(source, {}).get("yolo") or {}).get("class_scope", CLASSES))
        for frame_id, frame in mapping.items():
            if frame["source_id"] != source:
                continue
            annotation = annotated.get(frame["frame_number"])
            if annotation is None:
                absent += 1
            elif annotation.get("complete") is not True:
                skipped_partial += 1
            else:
                eligible[frame_id] = frame
                scopes[frame_id] = scope
                for obj in annotation["objects"]:
                    objects[obj["class_name"]].append((frame_id, obj["bbox"]))
    errors, predictions, output_seen = [], defaultdict(list), set()
    output = stage_record.get("output")
    output_frames = output.get("frames", []) if isinstance(output, dict) else []
    if not isinstance(output_frames, list):
        errors.append("yolo output.frames must be a list")
        output_frames = []
    if stage_record.get("status") != "ok" and output is not None:
        errors.append("non-ok yolo stage contains an output")
        output_frames = []
    for result in output_frames:
        if not isinstance(result, dict):
            errors.append("yolo output frame must be an object")
            continue
        frame_id = result.get("frame_id")
        if not isinstance(frame_id, str):
            errors.append("invalid yolo frame_id type")
            continue
        frame = mapping.get(frame_id)
        if frame is None or result.get("source_id") != frame["source_id"] or frame_id in output_seen:
            errors.append("unknown/cross-source/duplicate yolo frame mapping")
            continue
        output_seen.add(frame_id)
        detections = result.get("detections")
        if not isinstance(detections, list):
            errors.append("yolo detections must be a list")
            continue
        for obj in detections:
            if not isinstance(obj, dict) or not isinstance(obj.get("class_name"), str) or obj.get("class_name") not in CLASSES or not _unit(obj.get("confidence")) or not _box_valid(obj.get("bbox"), frame.get("width"), frame.get("height")):
                errors.append("invalid yolo detection")
                continue
            if frame_id in eligible and obj["class_name"] in scopes[frame_id]:
                predictions[obj["class_name"]].append((obj["confidence"], frame_id, obj["bbox"]))
    per_class = {}
    tp_total = fp_total = fn_total = 0
    for class_name in sorted(set(objects) | set(predictions) | set().union(*scopes.values()) if scopes else set()):
        truth = objects[class_name]
        taken, matches = set(), []
        for _, frame_id, box in sorted(predictions[class_name], key=lambda p: -p[0]):
            candidates = [(_iou(box, gt_box), index) for index, (gt_frame, gt_box) in enumerate(truth)
                          if gt_frame == frame_id and index not in taken]
            overlap, index = max(candidates, default=(0.0, -1))
            matched = overlap >= .5
            if matched:
                taken.add(index)
            matches.append(int(matched))
        tp = sum(matches)
        fp, fn = len(matches) - tp, len(truth) - tp
        tp_total += tp
        fp_total += fp
        fn_total += fn
        per_class[class_name] = {"object_count": len(truth), "prediction_count": len(matches),
                                 "true_positives": tp, "false_positives": fp, "false_negatives": fn,
                                 "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
                                 "ap50": _ap101(matches, len(truth))}
    aps = [entry["ap50"] for entry in per_class.values() if entry["ap50"] is not None]
    available = bool(eligible)
    return {"evaluated_frame_count": len(eligible), "evaluated_object_count": sum(map(len, objects.values())),
            "unannotated_frame_count": absent, "partial_annotation_frame_count": skipped_partial,
            "noncanonical_annotation_frame_count": noncanonical,
            "missing_prediction_frame_count": len(set(eligible) - output_seen),
            "true_positives": tp_total if available else None,
            "false_positives": fp_total if available else None,
            "false_negatives": fn_total if available else None,
            "precision": _ratio(tp_total, tp_total + fp_total),
            "recall": _ratio(tp_total, tp_total + fn_total),
            "map50": sum(aps) / len(aps) if aps else None, "per_class": per_class,
            "output_mapping_valid": not errors if stage_record.get("status") == "ok" else None,
            "output_errors": errors, "stage_status": stage_record.get("status"),
            "event_classification_accuracy": None}


def _canonical_label(value):
    return SYNONYMS.get(value, value) if isinstance(value, str) else None


def _assessment_valid(entry):
    fields = {"source_id", "event_type", "event_confidence", "risk_axes", "evidence_refs",
              "needs_human_review", "uncertainty_reason"}
    if not isinstance(entry, dict) or set(entry) != fields:
        return False
    axes, refs = entry["risk_axes"], entry["evidence_refs"]
    return (isinstance(entry["source_id"], str) and entry["source_id"] in {f"SRC0{i}" for i in range(1, 7)}
            and isinstance(entry["event_type"], str) and entry["event_type"] in LABELS and _unit(entry["event_confidence"])
            and isinstance(axes, dict) and set(axes) == AXES
            and all(value is None or _unit(value) for value in axes.values())
            and isinstance(refs, list) and all(isinstance(ref, str) for ref in refs)
            and len(refs) == len(set(refs)) and type(entry["needs_human_review"]) is bool
            and (entry["uncertainty_reason"] is None or isinstance(entry["uncertainty_reason"], str)))


def _omission_cause(source, source_status, routing, active, attempted):
    """Name the observed failed path without attributing a non-call to VLM."""
    if source in attempted:
        return "vlm_execution_error" if source_status != "ok" else "missing_model_output"
    if source_status == "blocked":
        return "execution_blocked"
    if source_status == "error":
        return "execution_unavailable"
    if routing["actual_invoke_vlm"] is False:
        return "routing_false_negative" if routing["expected_invoke_vlm"] is True else "route_skipped"
    if routing["actual_invoke_vlm"] is None:
        return "routing_unavailable"
    return "execution_unavailable"


def evaluate_item(model_input, ground_truth_by_source, stage_records):
    """Evaluate a whole item, preserving failures and per-source denominators.

    A stage can declare ``active_sources`` (the sources actually requested). For
    VLM these default to model_input.active_sources. Pipeline recall/accuracy
    covers all reviewed sources, while conditional VLM accuracy covers attempted
    sources only. The caller retains raw responses and execution errors.
    """
    frames = _frames(model_input)
    metadata = {source: next(f for f in frames.values() if f["source_id"] == source)
                for source in model_input["sources"]}
    validation = validate_ground_truth(ground_truth_by_source, metadata)
    if not validation["valid"]:
        raise ValueError("invalid ground truth: " + "; ".join(validation["errors"]))
    stages = {name: stage_records.get(name, {"status": "blocked", "output": None})
              for name in ("yolo", "clef", "vlm")}
    for name, stage in stages.items():
        if stage.get("status") not in {"ok", "error", "blocked", "skipped"}:
            raise ValueError(f"invalid {name} stage status")
        if stage.get("mock") or str(stage.get("model", "")).startswith("mock_"):
            raise ValueError("mocks forbidden in real evaluation")
    result = {"ground_truth_validation": validation,
              "yolo": detection_metrics(model_input, ground_truth_by_source, stages["yolo"])}
    clef = stages["clef"]
    clef_output = clef.get("output")
    routes, routing_errors = {}, []
    clef_entries = []
    if clef.get("status") == "ok":
        if not isinstance(clef_output, dict) or not isinstance(clef_output.get("sources"), list):
            routing_errors.append("invalid clef output envelope")
        else:
            clef_entries = clef_output["sources"]
    elif clef_output is not None:
        routing_errors.append("unexecuted/failed clef contains an output")
    for row in clef_entries:
        source = row.get("source_id") if isinstance(row, dict) else None
        if not isinstance(source, str) or source not in model_input["sources"] or source in routes:
            routing_errors.append("unknown/duplicate clef source")
        elif type(row.get("invoke_vlm")) is not bool:
            routing_errors.append(f"{source}: invoke_vlm must be boolean")
        else:
            routes[source] = row
    if clef.get("status") == "ok" and set(routes) != set(model_input["sources"]):
        routing_errors.append("missing clef source decision")
    clef_rows, reviewed, correct, available, fn, fp, missing, missing_positive = {}, 0, 0, 0, 0, 0, 0, 0
    for source in model_input["sources"]:
        truth = (ground_truth_by_source.get(source, {}).get("clef") or {})
        expected = truth.get("invoke_vlm") if truth.get("reviewed") is True else None
        actual = routes.get(source, {}).get("invoke_vlm")
        known = type(expected) is bool
        reviewed += known
        if known:
            if actual is None:
                missing += 1
                missing_positive += expected is True
            else:
                available += 1
                correct += actual == expected
                fn += expected and not actual
                fp += not expected and actual
        proposed = routes.get(source, {}).get("proposed_route")
        proposed_bool = {"invoke_vlm": True, "human_review": True, "no_action": False}.get(proposed) if isinstance(proposed, str) else None
        clef_rows[source] = {"expected_invoke_vlm": expected, "actual_invoke_vlm": actual,
                             "correct": actual == expected if known and actual is not None else None,
                             "proposed_route": proposed,
                             "proposed_correct": proposed_bool == expected if known and proposed_bool is not None else None,
                             "reviewed": known}
    result["clef"] = {"per_source": clef_rows, "reviewed_source_count": reviewed,
                      "available_decision_count": available, "unavailable_decision_count": missing,
                      "accuracy_including_unavailable": _ratio(correct, reviewed),
                      "conditional_decision_accuracy": _ratio(correct, available),
                      "false_negative_calls": fn if reviewed else None,
                      "false_positive_calls": fp if reviewed else None,
                      "missing_required_calls": missing_positive if reviewed else None,
                      "output_format_valid": not routing_errors if clef.get("status") == "ok" else None,
                      "output_errors": routing_errors}
    vlm = stages["vlm"]
    active = vlm.get("active_sources", model_input.get("active_sources", model_input["sources"]))
    if len(active) != len(set(active)) or not set(active) <= set(model_input["sources"]):
        raise ValueError("invalid VLM execution source mapping")
    explicit_execution = vlm.get("source_execution", {})
    if (not isinstance(explicit_execution, dict) or not set(explicit_execution) <= set(model_input["sources"])
            or any(status not in {"ok", "error", "blocked", "skipped"} for status in explicit_execution.values())):
        raise ValueError("invalid per-source VLM execution status")
    source_statuses = {source: explicit_execution.get(source, vlm["status"] if source in active else "skipped")
                       for source in model_input["sources"]}
    attempted = {source for source in active if source_statuses[source] in {"ok", "error"}}
    if not vlm.get("executed", True):
        attempted.clear()
    output = vlm.get("output")
    entries, format_errors = {}, []
    if output is not None:
        if not isinstance(output, dict) or set(output) != {"assessments"} or not isinstance(output.get("assessments"), list):
            format_errors.append("invalid VLM output envelope")
        else:
            for entry in output["assessments"]:
                source = entry.get("source_id") if isinstance(entry, dict) else None
                if not isinstance(source, str) or source not in attempted or source in entries:
                    format_errors.append("unknown/unrequested/duplicate VLM source")
                    if isinstance(source, str) and source in entries:
                        entries[source] = None
                else:
                    entries[source] = entry
                    if not _assessment_valid(entry):
                        format_errors.append(f"{source}: invalid assessment schema")
    if vlm.get("status") == "ok" and set(entries) != attempted:
        format_errors.append("missing VLM source assessment")
    if vlm.get("status") == "ok" and output is None:
        format_errors.append("missing VLM output")
    if model_input.get("output_schema") is not None and output is not None:
        from jsonschema import Draft202012Validator

        format_errors.extend("schema: " + error.message for error in
                             Draft202012Validator(model_input["output_schema"]).iter_errors(output))
    if not attempted and output is not None:
        format_errors.append("unexecuted VLM contains fabricated output")
    rows, reviewed, correct, attempted_reviewed, attempted_correct, omissions = {}, 0, 0, 0, 0, 0
    input_refs_valid = []
    for source in model_input["sources"]:
        truth = (ground_truth_by_source.get(source, {}).get("vlm") or {})
        expected = truth.get("label") if truth.get("reviewed") is True else None
        known = expected is not None
        reviewed += known
        entry = entries.get(source)
        prediction = _canonical_label(entry.get("event_type")) if isinstance(entry, dict) else None
        semantic_correct = prediction == expected if known and prediction is not None else None
        refs = entry.get("evidence_refs") if isinstance(entry, dict) else None
        reference_valid = (isinstance(refs, list) and all(isinstance(ref, str) and ref in frames
                           and frames[ref]["source_id"] == source for ref in refs)) if entry else None
        if reference_valid is not None:
            input_refs_valid.append(reference_valid)
        if known:
            correct += semantic_correct is True
            omissions += entry is None
            if source in attempted:
                attempted_reviewed += 1
                attempted_correct += semantic_correct is True
        safety_valid = None
        if _assessment_valid(entry):
            safety_valid = (entry["needs_human_review"] or
                            (entry["event_type"] != "uncertain" and entry["event_confidence"] >= .9
                             and all(v is not None for v in entry["risk_axes"].values())
                             and reference_valid is True))
        rows[source] = {"expected_event_type": expected, "predicted_event_type": prediction,
                        "semantic_correct": semantic_correct, "executed": source in attempted,
                        "output_format_valid": _assessment_valid(entry) if entry else None,
                        "input_reference_valid": reference_valid,
                        "evidence_content_accuracy": None, "safety_policy_valid": safety_valid,
                        "status": source_statuses[source],
                        "omission_cause": _omission_cause(source, source_statuses[source], clef_rows[source],
                                                          active, attempted) if entry is None else None,
                        "omitted_reviewed_source": known and entry is None}
    result["vlm"] = {"per_source": rows, "reviewed_source_count": reviewed,
                     "attempted_reviewed_source_count": attempted_reviewed,
                     "pipeline_event_accuracy_including_omissions": _ratio(correct, reviewed),
                     "conditional_attempted_event_accuracy": _ratio(attempted_correct, attempted_reviewed),
                     "omitted_reviewed_source_count": omissions,
                     "output_format_valid": not format_errors if attempted and (output is not None or vlm["status"] == "ok") else None,
                     "input_reference_valid": all(input_refs_valid) if input_refs_valid else None,
                     "evidence_content_accuracy": None, "output_errors": format_errors}
    result["pipeline"] = {"all_stages_ok": all(stage.get("status") == "ok" for stage in stages.values()),
                          "event_accuracy": result["vlm"]["pipeline_event_accuracy_including_omissions"],
                          "stage_statuses": {name: stage["status"] for name, stage in stages.items()},
                          "fallback_recorded": any(stage.get("fallback") for stage in stages.values()),
                          "semantic_evidence_accuracy": None}
    return result
