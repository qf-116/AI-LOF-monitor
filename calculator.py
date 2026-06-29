"""
LOF溢价监控 - 计算模块
"""

from config import FUNDS, ALERT_THRESHOLD
from db import get_today_alerted


def merge(premium_map, price_map, quota_map, fundgz_map=None):
    """合并多个数据源，计算溢价率，按溢价率降序排列

    Args:
        premium_map: palmmicro数据（主源）
        price_map: 新浪行情数据
        quota_map: 天天基金申购状态数据
        fundgz_map: 天天基金fundgz估算净值数据（备用源，可选）

    当palmmicro某基金est/premium缺失时，尝试用fundgz数据补充。
    """
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
        est_date = e.get("est_date")
        ref_premium = e.get("ref_premium")

        # palmmicro缺失时，尝试用fundgz备用源补充
        if (est is None or premium is None) and fundgz_map:
            fg = fundgz_map.get(full_code, {})
            if est is None and fg.get("est") is not None:
                est = fg["est"]
                if est_date is None:
                    est_date = fg.get("est_date")

        # 如果仍无premium但有price和est，自行计算
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
                "est_date": est_date,
                "ref_premium": ref_premium,
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
