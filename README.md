# 数据质控 · 预处理工作台 v2

**独立运行**，不调用 `bd_structured_data/code/` 下任何现有脚本。适用于新数据集、可变更的处理逻辑。

## 工作流

| 步骤 | 功能 |
|------|------|
| **⓪ 数据源** | 选择服务器文件夹路径 **或** 上传 CSV/ZIP，创建项目 |
| **① Raw 质控** | 内置引擎扫描字段画像；改类型后 **同一套逻辑** 即时重算值域 |
### ② 逻辑关联

- **统计探查**：列值交集匹配率（无需 AI）
- **AI 识别关联**：结合字段画像 + 探查结果，生成规则表与 **Mermaid 关联图**（格式同 `关联规则与示例.csv`）
- 规则保存至项目 `config/关联规则与示例.csv`
| **③ AI 预处理** | **AI 自动生成**每列修改意见草稿 → 您审阅编辑（右侧可折叠值域 + 审阅状态）→ 确认后写入 `output/*_clean.csv`（raw 不变，可反复更新） |
| **④ 导出** | 下载 `workspaces/{项目}/output/` 下的 clean CSV |
| **⑤ 数据分析** | 可视化分析：Raw / 处理后 / **对比**（类型分布、缺失率、列分布直方图/频次），基于 Chart.js |

> ① Raw 质控页可点 **「下载质控 CSV」** 导出含已保存类型修改的字段画像总表。
> ② 逻辑关联页底部有 **「值域速查」**（跨表搜字段 + 频次图），点规则表里的字段可跳转查看。

## 启动

### Windows（推荐）

**双击 `start.bat`** 即可：自动装依赖、起服务、并打开浏览器。关闭窗口或按 Ctrl+C 停止。

或在 PowerShell 手动运行：

```powershell
cd "E:\medin_ai\数据预处理框架\preprocess_ui"
pip install -r requirements.txt
python -m uvicorn server.app:app --host 127.0.0.1 --port 8877 --app-dir .
```

换端口：`set PORT=9000` 后再双击 `start.bat`，或手动命令里改 `--port`。

### Linux / macOS

```bash
cd preprocess_ui
pip install -r requirements.txt
./start.sh                 # 换端口：PORT=9000 ./start.sh
```

浏览器：**http://127.0.0.1:8877**（默认端口 8877，避免与 8765 冲突）

### 离线运行

前端图表库（**Mermaid**、**Chart.js**）已本地化到 `web/vendor/`，`index.html` 走本地引用，**断网也能用**。整个 `preprocess_ui` 文件夹拷到离线机即可运行（该机需有 Python + `requirements.txt` 依赖）。

## AI 配置

**推荐：在界面中配置** — 点击右上角 **「点击配置 AI Key」**，按向导选择平台 → 获取 Key → 填写测试。

Key 保存在本机 `config/ai_settings.local.json`（不会提交 git）。

**配置优先级（key / base_url / model 作为一个整体同源，避免「A 家钥匙开 B 家门」导致 401）：**

1. `PREPROCESS_AI_*` 专用环境变量（显式覆盖，最高）
2. 界面保存的本地配置 `config/ai_settings.local.json`
3. 通用 `OPENAI_API_KEY` / `OPENAI_BASE_URL`

也可使用环境变量：

```bash
# Windows PowerShell:  $env:PREPROCESS_AI_API_KEY="sk-..."
export PREPROCESS_AI_API_KEY="sk-..."
export PREPROCESS_AI_BASE_URL="https://api.openai.com/v1"  # 可选
export PREPROCESS_AI_MODEL="gpt-4o-mini"                   # 可选
```

## 项目目录结构

每个项目在 `workspaces/{id}/`：

```
raw/              # 导入的原始 CSV
config/           # 类型覆盖、关联规则、AI 方案
output/           # 清洗后 CSV
profile.json      # 字段画像缓存
meta.json         # 项目元信息
```

## 值域逻辑（自包含）

类型 → 值域规则在 `server/qc_engine.py`：

- **数值型** → min/max/mean/中位数
- **日期型** → 最早/最晚
- **分类/枚举型** → Top 频次条形图
- **ID型** → Top 样例频次
- **文本型** → 去重数；≤200 类时展示频次
- **空列** → 全部缺失

修改类型后调用同一 `infer_field_stats` / `build_content_and_domain`，保证一致。

### 超大表采样

为避免对千万行级 CSV 做全量画像（耗时数分钟），`profile_all_tables` 默认对每张表**只读前 20 万行**算类型/值域/缺失率。被采样的表在画像里带 `sampled=true`，界面表名旁显示「采样 N 万行」标记。小表（行数 ≤ 上限）仍全量、无标记。

调整或关闭采样（`0` = 全量）：

```bash
export PREPROCESS_PROFILE_SAMPLE_ROWS=500000   # 改为 50 万行
export PREPROCESS_PROFILE_SAMPLE_ROWS=0        # 关闭采样，全量精确画像
```

## AI 清洗方案

AI 输出 JSON 操作列表（非 Python 代码），由 `transform_engine.py` 安全执行：

`rename_column` · `drop_columns` · `merge_columns` · `fillna` · `map_values` · `strip_whitespace` · `dedupe` · `filter_rows` · `select_columns`

方案可人工编辑 JSON 后再应用。

## 与旧版区别

- ❌ 不再调用 `apply_cleaned_v*.py`、`run_bdetyy_raw_qc.py` 等
- ❌ 不再绑定固定 `data/` 目录
- ✅ 项目制 + 上传/路径导入
- ✅ AI 驱动后续预处理
