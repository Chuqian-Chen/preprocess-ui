#!/usr/bin/env python3
"""Apply structured transform plans safely (no arbitrary code exec)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from qc_engine import read_csv, table_key_from_file


def load_table(raw_dir: Path, table_file: str) -> pd.DataFrame:
    return read_csv(raw_dir / table_file)


def apply_operation(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    action = op.get("action", "")
    out = df.copy()

    if action == "rename_column":
        src, dst = op["from"], op["to"]
        if src in out.columns:
            out = out.rename(columns={src: dst})
        return out

    if action == "drop_columns":
        cols = [c for c in op.get("columns", []) if c in out.columns]
        return out.drop(columns=cols, errors="ignore")

    if action == "merge_columns":
        cols = [c for c in op.get("columns", []) if c in out.columns]
        sep = op.get("separator", " ")
        target = op["target"]
        out[target] = out[cols].fillna("").astype(str).agg(sep.join, axis=1).str.strip()
        if op.get("drop_sources"):
            out = out.drop(columns=cols, errors="ignore")
        return out

    if action == "fillna":
        col = op["column"]
        if col in out.columns:
            out[col] = out[col].replace({"": pd.NA, "nan": pd.NA}).fillna(op.get("value", ""))
        return out

    if action == "map_values":
        col = op["column"]
        mapping = op.get("mapping", {})
        if col in out.columns:
            out[col] = out[col].replace(mapping)
        return out

    if action == "strip_whitespace":
        cols = op.get("columns") or list(out.columns)
        for c in cols:
            if c in out.columns:
                out[c] = out[c].astype(str).str.strip().replace({"nan": pd.NA, "None": pd.NA})
        return out

    if action == "dedupe":
        subset = op.get("columns")
        return out.drop_duplicates(subset=subset, keep=op.get("keep", "first"))

    if action == "filter_rows":
        col = op["column"]
        values = set(op.get("values", []))
        if col in out.columns and values:
            out = out[out[col].isin(values)]
        return out

    if action == "select_columns":
        cols = [c for c in op.get("columns", []) if c in out.columns]
        return out[cols] if cols else out

    raise ValueError(f"不支持的操作: {action}")


def apply_plan(raw_dir: Path, output_dir: Path, plan: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    results = []

    for table_file, spec in (plan.get("tables") or {}).items():
        src_path = raw_dir / table_file
        if not src_path.exists():
            log.append(f"[SKIP] 文件不存在: {table_file}")
            continue
        df = load_table(raw_dir, table_file)
        log.append(f"\n=== {table_file} ({len(df)} 行) ===")
        for i, op in enumerate(spec.get("operations") or [], 1):
            try:
                df = apply_operation(df, op)
                log.append(f"  {i}. {op.get('action')} OK")
            except Exception as e:
                log.append(f"  {i}. {op.get('action')} FAIL: {e}")
                raise

        out_name = spec.get("output") or table_file.replace(".csv", "_clean.csv")
        out_path = output_dir / out_name
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        log.append(f"  → 输出 {out_name} ({len(df)} 行, {len(df.columns)} 列)")
        results.append({"input": table_file, "output": out_name, "rows": len(df), "columns": len(df.columns)})

    return {"results": results, "log": "\n".join(log)}


def build_schema_summary(
    fields: list[dict], max_tables: int = 30, with_domain: bool = False, domain_top: int = 15
) -> str:
    by_table: dict[str, list[dict]] = {}
    for f in fields:
        by_table.setdefault(f.get("table_key", ""), []).append(f)
    lines = []
    for tkey in sorted(by_table.keys())[:max_tables]:
        lines.append(f"表 {tkey}:")
        for f in by_table[tkey][:40]:
            lines.append(
                f"  - {f['field']}: {f.get('inferred_dtype')} | 缺失{f.get('null_pct')}% | {f.get('variable_content','')[:80]}"
            )
            # 关联识别时，把 ID/分类 字段的完整 top 值域喂给 AI（更利于判断列对是否能 join）
            if with_domain and f.get("inferred_dtype") in ("ID型", "分类/枚举型"):
                dom = f.get("value_domain") or []
                if dom:
                    vals = ", ".join(f"{r.get('值')}({r.get('频次')})" for r in dom[:domain_top])
                    lines.append(f"      值域top: {vals}")
    return "\n".join(lines)


def sample_table_preview(raw_dir: Path, table_file: str, n: int = 3) -> str:
    df = load_table(raw_dir, table_file)
    return df.head(n).to_csv(index=False)
