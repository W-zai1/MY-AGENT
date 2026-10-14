# -*- coding: utf-8 -*-
"""v117 回归：别名单次生成 + 旧别名键迁移（P0-3）。

## 背景

`registry.load()` 里原先有这两句：

    tool.alias = ALIAS_OVERRIDES.get(name) or self._alias_external(name, rel, used)
    if tool.alias in used:                      # ← `_make_alias` 自己已 used.add() ⇒ 必然成立
        tool.alias = self._alias_external(name, rel, used)

⇒ 每个工具被生成**两遍**、别名永远带一个无意义后缀。实测本机：**147 个**受影响
（108 个 `_2` + 39 个被顶到 `_4`/`_6`/…/`_80`；因为双重生成让**同基名**工具每次跳 2，
40 个中文名工具全落在 `tool` / `tool_2` / … / `tool_80` 家族）。

这段长期被一段"刻意冻结"的 docstring 保护着，理由是：
`tool_overrides.json` / `invocation_templates.json` **按 alias 索引**，
改别名会让覆写**静默失效、闸门悄悄变松、不报任何错**。
⇒ 所以本条不是"删掉一句话"，而是**算法 + 键迁移 + 自检**三件一起做。

## 本套件守什么

1. 别名回到干净形态（`_2` 不再按构造出现），且**仍然唯一**；
2. `legacy_alias_map()` 能算出 `{旧: 新}`，且映射**自洽**（新名在册、旧名不在册）；
3. 迁移**幂等**、**不覆盖**已占用的键（覆盖会静默丢配置，比不迁移更坏）、保留 `_说明`；
4. ⭐ **三份配置的键都能匹配到真实工具/别名（0 死条目）** —— 这是"没迁一半"的终极自检；
5. 迁移**不是写死的一张表**（换台机器也能算出来）。

    python test_v117_alias_migration.py
"""
from __future__ import annotations

import json
import pathlib
import sys

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


# ============================================================ A · 别名回到干净形态
def test_a_clean_aliases():
    print("\n[A] 单次生成：别名干净且唯一")
    from app.registry import ALIAS_OVERRIDES, registry                  # noqa: PLC0415
    registry.load()
    tools = list(registry.tools)
    aliases = [t.alias for t in tools]
    check("全部工具都有别名", all(aliases), str([t.name for t in tools if not t.alias][:3]))
    check("⭐ 别名唯一", len(set(aliases)) == len(aliases),
          f"{len(set(aliases))} 个唯一 / {len(aliases)} 个工具")

    # ⭐⭐ 决定性判据：实际别名序列 == 「单次生成」算法算出的序列（**逐项同序**）。
    # 这一条比"有没有 _2 后缀"之类的启发式强得多 —— 后缀可能来自文件名
    # （`Struts2-19检测工具` 的 `19`），也可能来自真实重名，启发式分不清这两者。
    from app.registry import _alias_plan, _raw_tools_json                  # noqa: PLC0415
    raw = _raw_tools_json()
    plan_new = _alias_plan(raw, legacy=False)
    live_ext = [t.alias for t in tools if not getattr(t, "source", "")]
    check("⭐ 实际别名与「单次生成」算法的结果逐项一致",
          live_ext == plan_new,
          f"首个不一致处：" + str(next(((i, a, b) for i, (a, b)
                                        in enumerate(zip(live_ext, plan_new)) if a != b), "—")))
    check("⭐ 实际别名与**旧**算法（双重生成）的结果不一致（证明确实改了）",
          live_ext != _alias_plan(raw, legacy=True))

    ext = [t for t in tools if not getattr(t, "source", "")]
    check("外部工具数不变（197）", len(ext) == 197, str(len(ext)))
    n2 = sum(1 for a in aliases if a.endswith("_2"))
    check(f"以 `_2` 结尾的从 108 降到个位数（实测 {n2}）", n2 <= 5, str(n2))
    check("`webshell` 回来了、`webshell_2` 没了",
          "webshell" in aliases and "webshell_2" not in aliases)

    # 覆写过的工具别名必须原样保留（那一批走 ALIAS_OVERRIDES，不受本次改动影响）
    keep = [n for n in ALIAS_OVERRIDES if ALIAS_OVERRIDES[n] in aliases]
    check("ALIAS_OVERRIDES 指定的别名全部仍然在册", len(keep) == len(ALIAS_OVERRIDES),
          f"{len(keep)}/{len(ALIAS_OVERRIDES)}")
    check("load 没有报错", not registry.errors, str(registry.errors[:3]))


