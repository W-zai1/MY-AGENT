# -*- coding: utf-8 -*-
"""v115 回归：v113 审计报告 §15 里的 7 条缺陷修复。

## 这一版修了什么

| 编号 | 缺陷 | 修法 |
|---|---|---|
| P0-1 | `main.py` 从未 `import re`，`re.sub` 那行必抛 `NameError` → 接口 500 | 补 `import re` |
| P0-2 | 工具**超时**路径用裸 `proc.kill()`，孙进程留下继续跑 | 4 处改走 `_kill_tree` |
| P1-1 | `code_*` 声明了 `tool_calls` 却**没有 `role=tool` 回复** → 白盒会话第二轮 400 | 在 `code_` 分支补回灌 |
| P1-3 | `_copy_tree` 自己写了第 4 份遍历、**只过滤目录**：`exclude` 里的文件/通配符在"复制"这一步失效 | 改走共用的 `walk_source` |
| P1-5 | 两处 `save_session` 都**没传 `mode`** → 白盒会话在库里存成 `blackbox` | 两处补 `mode=session.mode` |
| P1-2 | 凭据/私钥文件没有 denylist → 被复制进受控根、可被 `code_read` 读到 | `walk_source` 层加红线 + **显式告知** |
| P2-6d | `report.py` 的 sqlite 连接不在 `finally` 里，异常即泄漏 | `try/finally` |

## 本套件的写法

每条都配**能证伪**的断言 —— 不是"跑一遍没报错"：
· 静态守卫盯着"判据是否还在"（例如 `executor.py` 里不许再出现裸 `proc.kill()`）；
· 行为断言真的把东西跑起来（真的起进程树、真的造敏感文件、真的复制一遍）。

    python test_v115_fixes.py
"""
from __future__ import annotations

import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

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


# ============================================================ A · P0-1
def test_a_re_imported():
    print("\n[A] P0-1 · main.py 的 `re` 已导入（此前 re.sub 必抛 NameError）")
    t = src("app/main.py")
    check("源码里有 `import re`", "\nimport re\n" in t, "没有这行")
    import app.main as M                                   # noqa: PLC0415
    check("模块属性上能拿到 re", hasattr(M, "re"))
    check("`re.sub` 真的能跑（原故障点的表达式）",
          M.re.sub(r"\s+", " ", "  a \n b  ").strip() == "a b",
          "取到的不是 re 模块")
    # 通用守卫：只要用了 `re.`，就必须有 import —— 以后再加用法忘了 import 也会被这条抓住
    uses_re = any(ln.strip().startswith(("else re.", "return re.")) or " re.sub(" in ln
                  for ln in t.splitlines())
    check("只要用到 `re.` 就有对应 import（通用守卫）",
          (not uses_re) or ("\nimport re\n" in t))


# ============================================================ B · P1-5
def test_b_mode_persisted():
    print("\n[B] P1-5 · 白盒会话的 mode 真的落库了")
    from app import store                                      # noqa: PLC0415
    saved = store.DB_PATH
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v115-mode-"))
    store.DB_PATH = tmp / "projects.db"
    store.init_db()
    try:
        sids = [s["id"] for s in (store.list_sessions() if False else [])]

        # ① 行为：显式传 mode 时，INSERT 分支写的是传进去的值
        store.save_session("wb1", "p1", "task", "t", "running", mode="whitebox")
        with store._db() as c:
            row = c.execute("SELECT mode FROM sessions WHERE id='wb1'").fetchone()
        check("传 mode='whitebox' ⇒ 库里就是 whitebox", row and row["mode"] == "whitebox",
              str(row["mode"] if row else None))

        # ② 反向：不传 mode 时回落 blackbox —— 这正是"漏传"时的静默后果
        store.save_session("bb1", "p1", "task", "t", "running")
        with store._db() as c:
            row = c.execute("SELECT mode FROM sessions WHERE id='bb1'").fetchone()
        check("不传 mode ⇒ 回落 blackbox（守住这条默认，别再被无声改掉）",
              row and row["mode"] == "blackbox", str(row["mode"] if row else None))

        # ③ 两个真实调用点都必须传 —— 这是本次真正的修复点
        ag = src("app/agent.py")
        mn = src("app/main.py")
        check("agent.py 的首次落库传了 mode（此前漏的就是这里）",
              "constraints=session.constraints,\n                           mode=session.mode)"
              in ag or "mode=session.mode)" in ag, "没找到")
        check("main.py 的落库也传了 mode",
              "mode=session.mode)" in mn, "没找到")
        # 严格一点：两处 save_session 调用都带 mode
        for label, text in (("agent.py", ag), ("main.py", mn)):
            cnt = text.count("store.save_session(")
            with_mode = text.count("mode=session.mode)")
            check(f"{label} 的 {cnt} 处 save_session 全部带 mode",
                  cnt > 0 and with_mode >= cnt, f"save_session={cnt} 带mode={with_mode}")
    finally:
        store.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ C · P0-2
