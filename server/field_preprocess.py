#!/usr/bin/env python3
"""Per-field preprocess edits: working copy in output/, never modify raw/."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from project_manager import config_dir, load_json_config, output_dir, raw_dir, resolve_csv_file, save_json_config
from qc_engine import read_csv, table_key_from_file
from transform_engine import apply_operation

FIELD_EDITS_FILE = "field_edits.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_output_name(table_file: str) -> str:
    stem = Path(table_file).stem
    return f"{stem}_clean.csv"


def load_field_edits(project_id: str) -> dict:
    return load_json_config(project_id, FIELD_EDITS_FILE, {"tables": {}})


def save_field_edits(project_id: str, data: dict) -> None:
    save_json_config(project_id, FIELD_EDITS_FILE, data)


def get_table_config(project_id: str, table_key: str, raw_file: str | None = None) -> dict:
    edits = load_field_edits(project_id)
    tables = edits.setdefault("tables", {})
    if table_key not in tables:
        rf = raw_file or resolve_csv_file(project_id, table_key)
        tables[table_key] = {
            "table_key": table_key,
            "raw_file": rf,
            "output_file": default_output_name(rf),
            "table_note": "",
            "fields": {},
            "history": [],
        }
        save_field_edits(project_id, edits)
    return tables[table_key]


def resolve_working_source(project_id: str, table_key: str) -> tuple[Path, str, str]:
    """Return (read_path, source_kind, output_file_name). Never returns raw for write."""
    cfg = get_table_config(project_id, table_key)
    out_name = cfg.get("output_file") or default_output_name(cfg["raw_file"])
    out_path = output_dir(project_id) / out_name
    raw_path = raw_dir(project_id) / cfg["raw_file"]
    if out_path.exists():
        return out_path, "output", out_name
    if not raw_path.exists():
        raise FileNotFoundError(f"源文件不存在: {cfg['raw_file']}")
    return raw_path, "raw", out_name


def list_preprocess_tables(project_id: str, profile_fields: list[dict]) -> list[dict]:
    by_table: dict[str, list] = {}
    for f in profile_fields:
        by_table.setdefault(f.get("table_key", ""), []).append(f)

    rows = []
    for tkey in sorted(by_table.keys()):
        if not tkey:
            continue
        try:
            raw_file = by_table[tkey][0].get("table") or resolve_csv_file(project_id, tkey)
        except FileNotFoundError:
            raw_file = tkey + ".csv"
        cfg = get_table_config(project_id, tkey, raw_file)
        try:
            src, kind, out_name = resolve_working_source(project_id, tkey)
            ncols = len(read_csv(src, nrows=0).columns)
            nrows = sum(1 for _ in open(src, encoding="utf-8", errors="ignore")) - 1
        except Exception:
            kind, out_name, ncols, nrows = "raw", cfg.get("output_file", ""), 0, 0
        field_edits = cfg.get("fields", {})
        pending = sum(1 for v in field_edits.values() if (v.get("instruction") or "").strip())
        ai_draft = bool(cfg.get("ai_generated_at"))
        rows.append(
            {
                "table_key": tkey,
                "raw_file": cfg.get("raw_file"),
                "output_file": out_name,
                "working_source": kind,
                "field_count": len(by_table[tkey]),
                "edit_count": pending,
                "output_exists": (output_dir(project_id) / out_name).exists(),
                "rows": nrows,
                "columns": ncols,
                "updated_at": cfg.get("updated_at"),
                "ai_generated_at": cfg.get("ai_generated_at"),
                "ai_draft": ai_draft,
                "review_status": cfg.get("review_status", "pending" if not ai_draft else "ai_draft"),
            }
        )
    return rows


def merge_fields_with_edits(profile_fields: list[dict], table_key: str, cfg: dict) -> list[dict]:
    table_fields = [f for f in profile_fields if f.get("table_key") == table_key]
    field_edits = cfg.get("fields", {})
    merged = []
    for f in table_fields:
        fe = field_edits.get(f["field"], {})
        merged.append(
            {
                **f,
                "instruction": fe.get("instruction", ""),
                "edit_source": fe.get("source", ""),
                "edit_status": fe.get("status", "pending"),
                "last_applied_at": fe.get("last_applied_at"),
            }
        )
    return merged


def save_table_edits(
    project_id: str,
    table_key: str,
    *,
    table_note: str | None = None,
    fields: dict[str, str] | None = None,
    from_ai: bool = False,
    ai_model: str | None = None,
    mark_reviewed: bool = False,
) -> dict:
    cfg = get_table_config(project_id, table_key)
    if table_note is not None:
        cfg["table_note"] = table_note
    if fields is not None:
        for fname, instr in fields.items():
            entry = cfg["fields"].setdefault(fname, {})
            entry["instruction"] = instr
            if instr.strip():
                if from_ai:
                    entry["source"] = "ai"
                    entry["status"] = "draft"
                    entry.pop("last_applied_at", None)
                elif mark_reviewed:
                    entry["source"] = entry.get("source") or "user"
                    entry["status"] = "draft"
    if from_ai:
        cfg["ai_generated_at"] = _now()
        cfg["ai_model"] = ai_model
        cfg["review_status"] = "ai_draft"
    elif mark_reviewed:
        cfg["review_status"] = "reviewed"
    cfg["updated_at"] = _now()
    edits = load_field_edits(project_id)
    edits["tables"][table_key] = cfg
    save_field_edits(project_id, edits)
    return cfg


def run_ai_fill_table(
    project_id: str,
    table_key: str,
    profile_fields: list[dict],
    *,
    table_note: str = "",
    user_hint: str = "",
) -> dict:
    from ai_transformer import ai_suggest_field_edits

    fields = profile_fields
    cfg = get_table_config(project_id, table_key)
    merged = merge_fields_with_edits(fields, table_key, cfg)
    join_rules = load_json_config(project_id, "join_rules.json", {}).get("rules", [])
    src, _, _ = resolve_working_source(project_id, table_key)
    current_columns = list(read_csv(src, nrows=0).columns)

    result = ai_suggest_field_edits(
        table_key=table_key,
        fields=merged,
        table_note=table_note,
        join_rules=join_rules,
        current_columns=current_columns,
        user_hint=user_hint or table_note,
    )
    suggestions = result.get("suggestions", {})
    field_map = suggestions.get("fields") or {}
    # Ensure every profile field has an entry
    for f in merged:
        if f["field"] not in field_map:
            field_map[f["field"]] = "保留"
    note = suggestions.get("table_note") or table_note
    save_table_edits(
        project_id,
        table_key,
        table_note=note,
        fields=field_map,
        from_ai=True,
        ai_model=result.get("model"),
    )
    return {
        "fields": field_map,
        "table_note": note,
        "model": result.get("model"),
        "table_key": table_key,
    }


def _parse_instruction(field: str, instruction: str) -> list[dict]:
    """Rule-based fallback when AI unavailable."""
    text = instruction.strip()
    if not text or text in ("-", "保留", "keep", "不变"):
        return []

    ops: list[dict] = []

    m = re.search(r"(?:rename|改名(?:为|成)?|重命名(?:为|成)?)\s*[「\"']?(.+?)[」\"']?\s*$", text, re.I)
    if m:
        ops.append({"action": "rename_column", "from": field, "to": m.group(1).strip()})
        return ops

    if re.search(r"删除|drop|去掉", text, re.I):
        ops.append({"action": "drop_columns", "columns": [field]})
        return ops

    m = re.search(r"合并.*?[为到]\s*[「\"']?(.+?)[」\"']?\s*$", text)
    if m:
        others = re.findall(r"[「\"'](.+?)[」\"']", text)
        cols = [field] + [c for c in others if c != field]
        ops.append(
            {
                "action": "merge_columns",
                "columns": cols,
                "target": m.group(1).strip(),
                "separator": " ",
                "drop_sources": "删除" in text or "drop" in text.lower(),
            }
        )
        return ops

    if re.search(r"去空格|strip|trim", text, re.I):
        ops.append({"action": "strip_whitespace", "columns": [field]})
        return ops

    return []


def compile_operations_from_edits(
    table_key: str,
    fields: list[dict],
    current_columns: list[str],
    table_note: str = "",
) -> list[dict]:
    ops: list[dict] = []
    table_ops: list[dict] = []

    for f in fields:
        instr = (f.get("instruction") or "").strip()
        if not instr:
            continue
        field = f["field"]
        if field not in current_columns and not any(
            op.get("from") == field for op in ops if op.get("action") == "rename_column"
        ):
            continue
        parsed = _parse_instruction(field, instr)
        if parsed:
            ops.extend(parsed)
        else:
            table_ops.append({"field": field, "instruction": instr})

    if table_note.strip():
        table_ops.append({"field": "__table__", "instruction": table_note.strip()})

    return ops, table_ops


def apply_table_operations(source_path: Path, output_path: Path, operations: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    df = read_csv(source_path)
    log: list[str] = []
    for i, op in enumerate(operations, 1):
        df = apply_operation(df, op)
        log.append(f"  {i}. {op.get('action')} OK")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return df, log


def prepare_and_apply_table(
    project_id: str,
    table_key: str,
    profile_fields: list[dict],
    *,
    use_ai: bool = True,
) -> dict:
    from ai_transformer import ai_available, ai_compile_field_operations

    cfg = get_table_config(project_id, table_key)
    merged = merge_fields_with_edits(profile_fields, table_key, cfg)
    src_path, source_kind, _ = resolve_working_source(project_id, table_key)
    current_columns = list(read_csv(src_path, nrows=0).columns)

    instructions = [
        {"field": f["field"], "instruction": (f.get("instruction") or "").strip()}
        for f in merged
        if (f.get("instruction") or "").strip() and (f.get("instruction") or "").strip() not in ("保留", "-", "keep")
    ]
    table_note = (cfg.get("table_note") or "").strip()

    operations: list[dict] = []

    if use_ai and ai_available() and (instructions or table_note):
        sample_csv = read_csv(src_path, nrows=3).to_csv(index=False)
        ai_result = ai_compile_field_operations(
            table_key=table_key,
            current_columns=current_columns,
            field_instructions=instructions,
            table_note=table_note,
            sample_csv=sample_csv,
        )
        operations = ai_result.get("operations") or []
    else:
        operations, unparsed = compile_operations_from_edits(
            table_key, merged, current_columns, table_note
        )
        if unparsed and not operations:
            raise ValueError("存在无法解析的修改意见，请配置 AI Key 或改用「改名为/删除/合并为」等格式")

    return apply_table(project_id, table_key, operations)


def _compile_table_operations(
    project_id: str, table_key: str, profile_fields: list[dict], *, use_ai: bool, sample_rows: int = 3
) -> tuple[list[dict], Path, list[str]]:
    """编译变换操作（与 prepare_and_apply_table 同逻辑），返回 (operations, src_path, current_columns)。"""
    from ai_transformer import ai_available, ai_compile_field_operations

    cfg = get_table_config(project_id, table_key)
    merged = merge_fields_with_edits(profile_fields, table_key, cfg)
    src_path, _, _ = resolve_working_source(project_id, table_key)
    current_columns = list(read_csv(src_path, nrows=0).columns)

    instructions = [
        {"field": f["field"], "instruction": (f.get("instruction") or "").strip()}
        for f in merged
        if (f.get("instruction") or "").strip() and (f.get("instruction") or "").strip() not in ("保留", "-", "keep")
    ]
    table_note = (cfg.get("table_note") or "").strip()

    if use_ai and ai_available() and (instructions or table_note):
        sample_csv = read_csv(src_path, nrows=3).to_csv(index=False)
        ai_result = ai_compile_field_operations(
            table_key=table_key,
            current_columns=current_columns,
            field_instructions=instructions,
            table_note=table_note,
            sample_csv=sample_csv,
        )
        operations = ai_result.get("operations") or []
    else:
        operations, unparsed = compile_operations_from_edits(table_key, merged, current_columns, table_note)
        if unparsed and not operations:
            raise ValueError("存在无法解析的修改意见，请配置 AI Key 或改用「改名为/删除/合并为」等格式")
    return operations, src_path, current_columns


def preview_table(
    project_id: str, table_key: str, profile_fields: list[dict], *, use_ai: bool = True, n: int = 20
) -> dict:
    """应用前预览：对前 N 行跑同一套操作，返回 before/after 对照，不写 output。"""
    operations, src_path, _ = _compile_table_operations(
        project_id, table_key, profile_fields, use_ai=use_ai
    )
    before_df = read_csv(src_path, nrows=n)
    after_df = before_df.copy()
    log: list[str] = []
    for i, op in enumerate(operations, 1):
        try:
            after_df = apply_operation(after_df, op)
            log.append(f"{i}. {op.get('action')} OK")
        except Exception as e:  # noqa: BLE001
            log.append(f"{i}. {op.get('action')} 失败: {e}")

    def _records(df: pd.DataFrame) -> dict:
        return {
            "columns": list(df.columns),
            "rows": df.fillna("").astype(str).values.tolist(),
        }

    before_cols = set(before_df.columns)
    after_cols = set(after_df.columns)
    return {
        "table_key": table_key,
        "operations": operations,
        "before": _records(before_df),
        "after": _records(after_df),
        "added_columns": sorted(after_cols - before_cols),
        "dropped_columns": sorted(before_cols - after_cols),
        "n": n,
        "log": "\n".join(log) or "（无修改操作，前后一致）",
    }


def apply_table(project_id: str, table_key: str, operations: list[dict]) -> dict:
    src_path, source_kind, out_name = resolve_working_source(project_id, table_key)
    out_path = output_dir(project_id) / out_name
    cfg = get_table_config(project_id, table_key)

    log_lines = [f"=== {table_key} ===", f"读取: {src_path.name} ({source_kind})", f"写入: {out_name} (不修改 raw)"]

    if not operations:
        if source_kind == "raw":
            raise ValueError("无有效修改操作，请填写字段修改意见")
        log_lines.append("无新操作，跳过")
        return {"table_key": table_key, "output_file": out_name, "rows": 0, "log": "\n".join(log_lines)}

    df, op_log = apply_table_operations(src_path, out_path, operations)
    log_lines.extend(op_log)
    log_lines.append(f"完成: {len(df)} 行, {len(df.columns)} 列")

    cfg["output_file"] = out_name
    cfg["updated_at"] = _now()
    cfg.setdefault("history", []).append(
        {"at": _now(), "source": src_path.name, "output": out_name, "rows": len(df), "ops": len(operations)}
    )
    for fname, entry in cfg.get("fields", {}).items():
        if (entry.get("instruction") or "").strip():
            entry["status"] = "applied"
            entry["last_applied_at"] = _now()

    edits = load_field_edits(project_id)
    edits["tables"][table_key] = cfg
    save_field_edits(project_id, edits)

    return {
        "table_key": table_key,
        "output_file": out_name,
        "source_file": src_path.name,
        "source_kind": source_kind,
        "rows": len(df),
        "columns": len(df.columns),
        "log": "\n".join(log_lines),
    }
