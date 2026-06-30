"""
生成 GitHub Pages 静态看板页面
每次 daily 运行时调用，读取 SQLite 数据生成 docs/index.html
"""

import json
import os
import sqlite3
from datetime import datetime

from config import DB_PATH

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")


def get_dashboard_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 最新一天的所有基金数据
    c.execute("""
        SELECT full_code, date, price, change_pct, est, premium,
               est_date, ref_premium, dwjz, dwjz_premium, status, status_text, quota
        FROM premium_history
        WHERE date = (SELECT MAX(date) FROM premium_history)
        ORDER BY COALESCE(dwjz_premium, premium) DESC
    """)
    latest = [dict(row) for row in c.fetchall()]

    # 最近30天每日溢价率（用于趋势图 — 使用 DWJZ 溢价率优先）
    c.execute("""
        SELECT full_code, date, COALESCE(dwjz_premium, premium) as display_premium
        FROM premium_history
        WHERE (premium IS NOT NULL OR dwjz_premium IS NOT NULL)
          AND date >= date('now', '-30 days')
        ORDER BY full_code, date
    """)
    history = [dict(row) for row in c.fetchall()]

    # 基金名称映射
    c.execute("SELECT full_code, name FROM fund_info")
    names = {row["full_code"]: row["name"] for row in c.fetchall()}

    conn.close()
    return latest, history, names


