#!/usr/bin/env python3
"""Self-contained QC profile + value domain engine (no external code deps)."""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import pandas as pd

FIELD_TYPES = ["空列", "数值型", "日期型", "分类/枚举型", "文本型", "ID型"]


def _default_sample_rows() -> int | None:
    """超大表画像采样行数上限。0 / 空 = 不采样（全量）。可用环境变量覆盖。"""
    raw = os.environ.get("PREPROCESS_PROFILE_SAMPLE_ROWS", "200000").strip()
    if not raw:
        return 200000
    try:
        n = int(raw)
    except ValueError:
        return 200000
    return None if n <= 0 else n


DEFAULT_SAMPLE_ROWS = _default_sample_rows()


def read_csv(path: Path, nrows: int | None = None) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, dtype=str, low_memory=False, encoding=enc, nrows=nrows)
        except Exception:
            continue
    raise ValueError(f"无法读取: {path}")


def table_key_from_file(path: Path) -> str:
    return path.stem


def infer_field_stats(series: pd.Series, row_count: int, forced_type: str | None = None) -> dict:
    col_series = series.astype(str).replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    non_null = int(col_series.notna().sum())
    null = int(row_count - non_null)
    unique = int(col_series.nunique(dropna=True))
    non_null_vals = col_series.dropna()

    # 已知类型时（精确重算/类型覆盖），跳过不必要的 to_numeric/to_datetime 全列解析，大幅提速
    need_numeric = forced_type in (None, "数值型")
    need_date = forced_type in (None, "日期型")

    if need_numeric:
        numeric_conv = pd.to_numeric(non_null_vals, errors="coerce")
        numeric_rate = float(numeric_conv.notna().sum() / non_null) if non_null else 0.0
    else:
        numeric_conv = pd.Series([], dtype=float)
        numeric_rate = 0.0

    if need_date:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            parsed_dates = pd.to_datetime(non_null_vals, errors="coerce")
        date_rate = float(parsed_dates.notna().sum() / non_null) if non_null else 0.0
    else:
        parsed_dates = pd.Series([], dtype="datetime64[ns]")
        date_rate = 0.0

    # 收紧日期判定，避免纯数字串（如 BIOID、代码列）被误判为日期：
    #  - 解析出的年份要落在合理区间（1900–2100），挡掉 0002/5335 这类
    #  - 取值要"长得像日期"（含 - / : 分隔符，或 8 位 yyyymmdd），挡掉纯数字
    is_date = False
    if forced_type is None and date_rate >= 0.9 and non_null >= 5:
        valid_dates = parsed_dates.dropna()
        plausible_year_rate = (
            float(((valid_dates.dt.year >= 1900) & (valid_dates.dt.year <= 2100)).sum() / len(valid_dates))
            if len(valid_dates)
            else 0.0
        )
        datey = non_null_vals.str.contains(r"[-/:]", regex=True, na=False) | non_null_vals.str.match(
            r"^\d{8}$", na=False
        )
        datey_rate = float(datey.sum() / non_null) if non_null else 0.0
        is_date = plausible_year_rate >= 0.9 and datey_rate >= 0.8

    if forced_type:
        inferred_type = forced_type
    elif non_null == 0:
        inferred_type = "空列"
    elif is_date:
        inferred_type = "日期型"
    elif numeric_rate >= 0.9 and non_null >= 5:
        inferred_type = "数值型"
    elif unique <= 50 or (non_null > 0 and unique / non_null < 0.01):
        inferred_type = "分类/枚举型"
    else:
        inferred_type = "文本型"

    content, value_domain = build_content_and_domain(
        col_series, inferred_type, numeric_conv, parsed_dates, unique
    )
    result = {
        "non_null": non_null,
        "null": null,
        "null_pct": round(null / row_count * 100, 2) if row_count else 0,
        "unique": unique,
        "inferred_dtype": inferred_type,
        "variable_content": content,
        "value_domain": value_domain,
    }
    if inferred_type == "数值型":
        nums = numeric_conv.dropna().astype(float)
        if not nums.empty:
            result["numeric_stats"] = {
                "min": float(nums.min()),
                "max": float(nums.max()),
                "mean": float(nums.mean()),
                "median": float(nums.median()),
            }
    if inferred_type == "日期型":
        dates = parsed_dates.dropna()
        if not dates.empty:
            result["date_stats"] = {
                "min": str(dates.min().date()),
                "max": str(dates.max().date()),
            }
    return result


