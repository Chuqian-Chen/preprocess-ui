---
name: windows-dev-sop
description: >-
  本项目（preprocess_ui，数据质控预处理工作台）在 Windows + 中文路径 + Anaconda 环境下的开发与验证 SOP。
  当在本仓库里启动/验证服务、编写或修改 start.bat / start.sh 等启动脚本、准备向用户声称"已测试/没问题/能跑通"、
  在 Git Bash 或 PowerShell 里跑 cmd/进程/端口检查、或处理含中文的路径/文件编码时，务必参考本 skill。
  尤其在你打算说"测好了"之前，先按这里的"验证纪律"核对——它专治"零件验证当整车验证"。
---

# preprocess_ui · Windows 开发验证 SOP

这份 SOP 把本项目在 Windows（中文系统、含中文路径 `E:\medin_ai\数据预处理框架\`、Anaconda Python）上反复踩过的坑和正确做法固化下来。目标不是死记规则，而是理解"为什么"，从而少走弯路、不做虚假声称。

## 1. 验证纪律：只为你真正跑过的"那个产物"背书

最贵的一次教训：曾声称 `start.bat` "测试无误"，但其实只验证了**组成部分**（uvicorn 能起、端口轮询片段能跑、JS 语法 OK），从没真正让 cmd 解析执行 `.bat` 文件本身。而那个 bug（中文+码页导致 cmd 解析错位）**只在执行 .bat 时才暴露**。结果用户一双击就报错。

**原则**：
- 用户会**双击 .bat**，你就要**真的执行 .bat**，而不是只跑它内部的 uvicorn 命令。组件正常 ≠ 集成产物正常。
- 声称"已测试/能跑通"前，自问一句：**我执行的，是不是用户将要执行的那个完全相同的东西？** 如果不是，就如实说"我验证了 X，但没验证 Y"。
- 宁可说"我验证了服务能起，但还没真正双击跑过 .bat"，也不要笼统说"测好了"。faithful reporting 永远优先。

## 2. Windows 启动脚本（.bat）：纯 ASCII + CRLF

`start.bat` 一定要 **全英文（纯 ASCII）+ CRLF 行尾**，不含任何中文。

**为什么**：中文 Windows 的 cmd 用 OEM 码页（GBK/936）逐字节解析 .bat。若文件存为 UTF-8 且含中文（echo 文案、注释），多字节会被拆错，导致整行命令错位——典型症状是 `'nstall' is not recognized`（"install" 丢了首字母）、中文 echo 被当成命令执行。`chcp 65001` 救不了，因为解析时码页已定。纯 ASCII 在任何码页下字节一致，永不出错。

**落地**：
- 提示文案、注释一律英文。
- 写完用脚本核验：无 BOM、无非 ASCII 字节、CRLF（Write 工具默认写 LF，需转 CRLF）：
  ```bash
  python -c "b=open('start.bat','rb').read(); print('BOM',b[:3]==b'\xef\xbb\xbf','nonascii',any(c>127 for c in b),'crlf',b.count(b'\r\n'),'strayLF',b.count(b'\n')-b.count(b'\r\n'))"
  ```
- 转 CRLF：`python -c "b=open('start.bat','rb').read().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'); open('start.bat','wb').write(b)"`
- 中文界面文案放在 Web/Python（UTF-8 环境）里，不要进 .bat。

## 3. start.sh 是 Linux/macOS 的，不要在 Windows 双击

`.sh` 是 bash 脚本，Windows 双击只会用编辑器打开或闪退，**不会启动服务**。Windows 一律用 `start.bat`。README/文档要写明这一点，避免用户混淆。

## 4. 启动体验：等端口就绪再开浏览器

别用固定 `timeout 3` 就开浏览器——首次要 `pip install` + 加载 pandas 冷启动，常超 3 秒，浏览器会先打开得到"127.0.0.1 拒绝连接"。

**正确做法**：后台轮询 TCP 端口，连得上才开浏览器。
```bat
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$p=%PORT%; for($i=0;$i -lt 120;$i++){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$p); $c.Close(); Start-Process ('http://127.0.0.1:'+$p); break } catch { Start-Sleep -Milliseconds 500 } }"
```

## 5. 如何正确"跑一遍 .bat"来验证（这是第 1 条的执行手册）

测试 .bat 时，几种调用方式各有坑，下面是能用的：

- **Git Bash 调 cmd 必须用 `//c`**：MSYS 会把 `/c` 当路径转成 `C:\`，使 cmd 进交互模式不跑脚本。uvicorn 会阻塞，用 `timeout` 收尾：
  ```bash
  timeout 20 /c/Windows/System32/cmd.exe //c start.bat 2>&1 | head -30
  ```
  看到 `[1/2] Checking dependencies...`、`[2/2] Starting server...`、URL 行全部正确 = 解析无误。
