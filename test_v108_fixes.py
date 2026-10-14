# -*- coding: utf-8 -*-
"""v108 回归：内置能力不能被当成「本地可启动的程序」。

## 缺口是怎么来的（发布版实测暴露）

工具箱面板有一档筛选「本地工具（点击启动）」。点里面的条目会调
`POST /api/tools/launch/{alias}` → 由 `LocalExecutor.launch` spawn 本机程序。

而**内置能力**（HTTP 重放 / 代码执行 / 知识库检索 / 白盒代码审计 / 元认知工具 …）
的 `executable` 是 `builtin://…` —— 它们**不在磁盘上**，由 `app/replayer.py`
在本进程内托管执行，根本没有可启动的入口。可是：

    · 内置能力的 `exists` 为真（表示"该能力可用"）；
    · 端点的校验只有 `if not tool.executable: 400`（`builtin://…` 非空 ⇒ 通过）；
    · 前端那档筛选写的是 `!!t.exists && !t.url`（内置能力 ⇒ 通过）；
    · 前端还给每个条目绑了 `onclick=launchTool(alias)`。

四条叠在一起：点内置能力 → 拿 `builtin://httpreplay` 当路径去 spawn →
**WinError 123「文件名、目录名或卷标语法不正确」**，文案完全看不出原因。

## 本套件锁住的不变量

1. 端点对内置能力**明确拒绝**（400 + 说清"由 Agent 调用、不能单独启动"），不再抛 WinError；
2. 端点对不存在的别名 404、对没有可执行文件的（网页工具）400；
3. `/api/tools` 暴露 `builtin` 字段（前端据此区分，不再靠中文 `type` 串）；
4. `launchable_tools()` 不含内置能力（与界面用同一判据）；
5. 前端源码：那档筛选与点击绑定都排除内置能力。

⚠️ 本套件**绝不真的启动任何程序**：所有断言都在"被拒"的分支上。

    python test_v108_fixes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient                       # noqa: E402

from app import registry as R                                   # noqa: E402
from app.main import app                                        # noqa: E402

# TestClient 必须带回环 base_url，否则被 Host 守卫 403（见 test_console_api 的说明）
LOOPBACK = "http://127.0.0.1:8770"

ok, fail = [], []


def check(name, cond, extra=""):
    (ok if cond else fail).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" → {extra}" if extra else ""))


reg = R.registry
reg.load()

BUILTIN = "httpreplay"          # 内置能力（executable = builtin://httpreplay）
WEB_TOOL = None                 # 网页工具（url 非空、executable 为空）
for t in reg.tools:
    if t.url and not t.executable:
        WEB_TOOL = t.alias
        break

print("=" * 68)
print("v108 回归：内置能力不得被当作本地可启动的程序")
print("=" * 68)

# ---------------------------------------------------------------- 一、判据本身
print("\n=== 一、is_builtin 判据 ===")
bt = reg.get_by_alias(BUILTIN)
check("内置能力 is_builtin() 为真", bool(bt) and bt.is_builtin(), str(bt and bt.executable))
check("内置能力的 executable 是 builtin:// 前缀",
      bool(bt) and str(bt.executable).startswith(R.BUILTIN_SCHEME), str(bt and bt.executable))
ext = next((t for t in reg.tools if t.executable and not t.is_builtin()), None)
check("至少有一个非内置的可执行工具（否则本判据无从对照）", ext is not None)
check("外部工具的 is_builtin() 为假", ext is None or not ext.is_builtin(),
      str(ext and ext.executable))
check("to_dict 暴露 builtin 字段（前端据此区分，不再靠中文 type 串）",
      bt is not None and bt.to_dict().get("builtin") is True, str(bt and bt.to_dict().get("builtin")))
check("to_dict 的 builtin 对普通工具为假",
      ext is not None and ext.to_dict().get("builtin") is False)

print("\n=== 二、可一键启动清单不含内置能力 ===")
_lb = {t.alias for t in reg.launchable_tools()}
_builtins = {t.alias for t in reg.tools if t.is_builtin()}
check("launchable_tools() 与内置能力不相交", not (_lb & _builtins), str(sorted(_lb & _builtins)[:5]))
check("launchable_tools() 里的每个都不是内置能力",
      all(not reg.get_by_alias(a).is_builtin() for a in _lb))
print(f"      （可启动 {len(_lb)} 个 / 内置 {len(_builtins)} 个 / 工具总数 {len(reg.tools)}）")

# ---------------------------------------------------------------- 三、端点行为
print("\n=== 三、/api/tools/launch 的拒绝路径 ===")
with TestClient(app, base_url=LOOPBACK) as c:
    r = c.post(f"/api/tools/launch/{BUILTIN}")
    check("启动内置能力 → 400（不是 500 / 不是 WinError）", r.status_code == 400,
          str(r.status_code))
    body = r.text
    check("拒绝理由说清「是内置能力」", "内置能力" in body, body[:120])
    check("拒绝理由告诉用户该怎么做（派任务而不是点启动）",
          "任务" in body and "启动" in body, body[:160])
    check("拒绝文案里不再出现 WinError 字样（那是 spawn 失败才有的）",
          "WinError" not in body)

    r = c.post("/api/tools/launch/no_such_tool_xyz")
    check("启动不存在的别名 → 404", r.status_code == 404, str(r.status_code))

    if WEB_TOOL:
        r = c.post(f"/api/tools/launch/{WEB_TOOL}")
        check(f"启动没有可执行文件的工具（{WEB_TOOL}）→ 400", r.status_code == 400,
              str(r.status_code))
        check("拒绝理由提到「没有可执行文件」", "可执行文件" in r.text, r.text[:120])
    else:
        check("（本机没有网页工具样本，跳过该用例）", True)

# ---------------------------------------------------------------- 四、前端源码守卫
print("\n=== 四、前端：内置能力不给「点击启动」交互 ===")
_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
check("「本地工具（点击启动）」筛选排除了内置能力",
      "if (kind === 'launchable') return !!t.exists && !t.url && !t.builtin;" in _js)
check("点击绑定对内置能力跳过（click 为空则不挂 onclick）",
      "const click = t.builtin ? '' :" in _js)
check("内置能力有专属徽标", "badge builtin" in _js)
_css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
check("徽标样式已定义", ".badge.builtin" in _css)
check("内置条目不做可点击样式", ".tool.tool-builtin" in _css)

print("\n" + "=" * 68)
print(f"结果：{len(ok)} 通过 / {len(fail)} 失败")
if fail:
    for n in fail:
        print(f"  失败：{n}")
print("=" * 68)
sys.exit(1 if fail else 0)
