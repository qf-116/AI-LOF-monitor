"""
LOF溢价监控 - 通知模块（Server酱微信推送）
"""

import requests
from datetime import datetime

from config import get_serverchan_key


def send_wechat(title, content, sendkey):
    """通过 Server酱 推送微信消息"""
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    try:
        r = requests.post(
            url,
            data={"title": title, "desp": content},
            timeout=15,
        )
        result = r.json()
        if result.get("code") == 0:
            print("✅ 微信推送成功")
        else:
            print(f"⚠️  推送失败: {result}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")


def _fmt_money(val):
    if not val:
        return "无限制"
    if val >= 1e8:
        return f"{val/1e8:.0f}亿"
    if val >= 1e4:
        return f"{val/1e4:.0f}万"
    return f"{val:.0f}元"


def build_alert_message(alert_rows, now_str):
    """构建预警推送消息（仅超阈值基金）"""
    if not alert_rows:
        return None, None

    title = f"LOF溢价预警 {now_str}｜{len(alert_rows)}只超阈值"

    lines = [f"## LOF 溢价预警 · {now_str}", ""]
    lines.append(f"以下基金溢价率超过阈值，存在套利机会：", )
    lines.append("")
    lines.append("| 基金 | 净值溢价率 | 限额 | 状态 |")
    lines.append("|------|-----------|------|------|")
    for r in alert_rows:
        # 使用有效溢价率（DWJZ优先）
        prem = r.get("dwjz_premium") if r.get("dwjz_premium") is not None else r.get("premium")
        sign = "+" if (prem or 0) > 0 else ""
        lines.append(
            f"| {r['name']} `{r['full_code']}` "
            f"| **{sign}{prem:.2f}%** "
            f"| {_fmt_money(r['quota'])} "
            f"| {r['status_text']} |"
        )

    lines.append("")
    lines.append("---")
    lines.append(f"*数据来源：palmmicro + 天天基金 · {now_str}*")

    return title, "\n".join(lines)


def build_daily_summary(rows, now_str):
    """构建每日汇总推送消息"""
    today = datetime.now().strftime("%Y-%m-%d")

    def get_effective_prem(r):
        return r.get("dwjz_premium") if r.get("dwjz_premium") is not None else r.get("premium")

    def prem_cell(r, bold=True):
        prem = get_effective_prem(r)
        if prem is None:
            return "—"
        sign = "+" if prem > 0 else ""
        prem_str = (
            f"**{sign}{prem:.2f}%**" if bold and prem > 0 else f"{sign}{prem:.2f}%"
        )
        est_date = r.get("est_date")
        ref = r.get("ref_premium")
        if est_date and est_date != today:
            if ref is not None:
                ref_sign = "+" if ref > 0 else ""
                prem_str += f"（参考: {ref_sign}{ref:.2f}%）"
            else:
                prem_str += " ⚠️"
        return prem_str

    stale_est = any(
        r.get("est_date") and r["est_date"] != today for r in rows
    )

    arb = [
        r for r in rows if (get_effective_prem(r) or 0) > 0 and r["status"] in ("open", "limited")
    ]
    all_pos = [r for r in rows if (get_effective_prem(r) or 0) > 0]

    title = f"LOF溢价提醒 {now_str}｜{len(arb)}只套利机会"
    if not arb:
        title = f"LOF溢价提醒 {now_str}｜暂无套利机会"

    lines = [f"## LOF 溢价追踪 · {now_str}", ""]

    if stale_est:
        lines.append(
            "> ⚠️ 部分基金EST日期非今日，溢价率可能存在滞后，已显示参考EST溢价（如有）"
        )
        lines.append("")

    if arb:
        lines.append(f"### ⚡ 套利机会（{len(arb)}只）")
        lines.append("")
        lines.append("| 基金 | 净值溢价 | 限额 | 状态 |")
        lines.append("|------|---------|------|------|")
        for r in arb:
            lines.append(
                f"| {r['name']} `{r['full_code']}` "
                f"| {prem_cell(r, bold=True)} "
                f"| {_fmt_money(r['quota'])} "
                f"| {r['status_text']} |"
            )
        lines.append("")
    else:
        lines.append("### 暂无套利机会")
        lines.append("")

    if all_pos:
        closed_pos = [
            r for r in all_pos if r["status"] not in ("open", "limited")
        ]
        if closed_pos:
            lines.append(f"### ⚠️ 溢价但已暂停申购（{len(closed_pos)}只）")
            lines.append("")
            for r in closed_pos:
                lines.append(
                    f"- {r['name']} `{r['full_code']}` 净值溢价 {prem_cell(r, bold=False)} · {r['status_text']}"
                )
            lines.append("")

    lines.append("### 📊 净值溢价率排行（前10）")
    lines.append("")
    lines.append("| 排名 | 基金 | 净值溢价率 | 限额 |")
    lines.append("|------|------|-----------|------|")
    for i, r in enumerate(rows[:10], 1):
        lines.append(
            f"| {i} | {r['name']} | {prem_cell(r, bold=False)} | {_fmt_money(r['quota'])} |"
        )

    lines.append("")
    lines.append("---")
    lines.append(f"*数据来源：palmmicro + 天天基金 · {now_str}*")

    return title, "\n".join(lines)
