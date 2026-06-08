#!/usr/bin/env python3
"""AI-assisted transform plan generation via OpenAI-compatible API."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from ai_settings import resolve_ai_config

def ai_config() -> dict:
    return resolve_ai_config()


def ai_available() -> bool:
    return bool(ai_config()["api_key"])


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def ai_suggest_field_edits(
    *,
    table_key: str,
    fields: list[dict],
    table_note: str = "",
    join_rules: list[dict] | None = None,
    current_columns: list[str] | None = None,
    user_hint: str = "",
) -> dict[str, Any]:
    cfg = ai_config()
    if not cfg["api_key"]:
        raise RuntimeError("未配置 AI API Key")

    field_lines = []
    for f in fields:
        domain_hint = ""
        vd = f.get("value_domain") or []
        if vd:
            domain_hint = " | top=" + "|".join([str(d.get("值", ""))[:20] for d in vd[:3]])
        field_lines.append(
            f"- {f['field']}: {f.get('inferred_dtype')} | 缺失{f.get('null_pct')}% | {f.get('variable_content','')[:80]}{domain_hint}"
        )

    user_content = f"""## 表 {table_key}
## 用户补充要求
{user_hint or table_note or "（无，请按医疗数据常规清洗规范生成）"}

## 当前工作副本列名（意见中的列名必须与此一致）
{json.dumps(current_columns or [f['field'] for f in fields], ensure_ascii=False)}

## 字段画像（Raw 质控）
{chr(10).join(field_lines)}

## 表间关联规则（参考，便于保留/标注 ID 列）
{json.dumps((join_rules or [])[:20], ensure_ascii=False)[:4000]}

请为**每个字段**生成修改意见草稿。
"""

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": FIELD_EDIT_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    result = _extract_json(data["choices"][0]["message"]["content"])
    return {"suggestions": result, "model": cfg["model"]}


def ai_compile_field_operations(
    *,
    table_key: str,
    current_columns: list[str],
    field_instructions: list[dict],
    table_note: str = "",
    sample_csv: str = "",
) -> dict[str, Any]:
    cfg = ai_config()
    if not cfg["api_key"]:
        raise RuntimeError("未配置 AI API Key")

    user_content = f"""## 表 {table_key}
## 当前列名（working copy）
{json.dumps(current_columns, ensure_ascii=False)}

## 本表说明
{table_note}

## 字段修改意见
{json.dumps(field_instructions, ensure_ascii=False, indent=2)}

## 数据样例
{sample_csv[:4000]}
"""

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": COMPILE_OPS_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    result = _extract_json(data["choices"][0]["message"]["content"])
    return {"operations": result.get("operations", []), "model": cfg["model"]}
