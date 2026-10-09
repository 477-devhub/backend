import math
import pytest
from pydantic import ValidationError
from app.schemas.model import ModelInput, RiskAxes, TimeWindow
from app.services.risk import risk_score

def test_figma_example_score():
    assert risk_score(RiskAxes(severity=.9,imminence=.95,exposure=.8,persistence=.85))==89
@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,1.1])
def test_axes_reject_invalid(value):
    with pytest.raises(ValidationError):RiskAxes(severity=value,imminence=0,exposure=0,persistence=0)
def test_window_order():
    with pytest.raises(ValidationError):TimeWindow(start_ms=100,end_ms=50)
def test_ground_truth_rejected(mi):
    data=mi.model_dump();data['event_type']='collapse'
    with pytest.raises(ValidationError):ModelInput.model_validate(data)
def test_duplicate_frame(mi):
    data=mi.model_dump();data['evidence'].append(data['evidence'][0])
    with pytest.raises(ValidationError):ModelInput.model_validate(data)