- **PowerShell 直接跑 .bat（最接近双击）**：`Start-Process -FilePath "$dir\start.bat" -WorkingDirectory $dir`，再轮询端口确认起没起。
- 验证完**务必清理**残留服务（见第 6 条）。

## 6. PowerShell / 进程 / 端口的几个反直觉点

- **原生 exe 的 stderr 会让本工具误报 exit 255**：git/native 命令把进度写 stderr，PowerShell 5.1 包成 ErrorRecord，导致即便成功也报非 0。`git push` 真正成败看输出里的 `main -> main`，不是退出码。
- **按命令行关进程会"匹配到自己"**：`Get-CimInstance Win32_Process | Where CommandLine -like '*uvicorn*server.app*'` 会把你**正在运行这条过滤命令的 PowerShell 自身**也匹配进去（因为命令行里就含这串），表现为"杀不掉 / 总剩 1 个 / cannot terminate itself"。判断服务是否真存活，**以端口为准**：
  ```powershell
  if(Get-NetTCPConnection -LocalPort 8877 -State Listen -ErrorAction SilentlyContinue){'up'}else{'free'}
  ```
- 停服务：按命令行杀进程前，先确认那不是你自己的命令；或直接用 `start.bat` 窗口 Ctrl+C。

## 7. 中文路径 + 编码

- 本项目根路径含中文。**经 curl 传含中文的 JSON（如建项目的路径）会因编码错乱**报"路径必须是文件夹"——验证后端逻辑时优先直接调 Python 函数，或用浏览器 UI（浏览器正确编码）。
- 把含中文的字符串打印到 cmd/PowerShell（cp936/cp1252）控制台常抛 `UnicodeEncodeError`。需要时设 `PYTHONIOENCODING=utf-8`，或验证脚本只打印 ASCII。

## 8. 本项目跑起来 / 验证的标准姿势

- 启动：双击 `start.bat`；或 `python -m uvicorn server.app:app --host 127.0.0.1 --port 8877 --app-dir .`
- 健康检查：`curl -s http://127.0.0.1:8877/api/health`
- 跑单测：`python -m pytest tests/ -q`（控制台编码报错时前置 `set PYTHONIOENCODING=utf-8`）
- 用浏览器看界面 + 深链接定位：`http://127.0.0.1:8877/?project=<id>&step=1&table=0&field=0`
- 大表画像慢是因为采样默认 20 万行；`PREPROCESS_PROFILE_SAMPLE_ROWS=0` 关采样全量。
- AI 配置同源：优先级 `PREPROCESS_AI_*` 环境变量 > `config/ai_settings.local.json` > 通用 `OPENAI_API_KEY`；key/base_url/model 整组取用，混源会 401。

## 9. Git 提交小抄

- 提交信息含中文时，**别在 Bash 工具里用 PowerShell here-string `@'...'@`**（那是 PowerShell 语法，在 bash 里会把 `@` 混进信息）。在 Bash 工具用 here-doc：`git commit -F - <<'EOF' ... EOF`，或写临时文件 `git commit -F msg.txt`。
- 数据（`workspaces/`，含真实医疗数据与大文件）、密钥（`config/ai_settings.local.json`）、文档截图（`docs/images/`）均已 gitignore，提交前确认 `git ls-files` 不含这些。
