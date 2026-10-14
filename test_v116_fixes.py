# -*- coding: utf-8 -*-
"""v116 回归：v113 审计报告 §15「第三批」—— 文档 / 死代码 / 小不一致。

## 这一版修了什么

| 编号 | 缺陷 | 处置 |
|---|---|---|
| P2-6a | 「出网限速」三项参数（`GLOBAL_MIN_INTERVAL` / `TOOL_MIN_INTERVAL` / `REPLAY_MIN_INTERVAL`）在控制台可调、显示"已保存"，**运行时零效果** | **删掉**（连同 `app/ratelimit.py` 整条链） |
| P2-3 | 自备工具目录的 `java` 字段（JAVA8/JAVA11）**没人读** ⇒ 用户设了 JAVA11 仍静默用 JAVA8 | **让它生效** |
| P2-6c | `.ts/.tsx` 在扫描报告里被计数，却**在索引/检索里一个都没有** | **让它生效**（词法器本就写好了） |
| P2-6b | `kb.py` docstring 写死篇数 49/11（实际 58/12），且同一个数字在 5 处各抄一份 | 改成**不写死** |
| P2-6e | `format_unreachable` / `is_unreachable` / `unreachable_loc`（+ 前缀常量）自成一簇、零调用 | **删掉** |
| P2-6e | `is_stale()` 的唯一检查与 `index.build`/`search`/`sbom` 的 `CodeNotFound` 重复 | **删掉** |
| P2-6e | `load_anthropic_cfg()` 零调用点（真实路径是 `providers.get("anthropic")`） | **删掉** |
| P2-6f | 本地工具**预览**的 alias 与实际注册不一致（同 stem 的文件预览都叫 `a`、存完变 `a_2`） | **修** |

## 判断口径

"死代码"一律二选一：**能生效就生效、不值当就删**——
· `ratelimit` 是**倒退选项**（`traffic.governor` 明确取代它：sleep 式限速挡不住三类真实风险），所以删；
· `java` 字段 / TypeScript 的机制**其实都已写好**（executor 有双 java 路径、`index.py` 有 TS 三张表），
  只差最后一环没接上，所以生效。

    python test_v116_fixes.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f" → {detail}" if detail and not cond else ""))


def src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ============================================================ H · ratelimit 整链
def test_h_ratelimit_removed():
    print("\n[H] P2-6a · 「出网限速」三项参数与 ratelimit 整链已删除")
    check("app/ratelimit.py 已不存在", not (REPO / "app/ratelimit.py").exists())
    for rel in ("app/main.py", "app/executor.py", "app/difftest.py", "app/replayer.py"):
        t = src(rel)
        bad_imp = [ln.strip() for ln in t.splitlines()
                   if ln.strip().startswith("from . import") and "ratelimit" in ln]
        check(f"{rel} 不再 import ratelimit", not bad_imp, str(bad_imp))
        bad_call = [ln.strip() for ln in t.splitlines()
                    if "ratelimit." in ln and not ln.lstrip().startswith("#")]
        check(f"{rel} 里没有 ratelimit.xxx() 调用", not bad_call, str(bad_call[:2]))

    from app import param_spec                                      # noqa: PLC0415
    keys = {s["key"] for s in param_spec.SPECS}
    for k in ("GLOBAL_MIN_INTERVAL", "TOOL_MIN_INTERVAL", "REPLAY_MIN_INTERVAL"):
        check(f"控制台参数表里已无 {k}", k not in keys, str(sorted(keys)[:8]))
    groups = {s["group"] for s in param_spec.SPECS}
    check("「出网限速」组已从 SPECS 移除", "出网限速" not in groups)
    check("GROUP_ORDER 里也没有空组（否则界面会多一个空标题）",
          "出网限速" not in param_spec.GROUP_ORDER
          and groups <= set(param_spec.GROUP_ORDER),
          f"SPECS 组={sorted(groups)} ORDER={param_spec.GROUP_ORDER}")

    from app import config                                          # noqa: PLC0415
    for k in ("GLOBAL_MIN_INTERVAL", "TOOL_MIN_INTERVAL", "REPLAY_MIN_INTERVAL"):
        check(f"config 里已无 {k} 常量", not hasattr(config, k))
    check("config 里留了说明（用户改过 config.yaml 的话能看懂为什么没效果）",
          "TOOL_MIN_INTERVAL" in src("app/config.py"))


# ============================================================ I · 目录级 java 生效
def test_i_java_field_effective():
    print("\n[I] P2-3 · 自备工具目录的 `java` 字段真的生效")
    from app import local_tools as LT                                # noqa: PLC0415
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v116-java-"))
    try:
        (tmp / "tool.jar").write_bytes(b"PK\x03\x04")
        base = {"path": str(tmp), "label": "x", "enabled": True}

        s8 = LT.scan_root({**base, "java": "JAVA8"})
        s11 = LT.scan_root({**base, "java": "JAVA11"})
        t8 = {t["rel_path"]: t["type"] for t in s8["tools"]}
        t11 = {t["rel_path"]: t["type"] for t in s11["tools"]}
        check(".jar 被识别出来", "tool.jar" in t8, str(t8))
        check("根级 java=JAVA8 ⇒ type=JAVA8", t8.get("tool.jar") == "JAVA8", str(t8))
        check("⭐ 根级 java=JAVA11 ⇒ type=JAVA11（此前恒为 JAVA8）",
              t11.get("tool.jar") == "JAVA11", str(t11))
        check("缺省（没写 java）回落 JAVA8", LT.scan_root(base)["tools"][0]["type"] == "JAVA8")

        # 条目级 type 覆写仍然优先于根级 java（别把已有的优先级弄反）
        norm = LT.normalize_root({**base, "java": "JAVA11",
                                  "overrides": {"tool.jar": {"type": "命令行"}}})
        ov = LT.scan_root(norm)
        check("条目级 type 覆写优先于根级 java",
              ov["tools"][0]["type"] == "命令行", str(ov["tools"][0]["type"]))
        # 非法值不应把 type 弄坏
        bad = LT.scan_root({**base, "java": "JAVA99"})
        check("非法 java 值回落 JAVA8（不产生无效 type）",
              bad["tools"][0]["type"] in ("JAVA8", "JAVA11"), str(bad["tools"][0]["type"]))
        check("_resolve_java 只认 JAVA8/JAVA11",
              LT._resolve_java({"java": "java11"}, "JAVA8") == "JAVA11"
              and LT._resolve_java({"java": "x"}, "JAVA8") == "JAVA8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ J · TypeScript 生效
def test_j_typescript_effective():
    print("\n[J] P2-6c · TypeScript 不再「被计数却不被索引」")
    from app.codebase import ingest as G                             # noqa: PLC0415
    from app.codebase import index as IDX                            # noqa: PLC0415
    check("SUPPORTED_LANGS 含 typescript", "typescript" in G.SUPPORTED_LANGS,
          str(G.SUPPORTED_LANGS))
    check(".ts / .tsx 都映射到 typescript",
          G.LANG_BY_EXT.get(".ts") == "typescript"
          and G.LANG_BY_EXT.get(".tsx") == "typescript")
    # 决定性：词法器真的能从 TS 源码里抽到符号（不是只改了个元组）
    ts = ("import { Router } from 'express';\n"
          "export interface UserDTO { id: number; name: string }\n"
          "export class UserService {\n"
          "  private readonly repo: Map<string, UserDTO>;\n"
          "  async find(id: string): Promise<UserDTO | null> {\n"
          "    const sql = `SELECT * FROM users WHERE id = ${id}`;\n"
          "    return this.repo.get(id) ?? null;\n"
          "  }\n"
          "}\n"
          "export const buildRouter = (): Router => ({} as Router);\n")
    syms, strs, imports = IDX._lex_extract(ts, "svc.ts", "typescript")
    names = {s.name for s in syms}
    check("TS 里抽到了 class / interface / 函数符号",
          {"UserService", "UserDTO"} <= names, str(sorted(names)[:10]))
    check("TS 里抽到了 import",
          any("express" in (i.module or "") for i in imports), str(imports[:3]))
    check("TS 里抽到了字符串字面量（模板串也算）", len(strs) >= 1, str(len(strs)))

    # 索引与检索两层都按 SUPPORTED_LANGS 过滤 —— 断言它们用的是同一个元组
    check("index.py 按 SUPPORTED_LANGS 过滤（所以本改动即刻生效）",
          "if lang not in G.SUPPORTED_LANGS" in src("app/codebase/index.py"))
    check("search.py 同样按 SUPPORTED_LANGS 过滤",
          "if lang not in G.SUPPORTED_LANGS" in src("app/codebase/search.py"))

    # 扫描侧：.ts 现在既进 files 也进 by_lang
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v116-ts-"))
    try:
        (tmp / "a.ts").write_text(ts, encoding="utf-8")
        (tmp / "b.js").write_text("export const x = 1;\n", encoding="utf-8")
        s = G.scan_tree(tmp)
        check(".ts 进了扫描 files", "a.ts" in s.files, str(s.files))
        check("by_lang 里有 typescript", s.by_lang.get("typescript") == 1, str(dict(s.by_lang)))
        check("typescript 现在属「首批可分析」（此前被当不支持的）",
              "typescript" in G.SUPPORTED_LANGS)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ K · 篇数不再写死
def test_k_kb_count_not_hardcoded():
    print("\n[K] P2-6b · 知识库篇数不再在代码/文档里写死")
    import re                                                        # noqa: PLC0415
    stale = re.compile(r"\b(49|11)\s*篇")
    for rel in ("app/kb.py", "app/registry.py", "README.md"):
        hits = stale.findall(src(rel))
        check(f"{rel} 里没有过期的「N 篇」硬编码", not hits, str(hits))
    check("kb.py 说明了为什么刻意不写死（防再犯）",
          "刻意不写死" in src("app/kb.py"))
    check("kb.py 指明了篇数的权威来源",
          "data/kb/README.md" in src("app/kb.py"))
    # 工具描述是**直接喂给模型**的，尤其不能带过期数字
    from app.registry import registry                                 # noqa: PLC0415
    registry.load()
    kb_tool = [t for t in registry.tools if t.alias == "kb_search"]
    check("kb_search 在内置清单里", bool(kb_tool))
    if kb_tool:
        d = kb_tool[0].description
        check("⭐ kb_search 的 description 里没有「49 篇」（模型看到的就是它）",
              "49 篇" not in d, d[:80])


# ============================================================ L · 死代码：删/留
def test_l_dead_code_decided():
    print("\n[L] P2-6e · 死代码的处置：**零引用才删，受测试覆盖的保留**")
    # ---- ① 该删的：生产与测试**都没有**引用 ----
    check("`load_anthropic_cfg` 已删除（零调用点，真实路径是 providers）",
          not [ln for ln in src("app/llm.py").splitlines()
               if "def load_anthropic_cfg" in ln and not ln.lstrip().startswith("#")])
    check("`DeepSeekBackend` 别名**保留**（外部按旧名 import 的兼容点）",
          "DeepSeekBackend" in src("app/llm.py"))
    check("删除理由写在原位注释里（后人能查到为什么没了）",
          "v115 删掉了 `load_anthropic_cfg" in src("app/llm.py"))

    # ---- ② 不该删的：它们**有测试钉住契约/行为** ----
    # 判定依据不是"生产有没有人调"，而是"删掉会不会删掉一份被测试保护的规格"。
    keep = [
        ("app/codebase/evidence.py", "def format_unreachable(",
         "test_064_codebase_evidence.py"),
        ("app/codebase/evidence.py", "def is_unreachable(",
         "test_064_codebase_evidence.py"),
        ("app/codebase/evidence.py", "def unreachable_loc(",
         "test_064_codebase_evidence.py"),
        ("app/codebase/index.py", "def is_stale(",
         "test_060_codebase_index.py"),
    ]
    for rel, noun, testf in keep:
        bad = [ln for ln in src(rel).splitlines()
               if noun.strip() in ln and not ln.lstrip().startswith("#")]
        check(f"{rel} 里 {noun.strip('(')} **保留**（有 {testf} 覆盖）", bool(bad))
    def flat(rel: str) -> str:
        """把源码压成单行：说明文字常被换行断开，直接搜整句会搜不到。
        （这是"判据要认形态"的另一面 —— 文本的**换行位置**不该影响判定。）"""
        return " ".join(src(rel).split())

    check("evidence 里那组带了状态说明（不是被当成死代码）",
          "尚未接入" in flat("app/codebase/evidence.py")
          and "等接线" in flat("app/codebase/evidence.py"))
    check("is_stale 也带了状态说明", "尚未接入" in flat("app/codebase/index.py"))
    # ---- ③ 决定性：保留的依据（那些测试真的引用它们）----
    t64 = src("test_064_codebase_evidence.py")
    check("⭐ test_064 真的在断言这三个函数的行为（所以不能删）",
          all(x in t64 for x in ("format_unreachable", "is_unreachable", "unreachable_loc")),
          "测试没有引用 → 那才叫死代码")
    check("⭐ test_060 真的在断言 is_stale（所以不能删）",
          "is_stale" in src("test_060_codebase_index.py"))

    # ---- ④ ratelimit 那条链的脚手架也清掉了 ----
    # ⚠️ 只认**调用形态**（赋值/读取），不认裸文本 —— 我自己那两句解释性注释里
    #    也写着这个名字，裸文本判据会命中自己（本项目第五次踩这个坑）。
    tr = src("test_replayer.py")
    live = [ln.strip() for ln in tr.splitlines()
            if "REPLAY_MIN_INTERVAL" in ln and not ln.lstrip().startswith("#")]
    check("test_replayer 里不再**实际使用**已删的 REPLAY_MIN_INTERVAL",
          not live, str(live[:3]))


# ============================================================ M · 预览别名一致
def test_m_preview_alias_matches():
    print("\n[M] P2-6f · 本地工具预览的 alias 与实际注册一致")
    from app.registry import registry                                 # noqa: PLC0415
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v116-prev-"))
    try:
        # 同一 stem 的两个文件：实际注册会给 a / a_2，预览必须给同一对
        (tmp / "a.exe").write_bytes(b"MZ")
        (tmp / "a.py").write_text("print(1)\n", encoding="utf-8")
        (tmp / "b.exe").write_bytes(b"MZ")
        registry.load()
        pv = registry.preview_local_root({"path": str(tmp), "label": "x", "enabled": True})
        aliases = {t["rel_path"]: t["alias"] for t in pv["tools"]}
        check("三个工具都识别到了", len(aliases) == 3, str(aliases))
        check("⭐ 同 stem 的两个文件拿到**不同**别名（此前预览都叫 a）",
              aliases.get("a.exe") != aliases.get("a.py"), str(aliases))
        check("无冲突的那个仍是干净名 b", aliases.get("b.exe") == "b", str(aliases))
        check("被加后缀的那个标记了 conflict（界面上会提示）",
              any(t.get("conflict") for t in pv["tools"] if t["rel_path"] == "a.py")
              or aliases.get("a.py", "").endswith("_2"), str(aliases))
        check("所有别名唯一（预览里不该出现重名）",
              len(set(aliases.values())) == len(aliases), str(aliases))
        # 静态守卫：别再传那份"每轮新副本"
        check("preview 与 _add_local_tools 用同一个累积集（源码层面）",
              "set(taken))" not in src("app/registry.py").split("def preview_local_root")[1]
              .split("def _add_builtin_tools")[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("=" * 68)
    print("v116 回归：第三批（文档 / 死代码 / 小不一致）")
    print("=" * 68)
    test_h_ratelimit_removed()
    test_i_java_field_effective()
    test_j_typescript_effective()
    test_k_kb_count_not_hardcoded()
    test_l_dead_code_decided()
    test_m_preview_alias_matches()
    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
