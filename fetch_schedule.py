#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厦门大学教务服务平台 —— 课表拉取与可视化
============================================

给定 学号/工号 和 密码，自动完成统一身份认证(CAS)登录 + 教务微应用(gsapp)会话，
拉取当前学期课表，并生成一个自包含的 HTML 页面，展示：
  - 今日课程
  - 本周课表（周一~周日 网格，可切换周次）

运行:
    python fetch_schedule.py                 # 使用 config.json 中的账号，拉取并生成 schedule.html
    python fetch_schedule.py --user X --pass Y
    python fetch_schedule.py --week 3        # 指定查看第 3 周
    python fetch_schedule.py --term 20252    # 指定学年学期代码
    python fetch_schedule.py --no-open       # 生成但不自动打开浏览器

依赖:  pip install requests pycryptodome

说明: 登录页偶尔会弹滑块验证码（多次输错后）；正常情况无需处理。
"""

import argparse
import base64
import json
import os
import random
import re
import sys
import webbrowser
from pathlib import Path

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ----------------------------- 常量 -----------------------------
IDS = "https://ids.xmu.edu.cn"
PORTAL = "https://jw.xmu.edu.cn"
# 门户服务地址（CAS service）
SERVICE = f"{PORTAL}/login?service={PORTAL}/new/index.html"
LOGIN_URL = f"{IDS}/authserver/login?type=userNameLogin&service="
# 微应用（我的课表 gsapp）
GSAPP = f"{PORTAL}/gsapp/sys/wdkbapp"

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
OUTPUT_HTML = BASE_DIR / "schedule.html"

# --------- 星期数据（与教务系统一致：1=周一 …… 7=周日） ---------
DAY_NAMES = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
DAY_FULL = {1: "星期一", 2: "星期二", 3: "星期三", 4: "星期四", 5: "星期五", 6: "星期六", 7: "星期日"}

# 周末先行的显示顺序与周一先行（依据服务器参数 pkgl_xqdyt 的 CSZ：'7'=周日先行，其他=周一先行）
RANDOM_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"


# ----------------------------- 加密 -----------------------------
def random_string(n=64):
    return "".join(random.choice(RANDOM_CHARS) for _ in range(n))


def encrypt_password(plain, salt):
    """复现前端 encryptPassword：AES-128-CBC/PKCS7，key=salt(去首尾空白)，iv=随机16，
    明文 = randomString(64)+password，输出 Base64。"""
    if not salt:
        return plain
    key = salt.strip().encode("utf-8")
    iv = random_string(16).encode("utf-8")
    msg = (random_string(64) + plain).encode("utf-8")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return base64.b64encode(cipher.encrypt(pad(msg, AES.block_size))).decode()


# ----------------------------- 登录 -----------------------------
def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def cas_login(s, username, password):
    """统一身份认证登录，返回进入门户后的会话（含 CASTGC / JSESSIONID / asessionid）。"""
    url = LOGIN_URL + requests.utils.quote(SERVICE, safe="")
    r = s.get(url, timeout=20)
    html = r.text
    salt = re.search(r'pwdEncryptSalt" value="([^"]*)"', html)
    if not salt:
        raise RuntimeError("未在登录页找到 pwdEncryptSalt，页面可能已改版或需验证码。")
    salt = salt.group(1)
    em = re.search(r'name="execution" value="([^"]*)"', html)
    execution = em.group(1) if em else "e1s1"
    lt = re.search(r'name="lt" id="lt" value="([^"]*)"', html)
    lt = lt.group(1) if lt else ""

    data = {
        "username": username,
        "password": encrypt_password(password, salt),
        "_eventId": "submit",
        "cllt": "userNameLogin",
        "dllt": "generalLogin",
        "lt": lt,
        "execution": execution,
    }
    r = s.post(url, data=data, timeout=20, allow_redirects=False)
    loc = r.headers.get("Location")
    if not loc:
        raise RuntimeError("登录响应未返回跳转地址，可能账号或密码错误。")
    for _ in range(6):
        r = s.get(loc if loc.startswith("http") else PORTAL + loc, timeout=20, allow_redirects=False)
        if r.status_code not in (301, 302, 303, 307, 308):
            break
        loc = r.headers.get("Location")
    return s


def sso_gsapp(s):
    """完成教务微应用(gssapp)单点登录，拿到 /gsapp/ 会话(GS_SESSIONID)与 _WEU。"""
    gsapp_url = f"{GSAPP}/*default/index.do?EMAP_LANG=zh&THEME=cherry"
    r = s.get(gsapp_url, timeout=20, allow_redirects=False)
    loc = r.headers.get("Location")  # -> ids 登录(已有TGT会自动回跳)
    r = s.get(loc, timeout=20, allow_redirects=False)
    ticket_url = r.headers.get("Location")  # -> gsapp?ticket=ST-xxx
    for _ in range(4):
        r = s.get(ticket_url if ticket_url.startswith("http") else PORTAL + ticket_url,
                  timeout=20, allow_redirects=False)
        nxt = r.headers.get("Location")
        if not nxt:
            break
        ticket_url = nxt
    if "GS_SESSIONID" not in s.cookies:
        raise RuntimeError("未能获取微应用会话(GS_SESSIONID)。")
    s.headers["X-Requested-With"] = "XMLHttpRequest"
    s.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    s.headers["Origin"] = PORTAL
    s.headers["Referer"] = gsapp_url
    return s


# ----------------------------- 数据获取 -----------------------------
def post(s, path, data):
    url = GSAPP + path
    r = s.post(url, data=data, timeout=20)
    r.raise_for_status()
    return r.json()


def get_term_list(s):
    """开放学期列表（按开课时间倒序）。"""
    j = post(s, "/modules/xskcb/kfdxnxqcx.do", {})
    rows = j["datas"]["kfdxnxqcx"]["rows"]
    return rows


def get_current_week(s, xnxqdm):
    """服务器认定的当前周与总周数。"""
    j = post(s, "/wdkcb/getZcxx.do", {"XNXQDM": xnxqdm})
    return {
        "current": j.get("currentZc"),
        "weeks": [z["ZC"] for z in j.get("zcList", [])],
    }


def get_periods(s, xnxqdm, xh):
    """上课节次列表（含每节的开始/结束时间）。"""
    j = post(s, "/wdkcb/queryXsskjc.do", {"XNXQDM": xnxqdm, "XH": xh})
    return j.get("data", [])


def get_schedule(s, xnxqdm, xh):
    """学生排课结果：不传 ZC，返回整个学期的完整课程列表（含 ZCBH 周次掩码），
    由前端按所选周次对其过滤，从而支持周次切换。"""
    j = post(s, "/wdkcb/queryXspkjg.do", {"XNXQDM": xnxqdm, "XH": xh})
    return j.get("pkjgList", [])


def get_weekday_order(s):
    """星期显示顺序：依据 pkgl_xqdyt 的 CSZ，'7'=周日先行，否则周一先行。"""
    try:
        j = post(s, "/modules/xskcb/cspzcx.do", {"CSDM": "pkgl_xqdyt"})
        rows = j["datas"]["cspzcx"]["rows"]
        csz = (rows[0].get("CSZ") or "").strip() if rows else ""
    except Exception:
        csz = ""
    return [7, 1, 2, 3, 4, 5, 6] if csz == "7" else [1, 2, 3, 4, 5, 6, 7]


def get_student(s, xh):
    j = s.get(GSAPP + "/wdkcb/initXsxx.do", params={"XH": xh}, timeout=20).json()
    return j["data"][0] if j.get("data") else {}


def extract_term_start(term):
    """读取学期首周日期；当前接口通常不返回该字段，缺失时返回 None。"""
    for key in ("KSRQ", "XQKSRQ", "XNXQKSRQ", "START_DATE", "startDate", "start_date"):
        value = term.get(key)
        if value:
            match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(value).strip())
            if match:
                year, month, day = match.groups()
                return f"{year}-{int(month):02d}-{int(day):02d}"
    return None


# ----------------------------- 工具 -----------------------------
def to_time(minutes):
    """1430 -> '14:30'；800 -> '08:00'。"""
    if not minutes:
        return ""
    minutes = int(minutes)
    return f"{minutes // 100:02d}:{minutes % 100:02d}"


def active_in_week(zcbh, week):
    """ZCBH 为 30 位 0/1 字符串，week 从 1 开始。返回该课程当周是否有课。"""
    zcbh = zcbh or ""
    if len(zcbh) >= week:
        return zcbh[week - 1] == "1"
    # 若掩码长度不足，用常见 ZCMC 判断
    return False


def sort_key(c):
    return (c.get("XQ", 0), c.get("KSSJ", 0) or 0)


# ----------------------------- 主流程 -----------------------------
def collect(args):
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    username = args.user or os.environ.get("XMU_USER") or cfg.get("username")
    password = args.password or os.environ.get("XMU_PASS") or cfg.get("password")
    if not username or not password:
        raise SystemExit("未提供账号密码：请在 config.json 填写，或用 --user/--pass、环境变量 XMU_USER/XMU_PASS。")

    print("[1/5] 登录统一身份认证 ...")
    s = cas_login(make_session(), username, password)
    print("[2/5] 获取教务微应用会话 ...")
    s = sso_gsapp(s)

    print("[3/5] 获取学期信息 ...")
    terms = get_term_list(s)
    if not terms:
        raise SystemExit("当前未开放课表查询（无学年学期数据）。")
    term_code = args.term or cfg.get("term") or ""
    if term_code:
        # 学期列表偶尔尚未展示最新学期，但其余接口已经可以按代码查询；
        # 显式指定时保留该代码，不要静默回退到旧学期。
        fallback_name = str(term_code)
        match = re.fullmatch(r"(\d{4})([123])", fallback_name)
        if match:
            year, season = match.groups()
            season_name = {"1": "秋季", "2": "春季", "3": "夏季"}[season]
            fallback_name = f"{year}-{int(year) + 1}学年 {season_name}学期"
        term = next(
            (t for t in terms if t["XNXQDM"] == term_code),
            {"XNXQDM": term_code, "XNXQDM_DISPLAY": fallback_name},
        )
    else:
        term = terms[0]
    xnxqdm = term["XNXQDM"]
    term_name = term.get("XNXQDM_DISPLAY") or xnxqdm
    # 教务接口通常不返回开学日期，优先使用 config.json 中的手工配置。
    term_start = extract_term_start(cfg) or extract_term_start(term)

    print("[4/5] 获取当前周次与节次 ...")
    week_info = get_current_week(s, xnxqdm)
    default_week = args.week or cfg.get("week") or week_info["current"]
    default_week = int(default_week) if str(default_week).isdigit() else 1
    auto_week = not (args.week or cfg.get("week"))
    weeks = week_info["weeks"] or [default_week]

    periods = get_periods(s, xnxqdm, username)
    weekday_order = get_weekday_order(s)
    student = get_student(s, username)

    print("[5/5] 拉取课表数据 ...")
    schedule = get_schedule(s, xnxqdm, username)

    return {
        "username": username,
        "student": student,
        "term": {"code": xnxqdm, "name": term_name, "startDate": term_start},
        "week_info": {"current": default_week, "weeks": weeks, "auto": auto_week},
        "periods": periods,
        "weekday_order": weekday_order,
        "schedule": schedule,
    }


# ----------------------------- HTML 生成 -----------------------------
def build_html(data):
    student_name = data["student"].get("XM", "")
    term_name = data["term"]["name"]
    default_week = data["week_info"]["current"]
    weeks = data["week_info"]["weeks"]

    # 只嵌入前端展示所需字段，避免把学号、内部 ID 等敏感字段写入 HTML。
    schedule_fields = ("KCDM", "KCMC", "BJMC", "XQ", "ZCBH", "ZCMC", "KSJCDM", "JSJCDM", "KSSJ", "JSSJ", "JSXM", "JASMC")
    schedule = [{k: c.get(k) for k in schedule_fields} for c in data["schedule"]]
    payload = {
        "student": {"name": student_name},
        "term": {
            "code": data["term"]["code"],
            "name": term_name,
            "startDate": data["term"].get("startDate"),
        },
        "defaultWeek": default_week,
        "autoWeek": data["week_info"].get("auto", False),
        "weeks": weeks,
        "periods": data["periods"],
        "weekdayOrder": data["weekday_order"],
        "schedule": schedule,
        "dayNames": DAY_FULL,
        "dayShort": DAY_NAMES,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__DATA__", payload_json)
    return html


HTML_TEMPLATE = (BASE_DIR / "templates" / "schedule.html").read_text(encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="拉取厦门大学学期课表并生成可视化 HTML")
    ap.add_argument("--user", help="学号/工号")
    ap.add_argument("--password", help="密码")
    ap.add_argument("--term", help="学年学期代码，如 20252（默认使用当前开放学期）")
    ap.add_argument("--week", help="周次，如 3（默认使用服务器当前周）")
    ap.add_argument("--out", default=str(OUTPUT_HTML), help="输出 HTML 路径")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    try:
        data = collect(args)
    except requests.RequestException as e:
        raise SystemExit(f"网络请求失败：{e}")
    except (KeyError, RuntimeError) as e:
        raise SystemExit(f"登录/抓取失败：{e}")

    html = build_html(data)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\n✓ 已生成课表页面：{out}")
    print(f"  学生：{data['student'].get('XM','')} ({data['username']}) · {data['term']['name']} · 第 {data['week_info']['current']} 周")
    if not args.no_open:
        try:
            webbrowser.open(out.resolve().as_uri())
        except Exception:
            pass


if __name__ == "__main__":
    main()
