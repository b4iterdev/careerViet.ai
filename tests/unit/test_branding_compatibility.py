import pytest

from mocnghe.evaluation_runtime import EvaluationProviderConfig


@pytest.mark.parametrize("prefix", ["MOCNGHE", "CAREERVIET"])
def test_provider_environment_names(prefix):
    config = EvaluationProviderConfig.from_env({
        f"{prefix}_EVAL_ENDPOINT": "http://localhost:9999/v1/chat/completions",
        f"{prefix}_EVAL_MODEL": "synthetic-model",
        f"{prefix}_EVAL_API_KEY": "synthetic-key",
        f"{prefix}_EVAL_ALLOW_LOOPBACK_HTTP": "1",
    })
    assert config.model == "synthetic-model"
    assert config.api_key == "synthetic-key"
    assert config.allow_loopback_http


def test_new_provider_namespace_does_not_mix_legacy_credentials():
    env = {
        "CAREERVIET_EVAL_ENDPOINT": "https://legacy.invalid/v1/chat/completions",
        "CAREERVIET_EVAL_MODEL": "legacy-model",
        "CAREERVIET_EVAL_API_KEY": "legacy-secret",
        "CAREERVIET_EVAL_ALLOW_LOOPBACK_HTTP": "1",
        "MOCNGHE_EVAL_ENDPOINT": "https://new.invalid/v1/chat/completions",
    }
    with pytest.raises(ValueError, match="configuration requires"):
        EvaluationProviderConfig.from_env(env)
    env.update(MOCNGHE_EVAL_MODEL="new-model", MOCNGHE_EVAL_API_KEY="new-secret")
    config = EvaluationProviderConfig.from_env(env)
    assert config.endpoint == env["MOCNGHE_EVAL_ENDPOINT"]
    assert config.model == "new-model"
    assert config.api_key == "new-secret"
    assert not config.allow_loopback_http
    env["MOCNGHE_EVAL_API_KEY"] = ""
    with pytest.raises(ValueError, match="configuration requires"):
        EvaluationProviderConfig.from_env(env)
