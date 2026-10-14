# LuminaSec 更名 · 变更交接文档

> **给谁看**：需要把「LuminaSec 更名 + 启动大标题」这套改动**复现到另一个仓库/副本**的 agent 或人。
> **版本**：工程库 v114 / 发布库 1.006（2026-10-12）
> **复现难度**：低（纯字符串替换 + 一个新模块），但**有 7 个坑**（见 §6），不看必踩。
>
> **v115 追加**：起始页（`web/start.html`）视觉重做为「矩阵雨背景 + 打字机启动序列 +
> 终端 CLI 主体」三段式，含 5 套可切换背景色调。详见 §10。

---

## 0. 当前状态（2026-10-12 21:40 更新）

| 仓库 | 路径 | 版本 | 改名状态 |
|---|---|---|---|
| 工程库 | `<工程库>`（本文件所在仓库） | **114** | ✅ 已应用（含 `test_brand.py` 护栏） |
| 发布库 | `<发布库工作副本>` | **1.006** | ✅ 已同步（本文档作者于 21:30 完成） |

**⚠️ 改完文件不等于生效**：发布库那个正在跑的实例（PID 79012）是改名前启动的，
Python 早已把旧模块载入内存。**必须重启它**才能看到 LuminaSec。
重启前确认那边没有在跑的任务（服务重启时 `init_db()` 会把库里 `running`/
`awaiting_confirm` 的会话改成 `interrupted`，半程成果只到上次落库为止）。

**发布库刻意没加 `test_brand.py`** —— 发布纪律是「发布库不含 `test_*` 与内部文档」。
代价是发布库少了 bat/brand.py 漂移护栏；护栏只在工程库。若以后有人在发布库
直接改 bat，需要人工核对（或临时把 `test_brand.py` 拷过去跑一次再删）。



---

## 1. 先搞清楚：两个仓库

| | 工程库 | 发布库 |
|---|---|---|
| 路径 | `<工程库>`（本文件所在仓库） | `<发布库工作副本>` |
| 版本格式 | 递增整数（`113` → `114`） | 三段式（`1.005` → `1.006`） |
| 版本号文件 | `VERSION.txt` | `VERSION.txt` |
| git | 有，17+ 个提交 | 有，独立提交史（正式版 1.003/1.004/1.005/1.006） |
| 含 `test_*` / `docs/internal/` | 有 | **无**（发布纪律：只放运行组件） |
| **本次改动** | **✅ 已应用** | **✅ 已同步** |

**曾经的症状**（改动只落在工程库时，用户报告的两个问题，同源）：

| 症状 | 根因 |
|---|---|
| 前端网页标题还是 `SRC Agent` | 浏览器连的是**发布库**那个旧实例，它没改名 |
| `run.py` 跑起来就退出 | 发布库旧实例占着 8770，新实例 bind 失败 → uvicorn 直接退出（`[Errno 10048]` 通常每个套接字地址只允许使用一次） |

**结论**：这不是代码 bug，是「改了 A 副本、跑的是 B 副本」+「B 副本的进程没退」。
复现改动到发布库**之前或之后**，都得先处理端口占用（§7）。

---

## 2. 改动总览（17 个文件 / 40 行被替换 + 2 个新文件）

> 数字口径：`git diff --numstat` 实测 **40 行删除**（= 被替换掉的旧内容行）、
> **57 行新增**（含 README 的说明块与 bat 的 5 行艺术字），分布在 **17 个文件**；
> 另有 2 个新文件未计入 diff（尚未 `git add`）。

### 2.1 新增文件（2 个，未纳入 git diff）

| 文件 | 作用 |
|---|---|
| `app/brand.py` | **唯一数据源**：`NAME` / `TAGLINE` / `ART` / `banner()` / `bat_lines()` |
| `test_brand.py` | 防漂移护栏（18 项）：断言 bat 里的 echo 行与 `brand.ART` 一致 |

### 2.2 修改文件（17 个，按 git diff --numstat 实测）

