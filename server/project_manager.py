#!/usr/bin/env python3
"""Project workspace management: upload, path import, config persistence."""

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

WORKSPACES = Path(__file__).resolve().parents[1] / "workspaces"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspace_root(project_id: str) -> Path:
    return WORKSPACES / project_id


def raw_dir(project_id: str) -> Path:
    return workspace_root(project_id) / "raw"


def config_dir(project_id: str) -> Path:
    return workspace_root(project_id) / "config"


def output_dir(project_id: str) -> Path:
    return workspace_root(project_id) / "output"


def meta_path(project_id: str) -> Path:
    return workspace_root(project_id) / "meta.json"


def profile_path(project_id: str) -> Path:
    return workspace_root(project_id) / "profile.json"


def load_meta(project_id: str) -> dict:
    p = meta_path(project_id)
    if not p.exists():
        raise FileNotFoundError(f"项目不存在: {project_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_meta(project_id: str, meta: dict) -> None:
    meta_path(project_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def list_projects() -> list[dict]:
    if not WORKSPACES.exists():
        return []
    rows = []
    for p in sorted(WORKSPACES.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_dir():
            continue
        mp = p / "meta.json"
        if mp.exists():
            meta = json.loads(mp.read_text(encoding="utf-8"))
            meta["id"] = p.name
            meta["file_count"] = len(list((p / "raw").glob("*.csv"))) if (p / "raw").exists() else 0
            rows.append(meta)
    return rows


def _copy_csvs_from_path(src: Path, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for p in sorted(src.glob("*.csv")):
        shutil.copy2(p, dest / p.name)
        copied.append(p.name)
    if not copied:
        raise ValueError(f"目录中未找到 CSV 文件: {src}")
    return copied


def create_project_from_path(name: str, source_path: str) -> dict:
    src = Path(source_path).expanduser().resolve()
    if not src.is_dir():
        raise ValueError("路径必须是文件夹")
    project_id = uuid.uuid4().hex[:12]
    root = workspace_root(project_id)
    rd = raw_dir(project_id)
    config_dir(project_id).mkdir(parents=True)
    output_dir(project_id).mkdir(parents=True)
    files = _copy_csvs_from_path(src, rd)
    meta = {
        "id": project_id,
        "name": name or src.name,
        "source_type": "path",
        "source_path": str(src),
        "files": files,
        "created_at": _now(),
        "updated_at": _now(),
    }
    save_meta(project_id, meta)
    return meta


def create_project_from_upload(name: str, file_paths: list[tuple[str, bytes]]) -> dict:
    project_id = uuid.uuid4().hex[:12]
    rd = raw_dir(project_id)
    rd.mkdir(parents=True)
    config_dir(project_id).mkdir(parents=True)
    output_dir(project_id).mkdir(parents=True)
    copied: list[str] = []

    for fname, content in file_paths:
        fname = Path(fname).name
        if fname.lower().endswith(".zip"):
            zip_path = rd / fname
            zip_path.write_bytes(content)
            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    if info.filename.lower().endswith(".csv") and not info.is_dir():
                        base = Path(info.filename).name
                        (rd / base).write_bytes(zf.read(info))
                        if base not in copied:
                            copied.append(base)
            zip_path.unlink(missing_ok=True)
        elif fname.lower().endswith(".csv"):
            (rd / fname).write_bytes(content)
            if fname not in copied:
                copied.append(fname)

    if not copied:
        shutil.rmtree(workspace_root(project_id), ignore_errors=True)
        raise ValueError("请上传 CSV 文件或包含 CSV 的 ZIP 压缩包")

    meta = {
        "id": project_id,
        "name": name or f"项目_{project_id}",
        "source_type": "upload",
        "source_path": None,
        "files": sorted(copied),
        "created_at": _now(),
        "updated_at": _now(),
    }
    save_meta(project_id, meta)
    return meta


def load_json_config(project_id: str, name: str, default):
    p = config_dir(project_id) / name
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return default


def save_json_config(project_id: str, name: str, data) -> None:
    d = config_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_profile(project_id: str, fields: list[dict]) -> None:
    profile_path(project_id).write_text(
        json.dumps({"updated_at": _now(), "fields": fields}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = load_meta(project_id)
    meta["updated_at"] = _now()
    meta["field_count"] = len(fields)
    save_meta(project_id, meta)


def load_profile(project_id: str) -> list[dict]:
    p = profile_path(project_id)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("fields", [])


def resolve_csv_file(project_id: str, table_key: str) -> str:
    rd = raw_dir(project_id)
    for p in rd.glob("*.csv"):
        if p.stem == table_key or p.name == table_key:
            return p.name
    raise FileNotFoundError(f"未找到表: {table_key}")
