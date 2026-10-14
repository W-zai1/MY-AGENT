# -*- coding: utf-8 -*-
"""v112 回归：控制台「实时监控」的 `GET /api/console/runs`。

## 这一版解决了什么

`console/views/monitor.js` 是控制台**最后一个占位页**。它列的 6 个接口里 5 个「已有」，
只有 `GET /api/console/runs` 标着「待建」—— 而它恰恰是这一页的**入口**。

此前**没有任何"列会话"的口子**：`/api/projects` 只给项目；`/api/projects/{pid}` 带 sessions
但要走遍每个项目（N+1）；`store.list_sessions(None)` 存在却没被暴露。
于是监控页"必须事先知道 sid 才能看"，没法当监控用。

## 本套件锁住的不变量

1. **必须合并内存与库**：`POST /api/sessions` 只做 `sessions.create`（**不落库**），
   所以"刚建还没派任务"的会话**只存在于内存**；只查库会漏掉它。
2. **运行状态以内存为准**：库里的 `state` 只是落库时的快照。
3. **`cancelling` 读的是取消事件，不是 state**：`/cancel` 只 `set()` 事件，
   `state` 要跑到下一个步骤边界才变。只看 state 会把"取消中"显示成正常的"执行中"。
4. **响应里不得出现 `second`**：它在 SSE 事件里是"第几轮"，在 `/api/sessions/{sid}` 里
   是"是否需要双轮确认"——**同名不同义**，本项目的看板脚本曾因此把 L3 印成 L2。
   本接口一律用 `requires_double_confirm`。
5. **不新造确认/取消通道**：确认的双闸门（token + step_id + ack）是安全核心，
   本接口只列清单，前端仍调既有 `/api/sessions/{sid}/confirm` 与 `/cancel`。
6. 只读；`limit` 夹取；`active` / `project_id` / `mode` 过滤；`urgent` 排在最前。

## ⚠️ 本套件不碰真实数据库

落库侧跑在临时库上（`store.DB_PATH` 重定向），内存会话造完即从单例里移除。

    python test_console_runs.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient                    # noqa: E402

from app import config, console_api, store                   # noqa: E402
from app.agent import Step, sessions as live_mgr             # noqa: E402
from app.main import app                                     # noqa: E402

LOOPBACK = "http://127.0.0.1:8770"
PW = "test-console-pw-112"
NOW = time.time()

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f" → {detail}" if detail and not cond else ""))


class TempDB:
    def __enter__(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="runs-test-"))
        self.saved = store.DB_PATH
        store.DB_PATH = self.tmp / "projects.db"
        store.init_db()
        self._made: list[str] = []
        return self

    def __exit__(self, *a):
        for sid in self._made:
            live_mgr.remove(sid)
        store.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mk_live(self, **kw):
        s = live_mgr.create(**kw)
        self._made.append(s.id)
        return s


def add_db_session(c, sid, *, project_id="p1", title="", target="a.test",
                   state="done", mode="blackbox", created_at=None):
    cols = "id,project_id,task,target,state,title,status,context,summary,mode"
    c.execute(f"INSERT OR REPLACE INTO sessions ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (sid, project_id, "", target, state, title, "active", "[]", "", mode))
    if created_at is not None:
        c.execute("UPDATE sessions SET created_at=? WHERE id=?", (created_at, sid))
    else:
        c.execute("UPDATE sessions SET created_at=? WHERE id=?", (NOW, sid))


def add_step(c, sid, status="done", at=None):
    import uuid
    c.execute("INSERT INTO steps (id,session_id,tool_alias,tool_name,status,elapsed,"
              "created_at) VALUES (?,?,?,?,?,?,?)",
              (uuid.uuid4().hex[:12], sid, "httpreplay", "HTTP重放器", status, 1.0,
               at if at is not None else NOW))


def seed_db():
    with store._db() as c:
        c.execute("INSERT OR REPLACE INTO projects (id,name,target,note,created_at,mode) "
                  "VALUES (?,?,?,?,?,?)",
                  ("p1", "黑盒项目", "a.test", "", NOW - 9000, "blackbox"))
        c.execute("INSERT OR REPLACE INTO projects (id,name,target,note,created_at,mode) "
                  "VALUES (?,?,?,?,?,?)",
                  ("p2", "白盒项目", "b.test", "", NOW - 9000, "whitebox"))
        add_db_session(c, "db_done", title="已完成的库会话", state="done", created_at=NOW - 900)
        add_db_session(c, "db_intr", title="被中断的库会话", state="interrupted",
                       created_at=NOW - 800)
        add_db_session(c, "db_wb", title="白盒库会话", state="done", mode="whitebox",
                       project_id="p2", created_at=NOW - 700)
        add_db_session(c, "db_old", title="很旧的库会话", state="done", created_at=NOW - 500)
        add_step(c, "db_done")
        add_step(c, "db_done")
        add_step(c, "db_done", status="error")


def login(c):
    c.post("/api/console/login", json={"password": PW})


# ============================================================ A 鉴权与只读
def test_a_basic(client):
    print("\n[A] 鉴权 / 只读 / 参数夹取")
    saved = config.CONSOLE_PASSWORD
    empty_yml = pathlib.Path(tempfile.mkdtemp(prefix="runs-cfg-")) / "config.yaml"
    empty_yml.write_text("", encoding="utf-8")
    saved_yml = console_api._config_yaml_path
    try:
        console_api._config_yaml_path = lambda: empty_yml
        config.CONSOLE_PASSWORD = ""
        r = client.get("/api/console/runs")
        check("未设口令 → 403（fail-closed）", r.status_code == 403, str(r.status_code))
        console_api._config_yaml_path = saved_yml
        config.CONSOLE_PASSWORD = PW
        r = client.get("/api/console/runs")
        check("未登录 → 401", r.status_code == 401, str(r.status_code))

        login(client)
        r = client.get("/api/console/runs")
        check("登录后 200", r.status_code == 200, r.text[:150])
        d = r.json()
        for k in ("items", "counts", "window", "notes", "run_state_label", "live_total"):
            check(f"返回含 {k}", k in d)

        r = client.get("/api/console/runs?limit=9999")
        check("limit 超上限被夹到 200",
              r.json()["window"]["limit"] == 200 and r.json()["window"]["clamped"] is True,
              str(r.json()["window"]))
        r = client.get("/api/console/runs?limit=abc")
        check("limit 非数字 → 422", r.status_code == 422, str(r.status_code))

        with store._db() as c:
            before = tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                           for t in ("sessions", "steps"))
        client.get("/api/console/runs")
        with store._db() as c:
            after = tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                          for t in ("sessions", "steps"))
        check("端点只读（调用前后行数一致）", before == after, f"{before} → {after}")
    finally:
        config.CONSOLE_PASSWORD = saved
        console_api._config_yaml_path = saved_yml


# ============================================================ B 合并内存与库
def test_b_merge(td, client):
    print("\n[B] 合并内存与库（live / 内存独有 / urgent）")
    # 内存独有：模拟"刚建、还没派任务"（POST /api/sessions 不落库）
    mem_only = td.mk_live(project="p1", title="只在内存·空闲", mode="blackbox")
    # 内存 + 库里都有
    mem_db = td.mk_live(project="p1", title="内存与库都有", mode="blackbox")
    with store._db() as c:
        add_db_session(c, mem_db.id, title="内存与库都有", state="running")
        add_step(c, mem_db.id)
    # 等确认（内存态）
    awaiting = td.mk_live(project="p1", title="等确认", mode="blackbox")
    awaiting.target = "a.test"
    awaiting.steps.append(Step(id="st1", tool_alias="py_exec", tool_name="Python代码执行",
                               target="a.test", args="-c 1", risk={"level": "L3"},
                               status="running"))
    awaiting.state = "awaiting_confirm"
    awaiting.pending_confirm = {"step_id": "st1", "token": "tok-1", "double_confirm": True}
    # 正在取消：state 仍是 running，只有 cancel_event 被置位
    cancelling = td.mk_live(project="p1", title="取消中", mode="blackbox")
    cancelling.state = "running"
    cancelling.cancel_event.set()
    # 内存独有**且带步骤**（库里没有任何 step 行）→ 计数只能来自内存
    mem_steps = td.mk_live(project="p1", title="内存带步骤", mode="blackbox")
    for i, stt in enumerate(("done", "error")):
        mem_steps.steps.append(Step(id=f"x{i + 1}", tool_alias="httpreplay",
                                    tool_name="HTTP重放器", target="a.test", args="",
                                    risk={"level": "L2"}, status=stt))

    d = client.get("/api/console/runs?limit=200").json()
    items = {x["session_id"]: x for x in d["items"]}

    check("内存独有会话出现在列表里（只查库会漏）", mem_only.id in items,
          f"items={len(items)}")
    if mem_only.id in items:
        m = items[mem_only.id]
        check("  且 live=True / state=idle", m["live"] is True and m["state"] == "idle",
              str(m["state"]))
        check("  且项目名按内存里的 project 解析出来（不是空）",
              m["project_name"] == "黑盒项目", repr(m["project_name"]))
    check("库里独有的会话也在列表里且 live=False",
          items.get("db_done", {}).get("live") is False, str(items.get("db_done", {}))[:80])

    a = items.get(awaiting.id, {})
    check("等确认 → awaiting_confirmation=True", a.get("awaiting_confirmation") is True)
    check("  → urgent=True（需要人管）", a.get("urgent") is True)
    check("  → awaiting_summary 说清是谁在等哪一步",
          "py_exec" in (a.get("awaiting_summary") or "")
          and "L3" in (a.get("awaiting_summary") or ""), repr(a.get("awaiting_summary")))
    check("  → 待确认里带 token 与 step_id（前端要拿它提交）",
          (a.get("pending") or {}).get("token") == "tok-1"
          and (a.get("pending") or {}).get("step_id") == "st1", str(a.get("pending"))[:120])
    check("  → requires_double_confirm=True（L3）",
          (a.get("pending") or {}).get("requires_double_confirm") is True)

    check("库里 interrupted 的会话 → urgent=True（是个行动项）",
          items.get("db_intr", {}).get("urgent") is True,
          str(items.get("db_intr", {}))[:80])
    check("已完成的会话 → urgent=False", items.get("db_done", {}).get("urgent") is False)

    c2 = items.get(cancelling.id, {})
    check("取消中：state 仍是 running（证明不能只看 state）",
          c2.get("state") == "running", str(c2.get("state")))
    check("  cancelling=True（读的是取消事件）", c2.get("cancelling") is True,
          str(c2.get("cancelling")))

    urgent_first = [x["session_id"] for x in d["items"][:3]]
    check("urgent 的排在列表最前", awaiting.id in urgent_first and "db_intr" in urgent_first,
          str([(x["session_id"], x["urgent"]) for x in d["items"][:4]]))
    check("counts 分类正确",
          d["counts"]["awaiting"] >= 1 and d["counts"]["interrupted"] >= 1
          and d["counts"]["cancelling"] >= 1, str(d["counts"]))
    check("记忆：内存里的会话总数列出 live_total", d["live_total"] >= 4, str(d["live_total"]))

    # 步骤计数：live 走内存、库里的走批量查询
    check("库会话的步骤计数来自库（2 done + 1 error）",
          items.get("db_done", {}).get("steps", {}).get("total") == 3
          and items["db_done"]["steps"]["error"] == 1,
          str(items.get("db_done", {}).get("steps")))
    # 计数口径：内存与库**逐状态取较大值**（任一侧有都算发生过 —— 步骤是每步即时落库的）。
    # 这条用例里 DB 有 1 步、内存对象没装步骤 ⇒ 取 max 后应为 1（只信内存会报 0）。
    check("内存+库都有：计数取两侧较大值（DB 的 1 步不能被报成 0）",
          items.get(mem_db.id, {}).get("steps", {}).get("total") == 1,
          str(items.get(mem_db.id, {}).get("steps")))
    check("内存独有且带步骤：计数来自内存对象（库里没有 step 行）",
          items.get(mem_steps.id, {}).get("steps", {}).get("total") == 2
          and items[mem_steps.id]["steps"]["error"] == 1,
          str(items.get(mem_steps.id, {}).get("steps")))

    notes = " ".join(d["notes"])
    check("notes 提示「有运行正等着你确认」", "等着你确认" in notes, notes[:160])
    check("notes 解释 interrupted 是被中断、可续聊",
          "被中断" in notes and "续聊" in notes, notes[:200])
    check("notes 解释「正在取消」读的是取消事件而非状态",
          "取消事件" in notes, notes[:200])
    check("notes 说明内存独有的会话重启后会消失",
          "只存在于内存" in notes, notes[:240])
    check("notes 声明只读、确认取消透传既有接口",
          "透传" in notes and "不另造通道" in notes, notes[:400])


# ============================================================ C 不过滤 / 过滤
def test_c_filters(client):
    print("\n[C] 过滤与「second」守卫")
    all_d = client.get("/api/console/runs?limit=200").json()
    act_d = client.get("/api/console/runs?limit=200&active=1").json()
    check("active=1 只保留活跃状态",
          all(x["state"] in ("idle", "running", "awaiting_confirm") for x in act_d["items"]),
          str(sorted({x["state"] for x in act_d["items"]})))
    check("active=1 的条数不多于全部", act_d["counts"]["total"] <= all_d["counts"]["total"])

    wb = client.get("/api/console/runs?limit=200&mode=whitebox").json()
    check("mode=whitebox 只留白盒会话",
          all(x["mode"] == "whitebox" for x in wb["items"]) and wb["counts"]["total"] >= 1,
          str([x["mode"] for x in wb["items"]])[:80])
    pid = client.get("/api/console/runs?limit=200&project_id=p2").json()
    check("project_id 过滤生效",
          all(x["project_id"] == "p2" for x in pid["items"]) and pid["counts"]["total"] >= 1,
          str([x["project_id"] for x in pid["items"]])[:80])

    # ⚠️ `second` 是同名不同义的雷（SSE=第几轮 / session 详情=是否需双轮确认）。
    # 本项目曾有看板脚本拿它当风险等级用，把 L3 印成 L2 —— 本接口一律不出现它。
    bad = []
    for x in all_d["items"]:
        if "second" in x:
            bad.append(x["session_id"])
        if x.get("pending") and "second" in x["pending"]:
            bad.append(f"{x['session_id']}.pending")
    check("响应里**不出现** second（改用 requires_double_confirm）", not bad, str(bad))
    check("风险等级字段名是明确的 risk_level",
          all(("risk_level" in (x.get("pending") or {})) for x in all_d["items"]
              if x.get("pending")), str([x.get("pending") for x in all_d["items"]
                                         if x.get("pending")][:1]))

    check("run_state_label 给出人话说明",
          all_d.get("run_state_label", {}).get("awaiting_confirm") == "等待人工确认",
          str(all_d.get("run_state_label")))
    check("待确认的 risk_level 不是布尔/轮次（防 second 混淆回归）",
          all(isinstance((x.get("pending") or {}).get("risk_level"), str)
              for x in all_d["items"] if x.get("pending")))


# ============================================================ D 前端与"不新造通道"
def test_d_frontend_and_routes():
    print("\n[D] 前端守卫 + 不新造确认通道")
    mon = (REPO / "console" / "views" / "monitor.js").read_text(encoding="utf-8")
    check("monitor.js 不再引用占位工厂", "_placeholder" not in mon)
    check("monitor.js 请求 /runs", "/runs?" in mon)
    check("确认**透传**既有端点（不自己造）",
          "/api/sessions/${encodeURIComponent(x.session_id)}/confirm" in mon
          or "/confirm`" in mon)
    check("取消**透传**既有端点", "/cancel`" in mon or "/cancel'," in mon)
    check("提交确认时带 step_id 与一次性 token（双闸门的两项）",
          "step_id: x.pending.step_id" in mon and "token: x.pending.token" in mon)
    check("L3 走 auth_ack 且前端先拦一道（后端仍强制）",
          "auth_ack" in mon and "requires_double_confirm" in mon)
    check("cancelling 取自后端字段而不是自己猜",
          "x.cancelling" in mon or "cancelling" in mon)
    check("不引 CDN / 第三方库（认加载形态，不看裸词）",
          "http://" not in mon and "https://" not in mon
          and "src=" not in mon and "@import" not in mon)
    check("自动刷新会检查视图是否还在页面上（防切页后定时器空转）",
          "document.body.contains(host)" in mon)

    core = (REPO / "console" / "core.js").read_text(encoding="utf-8")
    check("core.js 的 monitor 视图已抬版本", "monitor.js?v=112" in core,
          core[core.find("monitor:"):][:80])

    idx = (REPO / "console" / "index.html").read_text(encoding="utf-8")
    import re as _re
    v_idx = set(_re.findall(r"core\.js\?v=(\d+)", idx))
    bad = []
    for f in sorted((REPO / "console" / "views").glob("*.js")):
        got = set(_re.findall(r"core\.js\?v=(\d+)", f.read_text(encoding="utf-8")))
        if not (got <= v_idx):
            bad.append(f"{f.name}:{sorted(got)}")
    check("所有视图与 index.html 的 core.js 版本一致（避免双实例）", not bad, str(bad))

    # 后端不新造通道：确认/取消仍只有既有的那一处定义。
    # ⚠️ 判据要认**路由形态**（`@router.xxx("…")`），不能查裸文本 ——
    # 本文件的说明性注释里就写了「透传既有接口（/api/sessions/{sid}/confirm 与 /cancel）」，
    # 查裸文本会把注释判红。这类"守卫自伤"本项目已经踩过三次了。
    ca = (REPO / "app" / "console_api.py").read_text(encoding="utf-8")
    routes = _re.findall(r'@router\.(get|post|put|delete)\("([^"]+)"', ca)
    check("console_api 不新造确认端点（按路由定义判，不看注释）",
          not any("confirm" in p for _, p in routes),
          str([p for _, p in routes if "confirm" in p]))
    check("console_api 不新造取消端点",
          not any("cancel" in p for _, p in routes),
          str([p for _, p in routes if "cancel" in p]))
    main_py = (REPO / "app" / "main.py").read_text(encoding="utf-8")
    check("既有 /confirm 端点仍然只有一处定义",
          main_py.count('@app.post("/api/sessions/{sid}/confirm")') == 1)
    check("既有 /cancel 端点仍然只有一处定义",
          main_py.count('@app.post("/api/sessions/{sid}/cancel")') == 1)
    check("runs 端点在 console_api 且是 GET（只读）",
          '@router.get("/runs")' in ca and '@router.post("/runs")' not in ca)


def main():
    print("=" * 68)
    print("v112 回归：控制台实时监控 /api/console/runs")
    print("=" * 68)
    saved_pw = config.CONSOLE_PASSWORD
    config.CONSOLE_PASSWORD = PW
    try:
        with TempDB() as td:
            seed_db()
            client = TestClient(app, base_url=LOOPBACK)
            test_a_basic(client)
            test_b_merge(td, client)
            test_c_filters(client)
        test_d_frontend_and_routes()
    finally:
        config.CONSOLE_PASSWORD = saved_pw
    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
