"""
storage.py - 数据存储模块
功能：
  - SQLite 本地存储（防止重复抓取）
  - 增量更新逻辑
  - 数据查询接口
  - CSV 导出
"""

import os
import sqlite3
import logging
import datetime
from pathlib import Path
from typing import Optional, Dict, List

import pandas as pd
import numpy as np

from config import DB_PATH, OUTPUT_DIR

logger = logging.getLogger(__name__)


def _ensure_dirs():
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path("output/charts").mkdir(parents=True, exist_ok=True)
    Path("output/reports").mkdir(parents=True, exist_ok=True)
    Path("output/csv").mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════
#  DataStorage 类
# ════════════════════════════════════════════════
class DataStorage:

    def __init__(self, db_path: str = DB_PATH):
        _ensure_dirs()
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_tables()
        logger.info(f"数据库初始化完成: {db_path}")

    # ─── 建表 ────────────────────────────────────
    def _init_tables(self):
        sql_list = [
            # A股指数日线
            """CREATE TABLE IF NOT EXISTS index_daily (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                symbol    TEXT NOT NULL,
                name      TEXT,
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL,
                volume    REAL,
                amount    REAL,
                pct_chg   REAL,
                turnover  REAL,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, symbol)
            )""",

            # 指数估值 PE/PB
            """CREATE TABLE IF NOT EXISTS index_valuation (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                name      TEXT,
                symbol    TEXT,
                pe        REAL,
                pe_pct    REAL,
                pb        REAL,
                pb_pct    REAL,
                market_cap REAL,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, symbol)
            )""",

            # ETF日线
            """CREATE TABLE IF NOT EXISTS etf_daily (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                code      TEXT NOT NULL,
                name      TEXT,
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL,
                volume    REAL,
                amount    REAL,
                pct_chg   REAL,
                net_inflow REAL,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, code)
            )""",

            # 行业板块
            """CREATE TABLE IF NOT EXISTS industry_perf (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                industry  TEXT NOT NULL,
                pct_chg   REAL,
                amount    REAL,
                pe        REAL,
                pb        REAL,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, industry)
            )""",

            # 海外市场
            """CREATE TABLE IF NOT EXISTS global_indices (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                symbol    TEXT NOT NULL,
                name      TEXT,
                close     REAL,
                pct_chg   REAL,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, symbol)
            )""",

            # 商品期货/指数
            """CREATE TABLE IF NOT EXISTS commodity (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                code      TEXT NOT NULL,
                name      TEXT,
                sector    TEXT,
                close     REAL,
                pct_chg   REAL,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, code)
            )""",

            # 市场情绪
            """CREATE TABLE IF NOT EXISTS market_sentiment (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                metric    TEXT NOT NULL,
                value     REAL,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, metric)
            )""",

            # 宏观高频
            """CREATE TABLE IF NOT EXISTS macro_hf (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                indicator TEXT NOT NULL,
                value     REAL,
                unit      TEXT,
                updated   TEXT DEFAULT (datetime('now')),
                UNIQUE(date, indicator)
            )""",
        ]
        c = self.conn.cursor()
        for sql in sql_list:
            c.execute(sql)
        self.conn.commit()

    # ─── 存储 ────────────────────────────────────
    def save_index_daily(self, data: Dict[str, pd.DataFrame]):
        """保存A股指数日线数据"""
        rows = 0
        c = self.conn.cursor()
        for sym, df in data.items():
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    c.execute("""
                        INSERT OR REPLACE INTO index_daily
                        (date, symbol, name, open, high, low, close, volume, amount, pct_chg, turnover)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        str(row.get("date", ""))[:10],
                        row.get("symbol", sym),
                        row.get("name", ""),
                        _safe_float(row.get("open")),
                        _safe_float(row.get("high")),
                        _safe_float(row.get("low")),
                        _safe_float(row.get("close")),
                        _safe_float(row.get("volume")),
                        _safe_float(row.get("amount")),
                        _safe_float(row.get("pct_chg")),
                        _safe_float(row.get("turnover")),
                    ))
                    rows += 1
                except Exception as e:
                    logger.debug(f"insert index_daily error: {e}")
        self.conn.commit()
        logger.info(f"  保存 index_daily: {rows} 行")

    def save_etf_daily(self, data: Dict[str, pd.DataFrame]):
        """保存ETF日线"""
        rows = 0
        c = self.conn.cursor()
        for code, df in data.items():
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    date_val = str(row.get("日期", row.get("date", "")))[:10]
                    c.execute("""
                        INSERT OR REPLACE INTO etf_daily
                        (date, code, name, open, high, low, close, volume, amount, pct_chg)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                    """, (
                        date_val,
                        row.get("code", code),
                        row.get("name", ""),
                        _safe_float(row.get("开盘", row.get("open"))),
                        _safe_float(row.get("最高", row.get("high"))),
                        _safe_float(row.get("最低", row.get("low"))),
                        _safe_float(row.get("收盘", row.get("close"))),
                        _safe_float(row.get("成交量", row.get("volume"))),
                        _safe_float(row.get("成交额", row.get("amount"))),
                        _safe_float(row.get("涨跌幅", row.get("pct_chg"))),
                    ))
                    rows += 1
                except Exception as e:
                    logger.debug(f"insert etf_daily error: {e}")
        self.conn.commit()
        logger.info(f"  保存 etf_daily: {rows} 行")

    def save_industry_perf(self, df: Optional[pd.DataFrame]):
        """保存行业数据"""
        if df is None or df.empty:
            return
        today = datetime.date.today().strftime("%Y-%m-%d")
        c = self.conn.cursor()
        rows = 0
        col_map = {
            "板块名称": "industry",
            "涨跌幅":   "pct_chg",
            "成交额":   "amount",
        }
        for _, row in df.iterrows():
            try:
                industry = str(row.get("板块名称", row.get("name", "")))
                pct = _safe_float(row.get("涨跌幅", row.get("pct_chg")))
                amt = _safe_float(row.get("成交额", row.get("amount")))
                c.execute("""
                    INSERT OR REPLACE INTO industry_perf (date, industry, pct_chg, amount)
                    VALUES (?,?,?,?)
                """, (today, industry, pct, amt))
                rows += 1
            except Exception as e:
                logger.debug(f"insert industry_perf error: {e}")
        self.conn.commit()
        logger.info(f"  保存 industry_perf: {rows} 行")

    def save_global_indices(self, data: Dict[str, pd.DataFrame]):
        """保存海外市场"""
        c = self.conn.cursor()
        rows = 0
        for sym, df in data.items():
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    date_val = str(row.get("日期", row.get("date", "")))[:10]
                    c.execute("""
                        INSERT OR REPLACE INTO global_indices (date, symbol, name, close, pct_chg)
                        VALUES (?,?,?,?,?)
                    """, (
                        date_val, sym,
                        row.get("name", sym),
                        _safe_float(row.get("收盘", row.get("close"))),
                        _safe_float(row.get("涨跌幅", row.get("pct_chg"))),
                    ))
                    rows += 1
                except Exception as e:
                    logger.debug(f"insert global_indices error: {e}")
        self.conn.commit()
        logger.info(f"  保存 global_indices: {rows} 行")

    def save_commodity(self, data: Dict[str, pd.DataFrame]):
        """保存商品期货"""
        c = self.conn.cursor()
        rows = 0
        for code, df in data.items():
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    date_val = str(row.get("date", row.get("日期", "")))[:10]
                    c.execute("""
                        INSERT OR REPLACE INTO commodity (date, code, name, sector, close, pct_chg)
                        VALUES (?,?,?,?,?,?)
                    """, (
                        date_val, code,
                        row.get("name", code),
                        row.get("sector", ""),
                        _safe_float(row.get("close", row.get("收盘"))),
                        _safe_float(row.get("pct_chg", row.get("涨跌幅"))),
                    ))
                    rows += 1
                except Exception as e:
                    logger.debug(f"insert commodity error: {e}")
        self.conn.commit()
        logger.info(f"  保存 commodity: {rows} 行")

    def save_sentiment(self, data: dict):
        """保存市场情绪数据"""
        c = self.conn.cursor()
        today = datetime.date.today().strftime("%Y-%m-%d")

        for key, df in data.items():
            if df is None or df.empty:
                continue
            # 取最新一行
            try:
                latest = df.iloc[-1]
                for col in df.columns:
                    val = _safe_float(latest.get(col))
                    if val is not None:
                        metric = f"{key}_{col}"
                        c.execute("""
                            INSERT OR REPLACE INTO market_sentiment (date, metric, value)
                            VALUES (?,?,?)
                        """, (today, metric, val))
            except Exception as e:
                logger.debug(f"save_sentiment {key} error: {e}")
        self.conn.commit()

    def save_all(self, data: dict):
        """统一保存全部抓取数据"""
        logger.info("开始写入数据库...")
        if data.get("index_daily"):
            self.save_index_daily(data["index_daily"])
        if data.get("etf_flows"):
            self.save_etf_daily(data["etf_flows"])
        if data.get("industry_perf") is not None:
            self.save_industry_perf(data["industry_perf"])
        if data.get("global_indices"):
            self.save_global_indices(data["global_indices"])
        if data.get("nanhua"):
            self.save_commodity(data["nanhua"])
        if data.get("sentiment"):
            self.save_sentiment(data["sentiment"])
        logger.info("数据库写入完成。")

    # ─── 查询 ────────────────────────────────────
    def query_index_daily(
        self,
        symbol: str,
        start_date: str = None,
        end_date: str = None,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM index_daily WHERE symbol = ?"
        params = [symbol]
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        sql += " ORDER BY date"
        return pd.read_sql_query(sql, self.conn, params=params)

    def query_latest_industry(self) -> pd.DataFrame:
        today = datetime.date.today().strftime("%Y-%m-%d")
        df = pd.read_sql_query(
            "SELECT * FROM industry_perf WHERE date = ? ORDER BY pct_chg DESC",
            self.conn, params=[today]
        )
        if df.empty:
            df = pd.read_sql_query(
                "SELECT * FROM industry_perf WHERE date = (SELECT MAX(date) FROM industry_perf) ORDER BY pct_chg DESC",
                self.conn
            )
        return df

    def query_recent_etf(self, code: str, days: int = 30) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM etf_daily WHERE code = ? ORDER BY date DESC LIMIT ?",
            self.conn, params=[code, days]
        )

    def get_last_update(self, table: str) -> Optional[str]:
        try:
            row = self.conn.execute(
                f"SELECT MAX(updated) FROM {table}"
            ).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    # ─── 导出 CSV ────────────────────────────────
    def export_csv(self, table: str):
        df = pd.read_sql_query(f"SELECT * FROM {table}", self.conn)
        path = f"output/csv/{table}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info(f"  导出 {path}")

    def export_all_csv(self):
        tables = ["index_daily", "etf_daily", "industry_perf",
                  "global_indices", "commodity", "market_sentiment"]
        for t in tables:
            try:
                self.export_csv(t)
            except Exception as e:
                logger.warning(f"export_csv {t} 失败: {e}")

    def close(self):
        self.conn.close()


# ─── 辅助 ────────────────────────────────────────
def _safe_float(v) -> Optional[float]:
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