| 文件 | 增 | 删 | 改了什么 |
|---|---|---|---|
| `README.md` | 24 | 2 | 一级标题 + 新增更名说明块 + 目录树补 `app/brand.py` |
| `run.py` | 8 | 7 | 启动横幅换成 `banner()`；docstring 与 argparse 描述改名 |
| `启动控制台.bat` | 9 | 4 | 标题行换成 5 行艺术字 echo；rem 注释改名并指向 brand.py |
| `console/index.html` | 3 | 3 | `<title>` + `login-sub` + `brand-sub` 三处 |
| `web/app.js` | 3 | 3 | 文件头注释 + `welcome-title` + `<span class="who">` |
| `web/index.html` | 3 | 3 | `<title>` + 顶栏 `brand-name` + `welcome-title` |
| `web/start.html` | 2 | 2 | `<title>` + `<h1>` |
| `团队协作指南.md` | 5 | 5 | 一级标题 + 项目名称 + 背景段 + 引言 + commit 示例 |
| `update.py` | 3 | 3 | docstring + GUI 窗口标题 + ttk.Label 文字 |
| `test_live_target.py` | 2 | 2 | docstring 与 note 里的描述 |
| `docs/internal/更新报告.md` | 29 | 0 | **纯追加** v114 条目（不计入改名替换） |
| `app/main.py` | 1 | 1 | `FastAPI(title=...)`；**另有一次缓存头修复**（见 §6.6，`+8 -1`） |
| `app/report.py` | 1 | 1 | 报告落款 |
| `app/__init__.py` | 1 | 1 | 包 docstring |
| `console/console.css` | 1 | 1 | 文件头注释 |
| `run_all_tests.py` | 1 | 1 | 启动打印 |
| `VERSION.txt` | 1 | 1 | `113` → `114`（发布库走三段式，见 §5） |

**另外还有 1 个文件改了但 `git diff` 看不到**：

| 文件 | 状态 |
|---|---|
| `审计报告.md` | **被 `.gitignore:81` 忽略**（本机文件，不入库）。已改名，但 `git status` / `git diff` 都不显示它 |

> ⚠️ 这是本次的一个重要发现：**`git grep` 与 `git status` 都会漏掉 gitignored 文件**。
> 工程库里 `审计报告.md`、`data/codebases_index/`、`config.yaml`、`data/scope.json` 等
> 都是本机文件。做全站扫描必须用**文件系统级 grep**，不能只信 `git grep`（见 §6.5）。

### 2.3 刻意**不**改的

| 位置 | 理由 |
|---|---|
| `data/artifacts/*.md`（2 份历史报告） | 已提交补天的凭证记录，改它等于篡改历史 |
| `_gen_report.py` | 未跟踪的临时脚本 |
| `docs/internal/*` | 内部账本，不随发布库分发 |
| `console/views/params.js` 的 `const SRC = {...}` | 这是变量名，语义是 "source"（配置来源），不是产品名 |

---

## 3. 艺术字字面量（直接复制，不需要 pyfiglet）

**字体**：FIGlet `slant`，`LuminaSec`，5 行 × 55 列。
**已固化为静态字符串**，运行时零依赖（pyfiglet **不在** `requirements.txt` 里，别加）。

```
    __                    _             _____
   / /   __  ______ ___  (_)___  ____ _/ ___/___  _____
  / /   / / / / __ `__ \/ / __ \/ __ `/\__ \/ _ \/ ___/
 / /___/ /_/ / / / / / / / / / / /_/ /___/ /  __/ /__
/_____/\__,_/_/ /_/ /_/_/_/ /_/\__,_//____/\___/\___/
```

**Python 源码里的转义形式**（注意反斜杠要双写）：

```python
ART: tuple[str, ...] = (
    "    __                    _             _____",
    "   / /   __  ______ ___  (_)___  ____ _/ ___/___  _____",
    "  / /   / / / / __ `__ \\/ / __ \\/ __ `/\\__ \\/ _ \\/ ___/",
    " / /___/ /_/ / / / / / / / / / / /_/ /___/ /  __/ /__",
    "/_____/\\__,_/_/ /_/ /_/_/_/ /_/\\__,_//____/\\___/\\___/",
)
```

---

## 4. 逐文件改动清单（可直接照做）

> 每条都标注了**精确的旧字符串**。复现时用「计数断言」：`old` 在文件里必须**恰好出现 1 次**，
> 否则停手检查——出现 0 次说明版本基线不同，出现多次说明还有别的引用点。

### 4.1 `app/brand.py`（新建，全文见工程库）

最小可用版本（如果不想引入 `_dw`/`bat_lines`，至少要有 `ART` 与 `banner()`）：

```python
# -*- coding: utf-8 -*-
"""LuminaSec 品牌标识 —— 启动横幅的唯一数据源。"""
from __future__ import annotations
import unicodedata

NAME = "LuminaSec"
TAGLINE = "本地控制台 · 仅限已获得书面授权的目标测试"
ART: tuple[str, ...] = ( ... )          # 见 §3

def _dw(s: str) -> int:
    """终端显示宽度：CJK/全角算 2 列。不能用 len() 对齐中文。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)

def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _dw(s))

def art_lines() -> list[str]:
    return list(ART)

def banner(subtitle: str = TAGLINE, *, border: str = "=", pad: int = 2) -> str:
    lines = art_lines()
    inner = max([_dw(l) for l in lines] + [_dw(subtitle)])
    out = [border * (inner + pad * 2)]
    for l in lines:
        out.append(" " * pad + _pad(l, inner))
    if subtitle:
        out.append(" " * pad + _pad(subtitle, inner))
    out.append(border * (inner + pad * 2))
    return "\n".join(out)
```

