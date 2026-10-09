from app.models.base import ModelAdapter
class UnconfiguredAdapter(ModelAdapter):
    def __init__(self, name):
        self.name = name
    async def evaluate(self, model_input):
        raise RuntimeError("Real adapter unavailable; do not substitute a mock")
