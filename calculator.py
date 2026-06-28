"""
LOF溢价监控 - 计算模块
"""

from config import FUNDS, ALERT_THRESHOLD
from db import get_today_alerted


def merge(premium_map, price_map, quota_map):
    """合并三个数据源，计算溢价率，按溢价率降序排列"""
    rows = []
    for full_code, code6, name in FUNDS:
        p = price_map.get(full_code, {})
        e = premium_map.get(full_code, {})
        q = quota_map.get(
            code6,
            {
                "status": "error",
                "status_text": "查询失败",
                "quota": None,
                "big_quota": None,
            },
        )
        price = p.get("price")
        change = p.get("change")
        est = e.get("est")
        premium = e.get("premium")
        if premium is None and price and est:
            premium = round((price - est) / est * 100, 2)
        rows.append(
            {
                "full_code": full_code,
                "code6": code6,
                "name": name,
                "price": price,
                "change": change,
                "est": est,
                "premium": premium,
                "est_date": e.get("est_date"),
                "ref_premium": e.get("ref_premium"),
                "status": q["status"],
                "status_text": q["status_text"],
                "quota": q["quota"],
                "big_quota": q.get("big_quota"),
            }
        )
    rows.sort(key=lambda x: (x["premium"] or -999), reverse=True)
    return rows


def check_alerts(rows, threshold=ALERT_THRESHOLD, date_str=None):
    """筛选溢价率超阈值且今日未推送的基金（仅正溢价且可申购的）"""
    alert_rows = []
    for r in rows:
        prem = r.get("premium")
        if prem is None or prem <= threshold:
            continue
        # 仅对可申购的基金预警（正溢价+可申购=套利机会）
        if r["status"] not in ("open", "limited"):
            continue
        if get_today_alerted(r["full_code"], date_str):
            continue
        alert_rows.append(r)
    return alert_rows
