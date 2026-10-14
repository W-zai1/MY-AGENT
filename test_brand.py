# -*- coding: utf-8 -*-
"""LuminaSec 品牌横幅：bat 与 brand.py 不许漂移（v114）。

背景：`启动控制台.bat` 在探测 Python **之前**就要打印横幅，那时还没有可用
解释器，所以不能 import `app/brand.py` —— 艺术字只能在 bat 里固化成 echo。
两份一旦漂移，现象是「run.py 和 bat 显示的标题不一样」，而这种不一致没有
任何运行时会报错，只能靠测试兜住。

本测试直接 `python test_brand.py` 运行，退出码 0 = 全过。不联网、不起服务。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import brand  # noqa: E402

BAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "启动控制台.bat")

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [!!] {name}" + (f" —— {detail}" if detail else ""))


def main() -> int:
    print("=" * 62)
    print("  LuminaSec 品牌横幅一致性")
    print("=" * 62)

    # ---- 1. 艺术字本身的自洽 ----
    print("\n[1] 艺术字")
    art = brand.art_lines()
    check("ART 非空", len(art) > 0)
    # FIGlet 字体右边缘天然不齐（L 比 m 窄），不能断言等宽；
    # 该断言的是「有存在感但不刷屏」与「不折行」。
    check("行数 3~8（大标题要有存在感，但不能刷屏）", 3 <= len(art) <= 8,
          f"实际 {len(art)} 行")
    check("纯 ASCII（GBK 安全）",
          all(ord(c) < 128 for l in art for c in l),
          "含非 ASCII 字符，cmd 936 代码页下会乱码")
    check("宽度 ≤ 78（80 列终端不折行）", max(len(l) for l in art) <= 78,
          f"最宽 {max(len(l) for l in art)}")
    check("art_lines() 返回副本（改返回值不污染 ART）",
          (lambda c: (c.append("x"), brand.ART[-1] != "x")[1])(brand.art_lines()))

    # ---- 2. banner() 渲染 ----
    print("\n[2] banner()")
    b = brand.banner()
    bl = b.split("\n")
    art = brand.art_lines()          # 重新取一份干净的（上面的探针动过副本）
    check("上下边框等宽", bl[0] == bl[-1] and set(bl[0]) == {"="})
    check("含全部艺术字行", all(l in b for l in art))
    check("含副标题", brand.TAGLINE in b)
    # 对齐必须按**显示宽度**（CJK 记 2 列）判，不能用 len()：
    # len("本地控制台")==5 但终端占 10 列。
    # 内容行（去掉上下边框）应等宽；边框比内容宽 pad*2。
    body = bl[1:-1]
    check("内容行显示宽度相等（中文副标题不会右移）",
          len({brand._dw(l) for l in body}) == 1,
          f"宽度集合 {sorted({brand._dw(l) for l in body})}")
    check("边框比内容宽一个 pad（内容行右侧还剩 pad 列余量）",
          brand._dw(bl[0]) == brand._dw(body[0]) + 2,
          f"边框 {brand._dw(bl[0])} vs 内容 {brand._dw(body[0])}")
    check("无行超过 80 列", max(brand._dw(l) for l in bl) <= 80,
          f"最宽 {max(brand._dw(l) for l in bl)}")

    # ---- 3. 与 bat 的一致性（本测试的重点）----
    print("\n[3] 启动控制台.bat 漂移")
    if not os.path.exists(BAT):
        check("bat 存在", False, BAT)
    else:
        raw = open(BAT, "rb").read()
        # bat 必须是 CRLF：cmd.exe 解析 .bat 用 CRLF，LF 会把整行当命令执行
        check("bat 是 CRLF（无裸 LF）",
              raw.count(b"\n") == raw.count(b"\r\n"),
              f"裸 LF {raw.count(b'\n') - raw.count(b'\r\n')} 个")
        try:
            txt = raw.decode("gbk")
        except UnicodeDecodeError as e:
            check("bat 是 GBK 可解码", False, str(e))
            txt = ""
        if txt:
            check("bat 是 GBK 可解码", True)
            bat_lines = txt.split("\r\n")
            # 艺术字每一行都必须以 "echo " 前缀原样出现在 bat 里
            missing = [l for l in art if ("echo   " + l) not in bat_lines]
            check("bat 含全部艺术字行（前缀 'echo   '）", not missing,
                  f"缺 {len(missing)} 行：{missing[:2]}")
            check("bat 不含旧标题",
                  "SRC 渗透 Agent - 本地控制台" not in txt)
            check("bat 的 rem 指向 brand.py",
                  "app/brand.py" in txt)

    # ---- 4. run.py 用上了 banner() ----
    print("\n[4] run.py 接线")
    rp = io.open(os.path.join(os.path.dirname(BAT), "run.py"),
                 encoding="utf-8").read()
    check("run.py import brand", "from app.brand import" in rp)
    check("run.py 不再手抄标题", "SRC 渗透 Agent · 本地控制台" not in rp)

    # ---- 5. HTML 入口必须 no-cache（v114 实测坑）----
    # 品牌名在 index.html 里。中间件原先只给 /static 与 /console-assets 设
    # no-cache，三个 HTML 入口（/、/app、/console）是 FileResponse 直出、
    # 默认不带缓存头 → 被浏览器缓存住就是「代码已改、界面不变」。
    # 这与注释里 v050.2（控制台 CSS 缓存）、线索图黑块事故是同一个坑第三次。
    print("\n[5] HTML 入口缓存头")
    try:
        from fastapi.testclient import TestClient
        from app.main import app as _app
        H = {"Host": "127.0.0.1:8770", "Origin": "http://127.0.0.1:8770"}
        with TestClient(_app) as c:
            for path in ("/", "/app", "/console"):
                r = c.get(path, headers=H)
                cc = r.headers.get("cache-control", "")
                check(f"{path} 返回 200 且 no-cache",
                      r.status_code == 200 and "no-cache" in cc,
                      f"status={r.status_code} cache-control={cc!r}")
            # 静态资源不能因这次改动被漏掉
            for path in ("/static/app.js", "/console-assets/core.js"):
                r = c.get(path, headers=H)
                check(f"{path} 仍为 no-cache",
                      "no-cache" in r.headers.get("cache-control", ""),
                      f"cache-control={r.headers.get('cache-control')!r}")
            # API 不该被误加 no-cache（它是动态响应，加了只会浪费带宽语义）
            r = c.get("/api/health", headers=H)
            check("/api/health 不被加 no-cache",
                  "no-cache" not in r.headers.get("cache-control", ""))
    except Exception as e:                                   # noqa: BLE001
        check("TestClient 可用", False, f"{type(e).__name__}: {e}")

    # ---- 6. 起始页（web/start.html）契约 ----
    # v115 视觉重做后最容易改坏的是**功能契约**（模式跳转、快捷键、CTF 预留位）
    # 和「开场日志必须移除」这条核心诉求。这里全部静态断言。
    print("\n[6] 起始页 web/start.html")
    sp = io.open(os.path.join(os.path.dirname(BAT), "web", "start.html"),
                 encoding="utf-8").read()
    check("标题是 LuminaSec", "<title>LuminaSec · 选择工作模式</title>" in sp)
    check("三个模式都在", all(f"id:'{m}'" in sp for m in ("blackbox", "whitebox", "ctf")))
    check("CTF 仍是预留位（ready:false）", "ready:false" in sp and "即将支持" in sp)
    # v116 起 url 先构造再跳（为了插过渡层），所以查的是 URL 格式而非赋值语句
    check("模式跳转契约未变（/app?mode=）",
          "'/app?mode=' + encodeURIComponent(id)" in sp)
    check("localStorage 键未变（src_mode）", "LS_MODE = 'src_mode'" in sp)
    check("快捷键 1/2 保留", "parseInt(e.key, 10)" in sp)
    # 注意：注释里会提到 src_theme（说明"本页不碰它"），所以这里查的是
    # **真实读写**而不是字符串存在性 —— 否则会被自己的注释误伤。
    check("不读写主 UI 的主题键（src_theme）",
          "getItem('src_theme')" not in sp and "setItem('src_theme'" not in sp
          and 'getItem("src_theme")' not in sp and 'setItem("src_theme"' not in sp)
    check("矩阵雨 canvas 在", 'id="rain"' in sp)
    check("启动日志节点在", 'id="boot"' in sp)
    check("打字机逐字逻辑在", "text.slice(0, ++ci)" in sp)
    # 核心诉求：日志必须**移除**，不是留占位
    check("开场日志跑完后从 DOM 移除", "bootEl.remove()" in sp)
    # v116 起淡出走 CSS 类 .gone（不再是内联 style），与 A 的 .on 同时触发
    check("淡出用 opacity 过渡（.gone 类）", "#boot.gone{opacity:0}" in sp.replace(" ", ""))
    check("移除有延时等过渡结束", "setTimeout(() => {" in sp and "380" in sp)
    # A 界面必须「浮现」：opacity + scale + blur，**不含 translateY 位移**
    #（位移会给出方向感，实测观感是"从下面顶上来"，很硬）
    check("A 界面是浮现入场（scale+blur，无位移）",
          "transform:scale(.985)" in sp and "filter:blur(5px)" in sp
          and "#main{" in sp and "translateY" not in sp.split("#main{")[1].split("}")[0])
    check("浮现用 ease-out 曲线", "cubic-bezier(.22,.61,.36,1)" in sp)
    check("reduced-motion 下仍能显形", "transition:opacity .01s" in sp)
    # 亮/暗（v116 撤掉彩色色调，改两态 + 按时段自动）
    check("已撤掉色调预设（v116）", "const TONES = {" not in sp
          and "src_accent" not in sp)
    check("复用主 UI 的主题键 src_theme", "LS_THEME = 'src_theme'" in sp)
    check("有日间时段定义（按时段自动选）",
          "DAY_START" in sp and "DAY_END" in sp and "autoTheme()" in sp)
    check("按时段取 getHours 判断", "new Date().getHours()" in sp)
    check("仅首次（无记录时）才落盘自动结果",
          "applyTheme(storedTheme || autoTheme(), !storedTheme)" in sp)
    check("有亮态 CSS 变量覆盖", 'html[data-theme="light"]' in sp)
    check("亮态强调色换深绿（白底上亮绿不可读）",
          "--acc:#0a8f63" in sp.replace(" ", ""))
    check("亮态取消艺术字辉光（换成实阴影）",
          'html[data-theme="light"] pre.art' in sp)
    check("矩阵雨两套配色（亮态拖白尾，否则一片黑污）",
          "const RAIN = {" in sp and "light:" in sp
          and "rainTheme = RAIN[t]" in sp)
    check("主题切换按钮在", 'id="themeBtn"' in sp and "themebtn" in sp)
    check("显示当前时段文案（日间/夜间）", 'id="themeWord"' in sp)
    check("body 背景有过渡（切亮暗不硬闪）", "transition:background .5s ease" in sp)
    # 平齐淡入：日志与 A 必须占同一网格单元
    # 注意：字符串已去空格，所以 pattern 也不能带空格
    check("日志与 A 在同一 grid 单元（平齐、零位移）",
          ".stage{display:grid" in sp.replace(" ", "")
          and "grid-area:1/1" in sp.replace(" ", ""))
    check("日志淡出用 .gone 类（与 A 的 .on 同时）",
          "#boot.gone" in sp.replace(" ", "") and "classList.add('gone')" in sp)
    check("A 浮现仍是 scale+blur 无位移",
          "transform:scale(.985)" in sp and "filter:blur(5px)" in sp)
    # v116：emoji 方向（曾写反：亮态显示月亮、暗态显示太阳）
    check("亮态显示 ☀️、暗态显示 🌙（不能反）",
          "t === 'light' ? '☀️' : '🌙'" in sp)
    check("不再有写反的 emoji 逻辑",
          "t === 'light' ? '🌙' : '☀️'" not in sp)
    # v116：进入工作区的过渡层
    check("有进入过渡层 #trans", 'id="trans"' in sp and "id=" + '"transCmd"' in sp)
    check("过渡层用 CSS 类 .on 触发", "#trans.on" in sp.replace(" ", ""))
    # 注意：字符串已去空格，pattern 也不能带空格
    check("过渡层有转圈指示", "spin" in sp and "@keyframesspin" in sp.replace(" ", ""))
    check("enter() 先过渡再跳转",
          "ov.classList.add('on')" in sp and "location.href = url" in sp)
    check("reduced-motion 下不留空窗直接跳",
          "if (REDUCED || !ov){ location.href = url; return; }" in sp)
    check("过渡延时与日志淡出同量级（~460ms）", "}, 460);" in sp)
    check("reduced-motion 时跳过动画", "prefers-reduced-motion" in sp
          and "if (REDUCED) finish()" in sp)
    check("页面不可见时停 rAF", "visibilitychange" in sp and "cancelAnimationFrame" in sp)
    check("可跳过开场", "finish, { once:true }" in sp or "finish,{once:true}" in sp)
    # 数据诚实：不许出现编造运行数据的字样
    for bad in ("已接入", "当前目标", "扫描中", "在线目标"):
        check(f"无编造数据「{bad}」", bad not in sp)

    # ---- 7. 主界面 style.css：配色对齐 + 入场浮现 ----
    print("\n[7] 主界面 web/style.css")
    css = io.open(os.path.join(os.path.dirname(BAT), "web", "style.css"),
                  encoding="utf-8").read()
    check("暗态强调色已是终端绿", "--accent: #00e59b" in css)
    check("暗态不再是蓝紫", "--accent: #6d7cff" not in css)
    check("亮态强调色是深绿（白底可读）", "--accent: #0a8f63" in css)
    check("亮态不再是蓝紫", "--accent: #4f6ef7" not in css)
    check("代码块配色也跟绿", "--code-cmd: #5eead4" in css)
    # accent-text/accent2-text 是派生色，用在 12+ 处（标签页/徽章/步骤 chip/
    # 分支卡/图节点/代码库项）—— 漏了它们这些全会留在旧紫
    check("暗态 accent-text 已跟着改", "--accent-text: #5eead4" in css)
    check("暗态 accent2-text 已跟着改", "--accent2-text: #7dd3fc" in css)
    check("亮态 accent-text 已跟着改", "--accent-text: #0a8f63" in css)
    check("亮态 accent2-text 已跟着改", "--accent2-text: #1f6feb" in css)
    # 旧蓝紫只允许出现在线索图节点色（--g-*，分类色板，刻意保留）
    check("旧蓝紫不再用于 UI（只许留在线索图 --g-* 里）",
          all(l.strip().startswith("--g-")
              for l in css.splitlines()
              if any(c in l for c in ("#a5b0ff", "#c4b5fd", "#4f6ef7", "#6a4ff0"))))
    # 线索图节点色是分类色板，刻意不跟品牌绿
    check("线索图节点色保持分类色板（刻意不改）",
          "--g-project: #9a6cff" in css and "categorical palette" in css)
    check("品牌名用等宽字体", "font-family: var(--mono)" in css)
    # 入场浮现：纯 CSS，页面加载即播
    check("主界面有入场浮现动画", "animation: appIn" in css
          and "@keyframes appIn" in css)
    check("浮现不含位移（scale+blur）",
          "transform:scale(.99)" in css and "filter:blur(4px)" in css
          and "translateY" not in css.split("@keyframes appIn")[1].split("}")[0])
    check("reduced-motion 下不播放", ".app{animation:none}" in css.replace(" ", ""))

    print("\n" + "=" * 62)
    # ⚠️ 汇总行必须与其余套件**同一格式**（`结果：N 通过 / M 失败`）：
    # run_all_tests.py 靠正则 `结果：(\d+) 通过 / (\d+) 失败` 收数字，
    # 写别的样子（例如 `通过 85 · 失败 0`）会让它报「跑完但没有结果统计行」并判整套未通过
    # —— 那护栏本身是好的（不静默放过），但代价是全量回归永远红。
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
