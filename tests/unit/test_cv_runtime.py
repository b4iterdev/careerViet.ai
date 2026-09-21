import json

import httpx
import pytest

from careerviet.cv import CVService
from careerviet.evaluation_runtime import EvaluationProviderConfig


def test_packet_binding_redaction_and_provider(repo):
    from careerviet.cv_runtime import create_packet, import_response, run_provider
    s = CVService(repo)
    cv = s.create("v1", ["ev1"], language="en", identity_keys=["name", "email"])
    with pytest.raises(PermissionError):
        create_packet(s, cv.id, consent=False)
    packet = create_packet(s, cv.id, consent=True)
    assert "synthetic@example.invalid" not in json.dumps(packet)
    assert "Ứng viên mẫu" not in json.dumps(packet, ensure_ascii=False)
    response = {"packet_hash": packet["packet_hash"], "claims": packet["claims"]}
    response["claims"][0]["text"] = "Volunteered in customer support."
    response["claims"][0]["mode"] = "proposed"
    imported = import_response(s, cv.id, response, provenance="cli-agent")
    assert not s.approved(imported.id)
    assert imported.identity == cv.identity
    def handler(request):
        assert request.url == "https://provider.invalid/v1/chat/completions"
        assert b"synthetic@example.invalid" not in request.content
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps(response)}}]})
    config = EvaluationProviderConfig(endpoint="https://provider.invalid/v1/chat/completions",
                                      model="synthetic-model", api_key="synthetic-not-secret")
    with pytest.raises(PermissionError):
        run_provider(s, cv.id, config, consent=False, transport=httpx.MockTransport(handler))
    result = run_provider(s, cv.id, config, consent=True, transport=httpx.MockTransport(handler))
    assert result.provenance == "direct:synthetic-model"
    response["packet_hash"] = "0" * 64
    with pytest.raises(ValueError, match="packet"):
        import_response(s, cv.id, response, provenance="cli-agent")
