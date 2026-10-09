import copy

import pytest

from pipeline477.metrics import detection_metrics, evaluate_item, validate_ground_truth


def inputs(sources=("SRC01",)):
    q, remainder = divmod(64, len(sources))
    frames = []
    for index, source in enumerate(sources):
        for n in range(q + (index < remainder)):
            frames.append({"frame_id": f"{source}-{n}", "source_id": source,
                           "frame_number": n, "timestamp_sec": float(n), "width": 100, "height": 100})
    return {"sources": list(sources), "frames": frames}


def truth(source="SRC01", label="normal", invoke=True, complete=True, objects=None):
    return {source: {"yolo": {"frames": [{"frame_number": 0, "complete": complete,
                         "objects": objects if objects is not None else [{"class_name": "person", "bbox": [0, 0, 20, 20]}]}]},
                    "clef": {"reviewed": True, "invoke_vlm": invoke, "rationale": "human-reviewed uncertainty"},
                    "vlm": {"reviewed": True, "label": label}}}


def assessment(source="SRC01", label="normal", refs=None):
    return {"source_id": source, "event_type": label, "event_confidence": .95,
            "risk_axes": {key: None for key in ["severity", "imminence", "exposure", "persistence"]},
            "evidence_refs": refs if refs is not None else [f"{source}-0"],
            "needs_human_review": True, "uncertainty_reason": "unmeasured risk axes"}


def record(detections=None):
    return {"status": "ok", "output": {"frames": [{"frame_id": "SRC01-0", "source_id": "SRC01",
             "detections": detections if detections is not None else [
                 {"class_name": "person", "bbox": [0, 0, 20, 20], "confidence": .9, "track_id": 1}]}]}}


def stages():
    return {"yolo": record(), "clef": {"status": "ok", "output": {"sources": [
        {"source_id": "SRC01", "invoke_vlm": True, "proposed_route": "human_review"}]}},
        "vlm": {"status": "ok", "output": {"assessments": [assessment()]}}}


def test_exact_match_detection_and_semantics():
    result = evaluate_item(inputs(), truth(), stages())
    assert result["yolo"]["precision"] == result["yolo"]["recall"] == result["yolo"]["map50"] == 1
    assert result["yolo"]["evaluated_frame_count"] == result["yolo"]["evaluated_object_count"] == 1
    assert result["clef"]["accuracy_including_unavailable"] == 1
    assert result["vlm"]["pipeline_event_accuracy_including_omissions"] == 1
    assert result["vlm"]["evidence_content_accuracy"] is None


@pytest.mark.parametrize("detections, tp, fp, fn, ap", [
    ([], 0, 0, 1, 0),
    ([{"class_name": "car", "bbox": [0, 0, 20, 20], "confidence": .9}], 0, 1, 1, 0),
    ([{"class_name": "person", "bbox": [70, 70, 90, 90], "confidence": .9}], 0, 1, 1, 0),
    ([{"class_name": "person", "bbox": [0, 0, 20, 20], "confidence": .9},
      {"class_name": "person", "bbox": [0, 0, 20, 20], "confidence": .8}], 1, 1, 0, 1),
])
def test_matching_wrong_class_duplicate_and_missed(detections, tp, fp, fn, ap):
    result = detection_metrics(inputs(), truth(), record(detections))
    assert [result[k] for k in ["true_positives", "false_positives", "false_negatives", "map50"]] == [tp, fp, fn, ap]


def test_high_confidence_false_positive_precedes_true_positive_ap():
    result = detection_metrics(inputs(), truth(), record([
        {"class_name": "person", "bbox": [60, 60, 80, 80], "confidence": .99},
        {"class_name": "person", "bbox": [0, 0, 20, 20], "confidence": .8}]))
    assert result["map50"] == .5


def test_complete_empty_ground_truth_false_positives_are_real_but_ap_unavailable():
    result = detection_metrics(inputs(), truth(objects=[]), record())
    assert result["false_positives"] == 1
    assert result["precision"] == 0
    assert result["recall"] is result["map50"] is None
    result = detection_metrics(inputs(), truth(objects=[]), record([]))
    assert result["false_positives"] == 0
    assert result["precision"] is result["recall"] is None


def test_partial_annotations_do_not_create_false_positives_or_recall():
    result = detection_metrics(inputs(), truth(complete=False), record())
    assert result["partial_annotation_frame_count"] == 1
    assert result["evaluated_frame_count"] == 0
    assert result["false_positives"] is result["map50"] is None