# ============================================================ B · 迁移映射自洽
def test_b_legacy_map_sane():
    print("\n[B] `legacy_alias_map()` 自洽")
    from app.registry import (_alias_plan, _raw_tools_json,              # noqa: PLC0415
                              legacy_alias_map, registry)
    registry.load()
    live = {t.alias for t in registry.tools}
    m = legacy_alias_map()
    raw = _raw_tools_json()
    check("tools.json 读得到", bool(raw), "读不到就无法算映射")
    check("映射非空（本条修复本来就是为它做的）", bool(m), str(len(m)))
    # 两套算法同长度（同一份输入、逐项对应）
    check("legacy / new 两个序列长度一致",
          len(_alias_plan(raw, legacy=True)) == len(_alias_plan(raw, legacy=False)) == len(raw))
    check("⭐ 映射的**新名**都在当前别名册里",
          all(v in live for v in m.values()),
          str([v for v in m.values() if v not in live][:5]))
    still = [k for k in m if k in live]
    # ⚠️ 旧名**可能**仍在新册里 —— 那不是 bug：新算法也会给**别的**工具产生 `tool_2`
    #    （旧的 `tool_4` 那个工具现在叫 `tool_2`）。所以这里不断言"旧名都不在册"，
    #    而是逐项验证**对应关系**：第 i 条旧名 → 第 i 条新名，且第 i 个工具现在就叫新名。
    old_plan = _alias_plan(raw, legacy=True)
    plan_new = _alias_plan(raw, legacy=False)
    ext_live = [t.alias for t in registry.tools if not getattr(t, "source", "")]
    pairs = [(o, n, ext_live[i]) for i, (o, n) in enumerate(zip(old_plan, plan_new)) if o != n]
    check("⭐ 每一对「旧→新」都对应到**同一个工具**的第 i 位",
          all(live_i == n for _o, n, live_i in pairs),
          str([p for p in pairs if p[1] != p[2]][:3]))
    print(f"    （其中 {len(still)} 条旧名恰好也是新册里的合法别名，"
          f"属正常 —— 新算法会给别的工具产生同名，已由逐项对应验证）")
    check("没有把自己映射到自己",
          all(k != v for k, v in m.items()))
    check("新名唯一（不会两条旧名并到同一个新名）",
          len(set(m.values())) == len(m),
          str([v for v in set(m.values()) if list(m.values()).count(v) > 1][:5]))


# ============================================================ C · 迁移函数本身
def test_c_migrate_function():
    print("\n[C] `migrate_alias_keys()` 行为")
    from app.registry import legacy_alias_map, migrate_alias_keys        # noqa: PLC0415
    m = legacy_alias_map()
    check("有可用的映射（否则下面几条前提不成立）", bool(m))
    old_k, new_k = next(iter(m.items()))

    # ① 正常改写
    data = {old_k: {"disabled": True}, "nuclei": {"timeout": 9}, "_说明": "保留我"}
    out, n = migrate_alias_keys(data)                 # path=None ⇒ 不落盘
    check(f"旧键 {old_k} → 新键 {new_k}", new_k in out and old_k not in out, str(list(out)[:5]))
    check("改写计数正确", n == 1, str(n))
    check("值跟着搬过去（没丢）", out.get(new_k) == {"disabled": True}, str(out.get(new_k)))
    check("无关键不动", out.get("nuclei") == {"timeout": 9})
    check("`_` 开头的说明键原样保留", out.get("_说明") == "保留我")
    check("原始输入没被就地修改（返回新字典）", old_k in data and new_k not in data)

    # ② 幂等：再迁一次应改 0 条
    out2, n2 = migrate_alias_keys(out)
    check("⭐ 幂等（第二次改 0 条）", n2 == 0, str(n2))
    check("幂等后内容不变", out2 == out)

    # ③ 目标键已被占用 ⇒ **不覆盖**（覆盖会静默丢掉另一条配置，比不迁移更坏）
    clash = {old_k: {"v": "old"}, new_k: {"v": "occupant"}}
    out3, n3 = migrate_alias_keys(clash)
    check("⭐ 目标键被占用时**不覆盖**", out3.get(new_k) == {"v": "occupant"}, str(out3))
    check("被占用的旧键原样保留（不丢配置）", old_k in out3, str(list(out3)))
    check("该条不计入改写数", n3 == 0, str(n3))

    # ④ 空映射 / 非字典不炸
    check("空字典安全", migrate_alias_keys({})[0] == {})
    check("非字典安全", migrate_alias_keys([])[0] == [])


