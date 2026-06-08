"""transform_engine.apply_operation：9 种白名单操作 + 未知操作拒绝。"""

import pandas as pd
import pytest

from transform_engine import apply_operation


def _df():
    return pd.DataFrame(
        {
            "A": ["1", "2", "3"],
            "B": ["x", "y", "z"],
            "C": [" a ", "b", None],
        }
    )


def test_rename_column():
    out = apply_operation(_df(), {"action": "rename_column", "from": "A", "to": "AA"})
    assert "AA" in out.columns and "A" not in out.columns


def test_rename_missing_column_noop():
    out = apply_operation(_df(), {"action": "rename_column", "from": "ZZ", "to": "QQ"})
    assert "QQ" not in out.columns  # 源列不存在则不改


def test_drop_columns():
    out = apply_operation(_df(), {"action": "drop_columns", "columns": ["B", "NOPE"]})
    assert "B" not in out.columns and "A" in out.columns


def test_merge_columns():
    out = apply_operation(
        _df(),
        {"action": "merge_columns", "columns": ["A", "B"], "target": "AB", "separator": "-", "drop_sources": True},
    )
    assert out["AB"].tolist() == ["1-x", "2-y", "3-z"]
    assert "A" not in out.columns and "B" not in out.columns


def test_merge_columns_keep_sources():
    out = apply_operation(
        _df(),
        {"action": "merge_columns", "columns": ["A", "B"], "target": "AB", "separator": "", "drop_sources": False},
    )
    assert "A" in out.columns and "B" in out.columns and "AB" in out.columns


def test_fillna():
    out = apply_operation(_df(), {"action": "fillna", "column": "C", "value": "FILL"})
    assert out["C"].tolist() == [" a ", "b", "FILL"]


def test_map_values():
    out = apply_operation(_df(), {"action": "map_values", "column": "B", "mapping": {"x": "X", "y": "Y"}})
    assert out["B"].tolist() == ["X", "Y", "z"]


def test_strip_whitespace():
    out = apply_operation(_df(), {"action": "strip_whitespace", "columns": ["C"]})
    assert out["C"].tolist()[0] == "a"


def test_dedupe():
    df = pd.DataFrame({"k": ["a", "a", "b"], "v": [1, 1, 2]})
    out = apply_operation(df, {"action": "dedupe", "columns": ["k"], "keep": "first"})
    assert out["k"].tolist() == ["a", "b"]


def test_filter_rows():
    out = apply_operation(_df(), {"action": "filter_rows", "column": "B", "values": ["x", "z"]})
    assert out["B"].tolist() == ["x", "z"]


def test_select_columns():
    out = apply_operation(_df(), {"action": "select_columns", "columns": ["A", "C"]})
    assert list(out.columns) == ["A", "C"]


def test_unknown_action_raises():
    with pytest.raises(ValueError):
        apply_operation(_df(), {"action": "DROP TABLE; rm -rf /"})


def test_does_not_mutate_input():
    df = _df()
    apply_operation(df, {"action": "drop_columns", "columns": ["A"]})
    assert "A" in df.columns  # 原 df 不被改动
