"""
LOF基金溢价率监控 - 主入口
"""

import sys
import os
import argparse
import time
from datetime import datetime

# Windows 终端默认 GBK 编码无法输出 emoji，统一切换到 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import FUNDS, ALERT_THRESHOLD, load_dotenv, get_serverchan_key
from db import init_db, upsert_fund_info, save_premium_batch, save_alert
from fetcher import fetch_premium, fetch_prices, fetch_quota, fetch_premium_fundgz, fetch_nav_data
from calculator import merge, check_alerts
from notifier import send_wechat, build_alert_message, build_daily_summary


# ─── 模拟数据 ────────────────────────────────────────────────────────────────

def make_test_rows():
    """生成模拟数据，覆盖推送消息的所有场景"""
    return [
        {
            "full_code": "SZ164906", "code6": "164906", "name": "中概互联网LOF",
            "price": 1.520, "change": 2.15, "est": 1.450, "premium": 4.83,
            "est_date": datetime.now().strftime("%Y-%m-%d"), "ref_premium": None,
            "status": "open", "status_text": "正常申购", "quota": None, "big_quota": None,
        },
        {
            "full_code": "SZ161130", "code6": "161130", "name": "纳斯达克100LOF",
            "price": 2.180, "change": 1.88, "est": 2.100, "premium": 3.81,
            "est_date": datetime.now().strftime("%Y-%m-%d"), "ref_premium": None,
            "status": "limited", "status_text": "限额申购", "quota": 10000.0, "big_quota": None,
        },
        {
            "full_code": "SZ162415", "code6": "162415", "name": "美国消费LOF",
            "price": 1.350, "change": 0.75, "est": 1.310, "premium": 3.05,
            "est_date": datetime.now().strftime("%Y-%m-%d"), "ref_premium": None,
            "status": "closed", "status_text": "暂停申购", "quota": None, "big_quota": None,
        },
        {
            "full_code": "SH501018", "code6": "501018", "name": "南方原油LOF",
            "price": 1.220, "change": -0.81, "est": 1.200, "premium": 1.67,
            "est_date": datetime.now().strftime("%Y-%m-%d"), "ref_premium": None,
            "status": "limited", "status_text": "限制大额", "quota": 1000000.0, "big_quota": None,
        },
        {
            "full_code": "SZ160719", "code6": "160719", "name": "嘉实黄金LOF",
            "price": 3.580, "change": 0.56, "est": 3.560, "premium": 0.56,
            "est_date": datetime.now().strftime("%Y-%m-%d"), "ref_premium": None,
            "status": "open", "status_text": "正常申购", "quota": None, "big_quota": None,
        },
        {
            "full_code": "SZ161226", "code6": "161226", "name": "国投白银LOF",
            "price": 3.120, "change": 3.22, "est": 3.180, "premium": -1.89,
            "est_date": datetime.now().strftime("%Y-%m-%d"), "ref_premium": None,
            "status": "open", "status_text": "正常申购", "quota": None, "big_quota": None,
        },
        {
            "full_code": "SZ160140", "code6": "160140", "name": "美国REIT精选LOF",
            "price": 1.340, "change": 1.82, "est": 1.380, "premium": -2.90,
            "est_date": datetime.now().strftime("%Y-%m-%d"), "ref_premium": None,
            "status": "open", "status_text": "正常申购", "quota": None, "big_quota": None,
        },
    ]


# ─── 终端表格输出 ────────────────────────────────────────────────────────────

