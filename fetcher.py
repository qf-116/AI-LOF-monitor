"""
LOF溢价监控 - 数据获取模块
数据源：palmmicro（EST估值+溢价率）、新浪财经（实时行情）、天天基金（申购状态）
"""

import re
import time
import requests

from config import FUNDS, HEADERS


def fetch_premium():
    """从palmmicro获取所有基金的EST数据（官方EST、EST日期、官方溢价、参考EST溢价）

    最多重试3次（间隔3/6/9秒），防止GitHub Actions环境偶发网络失败
    """
    url = "https://palmmicro.com/woody/res/lofcn.php?sort=premium"
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"获取溢价率（主列表页）...{f' (第{attempt}次重试)' if attempt > 1 else ''}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.encoding = "utf-8"
            html = r.text

            m = re.search(r'id="estimationtable".*?<tbody>(.*?)</tbody>', html, re.S)
            if not m:
                print("  未找到 estimationtable")
                if attempt < max_retries:
                    time.sleep(attempt * 3)
                    continue
                return {}

            tbody = m.group(1)
            result = {}

            for row_m in re.finditer(r'<tr>(.*?)</tr>', tbody, re.S):
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row_m.group(1), re.S)
                if len(cells) < 6:
                    continue

                code_m = re.search(r'>(S[HZ]\d{6})<', cells[0])
                if not code_m:
                    continue
                full_code = code_m.group(1)

                est_m = re.search(r'>([\d.]+)<', cells[1])
                est = float(est_m.group(1)) if est_m else None

                date_m = re.search(r'(\d{4}-\d{2}-\d{2})', cells[2])
                est_date = date_m.group(1) if date_m else None

                prem_m = re.search(r'>([-\d.]+)', cells[3])
                premium = float(prem_m.group(1)) if prem_m else None

                ref_premium = None
                if cells[5].strip():
                    ref_m = re.search(r'>([-\d.]+)', cells[5])
                    ref_premium = float(ref_m.group(1)) if ref_m else None

                result[full_code] = {
                    "est": est,
                    "est_date": est_date,
                    "premium": premium,
                    "ref_premium": ref_premium,
                }

            print(f"  完成：{len(result)} 只")
            return result
        except Exception as e:
            print(f"  溢价获取失败 (第{attempt}次): {e}")
            if attempt < max_retries:
                time.sleep(attempt * 3)
    print(f"  溢价获取最终失败，已重试{max_retries}次")
    return {}


def fetch_prices():
    """从新浪财经获取LOF实时场内行情"""
    print("获取实时行情...")
    codes = ",".join(
        ("sh" if f[0].startswith("SH") else "sz") + f[1] for f in FUNDS
    )
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={codes}",
            headers={**HEADERS, "Referer": "https://finance.sina.com.cn"},
            timeout=15,
        )
        r.encoding = "gbk"
        result = {}
        for line in r.text.splitlines():
            m = re.match(r'var hq_str_(s[hz])(\d{6})="([^"]+)"', line)
            if not m:
                continue
            full_code = m.group(1).upper() + m.group(2)
            parts = m.group(3).split(",")
            if len(parts) < 4:
                continue
            try:
                price = float(parts[3])
                prev = float(parts[2]) if parts[2] else 0
                change = round((price - prev) / prev * 100, 2) if prev else 0
                result[full_code] = {"price": price, "change": change}
            except (ValueError, ZeroDivisionError):
                pass
        print(f"  完成：{len(result)} 只")
        return result
    except Exception as e:
        print(f"  行情获取失败: {e}")
        return {}


def _parse_money_str(s):
    s = s.replace(",", "").strip()
    m = re.match(r'([\d.]+)\s*万元?', s)
    if m:
        return float(m.group(1)) * 10000
    m = re.match(r'([\d.]+)\s*亿元?', s)
    if m:
        return float(m.group(1)) * 1e8
    m = re.match(r'([\d.]+)\s*元?', s)
    if m:
        return float(m.group(1))
    return None