def generate_html(latest, history, names):
    # 使用北京时间（UTC+8），兼容本地Windows和GitHub Actions(UTC)
    from datetime import timezone, timedelta
    bj_tz = timezone(timedelta(hours=8))
    update_time = datetime.now(bj_tz).strftime("%Y-%m-%d %H:%M")

    # 构建历史趋势数据（仅取前10只溢价最高的基金）
    top_codes = [r["full_code"] for r in latest[:10]]
    trend_data = {}
    for h in history:
        if h["full_code"] in top_codes:
            trend_data.setdefault(h["full_code"], []).append({
                "date": h["date"],
                "premium": h["display_premium"],
            })

    # 统计（使用 DWJZ 溢价率优先）
    def get_effective_prem(r):
        return r.get("dwjz_premium") if r.get("dwjz_premium") is not None else r.get("premium")

    from config import ALERT_THRESHOLD
    arb_count = sum(1 for r in latest if (get_effective_prem(r) or 0) >= ALERT_THRESHOLD and r["status"] in ("open", "limited"))
    closed_count = sum(1 for r in latest if (get_effective_prem(r) or 0) >= ALERT_THRESHOLD and r["status"] not in ("open", "limited"))
    max_prem = max((get_effective_prem(r) for r in latest if get_effective_prem(r) is not None), default=0)

    # 表格行
    table_rows = ""
    for i, r in enumerate(latest, 1):
        prem = r.get("dwjz_premium")  # 优先显示 DWJZ 溢价率
        est_prem = r.get("premium")  # EST 溢价率（备用）
        if prem is None:
            prem = est_prem
        name = names.get(r["full_code"], r["full_code"])
        price_s = f"{r['price']:.3f}" if r.get("price") else "—"
        change_s = f"{r['change_pct']:+.2f}%" if r.get("change_pct") is not None else "—"
        est_s = f"{r['est']:.3f}" if r.get("est") else "—"
        # DWJZ 净值列
        dwjz = r.get("dwjz")
        dwjz_s = f"{dwjz:.4f}" if dwjz else "—"
        quota = r.get("quota")
        quota_s = "无限制" if not quota else (f"{quota/1e8:.0f}亿" if quota >= 1e8 else f"{quota/1e4:.0f}万" if quota >= 1e4 else f"{quota:.0f}元")

        if prem is None:
            prem_class = ""
            prem_s = "—"
        elif prem > 2:
            prem_class = "high"
            prem_s = f"+{prem:.2f}%"
        elif prem > 0:
            prem_class = "positive"
            prem_s = f"+{prem:.2f}%"
        else:
            prem_class = "negative"
            prem_s = f"{prem:.2f}%"

        # EST 溢价率（参考列）
        if est_prem is None:
            est_prem_s = "—"
        elif est_prem > 0:
            est_prem_s = f"+{est_prem:.2f}%"
        else:
            est_prem_s = f"{est_prem:.2f}%"

        status_class = {"open": "open", "limited": "limited", "closed": "closed"}.get(r.get("status", ""), "")

        table_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{name}<br><small>{r['full_code']}</small></td>
                <td>{price_s}</td>
                <td>{change_s}</td>
                <td>{est_s}</td>
                <td>{dwjz_s}</td>
                <td class="{prem_class}">{prem_s}</td>
                <td class="{status_class}">{r.get('status_text', '—')}</td>
                <td>{quota_s}</td>
            </tr>"""

    # 趋势图 series
    chart_series = []
    colors = ["#ef4444","#f97316","#eab308","#22c55e","#3b82f6","#8b5cf6","#ec4899","#14b8a6","#6366f1","#f43f5e"]
    for idx, code in enumerate(top_codes):
        name = names.get(code, code)
        data_points = trend_data.get(code, [])
        chart_series.append({
            "name": name,
            "data": [[d["date"], d["premium"]] for d in data_points],
            "color": colors[idx % len(colors)],
        })

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LOF溢价监控</title>
<script src="https://cdn.jsdelivr.net/npm/highcharts@11/highcharts.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; padding:20px; }}
.header {{ text-align:center; margin-bottom:24px; }}
.header h1 {{ font-size:28px; color:#f8fafc; }}
.header .time {{ color:#94a3b8; margin-top:4px; }}
.stats {{ display:flex; gap:16px; justify-content:center; margin-bottom:24px; flex-wrap:wrap; }}
.stat-card {{ background:#1e293b; border-radius:12px; padding:16px 24px; text-align:center; min-width:140px; }}
.stat-card .value {{ font-size:28px; font-weight:700; }}
.stat-card .label {{ color:#94a3b8; font-size:13px; margin-top:4px; }}
.stat-card .value.red {{ color:#ef4444; }}
.stat-card .value.green {{ color:#22c55e; }}
.stat-card .value.yellow {{ color:#eab308; }}
.chart-container {{ background:#1e293b; border-radius:12px; padding:16px; margin-bottom:24px; }}
table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:12px; overflow:hidden; }}
th {{ background:#334155; padding:12px 8px; text-align:center; font-size:13px; color:#94a3b8; }}
td {{ padding:10px 8px; text-align:center; font-size:14px; border-top:1px solid #334155; }}
tr:hover {{ background:#334155; }}
td small {{ color:#64748b; font-size:11px; }}
.high {{ color:#ef4444; font-weight:700; }}
.positive {{ color:#f87171; }}
.negative {{ color:#4ade80; }}
.open {{ color:#4ade80; }}
.limited {{ color:#fbbf24; }}
.closed {{ color:#f87171; }}
footer {{ text-align:center; color:#64748b; margin-top:24px; font-size:12px; }}
</style>
</head>
<body>
<div class="header">
    <h1>LOF 基金溢价监控</h1>
    <div class="time">更新时间：{update_time}</div>
</div>

<div class="stats">
    <div class="stat-card"><div class="value red">{arb_count}</div><div class="label">预警中(≥{ALERT_THRESHOLD:.0f}%)</div></div>
    <div class="stat-card"><div class="value yellow">{closed_count}</div><div class="label">溢价但暂停申购</div></div>
    <div class="stat-card"><div class="value {'red' if max_prem > 5 else 'yellow'}">{max_prem:+.2f}%</div><div class="label">最高净值溢价率</div></div>
    <div class="stat-card"><div class="value green">{len(latest)}</div><div class="label">监控基金数</div></div>
</div>

<div class="chart-container">
    <div id="trend-chart" style="height:360px;"></div>
</div>

<p style="color:#64748b;font-size:12px;margin-bottom:16px;text-align:center;">
    💡 净值溢价率 = (市价 - 昨收净值) / 昨收净值 × 100% — LOF申购套利核心指标<br>
    昨收净值数据来自天天基金，仅约 60% LOF 可用；无数据时回退到 EST 溢价率
</p>

<table>
<thead>
<tr><th>#</th><th>基金</th><th>现价</th><th>涨跌</th><th>EST</th><th>昨收净值</th><th>净值溢价率</th><th>状态</th><th>限额</th></tr>
</thead>
<tbody>
{table_rows}
</tbody>
</table>

<footer>数据来源：palmmicro + 天天基金 · 自动更新 · 仅供参考，不构成投资建议</footer>

<script>
Highcharts.chart('trend-chart', {{
    chart: {{ backgroundColor: 'transparent', style: {{ color: '#e2e8f0' }} }},
    title: {{ text: '溢价率趋势（近30天 Top10）', style: {{ color: '#e2e8f0' }} }},
    xAxis: {{ type:'category', labels: {{ style:{{ color:'#94a3b8' }}, rotation: -45 }}, tickInterval: 5 }},
    yAxis: {{ title:{{ text:'溢价率(%)', style:{{ color:'#94a3b8' }} }}, labels:{{ style:{{ color:'#94a3b8' }} }},
             plotLines:[{{ value:0, color:'#475569', width:1, dashStyle:'Dash' }}] }},
    legend: {{ itemStyle:{{ color:'#e2e8f0' }} }},
    tooltip: {{ valueSuffix: '%' }},
    series: {json.dumps(chart_series)}
}});
</script>
</body>
</html>"""

    return html


def main():
    if not os.path.exists(DB_PATH):
        print("数据库不存在，跳过看板生成")
        return

    os.makedirs(DOCS_DIR, exist_ok=True)
    latest, history, names = get_dashboard_data()
    if not latest:
        print("无最新数据，跳过看板生成")
        return

    # 数据质量保护：如果所有基金的EST和溢价率都缺失，不覆盖已有看板
    est_all_missing = all(r.get("est") is None for r in latest)
    prem_all_missing = all(r.get("premium") is None for r in latest)
    if est_all_missing and prem_all_missing:
        print("[WARNING] 所有基金的EST和溢价率数据均缺失，跳过看板更新（保留上一版）")
        return

    # 部分缺失时给出警告但仍生成
    est_missing_count = sum(1 for r in latest if r.get("est") is None)
    prem_missing_count = sum(1 for r in latest if r.get("premium") is None)
    if est_missing_count > 0 or prem_missing_count > 0:
        print(f"[WARNING] 部分数据缺失：EST缺失{est_missing_count}只，溢价率缺失{prem_missing_count}只")

    html = generate_html(latest, history, names)
    output_path = os.path.join(DOCS_DIR, "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"看板已生成: {output_path}")


if __name__ == "__main__":
    main()