def print_local_table(rows, now_str):
    """在终端以对齐表格打印完整查询结果"""
    today = datetime.now().strftime("%Y-%m-%d")

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def color_prem(val, est_date):
        if val is None:
            return "   —   "
        sign = "+" if val > 0 else ""
        stale = est_date and est_date != today
        text = f"{sign}{val:.2f}%"
        if stale:
            text += "⚠"
        if val > 2:
            return RED + BOLD + text + RESET
        elif val > 0:
            return RED + text + RESET
        else:
            return GREEN + text + RESET

    def color_status(status, text):
        if status == "open":
            return GREEN + text + RESET
        elif status == "limited":
            return YELLOW + text + RESET
        elif status == "closed":
            return RED + text + RESET
        return text

    def fmt_money(val):
        if not val:
            return "无限制"
        if val >= 1e8:
            return f"{val/1e8:.0f}亿"
        if val >= 1e4:
            return f"{val/1e4:.0f}万"
        return f"{val:.0f}元"

    sep = "─" * 78
    print(f"\n{BOLD}{CYAN}{'═'*78}{RESET}")
    print(f"{BOLD}{CYAN}  LOF 溢价实时查询  ·  {now_str}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*78}{RESET}")
    print(
        f"  {'排':>2}  {'代码':<10}  {'基金名称':<16}  {'现价':>7}  {'涨跌':>7}  {'EST':>7}  {'溢价率':>10}  {'状态':<8}  {'限额'}"
    )
    print(sep)

    arb_count = 0
    for i, r in enumerate(rows, 1):
        prem = r["premium"]
        price = r["price"]
        change = r["change"]
        est = r["est"]
        status = r["status"]

        price_s = f"{price:.3f}" if price is not None else "  —  "
        change_s = f"{change:+.2f}%" if change is not None else "  —  "
        est_s = f"{est:.3f}" if est is not None else "  —  "
        prem_s = color_prem(prem, r.get("est_date"))
        status_s = color_status(status, r["status_text"])
        quota_s = fmt_money(r["quota"])

        if prem and prem > 0 and status in ("open", "limited"):
            arb_count += 1
            rank_s = f"{BOLD}{RED}{i:>2}{RESET}"
        else:
            rank_s = f"{i:>2}"

        print(
            f"  {rank_s}  {r['full_code']:<10}  {r['name']:<16}  {price_s:>7}  {change_s:>8}  {est_s:>7}  {prem_s:>10}  {status_s:<8}  {quota_s}"
        )

    print(sep)

    arb_rows = [
        r for r in rows if (r["premium"] or 0) > 0 and r["status"] in ("open", "limited")
    ]
    closed_rows = [
        r for r in rows if (r["premium"] or 0) > 0 and r["status"] not in ("open", "limited")
    ]

    print(f"\n  {BOLD}套利机会{RESET}（正溢价且可申购）：{RED}{BOLD}{arb_count} 只{RESET}")
    if arb_rows:
        for r in arb_rows:
            sign = "+" if (r["premium"] or 0) > 0 else ""
            stale = (
                "⚠ EST非今日 "
                if r.get("est_date") and r["est_date"] != today
                else ""
            )
            print(
                f"    → {r['name']} {r['full_code']}  溢价 {RED}{sign}{r['premium']:.2f}%{RESET}  {stale}{r['status_text']}  限额:{fmt_money(r['quota'])}"
            )

    if closed_rows:
        print(f"\n  {BOLD}溢价但暂停申购{RESET}（{len(closed_rows)} 只）：")
        for r in closed_rows:
            print(
                f"    ⚠ {r['name']} {r['full_code']}  溢价 {r['premium']:.2f}%  · {r['status_text']}"
            )

    stale = [r for r in rows if r.get("est_date") and r["est_date"] != today]
    if stale:
        print(
            f"\n  {YELLOW}⚠  {len(stale)} 只基金的EST日期非今日，溢价率可能滞后{RESET}"
        )
        for r in stale:
            ref = r.get("ref_premium")
            ref_s = f"  参考溢价: {ref:+.2f}%" if ref is not None else ""
            print(f"     · {r['name']}  EST日期: {r['est_date']}{ref_s}")

    print(f"\n  数据来源: palmmicro + 天天基金  ·  {now_str}")
    print(f"{CYAN}{'═'*78}{RESET}\n")


