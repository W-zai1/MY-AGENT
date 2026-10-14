# -*- coding: utf-8 -*-
"""v102 工作模式（黑盒 / 白盒）回归：**模式的闸门必须真的挡得住**。

## 这份测试为什么存在

v102 给会话与项目都加了 `mode`（blackbox | whitebox），并引入 `registry.mode_allows()`
按模式过滤工具。但"加了模式"与"模式真的生效"是两件事，
下面每条都是从**实际检查里抓到的缺口**，各自对应一个具体失败模式：

1. **模式只挡了 schema / 清单，没挡执行**（最要紧）
   `registry.resolve(alias)` 是**不看模式**的查表，而系统提示词是所有模式共用的一份。
   于是白盒会话照样能被点名去调 `httpreplay` / `py_exec` 这类会**向外部发流量/执行代码**
   的工具 —— 与「白盒只做源码审计、不发目标流量」的结构性保险自相矛盾。
   同源问题：模型点了个不存在的工具时，提示信息里的可用清单若不按模式取，
   会把**另一侧的工具名**整份泄露给当前会话。

2. **白名单漏掉了"提示词点名要求调用"的工具**
   提示词写着「预算耗尽时调用 `halt_task` 收尾」「可疑点调 `propose_branch`」
   「可并行调 `split_task`」……这些片段不按模式裁剪，所以白盒白名单里必须也放行它们，
   否则模型会照着提示词去调一个"看不见"的工具：不是"收窄能力"，是**自相矛盾**。

3. **白名单里的死项**（初版写了 `kb_list` / `note_vuln`，这两个别名**根本不存在**）
   死项不报错、不生效，只让人以为"这些工具白盒能用"；而且它会掩盖真问题 ——
   真正该放行却漏掉的工具（如 `halt_task`）在 list 里看着依然"很完整"。

4. **一条永不报警的护栏**（KB 合规检查里的本机路径正则）
   原写法 `r"[A-Za-z]:\\\\Users\\\\"` 里 `\\\\` 匹配的是**两个**字面反斜杠，
   只命中 JSON/YAML 转义形态；而 KB 文档里真正的写法是**单**反斜杠 `C:\\Users\\…`
   ⇒ 真实写法、正斜杠写法**全部不命中**。**不报警的护栏等于没有护栏**，
   所以下面给它配了正向样本 + 反向样本 + 占位符豁免三组用例。

    python test_v102_modes.py
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import agent, console_api, registry  # noqa: E402

ok, fail = [], []
M = registry.ToolRegistry.mode_allows

#: 白盒侧必须放行的「元认知 / 协作」工具 —— 提示词**无条件**要求模型调用它们。
META = ("think", "halt_task", "propose_branch", "split_task", "search_history",
        "note_fact", "kb_read", "kb_search")
#: 白盒侧**绝不允许**的外部工具（会向目标发流量或执行代码）。
EXTERNAL = ("httpreplay", "burp_replay", "burp_history", "nuclei_cli",
            "py_exec", "fofa_search")
#: 提示词**逐字点名**的工具（在 SYSTEM_PROMPT 里明文出现）——
#: 这一类最危险：模型会照着提示词去调，白盒下若不可见就是自相矛盾。
PROMPT_NAMED = ("propose_branch", "split_task", "search_history")
#: 循环的元认知工具：halt_task 由运行期收敛提示点名，think 是"只想不做"的出口。
LOOP_META = ("think", "halt_task")
#: 代码审计工具：白盒专属，黑盒不该出现。
CODE = ("code_list", "code_ingest", "code_index", "code_search", "code_read")


def check(name, cond, extra=""):
    (ok if cond else fail).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" → {extra}" if extra else ""))


# ---------------------------------------------------------------- 1 白名单矩阵
def test_allow_matrix():
    print("\n[A] 模式白名单矩阵（白盒只放本侧、黑盒排除 code_*）")
    for a in META + CODE:
        check(f"白盒放行 {a}", M("whitebox", a))
    for a in EXTERNAL:
        check(f"白盒拒绝 {a}", not M("whitebox", a))
    for a in CODE:
        check(f"黑盒拒绝 {a}", not M("blackbox", a))
    for a in EXTERNAL + META:
        check(f"黑盒放行 {a}", M("blackbox", a))
    # 空模式 = 不过滤：老会话 / 未指定模式必须保持历史行为，否则是静默的功能收缩
    check("空模式不过滤（历史行为不变）",
          M("", "code_read") and M("", "httpreplay") and M("", "burp_replay"))


# ---------------------------------------------------------------- 2 提示词自洽
def test_prompt_named_tools_are_reachable():
    """提示词「点名要求调用」的工具，在白盒下必须同样可见。

    ⚠️ 这里刻意分两组，因为两类工具的"点名位置"不同（第一版把它们混成一组，
    结果被自己的前提校验抓出来 —— `think` 其实**没有**在 SYSTEM_PROMPT 里明文出现）：
      · `PROMPT_NAMED`：SYSTEM_PROMPT 里逐字出现的，模型会照着提示词去调；
      · `LOOP_META`：循环的元认知工具，其中 `halt_task` 由**运行期**的收敛提示点名
        （agent.py 预算耗尽文案「…调用 halt_task 收尾」），`think` 是"只想不做"的出口。
        二者与"审计外部目标还是审计源码"无关，任何模式都该有。
    """
    print("\n[B] 提示词点名的工具，在两种模式下都必须可调")
    prompt = agent.SYSTEM_PROMPT
    src = (ROOT / "app" / "agent.py").read_text(encoding="utf-8")
    for a in PROMPT_NAMED:
        check(f"（前提校验）提示词明文点名了 {a}", a in prompt)
        check(f"白盒放行提示词点名的 {a}", M("whitebox", a))
    check("（前提校验）halt_task 由运行期收敛提示点名（不在 SYSTEM_PROMPT 里）",
          "调用 halt_task 收尾" in src)
    for a in LOOP_META:
        check(f"白盒放行循环元认知工具 {a}", M("whitebox", a))


# ---------------------------------------------------------------- 3 白名单无死项
def test_allowlist_has_no_dead_entries():
    print("\n[C] 白名单里的每一项都必须对应一个真实存在的工具")
    reg = registry.ToolRegistry()
    reg._add_builtin_tools()          # 内置工具是纯本地定义，不依赖工具箱配置
    aliases = {t.alias for t in reg.tools}
    for entry in registry.ToolRegistry._WHITEBOX_ALLOW:
        matched = sorted(a for a in aliases if a.startswith(entry))
        check(f"白名单项 `{entry}` 匹配到真实工具", bool(matched), f"命中 {len(matched)} 个")


# ---------------------------------------------------------------- 4 真实 registry
def test_real_registry_subset():
    print("\n[D] 真实 registry 上的模式子集")
    reg = registry.ToolRegistry()
    reg._add_builtin_tools()
    wb = {t.alias for t in reg.usable_scriptable("whitebox")}
    bb = {t.alias for t in reg.usable_scriptable("blackbox")}
    check("白盒可用工具里没有外部工具", not (wb & set(EXTERNAL)),
          f"混入：{sorted(wb & set(EXTERNAL))}")
    check("黑盒可用工具里没有 code_*",
          not [a for a in bb if a.startswith("code_")],
          f"混入：{sorted(a for a in bb if a.startswith('code_'))}")
    check("白盒可用工具含全部 5 个 code_*", set(CODE) <= wb, f"缺：{sorted(set(CODE) - wb)}")
    check("白盒可用工具含元认知/协作工具（否则白盒会话无法正常收尾）",
          {"halt_task", "think"} <= wb, f"缺：{sorted({'halt_task','think'} - wb)}")


# ---------------------------------------------------------------- 5 执行闸门
def test_mode_gate_blocks_execution():
    """源码级守卫：这道闸门必须在**解析之后、执行之前**，且提示清单按模式取。"""
    print("\n[E] 模式闸门挡执行，不只是挡 schema")
    src = (ROOT / "app" / "agent.py").read_text(encoding="utf-8")
    i_resolve = src.find("tool, fuzzy = registry.resolve(alias)")
    i_gate = src.find("registry.mode_allows(session.mode")
    i_exec = src.find("await self._execute(session, step")
    check("找到工具名解析点", i_resolve > 0, str(i_resolve))
    check("存在跨模式拦截", i_gate > 0, str(i_gate))
    check("拦截点在「解析之后、执行之前」（关键）", 0 < i_resolve < i_gate < i_exec,
          f"resolve={i_resolve} gate={i_gate} exec={i_exec}")
    check("拦截后 continue（不落入风险闸门/执行）",
          "已拦截跨模式工具" in src)
    check("「工具不存在」的提示按当前模式给清单（不泄露另一侧工具名）",
          "registry.usable_scriptable(session.mode)" in src)
    check("白盒提示片段明确声明外部工具不可用",
          "外部工具在本模式下不可用" in src)


# ---------------------------------------------------------------- 6 模式片段
def test_mode_fragment():
    print("\n[F] 系统提示的模式片段")
    check("白盒片段与黑盒片段不同",
          agent.mode_fragment("whitebox") != agent.mode_fragment("blackbox"))
    check("白盒片段不为空且声明模式", "【工作模式：白盒侧测试】" in agent.mode_fragment("whitebox"))
    check("黑盒片段不为空且声明模式", "【工作模式：黑盒侧测试】" in agent.mode_fragment("blackbox"))
    check("未知模式返回空串（预留位不应污染提示词）",
          agent.mode_fragment("ctf") == "" and agent.mode_fragment("") == "")


# ---------------------------------------------------------------- 7 护栏自检
def test_kb_path_guard_can_actually_fire():
    """KB 合规检查里的「本机绝对路径」判据：能报警 + 不误报。

    用运行时拼装的原因与 test_056 相同：本文件不能真的写进本机用户名，
    否则这条护栏自己就成了新的泄露源（**避免"给扫描器加例外清单"**）。
    """
    print("\n[G] KB 合规护栏自检（不报警的护栏等于没有护栏）")
    user = "some" + "user"
    cases_bad = {
        "单反斜杠（KB 文档里的真实写法）": "C:" + chr(92) + "Users" + chr(92) + user,
        "双反斜杠（JSON/YAML 转义形态）": "C:" + chr(92) * 2 + "Users" + chr(92) * 2 + user,
        "正斜杠写法": "C:/Users/" + user,
    }
    for label, text in cases_bad.items():
        c = console_api._kb_compliance("probe-x.md", "正文\n" + text + "\n")
        check(f"含本机绝对路径被判 error：{label}",
              c["level"] == "error" and c["ok"] is False,
              f"{c['level']} {c['issues']}")
    # 反向：占位符与普通正文不得误报（否则一本正经的文档全被"修"一遍）
    c = console_api._kb_compliance("probe-x.md", "示例：E:" + chr(92) + "你的路径" + chr(92) + "target\n")
    check("占位符写法不误报", c["level"] == "ok", f"{c['level']} {c['issues']}")
    c = console_api._kb_compliance("probe-x.md", "普通正文，没有任何路径。")
    check("正常正文不误报", c["level"] == "ok", f"{c['level']} {c['issues']}")
    check("返回里带回字符数（供三级灯判断）", c["chars"] == len("普通正文，没有任何路径。"))


def main() -> int:
    print("=" * 68)
    print("v102 工作模式回归（白盒 / 黑盒闸门与提示词自洽）")
    print("=" * 68)
    test_allow_matrix()
    test_prompt_named_tools_are_reachable()
    test_allowlist_has_no_dead_entries()
    test_real_registry_subset()
    test_mode_gate_blocks_execution()
    test_mode_fragment()
    test_kb_path_guard_can_actually_fire()
    print("\n" + "=" * 68)
    print(f"结果：{len(ok)} 通过 / {len(fail)} 失败")
    if fail:
        for name in fail:
            print(f"  失败：{name}")
    print("=" * 68)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