### 4.2 `run.py`

**位置**：`main()` 里 `url = _browser_url(args.host, args.port)` 之后。

旧：
```python
    print("=" * 60)
    print("  SRC 渗透 Agent · 本地控制台")
    print("=" * 60)
```
新：
```python
    # 大标题（LuminaSec，符号拼成）来自 app/brand.py —— 与 启动控制台.bat
    # 共用同一份数据，不在这里手抄（ drift 由 test_brand.py 断言兜底）。
    from app.brand import banner as _brand_banner
    print(_brand_banner())
```
（`run.py` 顶部已有 `sys.path.insert(0, str(ROOT))`，所以函数内 import 能找到 `app` 包。）

另外两处纯字符串替换：
- `"""启动 SRC 渗透 Agent 控制台。` → `"""启动 LuminaSec 控制台。`
- `description="SRC 渗透 Agent 控制台"` → `description="LuminaSec 控制台"`

**保留不变**：横幅下方的「工具箱 / 模型 / 地址 / 仅限已获得书面授权」四行信息结构，
以及末尾两条 `print("=" * 59)`。

### 4.3 `启动控制台.bat` ⚠️ 最麻烦的一个，见 §6

**这是 GBK 编码 + CRLF 的批处理**，必须用「GBK 读 → 改 → GBK 写 + CRLF」，
不能用普通文本编辑器直接存 UTF-8（会全变乱码）。

旧（3 行）：
```bat
echo ============================================================
echo   SRC 渗透 Agent - 本地控制台
echo ============================================================
```
新（7 行）：
```bat
echo ===========================================================
echo     __                    _             _____
echo    / /   __  ______ ___  (_)___  ____ _/ ___/___  _____
echo   / /   / / / / __ `__ \/ / __ \/ __ `/\__ \/ _ \/ ___/
echo  / /___/ /_/ / / / / / / / / / / /_/ /___/ /  __/ /__
echo /_____/\__,_/_/ /_/ /_/_/_/ /_/\__,_//____/\___/\___/
echo ===========================================================
```

**复现脚本**（Python，可直接跑）：

```python
p = "启动控制台.bat"
lines = open(p, "rb").read().decode("gbk").split("\r\n")
old = "echo   SRC 渗透 Agent - 本地控制台"
i = [k for k, l in enumerate(lines) if l == old]
assert len(i) == 1, f"标题行命中 {len(i)} 次"      # 不唯一就停手
i = i[0]
lines[i-1] = "echo " + "=" * 59      # 上边框，按艺术字宽度重算
lines[i+1] = "echo " + "=" * 59      # 下边框
lines[i:i+1] = ["echo " + "  " + l for l in ART]   # 2 空格缩进，见 §6.3
open(p, "wb").write("\r\n".join(lines).encode("gbk"))
```

**验收**：写完后 `raw.count(b"\n") == raw.count(b"\r\n")`（无裸 LF），
且起真实子进程跑一遍确认无转义问题（见 §6.1）。

### 4.4 其余字符串替换（逐条，`old` 均应恰好命中 1 次）