# ─── 主程序 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LOF基金溢价率监控")
    parser.add_argument(
        "--test",
        action="store_true",
        help="使用模拟数据测试消息格式和推送（不抓取真实数据，不写库）",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="本地调试模式：抓取真实数据，终端表格展示，不写库，不推送",
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="预警模式：获取数据+检查预警+推送（不发送每日汇总）",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="每日汇总模式：获取数据+存库+预警+汇总推送",
    )
    args = parser.parse_args()

    load_dotenv()
    sendkey = get_serverchan_key()
    # 使用北京时间（UTC+8），兼容本地Windows和GitHub Actions(UTC)
    from datetime import timezone, timedelta
    bj_tz = timezone(timedelta(hours=8))
    now_str = datetime.now(bj_tz).strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now(bj_tz).strftime("%Y-%m-%d")

    # ── 测试模式 ──
    if args.test:
        print(f"=== [测试模式] LOF溢价监控 {now_str} ===")
        print("使用模拟数据，不请求远程接口，不写入数据库\n")
        rows = make_test_rows()
        title, content = build_daily_summary(rows, now_str)
        title = f"【测试】{title}"
        print(f"\n{'─'*60}")
        print(f"标题：{title}")
        print(f"{'─'*60}")
        print(content)
        print(f"{'─'*60}\n")
        if sendkey:
            send_wechat(title, content, sendkey)
        else:
            print("💡 提示：在项目根目录创建 .env 文件并写入 SERVERCHAN_KEY=SCTxxx 即可测试实际推送")
        return

    # ── 获取真实数据 ──
    init_db()
    upsert_fund_info(FUNDS)

    premium_map = fetch_premium()
    time.sleep(0.5)
    price_map = fetch_prices()
    time.sleep(0.5)
    quota_map = fetch_quota()
    time.sleep(0.5)
    nav_map = fetch_nav_data()

    # palmmicro数据不完整时，启用fundgz备用源补充
    fundgz_map = None
    est_missing = sum(1 for c in FUNDS if c[0] not in premium_map or premium_map[c[0]].get("est") is None)
    if est_missing > 0:
        print(f"  palmmicro缺失 {est_missing} 只基金EST数据，启用fundgz备用源...")
        fundgz_map = fetch_premium_fundgz()
    rows = merge(premium_map, price_map, quota_map, fundgz_map, nav_map)

    # ── 本地调试模式 ──
    if args.local:
        print_local_table(rows, now_str)
        return

    # ── 预警模式 ──
    if args.alert:
        print(f"=== [预警模式] LOF溢价监控 {now_str} ===")
        save_premium_batch(rows, date_str)
        alert_rows = check_alerts(rows, ALERT_THRESHOLD, date_str)
        if alert_rows:
            title, content = build_alert_message(alert_rows, now_str)
            print(f"\n{'─'*60}")
            print(f"标题：{title}")
            print(f"{'─'*60}")
            print(content)
            print(f"{'─'*60}\n")
            if sendkey:
                send_wechat(title, content, sendkey)
                for r in alert_rows:
                    save_alert(r["full_code"], date_str, r["premium"], ALERT_THRESHOLD)
            else:
                print("⚠️  未设置 SERVERCHAN_KEY，跳过推送")
        else:
            print(f"  当前无基金溢价率超过 {ALERT_THRESHOLD}%，无需预警")
        return

    # ── 每日汇总模式（默认，无参数时也执行） ──
    print(f"=== LOF溢价监控 {now_str} ===")
    save_premium_batch(rows, date_str)

    # 检查预警
    alert_rows = check_alerts(rows, ALERT_THRESHOLD, date_str)
    if alert_rows and sendkey:
        alert_title, alert_content = build_alert_message(alert_rows, now_str)
        send_wechat(alert_title, alert_content, sendkey)
        for r in alert_rows:
            save_alert(r["full_code"], date_str, r["premium"], ALERT_THRESHOLD)

    # 发送每日汇总
    title, content = build_daily_summary(rows, now_str)
    print(f"\n{'─'*60}")
    print(f"标题：{title}")
    print(f"{'─'*60}")
    print(content)
    print(f"{'─'*60}\n")

    if sendkey:
        send_wechat(title, content, sendkey)
    else:
        print("⚠️  未设置 SERVERCHAN_KEY，跳过推送")


if __name__ == "__main__":
    main()
