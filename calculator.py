"""
LOF溢价监控 - 计算模块
"""

from config import FUNDS, ALERT_THRESHOLD
from db import get_today_alerted


def merge(premium_map, price_map, quota_map, fundgz_map=None, nav_map=None):
    """合并多个数据源，计算溢价率，按溢价率降序排列

    Args:
        premium_map: palmmicro数据（主源）— EST估值 + EST溢价
        price_map: 新浪行情数据 — 市场价 + 涨跌幅
        quota_map: 天天基金申购状态数据 — 状态 + 限额
        fundgz_map: 天天基金fundgz估算净值（备用源，可选）
        nav_map: 天天基金昨收净值（用于DWJZ溢价率计算）

    溢价率有两种：
    - premium (EST溢价): (市价 - EST) / EST * 100  — 反映估值偏差
    - dwjz_premium (净值溢价): (市价 - DWJZ) / DWJZ * 100  — 反映申购套利空间
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

        # DWJZ 溢价率：使用昨收净值（每日确认净值），用于申购套利判断
        dwjz = nav_map.get(full_code, {}).get("dwjz") if nav_map else None
        dwjz_premium = None
        if dwjz and price:
            dwjz_premium = round((price - dwjz) / dwjz * 100, 2)

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
                "dwjz": dwjz,
                "dwjz_premium": dwjz_premium,
                "status": q["status"],
                "status_text": q["status_text"],
                "quota": q["quota"],
                "big_quota": q.get("big_quota"),
            }
        )
    # 默认按 DWJZ 溢价率排序（套利视角），如果没有 DWJZ 则回退到 EST 溢价率
    rows.sort(key=lambda x: (x["dwjz_premium"] if x["dwjz_premium"] is not None else (x["premium"] or -999)), reverse=True)
    return rows


def check_alerts(rows, threshold=ALERT_THRESHOLD, date_str=None):
    """筛选溢价率超阈值且今日未推送的基金（仅正溢价且可申购的）

    优先使用 DWJZ 溢价率（更准确的套利指标），无 DWJZ 时回退到 EST 溢价率
    """
    alert_rows = []
    for r in rows:
        # 优先使用 DWJZ 溢价率
        prem = r.get("dwjz_premium")
        if prem is None:
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