| 文件 | 旧 | 新 |
|---|---|---|
| `app/main.py` | `app = FastAPI(title="SRC 渗透 Agent", version="0.1.0")` | `app = FastAPI(title="LuminaSec", version="0.1.0")` |
| `app/report.py` | `> 本报告由本地 SRC 渗透 Agent 生成。所有操作均应在获得书面授权的前提下进行。` | `> 本报告由本地 LuminaSec 生成。所有操作均应在获得书面授权的前提下进行。` |
| `app/__init__.py` | `"""SRC 渗透测试 Agent —— 本地 Web 控制台后端。"""` | `"""LuminaSec —— 本地 Web 控制台后端。"""` |
| `web/index.html` | `<title>SRC 渗透 Agent · 控制台</title>` | `<title>LuminaSec · 控制台</title>` |
| `web/index.html` | `<div class="brand-name">SRC Agent</div>` | `<div class="brand-name">LuminaSec</div>` |
| `web/index.html` | `<div class="welcome-title">SRC 渗透测试编排助手</div>` | `<div class="welcome-title">LuminaSec 渗透测试编排助手</div>` |
| `web/app.js` | `/* SRC 渗透 Agent 控制台前端 — 对话式界面 */` | `/* LuminaSec 控制台前端 — 对话式界面 */` |
| `web/app.js` | `<div class="welcome-title">SRC 渗透测试编排助手</div>` | `<div class="welcome-title">LuminaSec 渗透测试编排助手</div>` |
| `web/app.js` | `<span class="who">SRC Agent</span>` | `<span class="who">LuminaSec</span>` |
| `web/start.html` | `<title>SRC Agent · 选择工作模式</title>` | `<title>LuminaSec · 选择工作模式</title>` |
| `web/start.html` | `<h1>SRC 渗透 Agent</h1>` | `<h1>LuminaSec</h1>` |
| `console/index.html` | `<title>SRC Agent · 配置控制台</title>` | `<title>LuminaSec · 配置控制台</title>` |
| `console/index.html` | `<p class="login-sub">SRC Agent · 本机运维界面</p>` | `<p class="login-sub">LuminaSec · 本机运维界面</p>` |
| `console/index.html` | `<div class="brand-sub">SRC Agent</div>` | `<div class="brand-sub">LuminaSec</div>` |
| `console/console.css` | `/* SRC Agent 配置控制台（v050）` | `/* LuminaSec 配置控制台（v050）` |
| `update.py` | `"""SRC Agent 更新工具（update.exe 源码）。` | `"""LuminaSec 更新工具（update.exe 源码）。` |
| `update.py` | `self.root.title("SRC Agent 更新工具")` | `self.root.title("LuminaSec 更新工具")` |
| `update.py` | `ttk.Label(head, text="SRC Agent 更新工具",` | `ttk.Label(head, text="LuminaSec 更新工具",` |
| `README.md` | `# SRC 渗透 Agent · 本地控制台` | `# LuminaSec · 本地控制台` |
| `团队协作指南.md` | `# SRC Agent · 团队协作指南` | `# LuminaSec · 团队协作指南` |
| `团队协作指南.md` | `2. **项目名称**：\`SRC Agent 渗透测试编排平台\`。` | `2. **项目名称**：\`LuminaSec\`。` |
| `团队协作指南.md` | `【项目背景】SRC 渗透测试编排 Agent：对话驱动的本地可控渗透平台` | `【项目背景】LuminaSec：对话驱动的本地可控渗透平台` |
| `团队协作指南.md` | `> 目标：让多位队员一起协同开发这个「SRC 渗透测试编排 Agent」，共享上下文、规范与代码，同时守住合规红线。` | `> 目标：让多位队员一起协同开发这个「LuminaSec」，共享上下文、规范与代码，同时守住合规红线。` |
| `团队协作指南.md` | `git commit -m "init: SRC 渗透编排 Agent（含 Phase 1-4 修复）"` | `git commit -m "init: LuminaSec（含 Phase 1-4 修复）"` |
| `审计报告.md` | `# 程序审计报告 · SRC 渗透 Agent 本地控制台` | `# 程序审计报告 · LuminaSec 本地控制台` |
| `run_all_tests.py` | `print("  SRC 渗透 Agent · 全量回归")` | `print("  LuminaSec · 全量回归")` |
| `test_live_target.py` | `驱动 SRC Agent 对` | `驱动 LuminaSec 对` |
| `test_live_target.py` | `验证 SRC Agent 实靶流程` | `验证 LuminaSec 实靶流程` |

> ⚠️ **两种 pattern 各扫一遍**（§6.4）：`SRC 渗透` 与 `SRC Agent`。
> 只扫前者会漏掉 `web/index.html:18` 的顶栏品牌名、`update.py` 的 GUI 标题、
> `web/start.html` 的 `<title>`——它们都不含「渗透」二字。

---

## 5. 版本号与发布库注意事项

| 仓库 | 版本文件 | 本次 |
|---|---|---|
| 工程库 | `VERSION.txt`，递增整数 | `113` → **`114`** |
| 发布库 | `VERSION.txt`，三段式 | 若发正式版则 `1.005` → `1.006`，**不要写成 114** |

**发布库版本号规则**（来自 `docs/internal/正式版发布流程.md`）：
- 更新器用**字符串相等**判断新旧 ⇒ 版本号必须**单调递增且同套格式**
- 工程库递增整数 / 发布库三段式，**两套格式不能混**
- `VERSION.txt` 与 `SHA256SUMS.txt` 必须**同一个 commit** 生成
- `SHA256SUMS.txt` 从 **git index** 生成（从工作区生成会因换行口径不一致导致自更新必然中止）
- 发布库**不含** `test_*` 与 `docs/internal/` 整目录

