from pathlib import Path
import pytest
from app.models.benchmark_media import assert_output_outside_inputs, snapshot_protected


@pytest.mark.parametrize("name", ["data", "media", "final_candidates_v1", "477_modeling_benchmark_v1"])
def test_outputs_never_write_inside_protected_inputs(tmp_path: Path, name: str):
    with pytest.raises(ValueError, match="protected"):
        assert_output_outside_inputs(tmp_path, tmp_path / name / "run")


def test_protected_snapshot_detects_changes_and_extra_files(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    file = data / "fixture.txt"
    file.write_text("fixture", encoding="utf-8")
    before = snapshot_protected(tmp_path)
    assert before == snapshot_protected(tmp_path)
    file.write_text("modified", encoding="utf-8")
    assert before != snapshot_protected(tmp_path)
    assert assert_output_outside_inputs(tmp_path, tmp_path / "runs") == tmp_path / "runs"