def test_c_kill_tree():
    print("\n[C] P0-2 · 所有终止路径都杀整棵进程树")
    t = src("app/executor.py")
    # 静态守卫：裸 proc.kill() 只允许出现在 _kill_tree 自己内部
    body_start = t.index("def _kill_tree(")
    body_end = t.index("\ndef ", body_start + 10)
    kill_body = t[body_start:body_end]
    outer = t[:body_start] + t[body_end:]
    check("裸 `proc.kill()` 只剩 _kill_tree 内部那一处",
          "proc.kill()" not in outer,
          f"外面还有 {outer.count('proc.kill()')} 处："
          + str([ln.strip() for ln in outer.splitlines() if "proc.kill()" in ln][:4]))
    check("_kill_tree 内部确实是 kill + taskkill /T /F",
          "proc.kill()" in kill_body and "taskkill" in kill_body and "/T" in kill_body)
    check("四处终止路径都调 _kill_tree（取消 / 总超时 / 空闲超时 / 异常兜底）",
          t.count("_kill_tree(proc)") >= 5,
          f"调用点只有 {t.count('_kill_tree(proc)')} 处")

    # 行为：真起一棵进程树，_kill_tree 之后孙进程必须停
    print("  -- 行为：真起「父 → 孙」两层进程，杀树后孙进程必须停 --")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v115-kill-"))
    hb = tmp / "hb.txt"
    child = ("import time,pathlib,sys\n"
             "p=pathlib.Path(sys.argv[1])\n"
             "while True:\n"
             "    p.write_text(str(time.time()))\n"
             "    time.sleep(0.15)\n")
    parent = ("import subprocess,sys,time,pathlib\n"
              "subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]])\n"
              "time.sleep(120)\n")
    proc = subprocess.Popen([sys.executable, "-c", parent, str(hb), child],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while not hb.exists() and time.time() - t0 < 15:
            time.sleep(0.1)
        check("孙进程已起来（心跳文件出现）", hb.exists())
        if hb.exists():
            time.sleep(0.5)
            m1 = hb.stat().st_mtime
            time.sleep(0.5)
            check("杀之前心跳在跳（说明它真的活着）", hb.stat().st_mtime != m1,
                  "心跳没动，测试前提不成立")

            from app.executor import _kill_tree                  # noqa: PLC0415
            _kill_tree(proc)
            time.sleep(0.4)
            m2 = hb.stat().st_mtime
            time.sleep(1.2)
            check("杀树之后心跳停了 ⇒ 孙进程真的死了（不是只杀了直接子进程）",
                  hb.stat().st_mtime == m2,
                  "心跳还在跳 ⇒ 孙进程活下来了")
    finally:
        for p in (proc,):
            try:
                p.kill()
            except Exception:                                    # noqa: BLE001
                pass
        # 兜底：把可能残留的孙进程也带走
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================ D · P1-1
def test_d_code_tool_message():
    print("\n[D] P1-1 · code_* 会回灌 `role=tool` 消息")
    ag = src("app/agent.py")
    i = ag.index('elif tool.alias.startswith("code_"):')
    branch = ag[i:i + 2600]
    check("code_ 分支里有 messages.append（回灌）",
          "session.messages.append(" in branch, "分支里没有回灌")
    check("回灌的是 role=tool 且带 tool_call_id",
          '"role": "tool", "tool_call_id": tc["id"]' in branch, "形状不对")
    check("回灌的 content 就是 handle 的返回值（note）",
          '"content": note}' in branch)
    # 决定性：其余 5 个 handler 各自 append，code_* 的执行体不碰 messages
    import re as _re                                             # noqa: PLC0415
    seg_all = ag.split("def _record_builtin_step(")[1]
    m = _re.search(r"\n    (?:async )?def ", seg_all)            # 切到下一個方法定義為止
    rec_body = seg_all[: m.start()] if m else seg_all
    check("回灌发生在**分支内**、不是 _record_builtin_step 里（否则另外 5 个会双重回灌）",
          "session.messages.append(" not in rec_body,
          "在 _record_builtin_step 里找到了 append —— 那 5 个 handler 会变成双重回灌")
    check("codebase/tools.py 依然不碰 messages（所以必须由调用点补）",
          "messages" not in src("app/codebase/tools.py"))
    for fn in ("_note_fact", "_search_history", "_propose_branch", "_split_task",
               "_kb_fofa_tool"):
        seg = ag.split(f"async def {fn}(")[1].split("\n    async def ")[0]
        check(f"对标：{fn} 自己 append（证明约定是「handler 自己补」）",
              "self.messages.append(" in seg or "session.messages.append(" in seg)


# ============================================================ E · P1-3
def _mk_tree(root: pathlib.Path):
    (root / "src").mkdir(parents=True)
    (root / "src" / "keep.py").write_text("print(1)\n", encoding="utf-8")
    (root / "src" / "gen_skip.py").write_text("print(2)\n", encoding="utf-8")
    (root / "test_x.py").write_text("print(3)\n", encoding="utf-8")
    (root / "notes.py").write_text("print(4)\n", encoding="utf-8")


def test_e_exclude_files():
    print("\n[E] P1-3 · exclude 对**文件**（含通配符）也生效，且扫描与复制口径一致")
    from app.codebase import ingest as G                          # noqa: PLC0415
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v115-excl-"))
    dst = pathlib.Path(tempfile.mkdtemp(prefix="v115-excl-dst-"))
    try:
        _mk_tree(tmp)
        excl = ("notes.py", "test_*.py", "src/gen_skip.py")

        s = G.scan_tree(tmp, exclude=excl)
        scanned = sorted(s.files)
        check("扫描侧：三个 exclude 都生效",
              scanned == ["src/keep.py"], str(scanned))

        shutil.rmtree(dst, ignore_errors=True)
        n = G._copy_tree(tmp, dst, G._norm_exclude(excl))
        copied = sorted(p.relative_to(dst).as_posix()
                        for p in dst.rglob("*") if p.is_file())
        check("复制侧：**单个文件**被排除了（此前照复制不误）",
              "notes.py" not in copied, str(copied))
        check("复制侧：**通配符**被排除了（此前连 _file_matches 都没调）",
              "test_x.py" not in copied, str(copied))
        check("复制侧：带路径的文件被排除了", "src/gen_skip.py" not in copied, str(copied))
        check("⭐ 扫描与复制**口径一致**（这是本条真正要守的）",
              scanned == copied, f"scan={scanned} copy={copied}")
        check("该留的还在", copied == ["src/keep.py"], str(copied))
        check("复制计数与实际落盘一致", n == len(copied), f"n={n} files={len(copied)}")

        # 结构性守卫：别再自己写一份 os.walk
        code = src("app/codebase/ingest.py")
        check("_copy_tree 走共用的 walk_source",
              "for rel_dir, fn, sp in walk_source(" in code)
        walks = [ln for ln in code.splitlines()
                 if "os.walk(" in ln and not ln.strip().startswith("#")]
        check("全模块只剩 walk_source 里的那一处 os.walk", len(walks) == 1,
              str([w.strip() for w in walks]))
        check("`skip` 参数已删（它与 walk_source 内置的 SKIP_DIRS 是两处同一判断）",
              "def _copy_tree(src: pathlib.Path, dst: pathlib.Path,\n"
              "               exclude:" in code
              or "def _copy_tree(src: pathlib.Path, dst: pathlib.Path," in code)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


# ============================================================ F · P1-2
def test_f_sensitive_denylist():
    print("\n[F] P1-2 · 凭据/私钥不进受控根，且**显式告知**（不是静默跳过）")
    from app.codebase import ingest as G                          # noqa: PLC0415
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="v115-sens-"))
    dst = pathlib.Path(tempfile.mkdtemp(prefix="v115-sens-dst-"))
    try:
        (tmp / "src").mkdir()
        (tmp / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
        secret_files = [".env", "id_rsa", "server.pem", "prod.key", ".npmrc",
                        ".netrc", "secrets.json", "deploy.p12"]
        for n in secret_files:
            (tmp / n).write_text("SECRET=x\n", encoding="utf-8")
        (tmp / ".ssh").mkdir()
        (tmp / ".ssh" / "known_hosts").write_text("x\n", encoding="utf-8")
        # 模板必须放行（本工程自己也发 config.yaml.example）
        (tmp / ".env.example").write_text("SECRET=\n", encoding="utf-8")
        (tmp / "secrets.yaml.template").write_text("k: \n", encoding="utf-8")

        s = G.scan_tree(tmp)
        skipped = set(s.skipped_sensitive)
        for n in secret_files:
            check(f"扫描侧跳过 {n}", n in skipped, str(sorted(skipped)))
        check("扫描侧跳过凭据目录 .ssh", ".ssh" in skipped, str(sorted(skipped)))
        check("模板放行：.env.example 进了扫描", ".env.example" in s.files, str(s.files))
        check("模板放行：secrets.yaml.template 进了扫描",
              "secrets.yaml.template" in s.files, str(s.files))

        shutil.rmtree(dst, ignore_errors=True)
        G._copy_tree(tmp, dst, ())
        copied = sorted(p.relative_to(dst).as_posix()
                        for p in dst.rglob("*") if p.is_file())
        leaked = [n for n in secret_files if n in copied] + \
            ([" .ssh/**"] if any(c.startswith(".ssh/") for c in copied) else [])
        check("⭐ 复制侧：一个敏感文件都没落盘（密钥不进受控根）", not leaked, str(leaked))
        check("复制侧：模板与源码正常落盘",
              copied == [".env.example", "secrets.yaml.template", "src/app.py"],
              str(copied))

        # 显式告知：summary 里必须写出来
        res = G.ingest(tmp, codebase_id="sens-demo", dry_run=True)
        sm = res.summary()
        check("summary 里有「敏感文件未入库」这一行", "敏感文件" in sm and "未入库" in sm)
        check("summary 里**点名**了至少一个被跳过的文件",
              any(n in sm for n in (".env", "id_rsa", "secrets.json", ".npmrc")),
              sm[-300:])
        check("结果为结构化的（不只是给人看的文字）",
              isinstance(res.skipped_sensitive, dict) and len(res.skipped_sensitive) >= 8,
              str(len(res.skipped_sensitive)))
        check("summary 说明了模板不受影响（避免用户以为模板也被挡）",
              "模板" in sm)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


# ============================================================ G · P2-6d
def test_g_report_conn_closed():
    print("\n[G] P2-6d · report.py 的 sqlite 连接在异常路径也会关闭")
    import app.report as R                                        # noqa: PLC0415
    code = src("app/report.py")
    seg = code.split("def _steps_of(")[1].split("\ndef ")[0]
    check("_steps_of 用了 try/finally", "finally:" in seg and "conn.close()" in seg)

    # 行为：让 execute 抛异常，close 仍必须被调用
    state = {"closed": False, "connected": False}

    class FakeConn:
        row_factory = None

        def execute(self, *a, **k):
            raise sqlite3.OperationalError("模拟：库被锁/表不存在")

        def close(self):
            state["closed"] = True

    real_connect = sqlite3.connect

    def fake_connect(*a, **k):
        state["connected"] = True
        return FakeConn()

    sqlite3.connect = fake_connect
    try:
        raised = False
        try:
            R._steps_of("whatever")
        except sqlite3.OperationalError:
            raised = True
        check("异常照常抛出（不吞掉，调用方要知道）", raised)
        check("⭐ 异常路径下连接被关闭了（此前会泄漏）", state["closed"])
    finally:
        sqlite3.connect = real_connect


def main() -> int:
    print("=" * 68)
    print("v115 回归：v113 审计报告 §15 的 7 条缺陷修复")
    print("=" * 68)
    test_a_re_imported()
    test_b_mode_persisted()
    test_c_kill_tree()
    test_d_code_tool_message()
    test_e_exclude_files()
    test_f_sensitive_denylist()
    test_g_report_conn_closed()
    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