def test_annotation_not_in_canonical_input_remains_unevaluated():
    gt = truth()
    gt["SRC01"]["yolo"]["frames"][0]["frame_number"] = 70
    result = detection_metrics(inputs(), gt, record())
    assert result["noncanonical_annotation_frame_count"] == 1
    assert result["evaluated_frame_count"] == 0


def test_explicit_class_scope_does_not_count_unannotated_other_class():
    gt = truth()
    gt["SRC01"]["yolo"]["class_scope"] = ["person"]
    result = detection_metrics(inputs(), gt, record([
        {"class_name": "car", "bbox": [0, 0, 20, 20], "confidence": .9}]))
    assert result["false_positives"] == 0
    assert result["false_negatives"] == 1


def test_missing_ground_truth_is_null_not_perfect():
    result = evaluate_item(inputs(), {}, stages())
    assert result["yolo"]["map50"] is None
    assert result["clef"]["accuracy_including_unavailable"] is None
    assert result["vlm"]["pipeline_event_accuracy_including_omissions"] is None
    assert result["ground_truth_validation"]["review_required"]


@pytest.mark.parametrize("path,value", [
    (("yolo", "frames", 0, "complete"), "yes"),
    (("yolo", "frames", 0, "frame_number"), True),
    (("yolo", "frames", 0, "objects", 0, "bbox"), [0, 0, 101, 10]),
    (("yolo", "frames", 0, "objects", 0, "bbox"), [0, 0, float("nan"), 10]),
    (("yolo", "frames", 0, "objects", 0, "class_name"), "alien"),
    (("clef", "invoke_vlm"), 1),
    (("vlm", "label"), "intrusion"),
])
def test_invalid_ground_truth_fails_preflight(path, value):
    gt = truth()
    current = gt["SRC01"]
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    validation = validate_ground_truth(gt, {"SRC01": {"width": 100, "height": 100, "frame_count": 80}})
    assert not validation["valid"]
    with pytest.raises(ValueError, match="invalid ground truth"):
        evaluate_item(inputs(), gt, stages())


def test_unknown_ground_truth_source_and_duplicate_annotation_are_rejected():
    assert not validate_ground_truth(truth("SRC06"), {"SRC01": {}})["valid"]
    gt = truth()
    gt["SRC01"]["yolo"]["frames"] *= 2
    assert not validate_ground_truth(gt, {"SRC01": {"width": 100, "height": 100}})["valid"]


def test_wrong_route_vs_missing_decision_are_separate():
    data = stages()
    data["clef"]["output"]["sources"][0]["invoke_vlm"] = False
    result = evaluate_item(inputs(), truth(), data)["clef"]
    assert result["false_negative_calls"] == 1
    assert result["missing_required_calls"] == 0
    data["clef"] = {"status": "error", "output": None}
    result = evaluate_item(inputs(), truth(), data)["clef"]
    assert result["false_negative_calls"] == 0
    assert result["missing_required_calls"] == 1
    assert result["accuracy_including_unavailable"] == 0
    assert result["conditional_decision_accuracy"] is None


def test_unnecessary_call_not_inferred_from_event_name():
    result = evaluate_item(inputs(), truth(label="physical_conflict", invoke=False), stages())["clef"]
    assert result["false_positive_calls"] == 1


def test_multisource_skip_is_pipeline_omission_not_a_vlm_wrong_answer():
    model_input = inputs(("SRC01", "SRC02"))
    model_input["active_sources"] = ["SRC01"]
    gt = {**truth(), **truth("SRC02", label="physical_conflict")}
    data = stages()
    data["clef"]["output"]["sources"].append({"source_id": "SRC02", "invoke_vlm": False})
    result = evaluate_item(model_input, gt, data)
    assert result["vlm"]["pipeline_event_accuracy_including_omissions"] == .5
    assert result["vlm"]["conditional_attempted_event_accuracy"] == 1
    assert result["vlm"]["per_source"]["SRC02"]["semantic_correct"] is None
    assert result["vlm"]["per_source"]["SRC02"]["status"] == "skipped"


def test_upstream_fallback_retains_failure_despite_correct_final_answer():
    data = stages()
    data["clef"] = {"status": "error", "output": None, "fallback": "invoke_all_sources"}
    result = evaluate_item(inputs(), truth(), data)
    assert not result["pipeline"]["all_stages_ok"]
    assert result["pipeline"]["fallback_recorded"]
    assert result["pipeline"]["event_accuracy"] == 1


