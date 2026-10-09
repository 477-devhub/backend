"""Evaluator-only MP4 companion annotation parsing. Never builds inference input."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

from app.schemas.model import RiskAxes

EVENT_TYPES = frozenset({"normal", "collapse", "conflict", "intrusion", "loitering", "uncertain"})


@dataclass(frozen=True)
class AnnotationDocument:
    videos: tuple[dict, ...]
    ground_truth: dict
    evaluation_only_annotations: dict


def parse_annotations(document: dict, *, event_mapping: Mapping[str, str]) -> AnnotationDocument:
    """Mapping and source/scenario/split decisions belong to the data owner.

    Caption/cot/answer/evidence (including annotation frame IDs and boxes) stay in
    evaluation_only_annotations. No FPS, event window or critical label is inferred.
    The caller must supply an independent inference plan and actual media separately.
    """
    if not isinstance(document, dict):
        raise ValueError("annotation document must be an object")
    videos, annotation = document.get("videos"), document.get("annotations")
    if not isinstance(videos, list) or not videos or not isinstance(annotation, dict):
        raise ValueError("videos and annotations are required")
    event_class = annotation.get("event_class")
    if not isinstance(event_class, str) or event_class not in event_mapping:
        raise ValueError("explicit event_class mapping is required")
    event_type = event_mapping[event_class]
    if event_type not in EVENT_TYPES:
        raise ValueError("mapped event type is invalid")
    names, views = set(), set()
    for video in videos:
        if not isinstance(video, dict):
            raise ValueError("video metadata must be an object")
        name, view = video.get("filename"), video.get("view")
        if not isinstance(name, str) or not name or not isinstance(view, str) or not view:
            raise ValueError("filename and view are required")
        if name in names or view in views:
            raise ValueError("duplicate filename or view")
        names.add(name)
        views.add(view)
    truth = {"event_type": event_type}
    for key in ("critical", "needs_human_review"):
        value = annotation.get(key)
        if value is not None and type(value) is not bool:
            raise ValueError("explicit review/critical annotations must be boolean")
        truth[key] = value
    axes = annotation.get("risk_axes")
    truth["risk_axes"] = RiskAxes.model_validate(axes).model_dump() if axes is not None else None
    return AnnotationDocument(tuple(deepcopy(videos)), truth, deepcopy(annotation))
