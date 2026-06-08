"""ai_settings.resolve_ai_config：key/base_url/model 同源解析与优先级。

修复的历史 bug：旧逻辑 key 与 base_url 各自挑来源，会出现「OpenAI 的 key + DeepSeek 的 url」→ 401。
本测试锁定「整组同源」行为。
"""

import ai_settings


ENV_KEYS = [
    "PREPROCESS_AI_API_KEY",
    "PREPROCESS_AI_BASE_URL",
    "PREPROCESS_AI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
]


def _clear_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def _set_local(monkeypatch, data):
    monkeypatch.setattr(ai_settings, "load_local_settings", lambda: dict(data))


def test_env_preprocess_wins(monkeypatch):
    _clear_env(monkeypatch)
    _set_local(monkeypatch, {"api_key": "sk-file", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"})
    monkeypatch.setenv("PREPROCESS_AI_API_KEY", "sk-env")
    monkeypatch.setenv("PREPROCESS_AI_BASE_URL", "https://env.example.com/v1")
    monkeypatch.setenv("PREPROCESS_AI_MODEL", "env-model")
    cfg = ai_settings.resolve_ai_config()
    assert cfg["source"] == "env"
    assert cfg["api_key"] == "sk-env"
    assert cfg["base_url"] == "https://env.example.com/v1"
    assert cfg["model"] == "env-model"


def test_local_file_beats_generic_openai(monkeypatch):
    # 关键场景：本地配置了 DeepSeek，环境里只有通用 OPENAI_API_KEY → 必须整组用本地（DeepSeek），不串台
    _clear_env(monkeypatch)
    _set_local(
        monkeypatch,
        {"api_key": "sk-deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "provider": "deepseek"},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-generic")
    cfg = ai_settings.resolve_ai_config()
    assert cfg["source"] == "file"
    assert cfg["api_key"] == "sk-deepseek"
    assert cfg["base_url"] == "https://api.deepseek.com/v1"
    assert cfg["model"] == "deepseek-chat"
    assert cfg["provider"] == "deepseek"


def test_generic_openai_when_no_file(monkeypatch):
    _clear_env(monkeypatch)
    _set_local(monkeypatch, {})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    cfg = ai_settings.resolve_ai_config()
    assert cfg["source"] == "env"
    assert cfg["api_key"] == "sk-openai"
    assert cfg["base_url"] == "https://api.openai.com/v1"  # 默认


def test_none_when_unconfigured(monkeypatch):
    _clear_env(monkeypatch)
    _set_local(monkeypatch, {})
    cfg = ai_settings.resolve_ai_config()
    assert cfg["source"] == "none"
    assert cfg["api_key"] == ""


def test_base_url_trailing_slash_stripped(monkeypatch):
    _clear_env(monkeypatch)
    _set_local(monkeypatch, {"api_key": "k", "base_url": "https://x.com/v1/"})
    cfg = ai_settings.resolve_ai_config()
    assert cfg["base_url"] == "https://x.com/v1"


def test_mask_key():
    assert ai_settings.mask_key("sk-1234567890ab") == "sk-1...90ab"
    assert ai_settings.mask_key("short") == "***"
    assert ai_settings.mask_key("") == ""