**发布闸门**（`docs/internal/更新报告.md` 第一节）：本次改动「使用者可见 = 是」，
且属于「新增/改变使用者可感知的能力」⇒ **已满足闸门条件 2，建议安排一次正式版**。

---

## 6. 七个坑（不看必踩）

### 6.1 批处理的特殊字符

艺术字里含 `(`、`)`、`` ` ``、`/`、`\`、`,`、`_`。在 Windows 批处理里：
- **`(` `)` 在 `echo` 行内是安全的**（echo 吃掉整行剩余内容）
- **`` ` `` 不是 cmd 的特殊字符**（那是 PowerShell 的），安全
- **没有 `|` `&` `^` `<` `>` `%` `!`** —— 这些才是要转义的，艺术字里一个都没有

**但必须实测**：把 bat 里的 echo 行抽出来写成临时 bat，起真实子进程跑一遍，
确认输出与预期逐字一致。本次实测通过，无转义问题。

### 6.2 GBK 编码 + CRLF

`启动控制台.bat` 是 **GBK** 编码、**CRLF** 换行。
- 用 UTF-8 存回去 → 中文全变乱码
- 用 LF → cmd.exe 会把整行当命令执行（本项目踩过，`echo` 那几行会报一堆
  「不是内部或外部命令」）
- 正确做法：`open(p,"rb").read().decode("gbk")` → 改 → `open(p,"wb").write(s.encode("gbk"))`，
  且全程用 `"\r\n"` 分行
- 验收：`raw.count(b"\n") == raw.count(b"\r\n")`

### 6.3 `echo` 会吃掉第一个空格

`echo   / /...` 实际输出是 `  / /...`（少一个空格）。
所以艺术字前要**刻意多给一个空格**（工程库用 2 空格缩进 = `echo ` + 2 空格 + 艺术字），
这样 `run.py` 的 `banner()`（`pad=2`）与 bat 的视觉缩进才一致。

### 6.4 改名要两种 pattern 各扫一遍

```bash
git grep -n "SRC 渗透\|SRC Agent\|SRC渗透" -- . | grep -v "^data/artifacts/"
```

**只扫 `SRC 渗透` 会漏**（本次实际漏了 3 处，第二批补扫才抓全）：
- `web/index.html:18` `<div class="brand-name">SRC Agent</div>` ← **界面顶栏品牌名，最要紧**
- `update.py` 的 GUI 窗口标题与 ttk.Label
- `web/start.html:6` 的 `<title>`

### 6.5 ⚠️ `git grep` 会漏掉 gitignored 文件（本次实测踩到）

**现象**：用 `git grep` 扫「残留旧品牌名」报告干净，但用文件系统 grep 一扫还有 10 处。

**根因**：`data/codebases_index/srcagent-self-2026-10-05.json` 被 `.gitignore:100`
（`data/codebases_index/`）忽略，`git grep` 只搜被跟踪文件，**根本不看它**。

**那 10 处是什么**：**Agent 自己的白盒自索引**。`data/codebases.json` 里登记了
`srcagent-self-2026-10-05`（root 指向工程库自身，`white_layer=partial`），
索引里存的是**改名前的源码字符串**（`app/__init__.py` 的 docstring、
`app/main.py` 的 FastAPI title、`run.py` 的 docstring 与横幅、`update.py` 的
GUI 标题、报告落款等）。

**影响**：白盒模式下 `code_search` / `code_read` 查自己会拿到**旧字符串**，
模型据此可能输出旧品牌名。不是 UI 问题，是「Agent 对自己的认知过期」。

**修法**：重建索引（二选一）
```bash
# 方式一：删掉旧索引文件，让下次 code_index 重建
rm data/codebases_index/srcagent-self-2026-10-05.json
# 方式二：在白盒会话里对该 codebase 重新跑一次 code_index
```
**正确扫描命令**（文件系统级，不要只信 git grep）：
```bash
grep -rn "SRC 渗透\|SRC Agent\|SRC渗透" . \
  --include="*.py" --include="*.js" --include="*.html" --include="*.css" \
  --include="*.bat" --include="*.md" --include="*.json" --include="*.yaml" \
  | grep -v "^./data/artifacts/" | grep -v "__pycache__" | grep -v "^./.git/"
```
允许的例外：`app/brand.py` 与 `docs/internal/*` 里**说明更名历史**的句子、
`test_brand.py` 的断言串本身、`_gen_report.py`（未跟踪的临时脚本）。

### 6.6 ⚠️ HTML 入口没有 no-cache → 改名后界面不变（本次真正的 bug）