def test_vlm_api_error_is_in_conditional_attempted_denominator():
    data = stages()
    data["vlm"] = {"status": "error", "output": None}
    result = evaluate_item(inputs(), truth(), data)
    assert result["vlm"]["conditional_attempted_event_accuracy"] == 0
    assert result["vlm"]["pipeline_event_accuracy_including_omissions"] == 0


def test_semantics_format_and_reference_validity_are_independent():
    data = stages()
    data["vlm"]["output"]["assessments"][0]["event_type"] = "physical_conflict"
    result = evaluate_item(inputs(), truth(), data)["vlm"]
    assert result["output_format_valid"]
    assert not result["per_source"]["SRC01"]["semantic_correct"]
    data["vlm"]["output"]["assessments"][0]["event_type"] = "normal"
    data["vlm"]["output"]["assessments"][0]["evidence_refs"] = ["does-not-exist"]
    result = evaluate_item(inputs(), truth(), data)["vlm"]
    assert result["per_source"]["SRC01"]["semantic_correct"]
    assert not result["input_reference_valid"]
    assert result["output_format_valid"]


def test_crosssource_references_unknown_and_duplicate_output_source():
    model_input = inputs(("SRC01", "SRC02"))
    data = stages()
    data["vlm"]["output"]["assessments"] = [assessment(refs=["SRC02-0"]), assessment("SRC02")]
    result = evaluate_item(model_input, {**truth(), **truth("SRC02")}, data)
    assert not result["vlm"]["input_reference_valid"]
    data["vlm"]["output"]["assessments"].append(assessment("SRC06"))
    result = evaluate_item(model_input, {**truth(), **truth("SRC02")}, data)
    assert not result["vlm"]["output_format_valid"]
    data["vlm"]["output"]["assessments"] = [assessment(), assessment()]
    result = evaluate_item(inputs(), truth(), data)
    assert result["vlm"]["pipeline_event_accuracy_including_omissions"] == 0


def test_synonym_can_match_semantics_without_claiming_schema_pass():
    data = stages()
    data["vlm"]["output"]["assessments"][0]["event_type"] = "fall"
    result = evaluate_item(inputs(), truth(label="fall_ground_posture"), data)["vlm"]
    assert result["per_source"]["SRC01"]["semantic_correct"]
    assert not result["output_format_valid"]


def test_skipped_vlm_does_not_create_prediction_even_if_fabricated_output():
    data = stages()
    data["vlm"]["status"] = "skipped"
    result = evaluate_item(inputs(), truth(), data)["vlm"]
    assert result["per_source"]["SRC01"]["predicted_event_type"] is None
    assert result["conditional_attempted_event_accuracy"] is None
    assert result["output_errors"]


def test_yolo_failed_stage_counts_annotated_object_omission():
    result = detection_metrics(inputs(), truth(), {"status": "error", "output": None})
    assert result["recall"] == 0
    assert result["map50"] == 0
    assert result["missing_prediction_frame_count"] == 1


def test_yolo_crosssource_mapping_is_not_counted_as_true_positive():
    data = record()
    data["output"]["frames"][0]["source_id"] = "SRC02"
    result = detection_metrics(inputs(), truth(), data)
    assert not result["output_mapping_valid"]
    assert result["true_positives"] == 0


def test_real_evaluation_forbids_mock_records_and_bad_input_mapping():
    data = stages()
    data["clef"]["model"] = "mock_clef"
    with pytest.raises(ValueError, match="mocks forbidden"):
        evaluate_item(inputs(), truth(), data)
    bad = inputs()
    bad["frames"][1] = copy.deepcopy(bad["frames"][0])
    with pytest.raises(ValueError, match="64 unique"):
        evaluate_item(bad, truth(), stages())


def test_supplied_output_schema_is_used_and_not_invented_by_evaluator():
    model_input = inputs()
    model_input["output_schema"] = {"type": "object", "required": ["extra_required_contract_field"]}
    result = evaluate_item(model_input, truth(), stages())
    assert not result["vlm"]["output_format_valid"]
    assert any(error.startswith("schema:") for error in result["vlm"]["output_errors"])


@pytest.mark.parametrize("field", ["yolo", "clef", "vlm"])
def test_nondict_ground_truth_stage_is_structural_preflight_error(field):
    gt = truth()
    gt["SRC01"][field] = ["malformed"]
    assert not validate_ground_truth(gt, {"SRC01": {"width": 100, "height": 100}})["valid"]


