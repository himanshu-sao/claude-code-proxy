from fastapi.testclient import TestClient
from src.main import app
from src.conversion.request_converter import _is_reasoning_model

client = TestClient(app)

def test_list_models():
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0
    model_ids = [m["id"] for m in data["data"]]
    assert "claude-3-5-sonnet-20241022" in model_ids

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data["endpoints"]
    assert data["endpoints"]["models"] == "/v1/models"

def test_is_reasoning_model():
    assert _is_reasoning_model("deepseek-r1") is True
    assert _is_reasoning_model("deepseek/deepseek-r1") is True
    assert _is_reasoning_model("moonshotai/kimi-k3") is True
    assert _is_reasoning_model("o1-mini") is True
    assert _is_reasoning_model("o3-mini") is True
    
    # Verify non-reasoning models with similar substrings do not falsely match
    assert _is_reasoning_model("gpt-4o") is False
    assert _is_reasoning_model("custom-provider1") is False
    assert _is_reasoning_model("server1") is False
    assert _is_reasoning_model("ver1") is False

