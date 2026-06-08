"""qc_engine：类型推断 / 值域 / 采样 的回归测试。"""

import pandas as pd
import pytest

from qc_engine import (
    build_content_and_domain,
    infer_field_stats,
    profile_all_tables,
)


def _stats(values, forced=None):
    s = pd.Series(values, dtype="object")
    return infer_field_stats(s, len(s), forced)


def test_infer_numeric():
    r = _stats(["1", "2", "3", "4", "5", "6"])
    assert r["inferred_dtype"] == "数值型"
    assert r["numeric_stats"]["min"] == 1.0
    assert r["numeric_stats"]["max"] == 6.0


def test_infer_date():
    r = _stats(["2020-01-01", "2020-06-15", "2021-12-31", "2019-03-03", "2022-05-05"])
    assert r["inferred_dtype"] == "日期型"
    assert "date_stats" in r
    assert r["date_stats"]["min"] == "2019-03-03"


def test_infer_category():
    # 取值很少 → 分类
    r = _stats(["男", "女", "男", "女", "男", "女", "男"])
    assert r["inferred_dtype"] == "分类/枚举型"
    assert r["unique"] == 2


def test_infer_text_high_cardinality():
    vals = [f"自由文本描述-{i}-{'x' * (i % 7)}" for i in range(300)]
    r = _stats(vals)
    assert r["inferred_dtype"] == "文本型"


def test_empty_column():
    r = _stats(["", "", None, "nan"])
    assert r["inferred_dtype"] == "空列"
    assert r["null"] == 4
    assert r["null_pct"] == 100.0


def test_forced_id_type_overrides_inference():
    # 看似数值，但强制为 ID 型
    r = _stats(["1001", "1002", "1003", "1004", "1005"], forced="ID型")
    assert r["inferred_dtype"] == "ID型"
    # ID 型给出 top 样例值域
    assert isinstance(r["value_domain"], list)
    assert r["value_domain"], "ID 型应有频次值域"


def test_null_pct_computation():
    r = _stats(["a", "a", "b", "", None])  # 5 行，2 个缺失
    assert r["null"] == 2
    assert r["null_pct"] == 40.0


def test_category_domain_has_counts():
    s = pd.Series(["A", "A", "B"], dtype="object")
    content, domain = build_content_and_domain(
        s, "分类/枚举型", pd.to_numeric(s, errors="coerce"), pd.Series([], dtype="datetime64[ns]"), 2
    )
    top = {d["值"]: d["频次"] for d in domain}
    assert top["A"] == 2 and top["B"] == 1


def test_profile_sampling_flag(tmp_path, monkeypatch):
    # 构造一个比采样上限略大的表，验证 sampled 标记与行数限制
    import qc_engine

    monkeypatch.setattr(qc_engine, "DEFAULT_SAMPLE_ROWS", 100)
    n = 250
    df = pd.DataFrame({"id": range(n), "grp": ["x" if i % 2 else "y" for i in range(n)]})
    p = tmp_path / "big.csv"
    df.to_csv(p, index=False, encoding="utf-8-sig")

    fields = profile_all_tables(tmp_path)
    by = {f["field"]: f for f in fields}
    # 采样后 non_null 应等于采样上限（100），而非全量 250
    assert by["id"]["sampled"] is True
    assert by["id"]["non_null"] == 100


def test_profile_small_table_not_sampled(tmp_path, monkeypatch):
    import qc_engine

    monkeypatch.setattr(qc_engine, "DEFAULT_SAMPLE_ROWS", 100000)
    df = pd.DataFrame({"v": ["a", "b", "c"]})
    (tmp_path / "small.csv").write_text(df.to_csv(index=False), encoding="utf-8-sig")
    fields = profile_all_tables(tmp_path)
    assert fields[0]["sampled"] is False