def test_failed_api_does_not_claim_valid_output_format():
    data = stages()
    data["vlm"] = {"status": "error", "output": None}
    result = evaluate_item(inputs(), truth(), data)
    assert result["vlm"]["output_format_valid"] is None
    assert result["vlm"]["per_source"]["SRC01"]["omission_cause"] == "vlm_execution_error"


def test_ok_stage_without_output_is_invalid_not_successful():
    data = stages()
    data["vlm"] = {"status": "ok", "output": None}
    data["clef"] = {"status": "ok", "output": None}
    result = evaluate_item(inputs(), truth(), data)
    assert not result["vlm"]["output_format_valid"]
    assert not result["clef"]["output_format_valid"]


def test_malformed_model_values_are_evaluable_errors_not_evaluator_crashes():
    data = stages()
    data["vlm"]["output"]["assessments"][0]["event_type"] = ["normal"]
    data["yolo"]["output"]["frames"][0]["frame_id"] = ["SRC01-0"]
    result = evaluate_item(inputs(), truth(), data)
    assert not result["vlm"]["output_format_valid"]
    assert not result["yolo"]["output_mapping_valid"]


def test_active_blocked_vlm_preserves_blocked_status_without_fake_attempt():
    data = stages()
    data["vlm"] = {"status": "blocked", "output": None, "executed": False,
                   "active_sources": ["SRC01"], "source_execution": {"SRC01": "blocked"}}
    result = evaluate_item(inputs(), truth(), data)["vlm"]
    source = result["per_source"]["SRC01"]
    assert source["status"] == "blocked"
    assert source["omission_cause"] == "execution_blocked"
    assert source["executed"] is False
    assert result["attempted_reviewed_source_count"] == 0
    assert result["conditional_attempted_event_accuracy"] is None
    assert result["pipeline_event_accuracy_including_omissions"] == 0


def test_source_execution_override_is_preserved_when_request_was_blocked():
    data = stages()
    data["vlm"] = {"status": "blocked", "output": None, "executed": False,
                   "active_sources": [], "source_execution": {"SRC01": "blocked"}}
    source = evaluate_item(inputs(), truth(), data)["vlm"]["per_source"]["SRC01"]
    assert source["status"] == "blocked"
    assert source["executed"] is False
    assert source["omission_cause"] == "execution_blocked"


def test_timeout_is_attempted_vlm_error_and_not_route_skip():
    data = stages()
    data["vlm"] = {"status": "error", "output": None, "executed": True,
                   "active_sources": ["SRC01"], "source_execution": {"SRC01": "error"},
                   "errors": [{"category": "execution", "code": "timeout"}]}
    result = evaluate_item(inputs(), truth(), data)["vlm"]
    source = result["per_source"]["SRC01"]
    assert source["status"] == "error"
    assert source["executed"] is True
    assert source["omission_cause"] == "vlm_execution_error"
    assert result["conditional_attempted_event_accuracy"] == 0


def test_unavailable_upstream_with_no_active_sources_is_routing_unknown():
    data = stages()
    data["clef"] = {"status": "blocked", "output": None, "executed": False}
    data["vlm"] = {"status": "skipped", "output": None, "executed": False,
                   "active_sources": [], "source_execution": {"SRC01": "skipped"}}
    result = evaluate_item(inputs(), truth(), data)["vlm"]
    source = result["per_source"]["SRC01"]
    assert source["status"] == "skipped"
    assert source["omission_cause"] == "routing_unavailable"
    assert result["conditional_attempted_event_accuracy"] is None


@pytest.mark.parametrize("expected, cause", [(True, "routing_false_negative"), (False, "route_skipped")])
def test_actual_false_route_is_only_false_negative_when_reviewed_truth_requires_call(expected, cause):
    data = stages()
    data["clef"]["output"]["sources"][0]["invoke_vlm"] = False
    data["vlm"] = {"status": "skipped", "output": None, "executed": False,
                   "active_sources": [], "source_execution": {"SRC01": "skipped"}}
    source = evaluate_item(inputs(), truth(invoke=expected), data)["vlm"]["per_source"]["SRC01"]
    assert source["omission_cause"] == cause
    assert source["predicted_event_type"] is None


def test_schema_invalid_semantic_output_retains_independent_prediction():
    data = stages()
    data["vlm"]["output"]["assessments"][0]["event_confidence"] = 2
    original = copy.deepcopy(data)
    result = evaluate_item(inputs(), truth(), data)["vlm"]
    assert result["per_source"]["SRC01"]["semantic_correct"]
    assert not result["output_format_valid"]
    assert data == original
