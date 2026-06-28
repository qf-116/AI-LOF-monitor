"""
LOF溢价监控 - 数据库模块（SQLite）
"""

import csv
import os
import sqlite3
from datetime import datetime

from config import DB_PATH


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """创建数据库表（如不存在）"""
    conn = _get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS fund_info (
            full_code TEXT PRIMARY KEY,
            code6     TEXT NOT NULL,
            name      TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS premium_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            full_code    TEXT NOT NULL,
            date         TEXT NOT NULL,
            price        REAL,
            change_pct   REAL,
            est          REAL,
            premium      REAL,
            est_date     TEXT,
            ref_premium  REAL,
            status       TEXT,
            status_text  TEXT,
            quota        REAL,
            UNIQUE(full_code, date)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS alert_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            full_code  TEXT NOT NULL,
            date       TEXT NOT NULL,
            premium    REAL NOT NULL,
            threshold  REAL NOT NULL,
            notified   INTEGER DEFAULT 1,
            UNIQUE(full_code, date)
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_premium_history_code_date
        ON premium_history(full_code, date)
    """)

    conn.commit()
    conn.close()


def upsert_fund_info(funds):
    """批量写入基金基本信息（存在则跳过）"""
    conn = _get_conn()
    c = conn.cursor()
    for full_code, code6, name in funds:
        c.execute(
            "INSERT OR IGNORE INTO fund_info (full_code, code6, name) VALUES (?, ?, ?)",
            (full_code, code6, name),
        )
    conn.commit()
    conn.close()


def save_premium_batch(rows, date_str):
    """批量写入当日溢价数据（存在则更新）"""
    conn = _get_conn()
    c = conn.cursor()
    for r in rows:
        c.execute(
            """INSERT OR REPLACE INTO premium_history
               (full_code, date, price, change_pct, est, premium, est_date, ref_premium, status, status_text, quota)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["full_code"],
                date_str,
                r.get("price"),
                r.get("change"),
                r.get("est"),
                r.get("premium"),
                r.get("est_date"),
                r.get("ref_premium"),
                r.get("status"),
                r.get("status_text"),
                r.get("quota"),
            ),
        )
    conn.commit()
    conn.close()


def save_alert(full_code, date_str, premium, threshold):
    """记录一次预警"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO alert_log (full_code, date, premium, threshold) VALUES (?, ?, ?, ?)",
        (full_code, date_str, premium, threshold),
    )
    conn.commit()
    conn.close()


def get_today_alerted(full_code, date_str=None):
    """查询某基金今日是否已预警"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM alert_log WHERE full_code = ? AND date = ?",
        (full_code, date_str),
    )
    result = c.fetchone() is not None
    conn.close()
    return result


def get_recent_premium(full_code, days=30):
    """查询某基金近N日的溢价率记录"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT date, premium FROM premium_history
           WHERE full_code = ? AND premium IS NOT NULL
           ORDER BY date DESC LIMIT ?""",
        (full_code, days),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def export_history_csv(filepath="history.csv"):
    """导出溢价历史为CSV（兼容GitHub Actions版本）"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT full_code, date, price, change_pct, est, premium,
                  est_date, ref_premium, status, status_text, quota
           FROM premium_history
           ORDER BY date DESC, premium DESC"""
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return

    fieldnames = [
        "full_code", "date", "price", "change_pct", "est", "premium",
        "est_date", "ref_premium", "status", "status_text", "quota",
    ]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
