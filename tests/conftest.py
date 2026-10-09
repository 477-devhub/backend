import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.schemas.model import ModelInput
@pytest.fixture
def mi():
    return ModelInput.model_validate_json(Path('fixtures/model_input.json').read_text(encoding='utf-8'))
@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(media_root=tmp_path))) as c:yield c
