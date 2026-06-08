#!/usr/bin/env python3
"""Statistical join-key discovery across raw CSV tables."""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

import pandas as pd

from qc_engine import list_raw_tables, read_csv, table_key_from_file

KEY_NAME_HINTS = re.compile(
    r"(?i)id$|patient|visit|brid|zyhm|zyh|mzhm|索引|档案|住院号|门诊|医嘱号|就诊|主键|编号|流水",
)

ID_LIKE_TYPES = {"ID型", "分类/枚举型", "数值型", "文本型"}


def _sample_series(path: Path, col: str, max_rows: int = 12000) -> pd.Series:
    try:
        df = read_csv(path, nrows=max_rows)
    except Exception:
        return pd.Series(dtype=str)
    if col not in df.columns:
        return pd.Series(dtype=str)
    s = df[col].astype(str).str.strip()
    return s.replace({"nan": pd.NA, "None": pd.NA, "": pd.NA}).dropna()


def _candidate_columns(table_key: str, fields: list[dict], all_cols: list[str]) -> list[str]:
    by_field = {f["field"]: f for f in fields if f.get("table_key") == table_key}
    scored: list[tuple[int, str]] = []
    for col in all_cols:
        score = 0
        meta = by_field.get(col, {})
        dtype = meta.get("inferred_dtype", "")
        unique = meta.get("unique") or 0
        non_null = meta.get("non_null") or 1
        if dtype == "ID型":
            score += 50
        if KEY_NAME_HINTS.search(col):
            score += 30
        if unique > 1 and non_null and unique / non_null > 0.01:
            score += 5
        if unique > 50000:
            score -= 10
        if score > 0:
            scored.append((score, col))
    scored.sort(reverse=True)
    return [c for _, c in scored[:12]]


def _match_stats(left_vals: set[str], right_vals: set[str]) -> dict:
    if not left_vals or not right_vals:
        return {"intersection": 0, "match_rate": 0.0, "left_rate": 0.0, "right_rate": 0.0}
    inter = left_vals & right_vals
    n = len(inter)
    lr = len(left_vals)
    rr = len(right_vals)
    return {
        "intersection": n,
        "match_rate": round(n / min(lr, rr) * 100, 1) if min(lr, rr) else 0.0,
        "left_rate": round(n / lr * 100, 1) if lr else 0.0,
        "right_rate": round(n / rr * 100, 1) if rr else 0.0,
    }


def probe_join_candidates(
    raw_dir: Path,
    fields: list[dict],
    *,
    min_match_rate: float = 15.0,
    max_pairs: int = 80,
    sample_rows: int = 12000,
) -> list[dict]:
    tables = list_raw_tables(raw_dir)
    if len(tables) < 2:
        return []

    col_cache: dict[str, dict[str, set[str]]] = {}
    table_cols: dict[str, list[str]] = {}

    for t in tables:
        path = raw_dir / t["file"]
        try:
            df_head = read_csv(path, nrows=0)
            cols = list(df_head.columns)
        except Exception:
            continue
        table_cols[t["table_key"]] = cols
        col_cache[t["table_key"]] = {}
        for col in _candidate_columns(t["table_key"], fields, cols):
            series = _sample_series(path, col, sample_rows)
            vals = set(series.head(8000).astype(str).tolist())
            if vals:
                col_cache[t["table_key"]][col] = vals

    candidates: list[dict] = []
    keys = [t["table_key"] for t in tables]
    for left_key, right_key in combinations(keys, 2):
        for lcol, lvals in col_cache.get(left_key, {}).items():
            for rcol, rvals in col_cache.get(right_key, {}).items():
                stats = _match_stats(lvals, rvals)
                if stats["match_rate"] < min_match_rate or stats["intersection"] < 3:
                    continue
                l_sample = next(iter(lvals & rvals), next(iter(lvals), ""))
                r_sample = next(iter(rvals & lvals), l_sample)
                candidates.append(
                    {
                        "左表": left_key,
                        "左字段": lcol,
                        "左值_示例": l_sample,
                        "右表": right_key,
                        "右字段": rcol,
                        "右值_示例": r_sample,
                        "匹配率": f"{stats['match_rate']}%",
                        "匹配率数值": stats["match_rate"],
                        "交集数": stats["intersection"],
                        "左覆盖率": f"{stats['left_rate']}%",
                        "右覆盖率": f"{stats['right_rate']}%",
                        "备注": f"样本探查 n≤{sample_rows}",
                    }
                )

    candidates.sort(key=lambda x: (-x["匹配率数值"], -x["交集数"]))
    return candidates[:max_pairs]


def export_rules_csv(rules: list[dict], out_path: Path) -> None:
    import csv

    cols = ["路径", "步骤", "左表", "左字段", "左值_示例", "右表", "右字段", "右值_示例", "匹配率", "备注"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rules:
            w.writerow(r)


def build_simple_mermaid(rules: list[dict]) -> str:
    """Fallback diagram from rules when AI does not return mermaid."""
    if not rules:
        return "flowchart TB\n  empty[暂无关联规则]"

    nodes: set[str] = set()
    edges: list[str] = []
    seen_edge: set[str] = set()

    for r in rules:
        left = (r.get("左表") or "").strip()
        right = (r.get("右表") or "").strip()
        if not left:
            continue
        nodes.add(left)
        lid = _mermaid_id(left)
        if right:
            nodes.add(right)
            rid = _mermaid_id(right)
            lf = r.get("左字段", "")
            rf = r.get("右字段", "")
            label = f"{lf}→{rf}".replace('"', "'")
            key = f"{left}|{right}|{label}"
            if key not in seen_edge:
                seen_edge.add(key)
                edges.append(f'  {lid} -->|"{label}"| {rid}')

    lines = ["flowchart TB"]
    for n in sorted(nodes):
        lines.append(f'  {_mermaid_id(n)}["{n}"]')
    lines.extend(edges[:40])
    return "\n".join(lines)


def _mermaid_id(name: str) -> str:
    s = re.sub(r"[^\w]", "_", name)
    return f"T_{s[:40]}"