def build_content_and_domain(
    col_series: pd.Series,
    inferred_type: str,
    numeric_conv: pd.Series,
    parsed_dates: pd.Series,
    unique: int,
) -> tuple[str, list[dict]]:
    if inferred_type == "空列":
        return "空列,全部缺失", []

    vc = col_series.dropna().value_counts()

    if inferred_type == "ID型":
        tops = "|".join([f"{idx}({int(v)})" for idx, v in vc.head(5).items()])
        content = f"ID型,去重数={unique}; top样例={tops}"
        domain = [
            {"值": str(k), "频次": int(v), "占比%": round(v * 100 / max(int(vc.sum()), 1), 2)}
            for k, v in vc.head(30).items()
        ]
        return content, domain

    if inferred_type == "数值型":
        nums = numeric_conv.dropna().astype(float)
        if not nums.empty:
            content = f"数值型,min={nums.min()}; max={nums.max()}; mean={nums.mean():.4g}"
        else:
            content = "数值型"
        return content, []

    if inferred_type == "日期型":
        dates = parsed_dates.dropna()
        if not dates.empty:
            content = f"日期型,min={dates.min().date()}; max={dates.max().date()}"
        else:
            content = "日期型"
        return content, []

    if inferred_type == "分类/枚举型" or (inferred_type == "文本型" and unique <= 200):
        domain = [
            {"值": str(k), "频次": int(v), "占比%": round(v * 100 / max(int(vc.sum()), 1), 2)}
            for k, v in vc.head(100).items()
        ]
        tops = "|".join([f"{idx}({int(v)})" for idx, v in vc.head(5).items()])
        content = f"{inferred_type},类别数={unique}; top={tops}"
        return content, domain

    if inferred_type == "文本型":
        content = f"非空去重数={unique}; top=未统计(文本过散)" if unique > 200 else f"非空去重数={unique}"
        domain = (
            [
                {"值": str(k), "频次": int(v), "占比%": round(v * 100 / max(int(vc.sum()), 1), 2)}
                for k, v in vc.head(50).items()
            ]
            if unique <= 200
            else []
        )
        return content, domain

    return inferred_type, []


def list_raw_tables(data_dir: Path) -> list[dict]:
    rows = []
    for p in sorted(data_dir.glob("*.csv")):
        try:
            df = read_csv(p, nrows=0)
            n = sum(1 for _ in open(p, encoding="utf-8", errors="ignore")) - 1
        except Exception:
            n = 0
            df = pd.DataFrame()
        key = table_key_from_file(p)
        rows.append({"file": p.name, "table_key": key, "rows": n, "columns": len(df.columns)})
    return rows


def profile_all_tables(
    data_dir: Path,
    type_overrides: dict[str, str] | None = None,
    sample_rows: int | None = "__default__",  # type: ignore[assignment]
) -> list[dict]:
    type_overrides = type_overrides or {}
    if sample_rows == "__default__":
        sample_rows = DEFAULT_SAMPLE_ROWS
    fields = []
    for p in sorted(data_dir.glob("*.csv")):
        df = read_csv(p, nrows=sample_rows)
        tkey = table_key_from_file(p)
        row_count = len(df)
        # 读到的行数达到上限 => 该表被截断采样，画像为样本估计
        sampled = bool(sample_rows) and row_count >= sample_rows
        for col in df.columns:
            key = f"{tkey}.{col}"
            override = type_overrides.get(key)
            stats = infer_field_stats(df[col], row_count, override)
            fields.append(
                {
                    "table": p.name,
                    "table_key": tkey,
                    "field": col,
                    "field_key": key,
                    "sampled": sampled,
                    "sample_rows": row_count if sampled else None,
                    **stats,
                }
            )
    return fields


def profile_single_table(
    data_dir: Path,
    table_file: str,
    type_overrides: dict[str, str] | None = None,
    sample_rows: int | None = "__default__",  # type: ignore[assignment]
) -> list[dict]:
    """画像单张表。sample_rows=None 时读全量（精确基数/缺失/值域）。"""
    type_overrides = type_overrides or {}
    if sample_rows == "__default__":
        sample_rows = DEFAULT_SAMPLE_ROWS
    p = data_dir / table_file
    df = read_csv(p, nrows=sample_rows)
    tkey = table_key_from_file(p)
    row_count = len(df)
    sampled = bool(sample_rows) and row_count >= sample_rows
    out = []
    for col in df.columns:
        key = f"{tkey}.{col}"
        override = type_overrides.get(key)
        stats = infer_field_stats(df[col], row_count, override)
        out.append(
            {
                "table": p.name,
                "table_key": tkey,
                "field": col,
                "field_key": key,
                "sampled": sampled,
                "sample_rows": row_count if sampled else None,
                **stats,
            }
        )
    return out


def recompute_field_domain(
    data_dir: Path,
    table_file: str,
    field: str,
    dtype: str,
    sample_rows: int | None = "__default__",  # type: ignore[assignment]
) -> dict:
    path = data_dir / table_file
    if sample_rows == "__default__":
        sample_rows = DEFAULT_SAMPLE_ROWS
    df = read_csv(path, nrows=sample_rows)
    if field not in df.columns:
        raise KeyError(field)
    tkey = table_key_from_file(path)
    row_count = len(df)
    sampled = bool(sample_rows) and row_count >= sample_rows
    stats = infer_field_stats(df[field], row_count, dtype)
    return {
        "table": table_file,
        "field": field,
        "field_key": f"{tkey}.{field}",
        "sampled": sampled,
        "sample_rows": row_count if sampled else None,
        **stats,
    }


def export_profile_csv(fields: list[dict], out_path: Path) -> None:
    import csv

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["原始变量名", "数值类型", "缺失数量", "缺失百分比", "变量内容"])
        for row in fields:
            w.writerow(
                [
                    row.get("field_key", ""),
                    row.get("inferred_dtype", ""),
                    row.get("null", ""),
                    row.get("null_pct", ""),
                    row.get("variable_content", ""),
                ]
            )
