#!/usr/bin/env python3
"""数据分析：列分布（数值直方图 / 分类频次），供可视化使用。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qc_engine import DEFAULT_SAMPLE_ROWS, read_csv


def _numeric_histogram(values: pd.Series, bins: int = 20) -> dict:
    nums = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if nums.empty:
        return {"kind": "empty", "data": []}
    nbins = int(min(bins, max(1, nums.nunique())))
    counts, edges = np.histogram(nums, bins=nbins)
    data = [
        {"label": f"{edges[i]:.4g}~{edges[i + 1]:.4g}", "count": int(counts[i])}
        for i in range(len(counts))
    ]
    return {
        "kind": "numeric",
        "data": data,
        "stats": {
            "min": float(nums.min()),
            "max": float(nums.max()),
            "mean": float(nums.mean()),
            "median": float(nums.median()),
            "count": int(nums.size),
        },
    }


def _category_distribution(values: pd.Series, top: int = 20) -> dict:
    vc = values.dropna().astype(str).value_counts()
    total = int(vc.sum()) or 1
    data = [
        {"label": str(k), "count": int(v), "pct": round(v * 100 / total, 2)}
        for k, v in vc.head(top).items()
    ]
    return {"kind": "category", "data": data, "unique": int(vc.size), "total": total}


def column_distribution(path: Path, field: str, sample_rows: int | None = "__default__") -> dict:  # type: ignore[assignment]
    if sample_rows == "__default__":
        sample_rows = DEFAULT_SAMPLE_ROWS
    df = read_csv(path, nrows=sample_rows)
    if field not in df.columns:
        raise KeyError(field)
    row_count = len(df)
    sampled = bool(sample_rows) and row_count >= sample_rows
    s = df[field].astype(str).replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})
    non_null = s.dropna()
    if non_null.empty:
        return {"kind": "empty", "data": [], "sampled": sampled}
    numeric_rate = float(pd.to_numeric(non_null, errors="coerce").notna().mean())
    # 数值且去重较多 → 直方图；否则按类别频次
    if numeric_rate >= 0.9 and non_null.nunique() > 20:
        out = _numeric_histogram(non_null)
    else:
        out = _category_distribution(s)
    out["sampled"] = sampled
    out["non_null"] = int(non_null.size)
    return out