**症状**（用户报告）：代码已确认全部改成 LuminaSec，但浏览器左上角仍是「SRC Agent」，
标签页标题也还是旧的。两个仓库的源码都扫干净了，问题不在源码。

**根因**：`app/main.py` 的 `remote_access_token_guard` 中间件原先只给
`/static` 与 `/console-assets` 设 `Cache-Control: no-cache`，而三个 **HTML 入口**
`/`（起始页）、`/app`（主界面）、`/console`（配置控制台）是 `FileResponse` 直出、
**默认不带任何缓存头**。Chromium 对无缓存头的响应会启发式缓存 ⇒ index.html 被
缓存住 ⇒ 品牌名（就在 index.html 里）不更新。

**这是同一个坑第三次出现**（`app/main.py` 注释里有记录）：
1. 2026-09-18 线索图黑块事故 —— 静态资源被启发式缓存
2. v050.2 控制台 CSS 缓存 —— 只覆盖了 `/static`，漏了 `/console-assets`
3. **v114 本次** —— 覆盖了两类静态目录，漏了 HTML 入口本身

**修法**（两个仓库都已改）：
```python
if (request.url.path in ("/", "/app", "/console")
        or request.url.path.startswith(("/static", "/console-assets"))):
    response.headers["Cache-Control"] = "no-cache"
```
`test_brand.py` 的 [5] 组用 `TestClient` 实测六个路径的缓存头（含反向断言
`/api/health` **不该**被加 no-cache），防第四次。

**给用户的即时解法**：`Ctrl+F5` 硬刷新（或 DevTools → 勾选 Disable cache 后刷新）。
代码修好后**首次访问仍可能吃旧缓存**，因为硬刷新之前的响应已经被缓存了。

---

## 7. 端口占用处理（复现前必须做）

**症状**：`run.py` 起来就退，日志里有
`ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8770)`。

**查占用**：
```bash
netstat -ano | grep ":8770"
```
LISTENING 那行的最后一个数字就是 PID。

**处理前先确认它是谁**（本次实测是发布库的旧实例）：
```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" |
  Select-Object ProcessId, Name, CreationDate, CommandLine | Format-List
```

**三个选择**（**杀进程是破坏性操作，先问人**）：

| 方案 | 做法 | 适用 |
|---|---|---|
| A | 停掉旧实例，从工程库跑新代码 | 想立刻验证工程库的改动 |
| B | 把改动复现到发布库，重启发布库 | 日常就用发布库（本次用户的实际情况） |
| C | 旧实例换个端口跑（`--port`） | 想两个同时跑 |

> ⚠️ 旧实例可能正持有**未保存的任务状态**。杀之前确认那边没有在跑的任务。
> 另外：服务重启时 `init_db()` 会把库里 `running`/`awaiting_confirm` 的会话
> 统一改成 `interrupted`，所以杀进程不会留僵尸会话，但半程成果只到上次落库为止。

---

## 8. 验收清单

复现完按这个逐条过：

- [ ] **文件系统级** grep 输出只剩允许的例外（`git grep` 会漏 gitignored 文件，见 §6.5）：
      ```bash
      grep -rn "SRC 渗透\|SRC Agent\|SRC渗透" . --include="*.py" --include="*.js" \
        --include="*.html" --include="*.css" --include="*.bat" --include="*.md" \
        --include="*.json" --include="*.yaml" \
        | grep -v "^./data/artifacts/" | grep -v "__pycache__" | grep -v "^./.git/"
      ```
      允许的例外只有：`app/brand.py` / `docs/internal/*` 里说明更名历史的句子、
      `test_brand.py` 的断言串、`_gen_report.py`（未跟踪临时脚本）
- [ ] **重建自索引**（若该机器有 `srcagent-self-*` 登记）：删掉
      `data/codebases_index/srcagent-self-*.json` 或在白盒会话重跑 `code_index`，
      否则 Agent 查自己会拿到旧字符串
- [ ] `python test_brand.py` 退出码 0（18 项全过）
- [ ] `python run.py --no-browser` 能起来并打印大标题（先解决端口占用）
- [ ] 浏览器打开 `http://127.0.0.1:8770/`，**标签页标题**是 `LuminaSec · 控制台`，
      左上角品牌名是 `LuminaSec`
- [ ] 浏览器打开 `http://127.0.0.1:8770/console`，标题是 `LuminaSec · 配置控制台`
- [ ] `启动控制台.bat` 双击后第一屏就是大标题，中文无乱码
- [ ] `python run_all_tests.py` 全绿（工程库本次：3588 通过 / 0 失败 / 1 跳过 的基线未回归，
      但改了名的 9 个 Python 测试 + 4 个 JS 测试全过）
- [ ] `data/artifacts/` 下两份历史报告**未被改动**

