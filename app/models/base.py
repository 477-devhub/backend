from abc import ABC, abstractmethod
from app.schemas.model import ModelInput, ModelAssessment

class ModelAdapter(ABC):
    name: str
    @abstractmethod
    async def evaluate(self, model_input: ModelInput) -> ModelAssessment:
        """Must be async/nonblocking. CPU/GPU work uses a bounded external worker.
        Provider SDKs and provider request serializers belong in adapters only.
        Never serialize raw local filenames or ground truth into provider requests.
        """
        raise NotImplementedError
