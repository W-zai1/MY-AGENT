# -*- coding: utf-8 -*-
"""v110 回归：本机自备工具目录（用户指定目录 → 程序自动识别 → 并入工具箱）。

## 这一版解决了什么

工具来源原先**只有一个**：`<TOOLBOX_ROOT>/config/tools.json`（某个第三方工具箱的清单）。
于是没装那个工具箱的人**一个外部工具都没有**，也没法把自己的工具加进来 ——
"工具"这个概念被一家工具箱的目录布局绑死了。

现在来源有三类：外部工具箱清单（可选）/ 内置能力（进程内托管）/ **本机自备目录**。
本套件锁的是第三类，以及它与前两类的关系。

## 本套件锁住的不变量

1. **识别规则**：扩展名 → 类型；跳过目录 / 隐藏目录 / 深度上限 / 条数上限；`.url` 收作书签；
   `.lnk` 只统计不纳入（目标不在本目录内）。
2. **输入校验**：空 / 相对路径 / 文件 / 盘符根 / 不存在 —— 各有明确报错，不是静默 0 结果。
3. **两类工具同一套闸门**：自备工具与外部工具共用 `risk_grades.json`（按名）与
   `tool_overrides.json`（按别名）—— 本套件**真的写这两个文件再重载**，看分级/禁用是否生效，
   而不是只看"它出现在列表里"。
4. **自备工具始终进模型清单**（不被 197 个外部工具的配额挤掉）—— 否则"加了却看不见"。
5. **幂等**：`load()` 反复调用不膨胀（历史踩过：清单线性膨胀到 605）。
6. **外部 alias 冻结**：197 个外部工具里 147 个带 `_2` 后缀，不能因为本版改动而变 ——
   变了会让 `tool_overrides.json` 里那 147 条闸门覆写静默失效。本套件直接钉住这个数字。
7. **两段式写入**：preview 发票据 → commit 核对票据 + 乐观锁；绕过前端也挡得住。
8. **红线**：`data/local_tools.json` 必须 gitignored；模板里不得出现本机绝对路径。

## ⚠️ 本套件不碰任何真实文件

用户真实的 `data/local_tools.json`（可能有他自己加的目录）与审计日志全部重定向到临时目录。

    python test_local_tools.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient                       # noqa: E402

from app import config, config_io, console_api, local_tools     # noqa: E402
from app.main import app                                        # noqa: E402

# TestClient 必须带回环 base_url，否则被 Host 守卫 403（见 test_console_api 的说明）
LOOPBACK = "http://127.0.0.1:8770"
PW = "test-console-pw-110"

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" → {detail}" if detail and not cond else ""))


class Sandbox:
    """把 DATA_DIR / 审计 / 备份 / 自备工具配置全部重定向到临时目录。

    为什么必须这么做：用户真实的 `data/local_tools.json` 里可能有他自己添加的目录，
    测试若读写它，跑一次回归就把用户的工具清单改了（现象是"跑完测试工具全没了"）。
    """

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lt-test-"))
        data = self.tmp / "data"
        data.mkdir()
        (data / "risk_grades.json").write_text("{}", encoding="utf-8")
        (data / "tool_overrides.json").write_text("{}", encoding="utf-8")
        self.saved = (config.DATA_DIR, config_io.AUDIT_FILE, config_io.BACKUP_DIR,
                      config_io.OVERRIDES_FILE, local_tools.CONFIG_FILE,
                      local_tools.EXAMPLE_FILE, config.CONSOLE_PASSWORD)
        config.DATA_DIR = data
        config_io.AUDIT_FILE = data / "console_audit.jsonl"
        config_io.BACKUP_DIR = data / "backups"
        config_io.OVERRIDES_FILE = data / "runtime_overrides.json"
        local_tools.CONFIG_FILE = data / "local_tools.json"
        local_tools.EXAMPLE_FILE = data / "local_tools.json.example"
        console_api._CONFIRMS.clear()
        return self

    def __exit__(self, *a):
        (config.DATA_DIR, config_io.AUDIT_FILE, config_io.BACKUP_DIR,
         config_io.OVERRIDES_FILE, local_tools.CONFIG_FILE,
         local_tools.EXAMPLE_FILE, config.CONSOLE_PASSWORD) = self.saved
        console_api._CONFIRMS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)


def make_tools_dir(root: Path) -> Path:
    """造一个"用户的工具目录"：各种扩展名 + 干扰项 + 需要跳过的目录。"""
    (root / "web").mkdir(parents=True)
    (root / "帮助" / "deep").mkdir(parents=True)
    (root / ".hidden").mkdir(parents=True)
    (root / "a" / "b" / "c" / "d" / "e").mkdir(parents=True)     # 超深度
    for n in ("MyScan.exe", "helper.bat", "cmd_tool.cmd", "vbs_tool.vbs",
              "script.py", "Tool.jar", "站点.url", "说明.txt", "README.md",
              "shortcut.lnk", "noext"):
        (root / n).write_text("URL=https://example.org/\n" if n.endswith(".url") else "x",
                              encoding="utf-8")
    (root / "web" / "dirsearch.exe").write_text("x", encoding="utf-8")
    (root / "帮助" / "deep" / "should_not_appear.exe").write_text("x", encoding="utf-8")
    (root / ".hidden" / "hidden.exe").write_text("x", encoding="utf-8")
    (root / "a" / "b" / "c" / "d" / "e" / "too_deep.exe").write_text("x", encoding="utf-8")
    return root


def login(c: TestClient) -> None:
    """登录。⚠️ 调用前必须已设置 `config.CONSOLE_PASSWORD`（未设置时是 403 fail-closed）。"""
    r = c.post("/api/console/login", json={"password": PW})
    assert r.status_code == 200, r.text


# ============================================================ A 扫描器
def test_a_scanner(sb, tools_dir):
    print("\n[A] 扫描器：识别规则与输入校验")
    scan = local_tools.scan_root({"path": str(tools_dir), "label": "测试工具"})
    check("目录存在", scan["exists"], scan.get("problem", ""))
    names = {t["name"] for t in scan["tools"]}
    rel = {t["rel_path"] for t in scan["tools"]}
    check("识别 .exe", "MyScan" in names)
    check("识别 .bat", "helper" in names)
    check("识别 .cmd", "cmd_tool" in names)
    check("识别 .vbs", "vbs_tool" in names)
    check("识别 .py", "script" in names)
    check("识别 .jar", "Tool" in names)
    check("识别 .url（网页书签）", "站点" in names)
    check(".txt 不识别", "说明" not in names)
    check(".md 不识别", "README" not in names)
    check("无扩展名不识别", "noext" not in names)
    check(".lnk 不纳入", "shortcut" not in names)

    kinds = {t["rel_path"]: t["type"] for t in scan["tools"]}
    check("MyScan.exe → 命令行", kinds.get("MyScan.exe") == "命令行", str(kinds.get("MyScan.exe")))
    check("helper.bat → 批处理", kinds.get("helper.bat") == "批处理")
    check("script.py → Python", kinds.get("script.py") == "Python")
    check("Tool.jar → JAVA8", kinds.get("Tool.jar") == "JAVA8")
    check("站点.url → 网页", kinds.get("站点.url") == "网页")
    check("类型值都落在 SCRIPTABLE_TYPES（否则不进 Agent 清单）",
          all(v in config.SCRIPTABLE_TYPES for v in kinds.values() if v != "网页"),
          str(sorted({v for v in kinds.values() if v != '网页'})))

    check("跳过「帮助」目录", not any("should_not_appear" in x for x in rel))
    check("跳过隐藏目录", not any("hidden.exe" in x for x in rel))
    check("深度上限生效（第 5 层不进）", not any("too_deep" in x for x in rel))
    check("子目录工具的分类带子目录名",
          [t["category"] for t in scan["tools"] if t["rel_path"] == "web/dirsearch.exe"]
          == ["测试工具 · web"])
    check(".url 抽出真实 URL",
          [t["url"] for t in scan["tools"] if t["rel_path"] == "站点.url"]
          == ["https://example.org/"])
    check("统计 shortcuts 计数", scan["stats"]["shortcuts"] == 1)
    check("给出快捷方式提示", "快捷方式" in (scan.get("hint") or ""))

    # 排除 / 覆写
    s2 = local_tools.scan_root({"path": str(tools_dir), "label": "T", "category": "C",
                                "excluded": ["helper.bat"],
                                "overrides": {"MyScan.exe": {"alias": "pinned_scan",
                                                             "name": "改名", "category": "X"}}})
    check("excluded 标记生效",
          [t["excluded"] for t in s2["tools"] if t["rel_path"] == "helper.bat"] == [True])
    check("overrides 改 name/category",
          [(t["name"], t["category"]) for t in s2["tools"] if t["rel_path"] == "MyScan.exe"]
          == [("改名", "X")])
    check("stale.excluded 计数正确", s2["stats"]["excluded"] == 1)
    check("stale.included = found - excluded",
          s2["stats"]["included"] == s2["stats"]["found"] - 1)

    # 输入校验（负向）
    cases = [
        ("", "空"),
        ("relative/dir", "相对路径"),
        (str(tools_dir / "说明.txt"), "这是文件不是目录"),
        ("E:\\", "盘符根"),
        (str(tools_dir / "不存在"), "目录不存在"),
    ]
    for val, why in cases:
        p, err = local_tools.validate_root_path(val)
        check(f"拒绝{why}", p is None and bool(err), f"{val!r} -> {p}")
    p, err = local_tools.validate_root_path(str(tools_dir))
    check("接受合法目录", p is not None and not err)

    check("root_id 与大小写/分隔符无关",
          local_tools.root_id(str(tools_dir)) == local_tools.root_id(str(tools_dir).upper() + "\\"))

    # 不存在与空目录
    bad = local_tools.scan_root({"path": str(tools_dir / "nope")})
    check("不存在目录：exists=False 且给出 problem", not bad["exists"] and bool(bad["problem"]))
    empty = Path(tempfile.mkdtemp(prefix="lt-empty-"))
    e = local_tools.scan_root({"path": str(empty)})
    check("空目录：exists=True 但 0 个工具",
          e["exists"] and e["stats"]["found"] == 0)

    # save_config
    conf = local_tools.save_config([{"path": str(tools_dir), "label": "L"}, {"path": "", "x": 1}])
    check("save_config 丢掉空路径", len(conf["roots"]) == 1)
    check("save_config 补出 id", bool(conf["roots"][0].get("id")))
    check("save_config 补齐默认值（java/category/excluded）",
          conf["roots"][0]["java"] == "JAVA8" and conf["roots"][0]["category"] == "L"
          and conf["roots"][0]["excluded"] == [])


# ============================================================ B registry 集成
def test_b_registry(sb, tools_dir):
    print("\n[B] registry：载入、同一套闸门、幂等")
    from app.registry import registry as reg

    # 先**在无自备配置下**载入一次，拿到外部工具的 alias 基线 ——
    # 否则拿空集去对比，冻结检查会假通过（一片全 0 的假绿）。
    local_tools.CONFIG_FILE.unlink(missing_ok=True)
    reg.load()
    before_ext = {t.alias for t in reg.tools if not t.source}
    before_suffixed = sorted(a for a in before_ext
                             if a.rsplit("_", 1)[-1].isdigit())
    check("基线：已载入外部工具", len(before_ext) > 100, str(len(before_ext)))

    local_tools.CONFIG_FILE.write_text(json.dumps({
        "version": 1, "roots": [{"path": str(tools_dir), "label": "自备",
                                 "category": "自备工具"}],
    }, ensure_ascii=False), encoding="utf-8")

    reg.load()
    locals_ = [t for t in reg.tools if t.source == "local"]
    after_ext = {t.alias for t in reg.tools if not t.source}
    after_suffixed = sorted(a for a in after_ext if a.rsplit("_", 1)[-1].isdigit())

    check("自备工具已注册", len(locals_) >= 8, str(len(locals_)))
    check("全部标了 source=local", all(t.source == "local" for t in locals_))
    check("记录了 root_label", all(t.root_label == "自备" for t in locals_))
    # 网页书签（.url）**本来就没有可执行文件**，所以只对非网页工具要求 executable。
    exed = [t for t in locals_ if not t.url]
    check("非网页的自备工具都有绝对路径 executable",
          bool(exed) and all(Path(t.executable).is_absolute() for t in exed),
          str([t.alias for t in exed if not Path(t.executable).is_absolute()]))
    check("workdir 指向工具所在目录",
          all(t.workdir and Path(t.workdir).is_dir() for t in exed))
    check("executable 不是 TOOLBOX_ROOT 下的路径（各自相对自己的目录解析）",
          all(str(Path(t.executable).parent).startswith(str(tools_dir)) for t in exed))
    by_alias = {t.alias: t for t in locals_}
    by_rel = {t.rel_path: t for t in locals_}
    check("alias 干净（无多余 _2 后缀）", "myscan" in by_alias, str(sorted(by_alias)))
    check(".url 收作网页工具（scriptable=False、有 url、无 executable）",
          by_rel.get("站点.url") is not None
          and by_rel["站点.url"].scriptable is False
          and by_rel["站点.url"].url == "https://example.org/"
          and by_rel["站点.url"].executable == "",
          str(by_rel.get("站点.url")))
    check("可编排的默认 L2（未在分级表里 → 默认档）",
          by_alias["myscan"].risk_level == config.DEFAULT_RISK_LEVEL)
    check("中文名工具的自动别名会被标成占位名（需用户改）",
          local_tools.alias_looks_placeholder(by_rel["站点.url"].alias),
          by_rel["站点.url"].alias)

    # ⚠️ 外部 alias 冻结：改 registry 很容易顺手"修好"那个 _2 后缀，
    # 而那会让 tool_overrides.json 里按 alias 索引的 147 条覆写静默失效。
    check("外部工具 alias 集合未被本版改动", before_ext == after_ext,
          f"新增/丢失 {sorted(after_ext ^ before_ext)[:6]}")
    check("外部带数字后缀的 alias 数量不变（冻结）",
          before_suffixed == after_suffixed,
          f"{len(before_suffixed)} -> {len(after_suffixed)}")
    check("stats 按来源分账",
          reg.stats()["local"] == len(locals_) and reg.stats()["external"] == len(after_ext))

    # 幂等
    n1 = len(reg.tools)
    reg.load()
    check("load() 幂等（不膨胀）", len(reg.tools) == n1, f"{n1} -> {len(reg.tools)}")

    # ---- 同一套闸门：真的写 risk_grades.json / tool_overrides.json 再重载 ----
    (config.DATA_DIR / "risk_grades.json").write_text(
        json.dumps({"MyScan": {"level": "L1", "reason": "只读信息收集，已人工确认"}},
                   ensure_ascii=False), encoding="utf-8")
    reg.load()
    t = reg.get_by_alias("myscan")
    check("自备工具能吃 risk_grades.json 的分级",
          t is not None and t.risk_level == "L1",
          f"{t.risk_level if t else None}")
    check("分级依据来自分级表", t is not None and "已人工确认" in (t.risk_reason or ""))

    (config.DATA_DIR / "tool_overrides.json").write_text(
        json.dumps({"myscan": {"disabled": True, "reason": "实测在本机不可用",
                               "allowed_flags": ["-u"], "target_type": "url"}},
                   ensure_ascii=False), encoding="utf-8")
    reg.load()
    t = reg.get_by_alias("myscan")
    check("自备工具能吃 tool_overrides.json 的禁用", t is not None and t.disabled)
    check("自备工具的旗标白名单生效", t is not None and t.allowed_flags == ["-u"])
    check("自备工具的 target_type 生效", t is not None and t.target_type == "url")
    check("禁用后不进模型清单",
          not any(x.alias == "myscan" for x in reg.usable_scriptable()))
    check("禁用后不进 schema",
          not any(s["function"]["name"] == "myscan" for s in reg.build_schemas()))

    # 恢复：只留 excluded 之外的全量
    (config.DATA_DIR / "tool_overrides.json").write_text("{}", encoding="utf-8")
    (config.DATA_DIR / "risk_grades.json").write_text("{}", encoding="utf-8")
    reg.load()

    # ---- 自备工具不被配额挤掉 ----
    schemas = [s["function"]["name"] for s in reg.build_schemas()]
    check("自备工具**始终**在 schema 里（不被外部工具配额挤掉）",
          "myscan" in schemas, f"共 {len(schemas)} 条，含 myscan={'myscan' in schemas}")
    check("配额之外仍按上限收敛（总条数不爆）",
          len(schemas) <= max(config.MAX_TOOL_SCHEMAS,
                              len([x for x in reg.usable_scriptable()
                                   if x.source == "local"])) + 1,
          str(len(schemas)))
    check("白盒模式不给自备工具（白盒不发流量）",
          not any(x.alias == "myscan" for x in reg.usable_scriptable("whitebox")))
    check("黑盒模式给自备工具",
          any(x.alias == "myscan" for x in reg.usable_scriptable("blackbox")))

    # ---- 坏目录不影响其余 ----
    local_tools.CONFIG_FILE.write_text(json.dumps({
        "version": 1,
        "roots": [{"path": str(tools_dir / "没了"), "label": "坏的"}],
    }, ensure_ascii=False), encoding="utf-8")
    reg.load()
    check("坏目录只记错误，不影响内置能力",
          reg.get_by_alias("httpreplay") is not None and len(reg.errors) >= 1)
    check("坏目录的错误里说了是哪个目录",
          any("坏的" in e for e in reg.errors), str(reg.errors[:2]))

    # ---- 配置缺失/损坏不炸 ----
    local_tools.CONFIG_FILE.write_text("{ 这不是 json", encoding="utf-8")
    reg.load()
    check("配置损坏时退化为空而不是崩",
          reg.stats()["local"] == 0 and reg.get_by_alias("httpreplay") is not None)
    local_tools.CONFIG_FILE.unlink(missing_ok=True)
    reg.load()
    check("没有自备配置时不报错", reg.stats()["local"] == 0 and not reg.errors)


# ============================================================ C 控制台端点
def test_c_api(sb, tools_dir):
    print("\n[C] 控制台端点：两段式 + 乐观锁")
    from app.registry import registry as reg

    local_tools.CONFIG_FILE.unlink(missing_ok=True)
    reg.load()
    c = TestClient(app, base_url=LOOPBACK)

    # 口令必须先配上：未配口令时 require_auth 是 **403 fail-closed**（不是 401），
    # 这是刻意的设计 ——「没设口令」和「没登录」要人做的事不同。
    saved_pw = config.CONSOLE_PASSWORD
    config.CONSOLE_PASSWORD = PW
    try:
        _test_c_body(c, tools_dir, reg)
    finally:
        config.CONSOLE_PASSWORD = saved_pw


def _test_c_body(c, tools_dir, reg):
    r = c.get("/api/console/localtools")
    check("未登录 → 401", r.status_code == 401, str(r.status_code))

    login(c)
    r = c.get("/api/console/localtools")
    check("登录后取到列表", r.status_code == 200 and r.json()["ok"])
    d = r.json()
    check("返回支持的扩展名表", ".exe" in d["ext_types"] and d["ext_types"][".exe"] == "命令行")
    check("返回深度上限与告警阈值", d["max_depth"] >= 1 and d["warn_count"] > 0)
    check("返回按来源分账的计数", "local_tools" in d["counts"])

    # scan（不写盘）
    r = c.post("/api/console/localtools/scan",
               json={"path": str(tools_dir), "label": "自备"})
    check("scan 成功", r.status_code == 200, r.text[:160])
    scan = r.json()
    check("scan 带 alias（与最终一致）", all(t.get("alias") for t in scan["tools"]))
    check("scan 标了 alias_auto", all("alias_auto" in t for t in scan["tools"]))
    check("scan 标出「别名是占位名、建议改」的条目",
          any(t.get("needs_alias") for t in scan["tools"]),
          str([(t["rel_path"], t["alias"], t.get("needs_alias")) for t in scan["tools"]][:4]))
    check("scan 不写盘", not local_tools.CONFIG_FILE.exists())

    r = c.post("/api/console/localtools/scan", json={"path": "relative/x"})
    check("scan 相对路径 → 400", r.status_code == 400, str(r.status_code))
    check("  且说明是绝对路径问题", "绝对路径" in r.text)
    r = c.post("/api/console/localtools/scan", json={"path": "E:\\"})
    check("scan 盘符根 → 400", r.status_code == 400, str(r.status_code))
    check("  且说清为什么拒绝", "盘符" in r.text)

    # browse（只列目录）
    r = c.post("/api/console/localtools/browse", json={"path": ""})
    check("browse 空路径 → 列盘符", r.status_code == 200 and r.json()["is_root_list"])
    r = c.post("/api/console/localtools/browse", json={"path": str(tools_dir)})
    bd = r.json()
    check("browse 只列目录名", all("name" in x and "path" in x for x in bd["dirs"]))
    check("browse 不返回文件内容（无 content/body 字段）",
          all("content" not in x for x in bd["dirs"]))
    check("browse 报告当前目录识别到几个工具", bd.get("here", {}).get("found", 0) >= 8)
    check("browse 的 dirs 里不含文件（说明.txt 不在）",
          not any(x["name"] == "说明.txt" for x in bd["dirs"]))

    # alias 非法
    r = c.post("/api/console/localtools/preview", json={
        "roots": [{"path": str(tools_dir), "label": "自备",
                   "aliases": {"MyScan.exe": "中文别名"}}]})
    check("非法 alias → 400", r.status_code == 400, str(r.status_code))
    check("  且解释模型侧要求 ASCII", "ASCII" in r.text)

    # 正常 preview → commit
    roots = [{"path": str(tools_dir), "label": "自备", "category": "自备工具",
              "excluded": ["helper.bat"], "aliases": {"MyScan.exe": "my_scan"}}]
    r = c.post("/api/console/localtools/preview", json={"roots": roots})
    check("preview 成功", r.status_code == 200, r.text[:200])
    prev = r.json()
    check("preview 给出 diff", len(prev["diff"]) >= 1)
    check("preview 新增目录 ⇒ level=high", prev["level"] == "high")
    check("preview 发票据", bool(prev["confirm_token"]))

    r = c.post("/api/console/localtools/commit", json={"roots": roots})
    check("无票据直接提交 → 400", r.status_code == 400, str(r.status_code))

    r = c.post("/api/console/localtools/commit", json={
        "roots": roots, "confirm_token": prev["confirm_token"],
        "expect_sha256": prev["expect_sha256"]})
    check("带票据提交成功", r.status_code == 200, r.text[:200])
    done = r.json()
    # 目录里共 8 个可识别工具，其中 helper.bat 被排除 ⇒ 期望 7 个
    check("提交后 registry 已重载并带上自备工具", done["local_tools"] >= 7,
          str(done.get("local_tools")))
    check("落盘了 local_tools.json", local_tools.CONFIG_FILE.exists())
    saved = json.loads(local_tools.CONFIG_FILE.read_text(encoding="utf-8"))
    check("落盘内容含 excluded", "helper.bat" in saved["roots"][0]["excluded"])
    check("落盘内容含钉住的 alias",
          saved["roots"][0]["overrides"]["MyScan.exe"]["alias"] == "my_scan")
    check("审计留痕", config_io.AUDIT_FILE.exists()
          and "localtools" in config_io.AUDIT_FILE.read_text(encoding="utf-8"))

    # 乐观锁
    r = c.post("/api/console/localtools/preview", json={"roots": roots + [
        {"path": str(Path(tempfile.mkdtemp(prefix="lt2-"))), "label": "第二个"}]})
    check("再来一次 preview 仍成功", r.status_code == 200, r.text[:160])
    prev2 = r.json()
    local_tools.CONFIG_FILE.write_text("{}\n", encoding="utf-8")     # 模拟别人改过
    r = c.post("/api/console/localtools/commit", json={
        "roots": roots, "confirm_token": prev2["confirm_token"],
        "expect_sha256": prev2["expect_sha256"]})
    check("预览后文件被改动 ⇒ 409 拒绝覆盖", r.status_code == 409, str(r.status_code))

    # 移除
    local_tools.CONFIG_FILE.write_text(json.dumps(
        local_tools.save_config(roots), ensure_ascii=False), encoding="utf-8")
    reg.load()
    r = c.post("/api/console/localtools/preview", json={"roots": []})
    check("清空全部目录 → preview 成功", r.status_code == 200, r.text[:160])
    p3 = r.json()
    check("清空会给出警告", any("清空" in w for w in p3["warnings"]), str(p3["warnings"]))
    r = c.post("/api/console/localtools/commit", json={
        "roots": [], "confirm_token": p3["confirm_token"],
        "expect_sha256": p3["expect_sha256"]})
    check("清空后自备工具归零", r.status_code == 200 and r.json()["local_tools"] == 0,
          r.text[:160])
    check("清空后外部/内置不受影响",
          reg.get_by_alias("httpreplay") is not None and reg.stats()["external"] > 0)

    # 无改动
    r = c.post("/api/console/localtools/preview", json={"roots": []})
    check("空 → 空 无改动 ⇒ 400 说明没有变化",
          r.status_code == 400 and "改动" in r.text, f"{r.status_code} {r.text[:120]}")

    # /api/tools 的提示（作战界面用）
    r = c.get("/api/tools?kind=all")
    tj = r.json()
    check("/api/tools 暴露 stats 与 local_hint",
          "stats" in tj and "local_hint" in tj)
    check("local_hint 在无自备工具时指向「本地工具」页",
          "本地工具" in tj["local_hint"], tj["local_hint"][:60])
    check("/api/tools 的 items 带 source 字段",
          all("source" in x for x in tj["items"]))


# ============================================================ D 前端与文案守卫
def test_d_frontend():
    print("\n[D] 前端与文案守卫")
    idx = (REPO / "console" / "index.html").read_text(encoding="utf-8")
    core = (REPO / "console" / "core.js").read_text(encoding="utf-8")
    view = REPO / "console" / "views" / "localtools.js"
    check("控制台有「本地工具」标签", 'data-view="localtools"' in idx)
    check("core.js 注册了 localtools 视图", "localtools: () => import(" in core)
    check("core.js 有对应标题", "localtools: '本地工具" in core)
    check("视图文件存在", view.exists())
    v = view.read_text(encoding="utf-8") if view.exists() else ""
    check("视图调用 preview/commit（不是直接写）",
          "/localtools/preview" in v and "/localtools/commit" in v)
    check("视图调用 browse 做目录选择", "/localtools/browse" in v)
    check("视图带确认勾选框（requireAck）", "requireAck: true" in v)

    # ⚠️ 缓存不变量：所有视图必须用**与 index.html 相同**的 core.js 版本串。
    # 不一致会让浏览器把 core.js 加载成**两个模块实例** —— 模块级状态（弹窗 resolve、
    # 当前视图）各持一份，表现为「弹窗点了没反应」「切页不刷新」这类鬼现象。
    import re as _re
    vers = set(_re.findall(r"core\.js\?v=(\d+)", idx))
    for f in sorted((REPO / "console" / "views").glob("*.js")):
        found = _re.findall(r"core\.js\?v=(\d+)", f.read_text(encoding="utf-8"))
        check(f"{f.name} 的 core.js 版本与 index.html 一致", set(found) <= vers,
              f"{found} vs {sorted(vers)}")
    check("core.js 版本串已 bump（防老用户拿到缓存里的旧视图表）",
          vers and max(int(x) for x in vers) >= 110, str(sorted(vers)))

    appjs = (REPO / "web" / "app.js").read_text(encoding="utf-8")
    check("作战界面给自备工具加「自备」徽标", "badge local-src" in appjs)
    check("徽标样式已定义",
          ".badge.local-src" in (REPO / "web" / "style.css").read_text(encoding="utf-8"))
    check("提示区会显示「下一步」", "state.toolboxHint" in appjs)

    start = (REPO / "web" / "start.html").read_text(encoding="utf-8")
    check("起始页不再点名某个具体工具箱", "天狐" not in start)

    # config.py 的守卫只针对**用户可见的运行期文案**（TOOLBOX_ROOT_HELP）。
    # 注释里那段历史说明（讲为什么删掉写死路径）刻意保留 —— 那是给人看的来龙去脉，
    # 把它一起判红就是"守卫误伤"，本项目已经踩过好几次。
    import re as _re2
    cfg = (REPO / "app" / "config.py").read_text(encoding="utf-8")
    m = _re2.search(r"TOOLBOX_ROOT_HELP = \((.*?)\)\n", cfg, _re2.S)
    help_text = m.group(1) if m else ""
    check("取到了未配置提示文案", bool(help_text))
    check("未配置提示不再点名某个具体工具箱", "天狐" not in help_text, help_text[:80])
    check("未配置提示里说清「工具箱是可选的」", "不是必须" in help_text)
    check("未配置提示里给出了「本地工具」这条出路", "本地工具" in help_text)


# ============================================================ E 红线
def test_e_redline():
    print("\n[E] 红线自检")
    gi = (REPO / ".gitignore").read_text(encoding="utf-8")
    check("data/local_tools.json 已 gitignore", "data/local_tools.json" in gi)
    ex = REPO / "data" / "local_tools.json.example"
    check("模板文件存在（机制可克隆）", ex.exists())
    if ex.exists():
        raw = ex.read_text(encoding="utf-8")
        check("模板里没有本机绝对路径（C:\\Users 之类）",
              "C:\\Users" not in raw and "C:/Users" not in raw)
        check("模板里没有点名具体第三方工具箱", "天狐" not in raw)
        tpl = json.loads(raw)          # 必须是合法 JSON（否则用户复制过去直接坏）
        check("模板是合法 JSON 且有 roots", isinstance(tpl.get("roots"), list))


def main():
    print("=" * 68)
    print("v110 回归：本机自备工具目录")
    print("=" * 68)
    with Sandbox() as sb:
        tools_dir = make_tools_dir(sb.tmp / "MyTools")
        test_a_scanner(sb, tools_dir)
        test_b_registry(sb, tools_dir)
        test_c_api(sb, tools_dir)
    test_d_frontend()
    test_e_redline()
    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
