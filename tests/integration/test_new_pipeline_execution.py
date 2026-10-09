import asyncio

from app.models.execution import execute_pipeline_stage

def test_portable_stage_execution_sanitizes_and_preserves_input():
    class Adapter:
        async def run(self, data, context):
            data["frames"].append("mutated")
            return {"status": "ok", "output": {"invented": True}}
    original = {"frames": []}
    outcome = asyncio.run(execute_pipeline_stage(Adapter(), original, {}))
    assert original == {"frames": []}
    assert outcome["status"] == "error" and outcome["output"] is None
    assert outcome["errors"][0]["category"] == "benchmark"
