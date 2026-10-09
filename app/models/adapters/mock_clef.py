from app.models.base import ModelAdapter
from app.schemas.model import ModelInput, ModelAssessment, ModelMetadata
class MockClefDirectAdapter(ModelAdapter):
    name = "mock_clef"
    async def evaluate(self, model_input: ModelInput) -> ModelAssessment:
        return ModelAssessment(event_type="uncertain", event_confidence=0, risk_axes=None,
            needs_human_review=True, uncertainty_reason="mock: no real inference",
            evidence_refs=[e.frame_id for e in model_input.evidence],
            metadata=ModelMetadata(adapter=self.name, model="mock", is_mock=True))
