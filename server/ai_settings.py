#!/usr/bin/env python3
"""Persist AI API settings from UI (local file, gitignored)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

UI_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = UI_ROOT / "config" / "ai_settings.local.json"

PROVIDER_PRESETS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "signup_url": "https://platform.openai.com/signup",
        "keys_url": "https://platform.openai.com/api-keys",
        "docs_url": "https://platform.openai.com/docs/api-reference/authentication",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "steps": [
            "注册 / 登录 OpenAI 账号",
            "打开 API Keys 页面，点击「Create new secret key」",
            "复制以 sk- 开头的密钥（只显示一次，请立即保存）",
            "粘贴到下方 API Key 输入框",
        ],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek（国产 · OpenAI 兼容）",
        "signup_url": "https://platform.deepseek.com/sign_in",
        "keys_url": "https://platform.deepseek.com/api_keys",
        "docs_url": "https://platform.deepseek.com/api-docs",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "steps": [
            "注册 DeepSeek 开放平台账号",
            "进入 API Keys 页面创建密钥",
            "复制 API Key 粘贴到下方",
            "Base URL 保持 https://api.deepseek.com/v1",
        ],
    },
    {
        "id": "moonshot",
        "name": "Moonshot / Kimi",
        "signup_url": "https://platform.moonshot.cn/console",
        "keys_url": "https://platform.moonshot.cn/console/api-keys",
        "docs_url": "https://platform.moonshot.cn/docs/api/chat",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "steps": [
            "登录 Kimi 开放平台控制台",
            "创建 API Key 并复制",
            "粘贴到下方",
        ],
    },
    {
        "id": "custom",
        "name": "其他 OpenAI 兼容接口",
        "signup_url": "",
        "keys_url": "",
        "docs_url": "",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "steps": [
            "向您的模型服务商获取 API Key 与 Base URL",
            "确保接口兼容 OpenAI /v1/chat/completions",
            "填入下方三项并测试连接",
        ],
    },
]


def load_local_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_local_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        SETTINGS_FILE.chmod(0o600)
    except Exception:
        pass


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-4:]


def resolve_ai_config() -> dict:
    """按「整组同源」解析，避免 key 与 base_url 串台（A 家钥匙敲 B 家门 → 401）。

    优先级（key/base_url/model 作为一个整体）：
      1. PREPROCESS_AI_* 专用环境变量（显式覆盖）
      2. 界面保存的本地配置（用户显式选过平台）
      3. 通用 OPENAI_API_KEY / OPENAI_BASE_URL
    """
    local = load_local_settings()
    default_base = "https://api.openai.com/v1"

    if os.environ.get("PREPROCESS_AI_API_KEY"):
        api_key = os.environ["PREPROCESS_AI_API_KEY"]
        base_url = os.environ.get("PREPROCESS_AI_BASE_URL") or default_base
        model = os.environ.get("PREPROCESS_AI_MODEL") or "gpt-4o-mini"
        source, provider = "env", local.get("provider", "")
    elif local.get("api_key"):
        api_key = local["api_key"]
        base_url = local.get("base_url") or default_base
        model = local.get("model") or "gpt-4o-mini"
        source, provider = "file", local.get("provider", "")
    elif os.environ.get("OPENAI_API_KEY"):
        api_key = os.environ["OPENAI_API_KEY"]
        base_url = os.environ.get("OPENAI_BASE_URL") or default_base
        model = os.environ.get("PREPROCESS_AI_MODEL") or "gpt-4o-mini"
        source, provider = "env", ""
    else:
        api_key, base_url, model = "", default_base, "gpt-4o-mini"
        source, provider = "none", ""

    return {
        "api_key": api_key.strip(),
        "base_url": base_url.rstrip("/"),
        "model": model,
        "source": source,
        "provider": provider,
    }


def get_public_settings() -> dict:
    cfg = resolve_ai_config()
    local = load_local_settings()
    return {
        "configured": bool(cfg["api_key"]),
        "source": cfg["source"],
        "provider": local.get("provider") or cfg.get("provider") or "",
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "key_hint": mask_key(cfg["api_key"]),
        "providers": PROVIDER_PRESETS,
        "env_override": cfg["source"] == "env",
    }


def save_settings_from_ui(
    *,
    api_key: str,
    base_url: str,
    model: str,
    provider: str = "",
) -> dict:
    data = load_local_settings()
    if api_key.strip():
        data["api_key"] = api_key.strip()
    elif not data.get("api_key") and not (
        os.environ.get("PREPROCESS_AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    ):
        raise ValueError("请填写 API Key")
    data["base_url"] = (base_url or "https://api.openai.com/v1").rstrip("/")
    data["model"] = model or "gpt-4o-mini"
    data["provider"] = provider
    save_local_settings(data)
    return get_public_settings()


def test_connection(api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> dict:
    cfg = resolve_ai_config()
    key = (api_key or cfg["api_key"]).strip()
    url_base = (base_url or cfg["base_url"]).rstrip("/")
    mdl = model or cfg["model"]
    if not key:
        raise ValueError("请先填写 API Key")

    url = url_base + "/chat/completions"
    payload = {
        "model": mdl,
        "messages": [{"role": "user", "content": "回复 OK"}],
        "max_tokens": 5,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"ok": True, "model": mdl, "reply": reply.strip()[:50]}