def _fetch_quota_batch(codes6_batch):
    fcodes = ",".join(codes6_batch)
    url = (
        f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
        f"?pageIndex=1&pageSize={len(codes6_batch)}&plat=Android"
        f"&appType=ttjj&product=EFund&Version=1&Fcodes={fcodes}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        data = r.json()
        if not data.get("Datas"):
            return {}
        result = {}
        for item in data["Datas"]:
            code = item.get("FCODE", "")
            sgzt = str(item.get("SGZT", "0"))
            sgsxe = float(item.get("SGSXE") or 0)
            sgba = float(item.get("SGBA") or 0)
            if sgzt == "1":
                status, status_text = "closed", "暂停申购"
            elif sgzt == "3":
                status, status_text = "closed", "封闭期"
            elif sgzt == "2":
                status, status_text = "limited", "限制大额"
            elif sgsxe > 0:
                status, status_text = "limited", "限额申购"
            else:
                status, status_text = "open", "正常申购"
            result[code] = {
                "status": status,
                "status_text": status_text,
                "quota": sgsxe if sgsxe > 0 else None,
                "big_quota": sgba if sgba > 0 else None,
            }
        return result
    except Exception:
        return {}


def _fetch_quota_page(code6):
    try:
        r = requests.get(
            f"https://fund.eastmoney.com/{code6}.html",
            headers=HEADERS,
            timeout=10,
        )
        r.encoding = "utf-8"
        html = r.text
        raw_cells = re.findall(
            r'class="staticCell"[^>]*>(.*?)</span>\s*(?=<span|<div|$)', html, re.S
        )
        cells = [re.sub(r"<[^>]+>", "", c) for c in raw_cells]
        cell_text = " ".join(c.strip() for c in cells)
        status, status_text, quota = "unknown", "未知", None
        if "暂停申购" in cell_text or "暂停大额" in cell_text:
            status, status_text = "closed", "暂停申购"
        elif "封闭期" in cell_text:
            status, status_text = "closed", "封闭期"
        elif "限大额" in cell_text or "限制大额" in cell_text:
            status, status_text = "limited", "限制大额"
        elif "开放申购" in cell_text or "正常申购" in cell_text:
            status, status_text = "open", "正常申购"
        for target in [cell_text, html]:
            for pat in [
                r"单日累计购买上限\s*([\d.,]+\s*[万亿]?元?)",
                r"单笔限购[：:]\s*([\d.,]+\s*[万亿]?元?)",
                r"每日累计限购[：:]\s*([\d.,]+\s*[万亿]?元?)",
            ]:
                m = re.search(pat, target)
                if m:
                    quota = _parse_money_str(m.group(1))
                    break
            if quota:
                break
        if quota and status not in ("closed",):
            status = "limited"
            status_text = "限制大额" if "限大额" in cell_text else "限额申购"
        return {
            "status": status,
            "status_text": status_text,
            "quota": quota,
            "big_quota": None,
        }
    except Exception as e:
        print(f"  网页抓取失败 {code6}: {e}")
        return {
            "status": "error",
            "status_text": "查询失败",
            "quota": None,
            "big_quota": None,
        }


def fetch_premium_fundgz():
    """从天天基金fundgz获取估算净值(GSZ)作为palmmicro的备用数据源

    覆盖约20/35只基金（A股、港股相关），QDII海外基金通常无数据
    返回格式与fetch_premium()一致: {full_code: {est, est_date, premium, ref_premium}}
    """
    import json as _json

    print("获取fundgz估算净值（备用源）...")
    from config import FUNDS

    result = {}
    for full_code, code6, _name in FUNDS:
        url = f"https://fundgz.1234567.com.cn/js/{code6}.js"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = "utf-8"
            m = re.match(r"jsonpgz\((.*)\);", r.text)
            if not m or not m.group(1).strip():
                continue
            data = _json.loads(m.group(1))
            gsz = data.get("gsz")
            if not gsz:
                continue
            est_date = data.get("gztime", "")[:10]  # "2026-06-29 15:00" → "2026-06-29"
            result[full_code] = {
                "est": float(gsz),
                "est_date": est_date if est_date else None,
                "premium": None,  # 需要结合price在merge()中计算
                "ref_premium": None,
            }
        except Exception:
            pass
        time.sleep(0.1)

    print(f"  完成：{len(result)} 只（fundgz备用源）")
    return result


def fetch_nav_data():
    """从天天基金fundgz获取昨收净值(DWJZ)和估算净值(GSZ)

    用于计算 DWJZ 溢价率（LOF套利的关键指标）：
    dwjz_premium = (市价 - DWJZ) / DWJZ * 100

    返回: {full_code: {dwjz, gsz, gszzl, gztime}}
    """
    import json as _json

    print("获取昨收净值(DWJZ)...")
    from config import FUNDS

    result = {}
    for full_code, code6, _name in FUNDS:
        url = f"https://fundgz.1234567.com.cn/js/{code6}.js"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = "utf-8"
            m = re.match(r"jsonpgz\((.*)\);", r.text)
            if not m or not m.group(1).strip():
                continue
            data = _json.loads(m.group(1))
            dwjz = data.get("dwjz")
            if not dwjz:
                continue
            result[full_code] = {
                "dwjz": float(dwjz),
                "gsz": float(data["gsz"]) if data.get("gsz") else None,
                "gszzl": data.get("gszzl"),
                "gztime": data.get("gztime"),
            }
        except Exception:
            pass
        time.sleep(0.1)

    print(f"  完成：{len(result)} 只（昨收净值）")
    return result


def fetch_quota():
    """获取所监控基金的申购状态和限额"""
    print("获取限购状态...")
    all_codes = [f[1] for f in FUNDS]
    result = {}
    for i in range(0, len(all_codes), 20):
        result.update(_fetch_quota_batch(all_codes[i : i + 20]))
        time.sleep(0.5)
    failed = [f[1] for f in FUNDS if f[1] not in result]
    if failed:
        print(f"  App API 未返回 {len(failed)} 只，改用网页...")
        for code6 in failed:
            result[code6] = _fetch_quota_page(code6)
            time.sleep(0.3)
    print("  完成")
    return result