# ============================================================ D · 配置键空间自检
def test_d_config_keys_alive():
    print("\n[D] ⭐ 三份配置的键都能匹配到真实工具/别名（0 死条目）")
    from app.registry import registry                                    # noqa: PLC0415
    registry.load()
    tools = list(registry.tools)
    aliases = {t.alias for t in tools}
    names = {t.name for t in tools}
    for fn in ("risk_grades.json", "tool_overrides.json", "invocation_templates.json"):
        p = REPO / "data" / fn
        if not p.exists():
            check(f"{fn} 存在", False, "文件不在")
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        keys = [k for k in data if not k.startswith("_")]
        dead = [k for k in keys if k not in aliases and k not in names]
        check(f"⭐ {fn}（{len(keys)} 条）无死条目", not dead,
              f"{len(dead)} 条匹配不上：{dead[:6]}")
    # 覆写是不是"按别名"就位（不是靠工具名兜住的）
    ov = json.loads((REPO / "data" / "tool_overrides.json").read_text(encoding="utf-8"))
    ovk = [k for k in ov if not k.startswith("_")]
    check("tool_overrides.json 的键**按别名**全部命中",
          all(k in aliases for k in ovk), str([k for k in ovk if k not in aliases][:5]))


# ============================================================ E · 不是写死的表
def test_e_not_hardcoded():
    print("\n[E] 迁移是**算出来的**，不是写死的表")
    code = src("app/registry.py")
    check("存在 `_raw_tools_json()`（从 tools.json 推导）", "def _raw_tools_json(" in code)
    check("存在 `_alias_plan()`（两套算法写在一处）", "def _alias_plan(" in code)
    seg = code.split("def _alias_plan(")[1].split("\ndef ")[0]
    check("`_alias_plan` 同时支持 legacy 与新版（`legacy` 参数）", "legacy" in seg)
    check("`legacy_alias_map()` 由两套算法对比得出（不是字面表）",
          "old = _alias_plan" in code and "new = _alias_plan" in code)
    check("映射有缓存（load 与 load_templates 都要用）", "_LEGACY_MAP_CACHE" in code)
    # 两份别名校验配置都要走迁移
    check("registry 的 _load_overrides 调了迁移",
          "migrate_alias_keys(data, path=p)" in src("app/registry.py"))
    check("executor 的 load_templates 也调了迁移（否则模板会失联）",
          "migrate_alias_keys(data, path=p)" in src("app/executor.py"))


# ============================================================ F · 冻结说明已改写
def test_f_freeze_note_updated():
    print("\n[F] '刻意冻结'的说明已随语义改写")
    code = src("app/registry.py")
    check("旧说明（`本版刻意冻结`）已不在", "本版刻意冻结" not in code)
    check("新说明标了 v117 且说清迁移由谁负责",
          "v117" in code and "legacy_alias_map" in code)
    check("仍保留「别把重复生成搬进来变四重生成」的警告（防止反向改错）",
          "四重生成" in code or "_4" in code)
    check("仍提醒「改生成算法 = 改所有别名，必须配键迁移」",
          "必须配一次键迁移" in code or "都必须配" in code)


def main() -> int:
    print("=" * 68)
    print("v117 回归：别名单次生成 + 旧别名键迁移（P0-3）")
    print("=" * 68)
    test_a_clean_aliases()
    test_b_legacy_map_sane()
    test_c_migrate_function()
    test_d_config_keys_alive()
    test_e_not_hardcoded()
    test_f_freeze_note_updated()
    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
