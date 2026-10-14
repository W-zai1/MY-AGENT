# -*- coding: utf-8 -*-
"""v111 回归：控制台「统计看板」的 `/api/console/stats`。

## 这一版解决了什么

`console/views/charts.js` 一直是占位页，它列的 4 个接口里 3 个 `/api/usage/*` 是「已有」，
**只有 `GET /api/console/stats` 是「待建」** —— 整页就卡在这一个口上。

它是**执行侧**聚合（步骤成功率 / 耗时 / 工具调用 / 目标流量），
与 `/api/usage/*` 的**成本侧**（token、费用）互补、刻意不重叠。

## 本套件锁住的不变量

**口径（最重要的四条）**
1. 「成功率」分母**只算 done + error**：`denied`（闸门按设计拦下）与 `running`（在途）都不算失败。
   —— 混进来的话成功率会随"用户有没有配白名单/任务约束"漂移，看板直接骗人。
2. 耗时分位数**只取 `elapsed > 0`**。夹具刻意让**19 条里只有 10 条**有有效耗时（其余 9 条是 0），
   并把断言写成"p50 必须等于有效样本的中位数（5.0）" —— 若 0 值混进去，p50 会掉到 3.0，
   这条断言就会红。不这么设计的话「剔 0」这条口径**根本测不出来**（第一版就写成了那样）。
3. 空窗口 / 分母为 0 时 `success_rate` 返回 **None 而不是 0**（0 会被读成"全线失败"）。
4. `attribution` 归一化成有限几个可行动的桶；未知取值**必须显式出现**（不得静默丢弃）；
   v111 之前的 `denied` 旧数据要单独归成「未标注（旧数据）」，不能混进"未归因"。

**工程约束**
5. 只读：调用前后 DB 行数不变。
6. `days` 夹取到 [0, 365]；`days=0` = 全部历史；`refresh=1` 跳过缓存。
7. `idx_steps_created` 必须存在、且**真的被规划器用上**（EXPLAIN 不能是 `SCAN steps`）。
   ⚠️ 这一条必须用**足够大的表**来验：小表上 SQLite 合法地选择全扫（比走索引更划算），
   拿小表去断言会得到一个"在别人机器上随机红"的测试。
8. 窗口内没有数据时要能**解释原因**（库里的数据可能早于窗口）—— 否则用户只看到一片空白。

## ⚠️ 本套件不碰真实数据库

全部在临时库上跑（`store.DB_PATH` 重定向 + `init_db()` 建表），跑完删掉。
用户的 `data/projects.db` 里有真实交战数据，测试若写它会直接毁掉历史。

    python test_console_stats.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import time
import uuid

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient                    # noqa: E402

from app import config, console_api, store                   # noqa: E402
from app.main import app                                     # noqa: E402

LOOPBACK = "http://127.0.0.1:8770"
PW = "test-console-pw-111"
NOW = time.time()

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" → {detail}" if detail and not cond else ""))


class TempDB:
    """把 store.DB_PATH 指到临时库并建好 schema（跑完还原并删除）。"""

    def __init__(self, n_steps: int = 0):
        self.n = n_steps

    def __enter__(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="stats-test-"))
        self.saved = store.DB_PATH
        store.DB_PATH = self.tmp / "projects.db"
        store.init_db()
        console_api.STATS_CACHE.clear()
        if self.n:
            with store._db() as c:
                for i in range(self.n):
                    c.execute(
                        "INSERT INTO steps (id,session_id,tool_alias,tool_name,status,"
                        "attribution,elapsed,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (f"b{i}", "s", "tool_a", "工具A", "done", "", 1.0,
                         NOW - (i % 40) * 86400))
        return self

    def __exit__(self, *a):
        store.DB_PATH = self.saved
        console_api.STATS_CACHE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)


def add_step(c, *, status="done", attribution="", elapsed=0.0, at=None,
             alias="httpreplay", name="HTTP重放器"):
    """插一条步骤。

    ⚠️ `elapsed` 默认 **0.0**（= 没记录到耗时）。夹具刻意让绝大多数行都是 0，
    只有少数几条有真实耗时 —— 这样「分位数剔 0」才有可证伪的检验
    （见文件头第 2 条）。
    """
    c.execute(
        "INSERT INTO steps (id,session_id,tool_alias,tool_name,target,args,risk_level,"
        "status,output,attribution,elapsed,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex[:12], "s1", alias, name, "a.test", "", "L1",
         status, "", attribution, elapsed, at if at is not None else NOW))


def seed():
    """夹具：19 条步骤 + 流量 + 漏洞 + flow。

    steps 分布（全部在窗口内，另 1 条在 40 天前）：
      done × 8          耗时 1..8 秒（**有效**）
      done × 1（40 天前）耗时 3 秒（**有效**，用于验「窗口外不计入」）
      error L1 × 1      耗时 10 秒（**有效**）
      error L1 × 1      耗时 0（无效）
      error SCOPE / WAF_BLOCKED / L4 / XYZ 各 1（耗时 0）
      denied × 3        其中 1 条带 GATE_CONSTRAINT，2 条是旧数据（空归因）
      running × 1
    ⇒ 有效耗时 10 条（8 条 done + 1 条 error L1 的 10 秒 + 那条 40 天前的 3 秒）、无效 9 条；
      有效样本排序 = [1,2,3,3,4,5,6,7,8,10] ⇒ 取 offset=int(10*0.5)=5 ⇒ p50 = 5.0
      （若把 9 条 0 混进来：19 个样本、offset=9 ⇒ p50 变成 3.0 —— 断言能抓住）
    """
    with store._db() as c:
        c.execute("INSERT INTO projects (id,name,target,note,created_at,mode) "
                  "VALUES (?,?,?,?,?,?)",
                  ("p1", "测试项目", "a.test", "", NOW - 90000, "blackbox"))
        c.execute("INSERT INTO sessions (id,project_id,title,status,created_at) "
                  "VALUES (?,?,?,?,?)", ("s1", "p1", "会话", "active", NOW - 90000))
        for i in range(8):
            add_step(c, status="done", elapsed=float(i + 1))
        add_step(c, status="error", attribution="L1", elapsed=10.0)
        add_step(c, status="error", attribution="L1", elapsed=0.0)
        add_step(c, status="denied", attribution="GATE_CONSTRAINT")
        add_step(c, status="denied", attribution="")
        add_step(c, status="denied", attribution="")
        add_step(c, status="running")
        add_step(c, status="error", attribution="SCOPE")
        add_step(c, status="error", attribution="WAF_BLOCKED")
        add_step(c, status="error", attribution="L4")
        add_step(c, status="error", attribution="XYZ")               # 未知取值
        add_step(c, status="done", elapsed=3.0, at=NOW - 86400 * 40)  # 窗口外
        # 流量：sent 30 / settled 28 / rejected 2 ⇒ settled < sent（用于验"差 3 条"的提示）
        # 错误类型挂在 sent 上，免得把 settled 顶得比 sent 还多、把夹具自己搞反。
        for et, n in (("sent", 30), ("settled", 28), ("rejected", 2)):
            for _ in range(n):
                c.execute(
                    "INSERT INTO traffic_events (project_id,session_id,event_type,"
                    "error_type,status_code,bytes_in,created_at) VALUES (?,?,?,?,?,?,?)",
                    ("p1", "s1", et, "", 200, 100, NOW))
        for _ in range(5):
            c.execute(
                "INSERT INTO traffic_events (project_id,event_type,error_type,created_at) "
                "VALUES (?,?,?,?)", ("p1", "sent", "ConnectError", NOW))
        c.execute("INSERT INTO findings (id,project_id,title,severity,target,created_at) "
                  "VALUES (?,?,?,?,?,?)", ("f1", "p1", "未授权访问", "高危", "a.test", NOW))
        c.execute("INSERT INTO findings (id,project_id,title,severity,target,created_at) "
                  "VALUES (?,?,?,?,?,?)", ("f2", "p1", "信息泄露", "低危", "a.test", NOW))
        c.execute("INSERT INTO flow_runs (id,project_id,verdict,created_at) VALUES (?,?,?,?)",
                  ("r1", "p1", "flow_protected", NOW))


def login(c):
    c.post("/api/console/login", json={"password": PW})


# ============================================================ A 端点基础
def test_a_basic(client):
    print("\n[A] 端点基础：鉴权 / 参数夹取 / 缓存 / 只读")
    saved = config.CONSOLE_PASSWORD
    # 「未设口令」要为真：本机 config.yaml 里**是配了** consolePassword 的，
    # 所以光把 config.CONSOLE_PASSWORD 置空不够 —— console_password() 会回落到
    # config.yaml 从而仍然非空（现象是拿到 401 而不是 403）。把 yaml 路径指到一个
    # 空文件才真的构成"未设口令"这个前提。
    empty_yml = pathlib.Path(tempfile.mkdtemp(prefix="stats-cfg-")) / "config.yaml"
    empty_yml.write_text("", encoding="utf-8")
    saved_yml = console_api._config_yaml_path
    try:
        console_api._config_yaml_path = lambda: empty_yml
        config.CONSOLE_PASSWORD = ""
        r = client.get("/api/console/stats")
        check("未设口令 → 403（fail-closed，不是 401）", r.status_code == 403,
              str(r.status_code))
        console_api._config_yaml_path = saved_yml
        config.CONSOLE_PASSWORD = PW
        console_api.STATS_CACHE.clear()
        r = client.get("/api/console/stats")
        check("未登录 → 401", r.status_code == 401, str(r.status_code))

        login(client)
        r = client.get("/api/console/stats")
        check("登录后 200", r.status_code == 200, r.text[:150])
        d = r.json()
        for k in ("window", "cache", "steps", "attribution", "attribution_raw",
                  "tools", "traffic", "findings", "flow", "span", "notes"):
            check(f"返回含 {k}", k in d)

        r = client.get("/api/console/stats?days=9999")
        j = r.json()
        check("days 超过上限被夹到 365",
              j["window"]["days"] == 365 and j["clamped"] is True, str(j["window"]))
        check("  并说明已被夹取", any("上限" in n for n in j["notes"]),
              str(j["notes"])[:120])
        r = client.get("/api/console/stats?days=-5")
        j = r.json()
        check("days 为负被夹到 0（全部历史）",
              j["window"]["days"] == 0 and j["window"]["since"] is None, str(j["window"]))
        r = client.get("/api/console/stats?days=abc")
        check("days 非数字 → 422（不是静默用默认值）", r.status_code == 422,
              str(r.status_code))

        console_api.STATS_CACHE.clear()
        h1 = client.get("/api/console/stats?days=0").json()["cache"]["hit"]
        h2 = client.get("/api/console/stats?days=0").json()["cache"]["hit"]
        h3 = client.get("/api/console/stats?days=0&refresh=1").json()["cache"]["hit"]
        check("缓存：首次未命中 → 二次命中", h1 is False and h2 is True, f"{h1}/{h2}")
        check("refresh=1 跳过缓存", h3 is False, str(h3))

        with store._db() as c:
            before = tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                           for t in ("steps", "traffic_events", "findings", "flow_runs"))
        client.get("/api/console/stats?days=0&refresh=1")
        with store._db() as c:
            after = tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                          for t in ("steps", "traffic_events", "findings", "flow_runs"))
        check("端点只读（调用前后行数一致）", before == after, f"{before} → {after}")
    finally:
        config.CONSOLE_PASSWORD = saved
        console_api._config_yaml_path = saved_yml


# ============================================================ B 口径
def test_b_semantics(client):
    print("\n[B] 口径：分母 / 耗时剔 0 / 归因归一化 / 窗口边界")
    console_api.STATS_CACHE.clear()
    d = client.get("/api/console/stats?days=0").json()
    st = d["steps"]
    bs = st["by_status"]
    check("状态分布齐全",
          bs.get("done") == 9 and bs.get("error") == 6 and bs.get("denied") == 3
          and bs.get("running") == 1, str(bs))
    check("分母 = done + error（不含 denied / running）", st["judged"] == 15,
          str(st["judged"]))
    check("success_rate = done / judged = 9/15",
          abs(st["success_rate"] - 9 / 15) < 1e-6, str(st["success_rate"]))
    naive = bs["done"] / st["total"]
    check("  与「全塞进分母」的错算法确实不同（这条口径真的起作用）",
          abs(naive - st["success_rate"]) > 0.01,
          f"naive={naive:.4f} vs 正确={st['success_rate']:.4f}")
    check("denied_by_gate 单列出来", st["denied_by_gate"] == 3, str(st["denied_by_gate"]))

    el = st["elapsed"]
    check("耗时：有效 10 条 / 排除 9 条（elapsed<=0）",
          el["valid"] == 10 and el["excluded"] == 9, str(el))
    check("max = 10.0（有效样本里的最大值）", abs(el["max"] - 10.0) < 1e-6, str(el["max"]))
    # ⭐ 这条是本套件的核心断言：有效样本排序 [1,2,3,3,4,5,6,7,8,10] 取 offset=5 ⇒ 5.0；
    # 若把 9 条 0 混进来，19 个样本取 offset=9 ⇒ 会变成 3.0。
    check("p50 = 5.0 —— 0 值若混进分位数会变成 3.0（剔 0 口径真的生效）",
          el["p50"] == 5.0, str(el["p50"]))

    buckets = {x["bucket"]: x["n"] for x in d["attribution"]}
    check("SCOPE → 停手·授权边界", buckets.get("停手·授权边界") == 1, str(buckets))
    check("WAF_BLOCKED → 停手·目标防护", buckets.get("停手·目标防护") == 1, str(buckets))
    check("L4 → 跑通但无结果", buckets.get("跑通但无结果") == 1, str(buckets))
    check("L1 归入「工具未跑起来」（2 条）", buckets.get("工具未跑起来") == 2, str(buckets))
    check("GATE_CONSTRAINT → 闸门拒绝·任务约束",
          buckets.get("闸门拒绝·任务约束") == 1, str(buckets))
    check("denied + 空归因（旧数据）→ 单独的「未标注」桶",
          buckets.get("闸门拒绝·未标注（旧数据）") == 2, str(buckets))
    check("未知归因 XYZ **不静默丢弃**，显式列为「其他（XYZ）」",
          buckets.get("其他（XYZ）") == 1, str(buckets))
    check("running 不出现在归因分布里（它不是失败）",
          all(x["status"] != "running" for x in d["attribution_raw"]),
          str(d["attribution_raw"]))
    check("归因桶总数 = 全部失败/拒绝条数（不丢不重）",
          sum(buckets.values()) == 9, f"{sum(buckets.values())} vs 9")

    console_api.STATS_CACHE.clear()
    d2 = client.get("/api/console/stats?days=1").json()
    check("窗口外的步骤不计入（19 → 18，只少了那条 40 天前的）",
          d2["steps"]["total"] == 18 and d["steps"]["total"] == 19,
          f"days=1:{d2['steps']['total']} vs 全部:{d['steps']['total']}")
    check("  span 仍是**全部历史**（不受窗口限制）",
          d2["span"]["last_step_at"] and d2["span"]["last_step_at"] > d2["span"]["first_step_at"],
          str(d2["span"]))

    check("流量事件统计（sent 30 + 5 条带错误的 sent = 35；settled 28）",
          d["traffic"]["by_event_type"].get("sent") == 35
          and d["traffic"]["by_event_type"].get("settled") == 28,
          str(d["traffic"]["by_event_type"]))
    check("错误类型统计", d["traffic"]["by_error_type"].get("ConnectError") == 5,
          str(d["traffic"]["by_error_type"]))
    check("sent > settled 时给出提示",
          any("settled" in n for n in d["notes"]), str(d["notes"])[:200])
    check("漏洞按严重度分组",
          d["findings"]["by_severity"].get("高危") == 1, str(d["findings"]))
    check("flow verdict 分组", d["flow"]["verdicts"].get("flow_protected") == 1,
          str(d["flow"]))
    # 夹具用的别名 `httpreplay` 是**真实存在于可用工具里的**，所以"从未用过"的集合
    # 必然比"可用工具"少一个 —— 这条断言才能真的验到「never_used 是拿可用工具做差」。
    check("工具统计：distinct / used 都在",
          d["tools"]["distinct"] == 1 and d["tools"]["used"] == ["httpreplay"],
          str(d["tools"])[:160])
    check("never_used = 可用工具 − 用过的（60 → 59）",
          d["tools"]["usable"] > 1
          and d["tools"]["never_used_total"] == d["tools"]["usable"] - 1,
          f"usable={d['tools']['usable']} never={d['tools']['never_used_total']}")
    check("never_used 里不含真正用过的那个别名",
          "httpreplay" not in d["tools"]["never_used"], str(d["tools"]["never_used"])[:120])


# ============================================================ C 空库
def test_c_empty(client):
    print("\n[C] 空库：不报错、返回 null 而不是 0")
    with TempDB():
        r = client.get("/api/console/stats?days=0&refresh=1")
        check("空库也返回 200", r.status_code == 200, r.text[:150])
        d = r.json()
        check("success_rate 是 None（不是 0 —— 0 会被读成全线失败）",
              d["steps"]["success_rate"] is None, str(d["steps"]["success_rate"]))
        check("judged = 0", d["steps"]["judged"] == 0)
        check("耗时分位都是 None", d["steps"]["elapsed"]["p50"] is None,
              str(d["steps"]["elapsed"]))
        check("归因分布为空列表", d["attribution"] == [], str(d["attribution"]))
        check("notes 说明「库里还没有任何步骤」",
              any("还没有任何步骤" in n for n in d["notes"]), str(d["notes"]))
        check("span 全 None", d["span"]["last_step_at"] is None, str(d["span"]))
        check("traffic 各桶为空 dict", d["traffic"]["by_event_type"] == {},
              str(d["traffic"]))


# ============================================================ D 索引
def test_c2_stale(client):
    """库里有数据、但全在窗口之外 —— 这是最容易让人以为"看板坏了"的场景。

    真实情形：用户一个月前跑过任务，今天打开看板选"最近 7 天" ⇒ 一片空白。
    如果不解释，人只会去翻代码。所以要断言 notes 说清"窗口内没有步骤"并给出库内跨度。
    """
    print("\n[C2] 数据全在窗口之外：要解释原因，而不是给一片空白")
    with TempDB():
        with store._db() as c:
            add_step(c, status="done", elapsed=2.0, at=NOW - 86400 * 60)
        console_api.STATS_CACHE.clear()
        d = client.get("/api/console/stats?days=7&refresh=1").json()
        check("窗口内 0 条步骤", d["steps"]["total"] == 0, str(d["steps"]["total"]))
        check("notes 指出「窗口内没有步骤」并给出库内跨度",
              any("窗口内没有步骤" in n and "跨度" in n for n in d["notes"]),
              str(d["notes"]))
        check("  notes 还提示可以调大 days 或设为 0",
              any("days" in n for n in d["notes"]), str(d["notes"]))
        check("span 仍反映全部历史（不是 None）",
              d["span"]["last_step_at"] is not None, str(d["span"]))
        check("空窗口不给假成功率（None）", d["steps"]["success_rate"] is None,
              str(d["steps"]["success_rate"]))
        console_api.STATS_CACHE.clear()


def test_d_index():
    print("\n[D] 索引：存在且在大表上真被用上")
    # 索引的**存在与列**是确定性事实，先验这个
    with TempDB():
        with store._db() as c:
            names = {r["name"] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='steps'")}
            check("idx_steps_created 已建", "idx_steps_created" in names, str(sorted(names)))
            cols = [r["name"] for r in c.execute(
                "PRAGMA index_info(idx_steps_created)")] if "idx_steps_created" in names else []
            check("  索引列就是 created_at", cols == ["created_at"], str(cols))

    # ⚠️ 规划器是否选索引**取决于表大小**：小表上全扫更划算，SQLite 会合法地选 SCAN。
    # 所以这条必须用足够大的表来验，否则测试会在别的机器上随机红。
    with TempDB(n_steps=3000):
        with store._db() as c:
            plan = " | ".join(r["detail"] for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT status, COUNT(*) FROM steps WHERE created_at >= ?",
                (NOW - 86400,)))
        check("3000 行时时间窗聚合走索引（不是 SCAN steps）",
              "idx_steps_created" in plan and "SCAN steps" not in plan, plan)
        check("  且计划里是 SEARCH", "SEARCH" in plan, plan)


# ============================================================ E 前端与文案
def test_e_frontend():
    print("\n[E] 前端：占位页换成真看板")
    charts = (REPO / "console" / "views" / "charts.js").read_text(encoding="utf-8")
    check("charts.js 不再引用占位工厂", "_placeholder" not in charts)
    check("charts.js 请求 /api/console/stats", "/stats?" in charts)
    check("自绘 SVG（viewBox + <svg>）", "viewBox" in charts and "<svg" in charts)
    # ⚠️ 不要写成 `"cdn" not in charts` —— 那会命中文件说明里那句「不引 CDN」注释，
    # 属典型的**守卫自伤**（本项目已踩过多次）。判据要认**调用形态**：
    # 有没有真正去外联（http(s) 字面量 / src= / @import）。
    check("不外部加载资源（无 http(s) 字面量、无 src=、无 @import）",
          "http://" not in charts and "https://" not in charts
          and "src=" not in charts and "@import" not in charts)
    check("时间窗含「全部历史」（days=0）", "'0', '全部历史'" in charts)
    check("口径区写明成本侧在 /api/usage/*（不重复造）", "usage/summary" in charts)
    check("归因说明提到三道闸门（并行子任务 / 任务级约束 / 风险确认）",
          "并行子任务" in charts and "任务级约束" in charts and "风险确认" in charts)
    check("说明成功率分母不含闸门拒绝", "不含" in charts and "闸门拒绝" in charts)

    core = (REPO / "console" / "core.js").read_text(encoding="utf-8")
    check("core.js 的 charts 视图已抬版本（防旧缓存拿到占位页）",
          "charts.js?v=111" in core, core[core.find("charts:"):][:80])
    import re as _re
    idx = (REPO / "console" / "index.html").read_text(encoding="utf-8")
    v_idx = set(_re.findall(r"core\.js\?v=(\d+)", idx))
    bad = []
    for f in sorted((REPO / "console" / "views").glob("*.js")):
        got = set(_re.findall(r"core\.js\?v=(\d+)", f.read_text(encoding="utf-8")))
        if not (got <= v_idx):
            bad.append(f"{f.name}:{sorted(got)}")
    check("所有视图与 index.html 的 core.js 版本一致（避免双实例）", not bad, str(bad))


def main():
    print("=" * 68)
    print("v111 回归：控制台统计看板 /api/console/stats")
    print("=" * 68)
    saved_pw = config.CONSOLE_PASSWORD
    config.CONSOLE_PASSWORD = PW
    try:
        with TempDB():
            seed()
            client = TestClient(app, base_url=LOOPBACK)
            test_a_basic(client)
            test_b_semantics(client)
            test_c_empty(client)
            test_c2_stale(client)
        test_d_index()
        test_e_frontend()
    finally:
        config.CONSOLE_PASSWORD = saved_pw
    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
