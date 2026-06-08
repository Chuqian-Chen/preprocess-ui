#!/usr/bin/env python3
"""AI discovery of table join rules + mermaid diagram."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ai_transformer import _extract_json, ai_config
from join_analyzer import build_simple_mermaid
from transform_engine import build_schema_summary, sample_table_preview

JOIN_REFERENCE = """
参考格式（关联规则与示例.csv）列：
路径, 步骤, 左表, 左字段, 左值_示例, 右表, 右字段, 右值_示例, 匹配率, 备注

路径取值示例：A_住院 / B_门诊 / C_跨域
步骤示例：0-患者, 1-就诊枢纽, 2-LIS, 3-医嘱

典型模式（若数据匹配）：
- 住院：HIS.PATIENTID = EMR.主索引；LIS.住院号加住院次 → PATIENTID
- 门诊：基本信息.BRID = 门诊.BRID；门诊.VISITID → LIS.门诊就诊号
- 跨域：门诊.BRID → 基本信息 → 住院号=HIS.ZYHM
"""

JOIN_SYSTEM_PROMPT = f"""你是医疗结构化数据关联分析专家。根据字段画像、统计探查结果和数据样例，输出表间 join 规则。

{JOIN_REFERENCE}

只输出 JSON，格式：
{{
  "summary": "一句话总结关联结构",
  "paths": [
    {{"id": "A_住院", "name": "住院路径", "description": "..."}},
    {{"id": "B_门诊", "name": "门诊路径", "description": "..."}}
  ],
  "rules": [
    {{
      "路径": "A_住院",
      "步骤": "1-就诊枢纽",
      "左表": "表名(文件名stem)",
      "左字段": "列名",
      "左值_示例": "样例值",
      "右表": "右表名",
      "右字段": "列名",
      "右值_示例": "样例值",
      "匹配率": "98.9%",
      "备注": "说明"
    }}
  ],
  "key_ids": [
    {{"字段": "PATIENTID", "含义": "...", "样例": "...", "注意": "..."}}
  ],
  "pitfalls": ["常见误区1", "常见误区2"],
  "mermaid": "flowchart TB\\n  BASIC[\\"基本信息\\"] --> OUT[\\"门诊\\"]\\n  ..."
}}

规则：
- rules 按路径 A/B/C 分组，步骤有序
- 优先采用统计探查中高匹配率的列对，低匹配率需备注不确定性
- mermaid 用 flowchart TB，节点用中文表名缩写，边标注 join 字段
- 左表/右表名与上传 CSV 文件名 stem 一致
- 若某表无法关联，在备注说明
"""


def discover_join_rules_with_ai(
    *,
    fields: list[dict],
    table_files: list[str],
    raw_dir,
    probe_candidates: list[dict],
    max_sample_tables: int = 10,
) -> dict[str, Any]:
    cfg = ai_config()
    if not cfg["api_key"]:
        raise RuntimeError("未配置 AI API Key（PREPROCESS_AI_API_KEY 或 OPENAI_API_KEY）")

    schema = build_schema_summary(fields, max_tables=40, with_domain=True)
    probe_text = json.dumps(probe_candidates[:60], ensure_ascii=False, indent=2)

    samples = []
    for tf in table_files[:max_sample_tables]:
        try:
            samples.append(f"--- {tf} ---\n{sample_table_preview(raw_dir, tf, 2)}")
        except Exception:
            pass

    user_content = f"""请分析以下数据的表间关联方式。

## 字段画像
{schema}

## 统计探查（列值交集匹配率，样本）
{probe_text}

## 数据样例
{chr(10).join(samples)}

请输出完整 JSON（含 rules 与 mermaid 关联图）。
"""

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": JOIN_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.15,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}

    with httpx.Client(timeout=180.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    result = _extract_json(data["choices"][0]["message"]["content"])
    rules = result.get("rules") or []
    if not result.get("mermaid") and rules:
        result["mermaid"] = build_simple_mermaid(rules)
    result.setdefault("rules", rules)
    return {"discovery": result, "model": cfg["model"], "probe_count": len(probe_candidates)}


def rules_from_probe_only(probe_candidates: list[dict]) -> dict[str, Any]:
    """When AI unavailable, build minimal rules from statistical probe."""
    rules = []
    for i, c in enumerate(probe_candidates[:40]):
        path = "C_跨域" if i % 3 == 2 else ("B_门诊" if i % 3 == 1 else "A_住院")
        rules.append(
            {
                "路径": path,
                "步骤": f"探查-{i + 1}",
                "左表": c.get("左表", ""),
                "左字段": c.get("左字段", ""),
                "左值_示例": c.get("左值_示例", ""),
                "右表": c.get("右表", ""),
                "右字段": c.get("右字段", ""),
                "右值_示例": c.get("右值_示例", ""),
                "匹配率": c.get("匹配率", ""),
                "备注": c.get("备注", "统计探查，建议 AI 复核"),
            }
        )
    return {
        "summary": "基于列值交集的统计探查结果（未经过 AI 语义归纳）",
        "paths": [],
        "rules": rules,
        "mermaid": build_simple_mermaid(rules),
        "pitfalls": ["统计探查仅基于样本，同名不同义字段可能误匹配"],
    }
