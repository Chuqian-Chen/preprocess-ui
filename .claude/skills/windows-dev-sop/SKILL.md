---
name: windows-dev-sop
description: >-
  本项目（preprocess_ui，数据质控预处理工作台）专属的启动与验证速查：端口、健康检查、单测、深链接、
  采样开关、AI 同源配置、提交前的忽略项核对。当在本仓库启动/验证服务、跑测试、或提交前自检时参考。
  通用的"验证纪律"与 Windows/Git Bash/PowerShell/编码坑见全局 skill verify-real-artifacts（本 skill 不再重复）。
---

# preprocess_ui · 项目专属速查

> 通用部分（验证纪律、.bat 纯 ASCII+CRLF、Git Bash 用 `//c` 跑 .bat、PowerShell exit255 噪声、
> 进程自匹配、中文路径编码、启动等端口就绪再开浏览器等）已收进全局 skill **verify-real-artifacts**。
> 本 skill 只记录本项目独有的事实。

## 启动 / 验证

- 启动：双击 `start.bat`（Windows）；或 `python -m uvicorn server.app:app --host 127.0.0.1 --port 8877 --app-dir .`
- 端口：默认 **8877**（`set PORT=9000` 可改）。判断服务存活以端口为准。
- 健康检查：`curl -s http://127.0.0.1:8877/api/health` → `{"ok":true,...}`
- 单测：`python -m pytest tests/ -q`（控制台中文编码报错时前置 `set PYTHONIOENCODING=utf-8`）
- 浏览器 + 深链接定位：`http://127.0.0.1:8877/?project=<id>&step=1&table=0&field=0`
  （step 0~5 对应 数据源/Raw质控/逻辑关联/AI预处理/导出/数据分析；step=1 支持 table、field 下标）

## 项目机制要点

- **大表画像慢**：默认采样前 20 万行；`PREPROCESS_PROFILE_SAMPLE_ROWS=0` 关采样全量，或设具体行数。
- **AI 配置同源**（避免 401）：优先级 `PREPROCESS_AI_*` 环境变量 > `config/ai_settings.local.json` > 通用 `OPENAI_API_KEY`；key/base_url/model 整组取用，跨源混用会 401。
- **raw 不可变**：清洗结果写 `workspaces/{id}/output/`；删掉对应 output 文件即回到读 raw 的初始态。
- 后端模块用裸名互相 import，跑脚本/测试需把 `server/` 加进 `sys.path`（`tests/conftest.py` 已处理）。

## 提交前自检

- 数据 `workspaces/`（含真实医疗数据与大文件）、密钥 `config/ai_settings.local.json`、文档截图 `docs/images/` 均已 gitignore。
- 提交前确认 `git ls-files` 不含上述任何项。
- 提交信息含中文时，在 Bash 工具用 here-doc（`git commit -F - <<'EOF' … EOF`），别用 PowerShell here-string。
