# 数据质控 · 预处理工作台 v2

一个**独立运行**的本地 Web 工具：导入结构化 CSV 数据集 → 自动字段画像质控 → AI 辅助识别表间关联 → AI 辅助逐列清洗 → 可视化分析与导出。前后端自包含，不依赖任何外部清洗脚本，适用于新数据集与可变更的处理逻辑。

> 📖 配套文档：[使用手册](docs/使用手册.md) · [代码原理](docs/代码原理.md)

## 工作流

| 步骤 | 功能 |
|------|------|
| **⓪ 数据源** | 选择服务器文件夹路径 **或** 上传 CSV/ZIP，创建项目（每个项目独立隔离） |
| **① Raw 质控** | 内置引擎扫描字段画像（类型 / 缺失率 / 去重 / 值域）；改类型后用 **同一套逻辑** 即时重算值域；可「下载质控 CSV」 |
| **② 逻辑关联** | **统计探查**（列值交集匹配率，无需 AI）+ **AI 识别关联**（结合画像+探查生成规则表与 Mermaid 关联图）；底部「值域速查」可跨表查字段分布 |
| **③ AI 预处理** | **AI 自动生成**每列修改意见草稿 → 你审阅编辑（右侧可折叠值域 + 审阅状态）→ 确认后写入 `output/*_clean.csv`（raw 永不改，output 可反复更新） |
| **④ 导出** | 下载 `workspaces/{项目}/output/` 下的 clean CSV |
| **⑤ 数据分析** | 可视化：Raw / 处理后 / **对比**（类型分布、缺失率、列分布直方图/频次），基于 Chart.js |

## 启动

### Windows（推荐）

**双击 `start.bat`**：自动装依赖、起服务、打开浏览器。关闭窗口或 Ctrl+C 停止。

或在 PowerShell 手动运行：

```powershell
cd "<项目路径>\preprocess_ui"
pip install -r requirements.txt
python -m uvicorn server.app:app --host 127.0.0.1 --port 8877 --app-dir .
```

换端口：`set PORT=9000` 后双击 `start.bat`，或手动命令里改 `--port`。

### Linux / macOS

```bash
cd preprocess_ui
pip install -r requirements.txt
./start.sh                 # 换端口：PORT=9000 ./start.sh
```

浏览器：**http://127.0.0.1:8877**（默认端口 8877）

### 离线运行

前端图表库（**Mermaid**、**Chart.js**）已本地化到 `web/vendor/`，`index.html` 走本地引用，**断网也能用**。整个 `preprocess_ui` 文件夹拷到离线机即可运行（该机需有 Python 3.10+ 与 `requirements.txt` 依赖）。

## AI 配置

**推荐在界面中配置** — 点右上角 **「配置 AI Key」**，按向导选平台（OpenAI / DeepSeek / Moonshot / 其他 OpenAI 兼容）→ 填 Key → 测试连接。Key 存于本机 `config/ai_settings.local.json`（已 gitignore，不入库）。

**配置优先级**（key / base_url / model 作为**一个整体同源**解析，避免「A 家钥匙开 B 家门」导致 401）：

1. `PREPROCESS_AI_*` 专用环境变量（显式覆盖，最高）
2. 界面保存的本地配置 `config/ai_settings.local.json`
3. 通用 `OPENAI_API_KEY` / `OPENAI_BASE_URL`

```bash
# Windows PowerShell:  $env:PREPROCESS_AI_API_KEY="sk-..."
export PREPROCESS_AI_API_KEY="sk-..."
export PREPROCESS_AI_BASE_URL="https://api.openai.com/v1"  # 可选
export PREPROCESS_AI_MODEL="gpt-4o-mini"                   # 可选
```

> AI 不可用时，② 退化为纯统计探查规则，③ 退化为内置正则解析「改名为/删除/合并为」等中文意图。

## 目录结构

```
preprocess_ui/
├─ start.bat / start.sh        # 一键启动
├─ requirements.txt
├─ server/                     # FastAPI 后端
│  ├─ app.py                   # 路由总入口（所有 /api/*）
│  ├─ project_manager.py       # 项目/工作区/配置/画像缓存的读写
│  ├─ qc_engine.py             # 字段画像引擎（类型推断 + 值域 + 采样）
│  ├─ join_analyzer.py         # 统计探查（列值交集匹配率）+ Mermaid
│  ├─ join_ai.py               # AI 识别表间关联规则
│  ├─ field_preprocess.py      # 逐列清洗：草稿/审阅/应用，raw→output
│  ├─ transform_engine.py      # 安全执行 JSON 操作（非 eval）+ schema 摘要
│  ├─ ai_transformer.py        # AI 生成清洗意见/编译操作
│  ├─ ai_settings.py           # AI 配置解析与持久化
│  └─ analysis.py              # 数据分析：列分布（直方图/频次）
├─ web/                        # 纯静态前端（无构建步骤）
│  ├─ index.html / app.js / style.css
│  └─ vendor/                  # 本地化的 mermaid.min.js / chart.umd.min.js
├─ config/                     # 默认配置模板（ai_settings.local.json 不入库）
└─ workspaces/{项目id}/        # 各项目数据（已 gitignore，不入库）
   ├─ raw/        # 导入的原始 CSV（只读，永不修改）
   ├─ config/     # 类型覆盖、关联规则、字段清洗意见、AI 方案
   ├─ output/     # 清洗后 CSV
   ├─ profile.json   # 字段画像缓存
   └─ meta.json      # 项目元信息
```

## 核心机制速览

- **字段画像与值域（`qc_engine.py`）**：类型推断（空列/数值/日期/分类/ID/文本），改类型后调用同一 `infer_field_stats` / `build_content_and_domain` 重算，保证一致。
- **超大表采样**：默认对每张表只读前 **20 万行** 算画像，避免千万行 CSV 全量扫描耗时数分钟。被采样表带 `sampled=true`，界面标「采样 N 万行」。调整：

  ```bash
  export PREPROCESS_PROFILE_SAMPLE_ROWS=500000   # 改为 50 万行
  export PREPROCESS_PROFILE_SAMPLE_ROWS=0        # 关闭采样，全量精确
  ```

- **AI 清洗安全执行**：AI 只输出 **JSON 操作列表**（非 Python 代码），由 `transform_engine.apply_operation` 白名单执行：
  `rename_column · drop_columns · merge_columns · fillna · map_values · strip_whitespace · dedupe · filter_rows · select_columns`。方案可人工编辑 JSON 后再应用。
- **raw 永不改**：所有清洗写入 `output/`；二次应用以上次 output 为输入，可反复迭代。

更深入的实现与数据流，见 [代码原理](docs/代码原理.md)。
