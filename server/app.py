#!/usr/bin/env python3
"""FastAPI backend — standalone preprocess UI (no legacy script calls)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

UI_ROOT = Path(__file__).resolve().parents[1]
WEB = UI_ROOT / "web"

import sys

sys.path.insert(0, str(UI_ROOT / "server"))

from ai_settings import get_public_settings, save_settings_from_ui, test_connection  # noqa: E402
from ai_transformer import ai_available  # noqa: E402
from field_preprocess import (  # noqa: E402
    apply_table,
    default_output_name,
    get_table_config,
    list_preprocess_tables,
    merge_fields_with_edits,
    prepare_and_apply_table,
    preview_table,
    run_ai_fill_table,
    save_table_edits,
)
from analysis import column_distribution  # noqa: E402
from project_manager import (  # noqa: E402
    config_dir,
    create_project_from_path,
    create_project_from_upload,
    list_projects,
    load_json_config,
    load_meta,
    load_profile,
    output_dir,
    profile_path,
    raw_dir,
    resolve_csv_file,
    save_json_config,
    save_profile,
)
from qc_engine import (  # noqa: E402
    FIELD_TYPES,
    export_profile_csv,
    list_raw_tables,
    profile_all_tables,
    profile_single_table,
    read_csv,
    recompute_field_domain,
)
from join_ai import discover_join_rules_with_ai, rules_from_probe_only  # noqa: E402
from join_analyzer import build_simple_mermaid, export_rules_csv, probe_join_candidates  # noqa: E402

app = FastAPI(title="Data Preprocess UI", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_project(x_project_id: str | None) -> str:
    if not x_project_id:
        raise HTTPException(400, "请先选择或创建项目（Header: X-Project-Id）")
    try:
        load_meta(x_project_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return x_project_id


class CreateFromPath(BaseModel):
    name: str = ""
    path: str


class TypeOverride(BaseModel):
    field_key: str
    dtype: str


class TypeOverrideBatch(BaseModel):
    overrides: dict[str, str]


class JoinRulesPayload(BaseModel):
    rules: list[dict]
    mermaid: str | None = None
    paths: list | None = None
    summary: str | None = None
    key_ids: list | None = None
    pitfalls: list | None = None


class JoinDiscoverPayload(BaseModel):
    use_ai: bool = True


class TableEditsPayload(BaseModel):
    table_key: str
    table_note: str = ""
    fields: dict[str, str] = {}
    mark_reviewed: bool = False


class ApplyTablePayload(BaseModel):
    table_key: str
    use_ai: bool = True


class AIFillTablePayload(BaseModel):
    table_key: str
    table_note: str = ""
    user_hint: str = ""
    regenerate: bool = False


class AIFillAllPayload(BaseModel):
    user_hint: str = ""
    only_missing: bool = True


class AISettingsPayload(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    provider: str = ""


@app.get("/api/health")
def health():
    pub = get_public_settings()
    return {"ok": True, "ai_configured": pub["configured"], "version": "2.0"}


@app.get("/api/ai/settings")
def api_get_ai_settings():
    return get_public_settings()


@app.put("/api/ai/settings")
def api_save_ai_settings(body: AISettingsPayload):
    local = get_public_settings()
    has_key = body.api_key.strip() or local.get("key_hint") or local.get("env_override")
    if not has_key:
        raise HTTPException(400, "请填写 API Key")
    try:
        result = save_settings_from_ui(
            api_key=body.api_key,
            base_url=body.base_url,
            model=body.model,
            provider=body.provider,
        )
        return result
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/ai/settings/test")
def api_test_ai_settings(body: AISettingsPayload):
    try:
        return test_connection(
            api_key=body.api_key or None,
            base_url=body.base_url or None,
            model=body.model or None,
        )
    except Exception as e:
        raise HTTPException(400, f"连接失败: {e}") from e


# --- Projects ---
@app.get("/api/projects")
def api_list_projects():
    return {"projects": list_projects()}


@app.post("/api/projects/from-path")
def api_create_from_path(body: CreateFromPath):
    try:
        meta = create_project_from_path(body.name, body.path)
        return meta
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/projects/upload")
async def api_create_from_upload(
    name: str = Form(""),
    files: list[UploadFile] = File(...),
):
    try:
        payloads = []
        for f in files:
            payloads.append((f.filename or "upload.csv", await f.read()))
        meta = create_project_from_upload(name, payloads)
        return meta
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str):
    try:
        meta = load_meta(project_id)
        meta["tables"] = list_raw_tables(raw_dir(project_id))
        return meta
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


# --- Raw QC (per project) ---
@app.get("/api/raw/field-types")
def api_field_types():
    return {"types": FIELD_TYPES}


@app.get("/api/raw/tables")
def api_raw_tables(x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    return {"tables": list_raw_tables(raw_dir(pid))}


@app.get("/api/raw/profile")
def api_raw_profile(x_project_id: str | None = Header(None), refresh: bool = False):
    pid = require_project(x_project_id)
    overrides = load_json_config(pid, "schema_overrides.json", {})
    if refresh:
        fields = profile_all_tables(raw_dir(pid), overrides)
        save_profile(pid, fields)
        return {"source": "live", "count": len(fields), "fields": fields}
    fields = load_profile(pid)
    if not fields:
        fields = profile_all_tables(raw_dir(pid), overrides)
        save_profile(pid, fields)
        return {"source": "live", "count": len(fields), "fields": fields}
    for f in fields:
        ov = overrides.get(f["field_key"])
        if ov:
            f["inferred_dtype"] = ov
    return {"source": "cache", "count": len(fields), "fields": fields}


@app.post("/api/raw/scan")
def api_raw_scan(x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    overrides = load_json_config(pid, "schema_overrides.json", {})
    fields = profile_all_tables(raw_dir(pid), overrides)
    save_profile(pid, fields)
    qc_out = config_dir(pid) / "qc_raw_字段画像_总表.csv"
    export_profile_csv(fields, qc_out)
    return {
        "ok": True,
        "count": len(fields),
        "fields": fields,
        "profile_csv": str(qc_out),
        "log": f"扫描完成：{len(fields)} 个字段，已保存画像",
    }


@app.get("/api/raw/profile/export")
def api_raw_profile_export(
    x_project_id: str | None = Header(None),
    project_id: str | None = None,
):
    """导出当前（含已保存类型修改的）Raw 质控画像总表 CSV。"""
    import csv

    pid = require_project(x_project_id or project_id)
    overrides = load_json_config(pid, "schema_overrides.json", {})
    fields = load_profile(pid)
    if not fields:
        fields = profile_all_tables(raw_dir(pid), overrides)
        save_profile(pid, fields)
    # 套用已保存的类型覆盖，保证导出反映「保存类型配置」后的状态
    for f in fields:
        ov = overrides.get(f.get("field_key"))
        if ov:
            f["inferred_dtype"] = ov

    out = config_dir(pid) / "qc_raw_字段画像_总表.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["表名", "字段", "类型", "缺失数", "缺失%", "去重数", "是否采样", "内容摘要"])
        for r in fields:
            w.writerow([
                r.get("table_key", ""),
                r.get("field", ""),
                r.get("inferred_dtype", ""),
                r.get("null", ""),
                r.get("null_pct", ""),
                r.get("unique", ""),
                "是" if r.get("sampled") else "",
                r.get("variable_content", ""),
            ])

    meta = load_meta(pid)
    safe_name = (meta.get("name") or pid).replace("/", "_").replace("\\", "_")
    return FileResponse(out, filename=f"质控画像_{safe_name}.csv", media_type="text/csv")


class ExactStatsPayload(BaseModel):
    table_key: str


@app.post("/api/raw/exact-stats")
def api_exact_stats(body: ExactStatsPayload, x_project_id: str | None = Header(None)):
    """对单表读全量，精确重算去重/缺失/值域（修正采样估计偏差）。"""
    pid = require_project(x_project_id)
    overrides = load_json_config(pid, "schema_overrides.json", {})
    table_file = resolve_csv_file(pid, body.table_key)
    # 固定类型只重算基数：用「已保存类型覆盖」+「现有画像推断类型」作为 forced，触发快速路径
    forced = dict(overrides)
    for f in load_profile(pid):
        if f.get("table_key") == body.table_key:
            forced.setdefault(f["field_key"], f.get("inferred_dtype"))
    forced = {k: v for k, v in forced.items() if v}
    try:
        new_fields = profile_single_table(raw_dir(pid), table_file, forced, sample_rows=None)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    # 合并回画像缓存：替换该表字段
    fields = load_profile(pid)
    new_keys = {f["field_key"] for f in new_fields}
    merged = [f for f in fields if f.get("field_key") not in new_keys] + new_fields
    save_profile(pid, merged)
    return {"ok": True, "table_key": body.table_key, "fields": new_fields, "count": len(new_fields)}


@app.post("/api/raw/type-override")
def api_type_override(body: TypeOverride, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    overrides = load_json_config(pid, "schema_overrides.json", {})
    overrides[body.field_key] = body.dtype
    save_json_config(pid, "schema_overrides.json", overrides)

    table_key, field = body.field_key.rsplit(".", 1)
    table_file = resolve_csv_file(pid, table_key)
    try:
        stats = recompute_field_domain(raw_dir(pid), table_file, field, body.dtype)
    except Exception as e:
        raise HTTPException(400, str(e)) from e

    fields = load_profile(pid)
    idx = next((i for i, f in enumerate(fields) if f.get("field_key") == body.field_key), -1)
    if idx >= 0:
        fields[idx] = {**fields[idx], **stats}
        save_profile(pid, fields)
    return {"overrides": overrides, "field": stats}


@app.post("/api/raw/type-overrides/batch")
def api_type_override_batch(body: TypeOverrideBatch, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    save_json_config(pid, "schema_overrides.json", body.overrides)
    return {"saved": len(body.overrides)}


# --- Join rules ---
@app.get("/api/join-rules")
def api_get_join_rules(x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    data = load_json_config(pid, "join_rules.json", {"rules": []})
    if not data.get("mermaid") and data.get("rules"):
        data["mermaid"] = build_simple_mermaid(data["rules"])
    return data


@app.put("/api/join-rules")
def api_put_join_rules(body: JoinRulesPayload, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    payload = body.model_dump(exclude_none=True)
    if "rules" not in payload:
        payload["rules"] = []
    save_json_config(pid, "join_rules.json", payload)
    export_rules_csv(payload["rules"], config_dir(pid) / "关联规则与示例.csv")
    return {"saved": len(payload["rules"])}


@app.post("/api/join-rules/probe")
def api_probe_join_rules(x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    if not fields:
        fields = profile_all_tables(raw_dir(pid), load_json_config(pid, "schema_overrides.json", {}))
    candidates = probe_join_candidates(raw_dir(pid), fields)
    save_json_config(pid, "join_probe.json", {"candidates": candidates})
    return {"count": len(candidates), "candidates": candidates}


@app.post("/api/join-rules/discover")
def api_discover_join_rules(body: JoinDiscoverPayload, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    if not fields:
        fields = profile_all_tables(raw_dir(pid), load_json_config(pid, "schema_overrides.json", {}))
    meta = load_meta(pid)
    candidates = probe_join_candidates(raw_dir(pid), fields)

    if body.use_ai:
        try:
            ai_result = discover_join_rules_with_ai(
                fields=fields,
                table_files=meta.get("files", []),
                raw_dir=raw_dir(pid),
                probe_candidates=candidates,
            )
            discovery = ai_result["discovery"]
            model = ai_result.get("model")
        except RuntimeError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"AI 识别失败: {e}") from e
    else:
        discovery = rules_from_probe_only(candidates)
        model = None

    payload = {
        "rules": discovery.get("rules", []),
        "mermaid": discovery.get("mermaid") or build_simple_mermaid(discovery.get("rules", [])),
        "paths": discovery.get("paths", []),
        "summary": discovery.get("summary", ""),
        "key_ids": discovery.get("key_ids", []),
        "pitfalls": discovery.get("pitfalls", []),
        "probe_candidates": candidates,
        "model": model,
    }
    save_json_config(pid, "join_rules.json", payload)
    export_rules_csv(payload["rules"], config_dir(pid) / "关联规则与示例.csv")
    return {"discovery": payload, "probe_count": len(candidates)}


# --- Field-level preprocess (working copy) ---
@app.get("/api/preprocess/tables")
def api_preprocess_tables(x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    if not fields:
        fields = profile_all_tables(raw_dir(pid), load_json_config(pid, "schema_overrides.json", {}))
    return {"tables": list_preprocess_tables(pid, fields)}


@app.get("/api/preprocess/fields")
def api_preprocess_fields(table_key: str, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    cfg = get_table_config(pid, table_key)
    merged = merge_fields_with_edits(fields, table_key, cfg)
    from field_preprocess import resolve_working_source

    src, kind, out_name = resolve_working_source(pid, table_key)
    cols = list(read_csv(src, nrows=0).columns)
    return {
        "table_key": table_key,
        "table_note": cfg.get("table_note", ""),
        "working_source": kind,
        "working_file": src.name,
        "output_file": out_name,
        "current_columns": cols,
        "ai_generated_at": cfg.get("ai_generated_at"),
        "review_status": cfg.get("review_status", "pending"),
        "fields": merged,
    }


@app.put("/api/preprocess/edits")
def api_save_preprocess_edits(body: TableEditsPayload, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    cfg = save_table_edits(
        pid,
        body.table_key,
        table_note=body.table_note,
        fields=body.fields,
        mark_reviewed=body.mark_reviewed,
    )
    return {"saved": True, "table_key": body.table_key, "edit_count": len(body.fields), "review_status": cfg.get("review_status")}


@app.post("/api/preprocess/ai-fill-table")
def api_ai_fill_table(body: AIFillTablePayload, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    cfg = get_table_config(pid, body.table_key)
    if not body.regenerate and cfg.get("ai_generated_at"):
        return {
            "fields": {k: v.get("instruction", "") for k, v in cfg.get("fields", {}).items()},
            "table_note": cfg.get("table_note", ""),
            "model": cfg.get("ai_model"),
            "cached": True,
            "table_key": body.table_key,
        }
    fields = load_profile(pid)
    try:
        result = run_ai_fill_table(
            pid,
            body.table_key,
            fields,
            table_note=body.table_note,
            user_hint=body.user_hint,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"AI 生成失败: {e}") from e
    return result


@app.post("/api/preprocess/ai-fill-all")
def api_ai_fill_all(body: AIFillAllPayload, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    if not fields:
        fields = profile_all_tables(raw_dir(pid), load_json_config(pid, "schema_overrides.json", {}))
    tables = list_preprocess_tables(pid, fields)
    logs = []
    results = []
    for t in tables:
        if body.only_missing and t.get("ai_generated_at"):
            logs.append(f"[SKIP] {t['table_key']} 已有 AI 草稿")
            continue
        try:
            r = run_ai_fill_table(pid, t["table_key"], fields, user_hint=body.user_hint)
            results.append(r)
            logs.append(f"[OK] {t['table_key']} ({r.get('model', '-')})")
        except Exception as e:
            logs.append(f"[FAIL] {t['table_key']}: {e}")
    return {"results": results, "log": "\n".join(logs), "count": len(results)}


@app.post("/api/preprocess/preview-table")
def api_preview_preprocess_table(body: ApplyTablePayload, x_project_id: str | None = Header(None)):
    """应用前预览：对前 N 行跑同一套变换，返回 before/after 对照，不写 output。"""
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    try:
        result = preview_table(pid, body.table_key, fields, use_ai=body.use_ai, n=20)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return result


@app.post("/api/preprocess/apply-table")
def api_apply_preprocess_table(body: ApplyTablePayload, x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    try:
        result = prepare_and_apply_table(pid, body.table_key, fields, use_ai=body.use_ai)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    return result


@app.post("/api/preprocess/apply-all")
def api_apply_preprocess_all(x_project_id: str | None = Header(None), use_ai: bool = True):
    pid = require_project(x_project_id)
    fields = load_profile(pid)
    tables = list_preprocess_tables(pid, fields)
    logs = []
    results = []
    for t in tables:
        cfg = get_table_config(pid, t["table_key"])
        if t.get("edit_count", 0) == 0:
            continue
        if cfg.get("review_status") != "reviewed":
            logs.append(f"[SKIP] {t['table_key']} 请先保存审阅结果")
            continue
        try:
            r = prepare_and_apply_table(pid, t["table_key"], fields, use_ai=use_ai)
            results.append(r)
            logs.append(r.get("log", ""))
        except Exception as e:
            logs.append(f"[FAIL] {t['table_key']}: {e}")
    return {"results": results, "log": "\n\n".join(logs)}


# --- Data analysis (visualization) ---
def _output_path_for(pid: str, table_key: str) -> tuple[Path, str]:
    raw_file = resolve_csv_file(pid, table_key)
    out_name = get_table_config(pid, table_key).get("output_file") or default_output_name(raw_file)
    return output_dir(pid) / out_name, out_name


@app.get("/api/analysis/fields")
def api_analysis_fields(
    table_key: str,
    scope: str = "raw",
    x_project_id: str | None = Header(None),
):
    """返回某表某 scope（raw/output）的字段画像，用于类型分布/缺失率图表。"""
    pid = require_project(x_project_id)
    if scope == "output":
        out_path, out_name = _output_path_for(pid, table_key)
        if not out_path.exists():
            return {"scope": scope, "table_key": table_key, "exists": False, "fields": []}
        fields = profile_single_table(output_dir(pid), out_name, {})
        return {"scope": scope, "table_key": table_key, "exists": True, "fields": fields}
    fields = [f for f in load_profile(pid) if f.get("table_key") == table_key]
    return {"scope": scope, "table_key": table_key, "exists": bool(fields), "fields": fields}


@app.get("/api/analysis/distribution")
def api_analysis_distribution(
    table_key: str,
    field: str,
    scope: str = "raw",
    x_project_id: str | None = Header(None),
):
    """返回某列分布：数值→直方图，分类/ID→频次。"""
    pid = require_project(x_project_id)
    if scope == "output":
        path, _ = _output_path_for(pid, table_key)
        if not path.exists():
            raise HTTPException(404, "无处理后文件，请先在 ③ 应用本表")
    else:
        path = raw_dir(pid) / resolve_csv_file(pid, table_key)
    try:
        return column_distribution(path, field)
    except KeyError:
        raise HTTPException(404, f"列不存在: {field}") from None
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/output/files")
def api_output_files(x_project_id: str | None = Header(None)):
    pid = require_project(x_project_id)
    od = output_dir(pid)
    files = []
    if od.exists():
        for p in sorted(od.glob("*.csv")):
            files.append({"name": p.name, "size": p.stat().st_size, "path": str(p)})
    return {"files": files}


@app.get("/api/output/download/{filename}")
def api_download_output(
    filename: str,
    x_project_id: str | None = Header(None),
    project_id: str | None = None,
):
    pid = require_project(x_project_id or project_id)
    path = output_dir(pid) / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=path.name)


app.mount("/assets", StaticFiles(directory=str(WEB)), name="assets")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