---

## 9. 换字体/换文案怎么改

只改 `app/brand.py` 一处：

| 想改什么 | 改哪 |
|---|---|
| 字体 | `ART` 元组（用 pyfiglet 生成后**固化成字符串**，别把 pyfiglet 加进依赖） |
| 副标题 | `TAGLINE` |
| 产品名 | `NAME`（同步改 `app/main.py` 的 FastAPI title 等引用处） |
| 边框字符/内缩 | `banner(border=..., pad=...)` |

改完必须同步 `启动控制台.bat` 的 echo 行，然后跑 `test_brand.py` —— 它就是干这个的。

**可选字体**（pyfiglet，均纯 ASCII，宽度 ≤ 78）：
`standard`(52) / `slant`(55，当前) / `big`(54) / `small`(40) / `rectangles`(41) /
`mini`(26) / `shadow`(54，不推荐：首字母 L 只剩一根竖线) / `cosmic`(88，**超宽，会折行**)

---

*本文档由实施 v114 改动的 agent 编写，所有结论均经实测（含真实子进程验证 bat 输出）。*

---

## 10. v115 起始页视觉重做（`web/start.html`）

### 10.1 三段式结构

| 阶段 | 内容 | 来源 |
|---|---|---|
| 背景 | 矩阵雨 canvas（字符雨 + 径向暗角），**颜色跟随色调** | G 方案 |
| 开场 | 打字机启动日志，10 行，打完**从 DOM 彻底移除** | E 方案 |
| 主体 | 终端 CLI 模式选择（状态栏 / ASCII 艺术字 / `01·02·03` 条目） | A 方案 |

### 10.2 三个关键实现决策

1. **A 界面用「浮现」不用滑入**：`opacity + scale(.985) + blur(5px→0)` 三段并行，
   **刻意不含 `translateY`** —— 位移会给出"从哪个方向来"的暗示，实测 `translateY(6px)`
   的观感是"从下面突然顶上来"，很硬。模糊值压到 5px 是因为大块文字上跑
   `filter:blur` 会触发栅格化，低端机上看得出卡顿。
2. **启动日志必须 `remove()` 而不是留占位**：留着会让「开场」和「主体」抢注意力，
   且每次进起始页都要多看一遍同样的十行。做法是先淡出（.38s）再移除，
   与 A 的浮现**同时进行**，让布局上移发生在两者都半透明的瞬间。
3. **色调用 5 套预设 + 新 localStorage 键**：`src_accent`（与 `src_theme`、`src_mode`
   三者互不干扰）。改色调只动 `TONES` 一个对象，它同时驱动强调色/边框/面板/
   矩阵雨字符色/艺术字辉光。

### 10.3 三条自我保护（缺一会变成"好看但烦人"）

- `prefers-reduced-motion` 时矩阵雨与打字机**整个不启动**，直接呈现终态
  （CSS `#rain{display:none}` + JS `if (REDUCED) finish()` 双保险）
- 页面不可见时停 `requestAnimationFrame`（切标签页不烧 CPU）
- 任意键 / 点右下角提示可跳过开场 —— 它最多惊艳一次，不能变成开机广告

### 10.4 数据诚实

启动日志里的内容全部是**产品真实静态事实**（19 个内置能力、72 条 sink、
30 req/600s 流量预算、4 级风险……），**没有编造任何运行期数据**。
要显示真实运行态请调 `/api/health`，不要在这里写死假数字。
`test_brand.py` 的 [6] 组有一条断言专门禁「已接入 / 当前目标 / 扫描中 / 在线目标」
这类编造字样。

### 10.5 ⚠️ 第七个坑：测试会把自己的流量预算烧光

**现象**：`test_replayer.py` 直跑时 section 7「真发一次请求」7 项全失败，
但换成 `run_all_tests.py` 或加 `AGENT_TRAFFIC_TEST_MODE=1` 就跑得过。

**根因**（不是代码 bug，是流量治理在按设计工作）：
- `test_replayer.py:203` 起本机临时 HTTP 服务（端口 0 = 随机），
  通过 `replayer` 发请求 → 必经 `traffic.governor.acquire()`
- governor 预算是「同一根域名 600s 内最多 30 个请求」，测试打的是 `127.0.0.1`
- **把回归连着跑几轮**（我这次连着跑了 3 轮）→ 600s 内烧了 47 个 → governor
  按设计**暂停** `127.0.0.1`，reason 写「不会自动提高额度」
