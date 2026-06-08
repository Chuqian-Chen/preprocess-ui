#!/usr/bin/env python3
"""AI-assisted transform plan generation via OpenAI-compatible API."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from transform_engine import build_schema_summary, sample_table_preview

from ai_settings import resolve_ai_config

SYSTEM_PROMPT = """你是医疗结构化数据预处理专家。根据用户的预处理意见、字段画像和表结构，生成 JSON 格式的清洗方案。

只输出 JSON，不要 markdown 代码块，不要额外解释。格式：
{
  "summary": "方案一句话摘要",
  "tables": {
    "文件名.csv": {
      "output": "输出文件名_clean.csv",
      "operations": [
        {"action": "rename_column", "from": "旧列名", "to": "新列名"},
        {"action": "drop_columns", "columns": ["列A"]},
        {"action": "merge_columns", "columns": ["列1","列2"], "target": "合并列", "separator": " ", "drop_sources": true},
        {"action": "fillna", "column": "列名", "value": ""},
        {"action": "map_values", "column": "列名", "mapping": {"旧值": "新值"}},
        {"action": "strip_whitespace", "columns": ["列名"]},
        {"action": "dedupe", "columns": ["主键列"], "keep": "first"},
        {"action": "filter_rows", "column": "列名", "values": ["保留值1"]},
        {"action": "select_columns", "columns": ["保留列1","保留列2"]}
      ]
    }
  },
  "join_notes": "表间关联说明（文字，不执行 join）"
}

规则：
- operations 仅使用上述 action，不要生成 Python 代码
- 文件名必须与输入文件完全一致
- 尊重用户指定的列名修改、合并、删除、标准化意图
- 若意见模糊，做保守、可解释的变换
"""


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


def generate_transform_plan(
    *,
    instructions: str,
    fields: list[dict],
    join_rules: list[dict] | None,
    table_files: list[str],
    raw_dir,
    sample_rows: int = 3,
) -> dict[str, Any]:
    cfg = ai_config()
    if not cfg["api_key"]:
        raise RuntimeError(
            "未配置 AI API Key。请设置环境变量 PREPROCESS_AI_API_KEY 或 OPENAI_API_KEY"
        )

    schema = build_schema_summary(fields)
    samples = []
    for tf in table_files[:8]:
        try:
            samples.append(f"--- {tf} 样例 ---\n{sample_table_preview(raw_dir, tf, sample_rows)}")
        except Exception:
            pass

    join_text = json.dumps(join_rules or [], ensure_ascii=False, indent=2)[:4000]
    user_content = f"""## 用户预处理意见
{instructions}

## 当前数据表文件
{json.dumps(table_files, ensure_ascii=False)}

## 字段画像
{schema}

## 表间关联规则（参考）
{join_text}

## 数据样例
{chr(10).join(samples)}
"""

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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

    content = data["choices"][0]["message"]["content"]
    plan = _extract_json(content)
    return {"plan": plan, "model": cfg["model"], "usage": data.get("usage")}


def refine_plan_with_feedback(
    *,
    current_plan: dict,
    feedback: str,
    fields: list[dict],
) -> dict[str, Any]:
    cfg = ai_config()
    if not cfg["api_key"]:
        raise RuntimeError("未配置 AI API Key")

    user_content = f"""请根据用户反馈修订清洗方案，只输出完整 JSON（格式同前）。

## 当前方案
{json.dumps(current_plan, ensure_ascii=False, indent=2)}

## 用户反馈
{feedback}

## 字段画像摘要
{build_schema_summary(fields, max_tables=20)}
"""
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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

    plan = _extract_json(data["choices"][0]["message"]["content"])
    return {"plan": plan, "model": cfg["model"]}


FIELD_EDIT_SYSTEM = """你是医疗结构化数据清洗专家。任务：根据 Raw 质控字段画像，为**每一个字段**撰写可执行的「修改意见」草稿，供人工审阅后应用。

只输出 JSON：
{
  "fields": {
    "字段名": "修改意见"
  },
  "table_note": "本表整体清洗思路（一句话）"
}

修改意见写法（择一，简洁明确）：
- 无需改动：`保留`
- 重命名：`改名为 中文列名`
- 删除冗余列：`删除`（并简述原因）
- 合并：`与列A、列B合并为「结果」，删除源列`
- 标准化：`去空格` / `统一日期格式` / `映射值：旧值→新值`
- ID/键列：`保留，作为关联键`

规则：
- **必须覆盖表中每一个字段**，不要遗漏
- 列名必须与「当前工作列名」完全一致
- 结合字段类型、缺失率、值域摘要做判断
- 英文列名优先建议规范中文名（若语义清晰）
- 明显冗余、重复、无分析价值的列建议删除并说明
- 不要输出 Python 代码或 JSON 操作
- 这是 AI 草稿，用户会审阅修改，意见要具体可执行
"""

COMPILE_OPS_SYSTEM = """将字段级修改意见编译为结构化 operations JSON。

只输出 JSON：
{
  "operations": [
    {"action": "rename_column", "from": "旧名", "to": "新名"},
    {"action": "drop_columns", "columns": ["列"]},
    {"action": "merge_columns", "columns": ["A","B"], "target": "合并列", "separator": " ", "drop_sources": true},
    {"action": "strip_whitespace", "columns": ["列"]},
    {"action": "map_values", "column": "列", "mapping": {"旧":"新"}},
    {"action": "fillna", "column": "列", "value": ""},
    {"action": "select_columns", "columns": ["保留列"]},
    {"action": "dedupe", "columns": ["键列"], "keep": "first"}
  ]
}

规则：
- 仅使用上述 action
- from/columns 必须存在于「当前列名」列表
- 按合理顺序排列（先 merge/rename 再 drop）
"""


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
