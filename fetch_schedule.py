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
        term = next((t for t in terms if t["XNXQDM"] == term_code), terms[0])
    else:
        term = terms[0]
    xnxqdm = term["XNXQDM"]
    term_name = term.get("XNXQDM_DISPLAY") or xnxqdm

    print("[4/5] 获取当前周次与节次 ...")
    week_info = get_current_week(s, xnxqdm)
    default_week = args.week or cfg.get("week") or week_info["current"]
    default_week = int(default_week) if str(default_week).isdigit() else 1
    weeks = week_info["weeks"] or [default_week]

    periods = get_periods(s, xnxqdm, username)
    weekday_order = get_weekday_order(s)
    student = get_student(s, username)

    print("[5/5] 拉取课表数据 ...")
    schedule = get_schedule(s, xnxqdm, username)

    return {
        "username": username,
        "student": student,
        "term": {"code": xnxqdm, "name": term_name},
        "week_info": {"current": default_week, "weeks": weeks},
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
        "term": {"code": data["term"]["code"], "name": term_name},
        "defaultWeek": default_week,
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


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>我的课表</title>
<style>
  :root{--bg:#f2f5f9;--card:#fff;--ink:#182334;--muted:#718096;--line:#e4eaf1;--accent:#1769aa;--accent-dark:#0b3764;--accent-soft:#e9f3fb;--today:#df5a54;--shadow:0 18px 50px rgba(27,55,90,.08)}
  *{box-sizing:border-box}
  html{background:var(--bg)}
  body{margin:0;background:radial-gradient(circle at 8% 5%,rgba(43,134,190,.10),transparent 24rem),radial-gradient(circle at 92% 0,rgba(113,168,211,.14),transparent 28rem),var(--bg);color:var(--ink);font-family:"Inter","PingFang SC","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}
  button,select,input{font:inherit}button,select{-webkit-tap-highlight-color:transparent}
  .wrap{max-width:1180px;margin:0 auto;padding:28px 20px 72px}
  .hero{position:relative;overflow:hidden;color:#fff;background:linear-gradient(125deg,#0a315b 0%,#10528b 58%,#1876ad 100%);border-radius:28px;padding:24px 28px 34px;box-shadow:0 24px 60px rgba(11,55,100,.22)}
  .hero::before,.hero::after{content:"";position:absolute;border:1px solid rgba(255,255,255,.13);border-radius:50%;pointer-events:none}.hero::before{width:280px;height:280px;right:-76px;top:-152px}.hero::after{width:180px;height:180px;right:66px;bottom:-144px}
  .hero-main{position:relative;z-index:1;display:flex;align-items:flex-end;justify-content:space-between;gap:32px;margin-top:8px}.eyebrow{margin:0 0 7px;color:#a9d6f5;font-size:11px;font-weight:750;letter-spacing:.18em}.hero h1{margin:0;font-family:Georgia,"Songti SC","STSong",serif;font-size:42px;font-weight:700;letter-spacing:.02em;line-height:1.15}.hero-name{margin:10px 0 0;color:rgba(255,255,255,.72);font-size:15px;font-weight:650}
  .week-orb{min-width:178px;padding:18px 20px;border:1px solid rgba(255,255,255,.22);border-radius:18px;background:rgba(255,255,255,.10);backdrop-filter:blur(10px);box-shadow:inset 0 1px 0 rgba(255,255,255,.12)}.week-orb span{display:block;color:rgba(255,255,255,.65);font-size:11px}.week-orb strong{display:block;margin:2px 0 4px;font-size:24px;line-height:1.25}.week-orb small{display:block;color:rgba(255,255,255,.72);font-size:12px;line-height:1.35;white-space:nowrap}
  .toolbar{display:flex;align-items:center;gap:20px;margin-bottom:18px;padding:14px 16px 14px 20px;background:rgba(255,255,255,.78);border:1px solid rgba(222,230,239,.92);border-radius:18px;box-shadow:0 8px 30px rgba(27,55,90,.05);backdrop-filter:blur(12px)}.control-copy{min-width:120px;margin-right:auto}.section-kicker{display:block;color:var(--accent);font-size:10px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}.control-copy strong{display:block;font-size:15px;margin-top:1px}
  .week-switch{display:flex;align-items:center;gap:8px;padding:4px;background:#edf2f7;border-radius:13px}select,button{height:38px;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:10px}select{min-width:104px;padding:0 34px 0 13px;font-weight:700;cursor:pointer}button{padding:0 12px;cursor:pointer;transition:transform .15s ease,background .15s ease,border-color .15s ease}button:hover{background:var(--accent-soft);border-color:#c9deee}button:active{transform:translateY(1px)}select:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid rgba(23,105,170,.18);outline-offset:2px}.week-switch button{width:38px;padding:0;font-size:18px;background:transparent;border-color:transparent}
  .toggle{display:flex;align-items:center;gap:9px;color:#536176;font-size:13px;font-weight:600;cursor:pointer;user-select:none}.toggle input{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}.switch{position:relative;width:38px;height:22px;border-radius:999px;background:#cbd5df;transition:background .2s ease}.switch::after{content:"";position:absolute;width:16px;height:16px;left:3px;top:3px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(33,45,61,.22);transition:transform .2s ease}.toggle input:checked + .switch{background:var(--accent)}.toggle input:checked + .switch::after{transform:translateX(16px)}.toggle input:focus-visible + .switch{outline:3px solid rgba(23,105,170,.18);outline-offset:2px}
  .card{background:rgba(255,255,255,.96);border:1px solid rgba(224,231,239,.95);border-radius:22px;padding:22px;margin-bottom:18px;box-shadow:0 12px 36px rgba(27,55,90,.055)}.section-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.section-head h2{margin:2px 0 0;font-size:19px;font-weight:750;letter-spacing:-.01em}.section-meta{display:inline-flex;align-items:center;min-height:30px;padding:0 11px;color:#5f6d7f;background:#f3f6f9;border:1px solid var(--line);border-radius:999px;font-size:12px}.section-meta b{color:var(--accent);margin-right:3px}.empty{position:relative;color:var(--muted);text-align:center;padding:32px 0 28px;font-size:14px}.empty::before{content:"";display:block;width:34px;height:34px;margin:0 auto 10px;border:2px solid #b8c9d8;border-top-color:transparent;border-radius:50%;transform:rotate(-22deg)}
  .timeline{display:flex;flex-direction:column;gap:10px}.lesson{position:relative;display:flex;gap:16px;align-items:center;min-height:76px;padding:12px 16px 12px 0;background:#f8fafc;border:1px solid var(--line);border-radius:15px;overflow:hidden;cursor:pointer;transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}.lesson:hover{transform:translateY(-1px);border-color:#d4e0eb;box-shadow:0 8px 20px rgba(27,55,90,.06)}.lesson:focus-visible{outline:3px solid rgba(23,105,170,.18);outline-offset:2px}.lesson .time{min-width:92px;padding:0 16px;color:var(--muted);font-size:12px;display:flex;flex-direction:column;justify-content:center;gap:1px;border-right:1px solid var(--line)}.lesson .time b{color:var(--ink);font-size:16px;letter-spacing:.02em}.lesson .info{flex:1;min-width:0}.lesson .name{overflow:hidden;font-size:15px;font-weight:750;text-overflow:ellipsis;white-space:nowrap}.lesson .class-name{color:var(--muted);font-size:12px;font-weight:500}.lesson .meta2{display:flex;flex-wrap:wrap;align-items:center;gap:7px;color:var(--muted);font-size:12px;margin-top:5px}.lesson .meta2 .sep{width:3px;height:3px;border-radius:50%;background:#b5c0cc}.color-strip{order:-1;align-self:stretch;width:5px;flex-shrink:0;background:var(--course);border-radius:0 5px 5px 0}
  .grid-scroll{overflow-x:auto;padding:1px 1px 6px;scrollbar-color:#c5d1dd transparent;scrollbar-width:thin}table.kb{width:100%;min-width:860px;border-spacing:0;border-collapse:separate;background:#fff;border:1px solid var(--line);border-radius:15px;overflow:hidden;font-size:13px}table.kb th,table.kb td{padding:0;vertical-align:top;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}table.kb tr:last-child td{border-bottom:0}table.kb th:last-child,table.kb td:last-child{border-right:0}table.kb thead th{height:48px;background:#f6f8fb;position:sticky;top:0;z-index:2}table.kb th.daycol{font-size:13px;font-weight:700;padding:13px 6px;text-align:center}table.kb th.daycol.today{position:relative;color:var(--today)}table.kb th.daycol.today::after{content:"";position:absolute;left:50%;bottom:7px;width:4px;height:4px;border-radius:50%;background:var(--today);transform:translateX(-50%)}table.kb th.timecol{width:92px;min-width:92px;color:var(--muted);font-size:11px;font-weight:650;padding:14px 6px;text-align:center}table.kb td.timecell{width:92px;color:var(--muted);font-size:11px;text-align:center;background:#f9fafc;vertical-align:middle}table.kb td.timecell div:first-child{color:#455368;font-size:12px;font-weight:750}table.kb td.cell{height:68px;position:relative;padding:2px;background:#fff}td.cell.today{background:rgba(223,90,84,.035)}
  .blk{position:absolute;left:2px;right:2px;padding:7px 8px;color:var(--course-ink);background:var(--course-bg);border:1px solid var(--course-border);border-left:3px solid var(--course);border-radius:7px;font-size:12px;overflow:hidden;cursor:pointer;box-shadow:0 2px 5px rgba(28,45,66,.035);transition:transform .16s ease,box-shadow .16s ease}.blk:hover,.blk:focus-visible{transform:translateY(-1px);box-shadow:0 6px 14px rgba(28,45,66,.12);outline:none}.blk .t1{display:block;overflow:hidden;font-weight:750;line-height:1.3;word-break:normal;overflow-wrap:anywhere}
  .tc1{--course:#3977c3;--course-bg:#edf4fc;--course-border:#d5e5f6;--course-ink:#245489;--course-muted:#5c7796}.tc2{--course:#3b9276;--course-bg:#edf8f4;--course-border:#d3ede4;--course-ink:#286b56;--course-muted:#5a7f72}.tc3{--course:#ca7b3a;--course-bg:#fff5ea;--course-border:#f4dfc7;--course-ink:#92531f;--course-muted:#947356}.tc4{--course:#8d67ba;--course-bg:#f6f0fb;--course-border:#e6d8f2;--course-ink:#66438f;--course-muted:#7d6a91}.tc5{--course:#348c9d;--course-bg:#ecf8fa;--course-border:#d0ebef;--course-ink:#286a76;--course-muted:#597e85}.tc6{--course:#c85e67;--course-bg:#fff0f1;--course-border:#f4d6d9;--course-ink:#93434a;--course-muted:#93686c}.tc7{--course:#6575b9;--course-bg:#f0f2fb;--course-border:#dce1f5;--course-ink:#45558f;--course-muted:#687399}
  body.modal-open{overflow:hidden}.modal-backdrop{position:fixed;inset:0;z-index:20;display:grid;place-items:center;padding:20px;background:rgba(8,29,53,.48);opacity:0;visibility:hidden;transition:opacity .18s ease,visibility .18s ease}.modal-backdrop.open{opacity:1;visibility:visible}.course-modal{position:relative;width:min(100%,460px);padding:27px 28px 25px;background:#fff;border:1px solid rgba(224,231,239,.95);border-radius:24px;box-shadow:0 24px 70px rgba(8,29,53,.25);transform:translateY(10px) scale(.98);transition:transform .2s ease}.modal-backdrop.open .course-modal{transform:none}.modal-close{position:absolute;right:15px;top:14px;width:32px;height:32px;padding:0;border:0;border-radius:50%;color:#718096;background:#f2f5f8;font-size:22px;line-height:1}.modal-close:hover{color:var(--ink);background:#e8eef4}.modal-kicker{color:var(--accent);font-size:10px;font-weight:800;letter-spacing:.16em}.modal-title{margin:7px 38px 3px 0;color:var(--ink);font-size:23px;line-height:1.3}.modal-class{min-height:18px;color:var(--muted);font-size:12px}.modal-details{display:grid;gap:9px;margin-top:22px;padding-top:18px;border-top:1px solid var(--line)}.detail-row{display:grid;grid-template-columns:58px 1fr;gap:12px;align-items:start;font-size:13px}.detail-row span{color:var(--muted)}.detail-row b{color:var(--ink);font-weight:650;word-break:normal;overflow-wrap:anywhere}.modal-hint{margin:20px 0 0;color:#93a0af;font-size:11px}
  @media (max-width:800px){.wrap{padding:16px 12px 48px}.hero{border-radius:22px;padding:20px 20px 30px}.hero-main{margin-top:8px}.toolbar{align-items:flex-end;flex-wrap:wrap;gap:12px}.control-copy{width:100%}.toggle{margin-left:auto}}
@media (max-width:560px){.hero-main{display:block;margin-top:8px}.hero h1{font-size:34px}.week-orb{display:flex;align-items:center;gap:8px;min-width:0;margin-top:22px;padding:12px 14px}.week-orb span{display:none}.week-orb strong{font-size:18px;margin:0}.week-orb small{margin-left:auto;font-size:11px;text-align:right;white-space:normal}.toolbar{padding:14px}.control-copy{display:none}.week-switch{flex:1}.week-switch select{flex:1}.toggle{width:100%;justify-content:flex-end}.card{padding:17px 14px;border-radius:18px}.lesson{gap:10px;padding-right:10px}.lesson .time{min-width:76px;padding:0 11px}.lesson .class-name{display:none}.section-meta{font-size:11px}.modal-backdrop{align-items:end;padding:12px}.course-modal{width:100%;padding:24px 20px 22px;border-radius:24px 24px 15px 15px}.modal-title{font-size:21px}}
  @media (max-width:560px){.wrap{padding-left:8px;padding-right:8px}.hero{padding:18px 16px 24px}.hero h1{font-size:31px}.hero-name{font-size:14px}.card{padding:15px 10px}.grid-scroll{overflow-x:hidden}.grid-scroll table.kb{min-width:0;table-layout:fixed;font-size:11px}.grid-scroll table.kb th.timecol,.grid-scroll table.kb td.timecell{width:58px;min-width:58px}.grid-scroll table.kb th.daycol{padding-left:2px;padding-right:2px;font-size:11px}.grid-scroll table.kb td.timecell div{white-space:nowrap;font-size:10px}.grid-scroll .blk{padding:5px 4px;font-size:10px;border-left-width:2px}.grid-scroll .blk .t1{line-height:1.2}.section-head h2{font-size:17px}.lesson .name{font-size:14px}}
  @media (prefers-reduced-motion:reduce){button,.switch,.switch::after,.lesson{transition:none}}
  pre.json{display:none}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="hero-main">
      <div>
        <p class="eyebrow">MY WEEKLY SCHEDULE</p>
        <h1>我的课表</h1>
        <p class="hero-name" id="heroName"></p>
      </div>
      <div class="week-orb"><span>当前查看</span><strong id="heroWeek"></strong><small id="heroWeekRange"></small></div>
    </div>
  </header>

  <div class="toolbar">
    <div class="control-copy"><span class="section-kicker">WEEK VIEW</span><strong>浏览课表</strong></div>
    <div class="week-switch">
      <button id="btnPrev" class="prev" aria-label="上一周" title="上一周">←</button>
      <select id="weekSel" aria-label="选择周次"></select>
      <button id="btnNext" class="next" aria-label="下一周" title="下一周">→</button>
    </div>
    <label class="toggle"><input type="checkbox" id="onlyToday"/><span class="switch"></span><span>仅显示今天</span></label>
  </div>

  <section class="card" id="cardToday">
    <div class="section-head">
      <div><span class="section-kicker">TODAY</span><h2>今日课程</h2></div>
      <span class="section-meta" id="todayDate"></span>
    </div>
    <div class="timeline" id="todayList"></div>
  </section>

  <section class="card">
    <div class="section-head">
      <div><span class="section-kicker">WEEKLY OVERVIEW</span><h2>本周课表</h2></div>
    </div>
    <div class="grid-scroll"><table class="kb" id="kb"></table></div>
  </section>
</div>

<div class="modal-backdrop" id="courseModal" aria-hidden="true">
  <section class="course-modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <button class="modal-close" id="modalClose" type="button" aria-label="关闭课程详情">×</button>
    <div class="modal-kicker">COURSE DETAILS</div>
    <h2 class="modal-title" id="modalTitle"></h2>
    <div class="modal-class" id="modalClass"></div>
    <div class="modal-details" id="modalDetails"></div>
    <p class="modal-hint">点击空白处或按 Esc 关闭</p>
  </section>
</div>

<script>
const DATA = __DATA__;
const $ = (s)=>document.querySelector(s);
const nameMap = {}; DATA.dayShort && Object.entries(DATA.dayShort).forEach(([k,v])=>nameMap[+k]=v);
function prettyText(s){ return String(s||'').replace(/([\u4e00-\u9fff])([A-Za-z0-9])/g,'$1 $2').replace(/([A-Za-z0-9])([\u4e00-\u9fff])/g,'$1 $2'); }
function dateLabel(d){
  const day = DATA.dayShort[d.getDay()===0?7:d.getDay()] || '';
  return d.getFullYear()+' 年 '+(d.getMonth()+1)+' 月 '+d.getDate()+' 日 · '+day;
}
function weekRangeLabel(week){
  const today = new Date();
  const monday = new Date(today);
  monday.setHours(0,0,0,0);
  monday.setDate(today.getDate()-((today.getDay()+6)%7)+(week-DATA.defaultWeek)*7);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate()+6);
  const left = monday.getFullYear()+' 年 '+(monday.getMonth()+1)+' 月 '+monday.getDate()+' 日';
  const right = sunday.getFullYear()===monday.getFullYear()
    ? (sunday.getMonth()+1)+' 月 '+sunday.getDate()+' 日'
    : sunday.getFullYear()+' 年 '+(sunday.getMonth()+1)+' 月 '+sunday.getDate()+' 日';
  return left+' - '+right;
}

const PALETTE = ['tc1','tc2','tc3','tc4','tc5','tc6','tc7'];
const ROW_HEIGHT = 68;
const courseColor = {};
let colorIdx = 0;
DATA.schedule.forEach(c=>{ const k = c.KCDM + '-' + c.BJMC; if(!courseColor[k]) courseColor[k] = PALETTE[colorIdx++ % PALETTE.length]; });

function fmt(t){ t = String(t||''); return t.length===4 ? t.slice(0,2)+':'+t.slice(2) : t; }
function activeWeek(c, week){
  const z = c.ZCBH || '';
  return z.length>=week ? z[week-1]==='1' : false;
}
function isToday(xq){
  const d = new Date();
  const iso = (d.getDay()===0 ? 7 : d.getDay()); // 周日=7
  return (xq==iso);
}
function byTime(a,b){ return (a.KSSJ||0)-(b.KSSJ||0); }

// 周次下拉
(function(){
  const sel = $('#weekSel');
  DATA.weeks.forEach(w=>{ const o=document.createElement('option'); o.value=w; o.textContent='第 '+w+' 周'; sel.appendChild(o); });
  sel.value = DATA.defaultWeek;
  sel.addEventListener('change', render);
  $('#btnPrev').addEventListener('click', ()=>step(-1));
  $('#btnNext').addEventListener('click', ()=>step(1));
  function step(d){ const cur=+sel.value; let n=cur+d; if(n<DATA.weeks[0])n=DATA.weeks[0]; if(n>DATA.weeks[DATA.weeks.length-1])n=DATA.weeks[DATA.weeks.length-1]; sel.value=n; render(); }
  $('#onlyToday').addEventListener('change', render);
})();

function render(){
  const week = +$('#weekSel').value;
  const onlyToday = $('#onlyToday').checked;
  const dayCols = DATA.weekdayOrder.filter(xq=>+xq>=1 && +xq<=5);
  // 本周有课的课程
  const weekCourses = DATA.schedule.filter(c=>activeWeek(c, week) && +c.XQ>=1 && +c.XQ<=5);
  $('#heroWeek').textContent = '第 '+week+' 周';
  $('#heroWeekRange').textContent = weekRangeLabel(week);
  renderToday(weekCourses, onlyToday);
  renderGrid(week, weekCourses, dayCols, onlyToday);
}

function renderToday(list, onlyToday){
  const box = $('#todayList');
  const todayCourses = list.filter(c=>isToday(c.XQ)).sort(byTime);
  if(!todayCourses.length){ box.innerHTML = ''; $('#cardToday').hidden = true; return; }
  $('#cardToday').hidden = false;
  box.innerHTML = '';
  todayCourses.forEach(c=>{
    const weeks = c.ZCMC || '';
    const div = document.createElement('div'); div.className='lesson';
    const key = c.KCDM+'-'+c.BJMC;
    const meta = weeks ? '<span>'+esc(prettyText(weeks))+'</span>' : '';
    div.innerHTML = '<div class="time"><b>'+fmt(c.KSSJ)+'</b><span>'+fmt(c.JSSJ)+'</span></div>'+ 
      '<div class="info"><div class="name">'+esc(prettyText(c.KCMC||''))+(c.BJMC?' <span class="class-name">('+esc(prettyText(c.BJMC))+')</span>':'')+'</div>'+ 
      '<div class="meta2">'+meta+'</div></div>'+ 
      '<div class="color-strip '+courseColor[key]+'"></div>';
    bindCourseTrigger(div,c);
    box.appendChild(div);
  });
}

function renderGrid(week, weekCourses, dayCols, onlyToday){
  const kb = $('#kb');
  const periods = DATA.periods;
  const d = new Date(); const iso = (d.getDay()===0?7:d.getDay());
  // 表头
  let html = '<thead><tr><th class="timecol">节次 / 时间</th>';
  dayCols.forEach(xq=>{ html += '<th class="daycol'+(xq===iso?' today':'')+'">'+(nameMap[xq]||xq)+'</th>'; });
  html += '</tr></thead><tbody>';
  periods.forEach(p=>{
    html += '<tr><td class="timecell"><div>'+esc(prettyText(p.MC||''))+'</div><div style="opacity:.7">'+fmt(p.KSSJ)+'~'+fmt(p.JSSJ)+'</div></td>';
    dayCols.forEach(xq=>{
      html += '<td class="cell'+(xq===iso?' today':'')+'"></td>';
    });
    html += '</tr>';
  });
  html += '</tbody>';
  kb.innerHTML = html;
  // 先计算每天的并行轨道，避免同一时段的课程互相覆盖
  const placements = [];
  weekCourses.forEach(c=>{
    if(onlyToday && !isToday(c.XQ)) return;
    const rows = periods.filter(p=>+p.DM>=+c.KSJCDM && +p.DM<=+c.JSJCDM);
    const colIdx = dayCols.indexOf(c.XQ);
    if(!rows.length || colIdx<0) return;
    placements.push({c,rowIdx:periods.indexOf(rows[0]),span:rows.length,colIdx});
  });
  const dayGroups = {};
  placements.forEach(item=>{ (dayGroups[item.colIdx] ||= []).push(item); });
  Object.values(dayGroups).forEach(items=>{
    items.sort((a,b)=>a.rowIdx-b.rowIdx || b.span-a.span);
    const chunks = [];
    let chunk = [], chunkEnd = -1;
    items.forEach(item=>{
      if(chunk.length && item.rowIdx>=chunkEnd){ chunks.push(chunk); chunk=[]; chunkEnd=-1; }
      chunk.push(item); chunkEnd = Math.max(chunkEnd, item.rowIdx + item.span);
    });
    if(chunk.length) chunks.push(chunk);
    chunks.forEach(group=>{
      const laneEnds = [];
      group.forEach(item=>{
        let lane = laneEnds.findIndex(end=>end<=item.rowIdx);
        if(lane<0){ lane=laneEnds.length; laneEnds.push(0); }
        item.lane = lane;
        laneEnds[lane] = item.rowIdx + item.span;
      });
      const total = laneEnds.length;
      group.forEach(item=>{
        const trs = kb.tBodies[0].rows;
        const cell = trs[item.rowIdx].cells[1 + item.colIdx]; // 第0列是时间
        const c = item.c, key = c.KCDM+'-'+c.BJMC;
        const block = document.createElement('div');
        block.className = 'blk ' + courseColor[key];
        block.style.top = '2px'; block.style.bottom = 'auto';
        block.style.height = 'calc(' + (item.span*ROW_HEIGHT - 4) + 'px)';
        block.style.left = 'calc(' + (item.lane*100/total) + '% + 2px)';
        block.style.right = 'auto';
        block.style.width = 'calc(' + (100/total) + '% - 4px)';
        block.title = '点击查看课程详情';
        block.innerHTML = '<span class="t1">'+esc(prettyText(c.KCMC||''))+'</span>';
        bindCourseTrigger(block,c);
        if(item.span>1){ block.style.zIndex=1; }
        cell.appendChild(block);
      });
    });
  });
}

function esc(s){ return String(s||'').replace(/[&<>"]/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m])); }

function bindCourseTrigger(el,c){
  el.tabIndex = 0;
  el.setAttribute('role','button');
  el.title = '点击查看课程详情';
  const activate = (e)=>{
    if(e.type==='keydown' && e.key!=='Enter' && e.key!==' ') return;
    if(e.type==='keydown') e.preventDefault();
    openCourse(c);
  };
  el.addEventListener('click',activate);
  el.addEventListener('keydown',activate);
}

function openCourse(c){
  const modal = $('#courseModal');
  $('#modalTitle').textContent = prettyText(c.KCMC || '课程详情');
  $('#modalClass').textContent = c.BJMC ? '班级：'+prettyText(c.BJMC) : '';
  const rows = [
    ['教师', c.JSXM], ['教室', c.JASMC], ['周次', c.ZCMC],
    ['时间', (nameMap[c.XQ]||'')+' '+fmt(c.KSSJ)+' - '+fmt(c.JSSJ)]
  ].filter(([,value])=>value);
  $('#modalDetails').innerHTML = rows.map(([label,value])=>
    '<div class="detail-row"><span>'+label+'</span><b>'+esc(prettyText(value))+'</b></div>'
  ).join('');
  modal.classList.add('open');
  modal.setAttribute('aria-hidden','false');
  document.body.classList.add('modal-open');
  $('#modalClose').focus();
}

function closeCourse(){
  const modal = $('#courseModal');
  modal.classList.remove('open');
  modal.setAttribute('aria-hidden','true');
  document.body.classList.remove('modal-open');
}

$('#modalClose').addEventListener('click', closeCourse);
$('#courseModal').addEventListener('click', e=>{ if(e.target===e.currentTarget) closeCourse(); });
document.addEventListener('keydown', e=>{ if(e.key==='Escape' && $('#courseModal').classList.contains('open')) closeCourse(); });

// 顶部信息
(function(){
  $('#heroName').textContent = prettyText(DATA.student.name);
  const today = new Date();
  $('#todayDate').textContent = dateLabel(today);
  render();
})();
</script>
</body>
</html>
"""


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