- **暂停状态持久化在 SQLite**（设计上就是「重启不能绕过」），所以之后每次都拒
- `AGENT_TRAFFIC_TEST_MODE=1` 只把预算放大 50×，**不解除已持久化的 PAUSED 状态**
  —— 因为 `_check_state()` 在预算检查**之前**（`traffic.py` 的 `acquire()`）

**解法**（两步，缺一不可）：
```python
from app import traffic
traffic.governor.resume('127.0.0.1')      # ① 先解除 PAUSED
# ② 再开测试模式放大预算（或等 600s 窗口滑过去）
```
**教训**：本地跑回归要么走 `run_all_tests.py`（它自动设测试模式），
要么跑完记得 `resume` 被暂停的根域名。否则会出现「代码没改、测试突然全红」的假象。

---

## 11. v116：起始页亮/暗 + 主界面终端化 + 进入过渡

### 11.1 emoji 方向（曾写反）

`applyTheme()` 里图标表示**当前状态**，不是"点它去到哪"：
```js
btn.querySelector('.tg').textContent = t === 'light' ? '☀️' : '🌙';   // ✅
// 错过的版本：t === 'light' ? '🌙' : '☀️'   → 亮态显示月亮
```
`test_brand.py` 有正反两条断言锁方向。

### 11.2 主界面终端化 —— 改动只落 style.css

**为什么只改 style.css**：`test_appjs.js:96` 记录过一次事故 —— `update.py`
拉上游更新时会**整体覆盖 `web/{app.js,index.html}`**（v006 时前端入口因此下线过）。
`style.css` 不在覆盖清单里，所以视觉改动全部放它，`index.html` / `app.js`
一行没动。这是"把改动放在不会被机械覆盖的位置"的实操。

替换的变量（暗 / 亮两套）：

| 变量 | 旧（蓝紫） | 新（终端绿） |
|---|---|---|
| `--accent` | `#6d7cff` / `#4f6ef7` | `#00e59b` / `#0a8f63` |
| `--bg` | `#0e1116` / `#f0f2f7` | `#060a08` / `#eef2ef` |
| `--code-cmd` | `#7dd3fc` / `#0e7490` | `#5eead4` / `#0a7d5a` |
| `--accent-text` | `#a5b0ff` / `#4f6ef7` | `#5eead4` / `#0a8f63` |
| `--accent2-text` | `#c4b5fd` / `#6a4ff0` | `#7dd3fc` / `#1f6feb` |

⚠️ **最容易漏的是 `--accent-text` / `--accent2-text`**：它们用在 **12+ 处**
（`.tab.active`、`.badge.L1`、`.step-chip .st.running`、`.branch-card .bc-title`、
`.gtab.active`、`.gsvg .gnode.onpath`、`.codebase-item .cb-id`……）。
只改 `--accent` 不改它们，这些地方会整片留在旧紫，而现象是"明明改了配色还有
一堆紫的"，很容易以为是没生效。

### 11.3 刻意不改：线索图节点色 `--g-*`

那是 **10 种节点类型的分类色板**（categorical palette）。分类色板要的是
**彼此可区分**，强行塞进单一色系会让图变得难读 —— 语义清晰优先于配色统一。
已知遗留小问题：`--g-project` 与 `--g-thread` 都偏紫、`--g-evidence` 与
`--g-accent` 都偏青，**改之前就有**，本轮不动（免得又引入新的难区分），
已在 `style.css` 注释里写明理由。要治得连图例一起重新设计。

### 11.4 入场浮现与进入过渡

- **主界面**：`.app{animation: appIn .62s cubic-bezier(.22,.61,.36,1) both}`
  —— `opacity + scale(.99) + blur(4px)`，**不含位移**（与起始页同一套语言，
  位移会暗示"从哪边来"）。纯 CSS，页面加载即播，无需 JS。
- **跨页过渡**：起始页点模式卡片 → 盖一层全屏终端画面
  （`luminasec@local:~$ ./luminasec run --mode <id>` + 转圈 + `entering workspace`）
  → 460ms 后跳 `/app` → `/app` 的 `appIn` 接上。
  两头一接，读作"终端执行了一条命令 → 工作区凝现"。
- `reduced-motion` 或过渡层缺失时**直接跳，不留空窗**。

### 11.5 为什么不用 View Transitions API

Chrome 126+ 支持跨文档 View Transitions（`@view-transition{navigation:auto}`），
理论上能做真正的共享元素过渡。没用它是因为：① 只有 Chromium 系支持，
 Firefox/Safari 上会静默退化；② 本项目大量界面是 `display:none` 切换的面板，
  快照语义不稳定；③ 两个页面没有视觉上对应的元素，"共享"无从谈起。
用「遮罩 + 各自入场」的组合更可控，且在任何浏览器下降级为"直接跳转"。
