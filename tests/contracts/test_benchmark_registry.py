import pytest
from app.models.budget import PaidBudget
from app.models.registry import get_benchmark_adapter


@pytest.mark.parametrize('name', ['local_cv', 'clef_direct', 'general_vlm'])
def test_factory_names_match_real_evaluation_slots(name, tmp_path):
    adapter = get_benchmark_adapter(name, root=tmp_path,
        budget=PaidBudget(tmp_path/'budget.json'))
    assert adapter.name == name
    assert not adapter.model.startswith('mock')


def test_paid_slots_require_persistent_budget(tmp_path):
    with pytest.raises(ValueError):
        get_benchmark_adapter('general_vlm', root=tmp_path)


def test_pose_off_profile_preserves_detector_configuration(tmp_path):
    full = get_benchmark_adapter('local_cv', root=tmp_path)
    fast = get_benchmark_adapter('local_cv', root=tmp_path, pose_enabled=False)
    assert full.pose_weights.name == 'yolo26s-pose.pt'
    assert fast.pose_weights is None
    assert fast.detector_weights == full.detector_weights
    assert (fast.imgsz, fast.conf) == (full.imgsz, full.conf) == (960, .10)


def test_pose_profile_rejects_ambiguous_flag(tmp_path):
    with pytest.raises(ValueError, match='boolean'):
        get_benchmark_adapter('local_cv', root=tmp_path, pose_enabled='false')
