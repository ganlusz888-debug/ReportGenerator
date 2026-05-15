"""
港股及海外市场数据抓取
覆盖：恒生指数/科技/国企、美欧日韩市场、南向资金
"""
import time
import logging
from typing import Dict, Optional

import pandas as pd
import numpy as np
import akshare as ak

from config import GLOBAL_INDICES, REPORT_DATE
from utils import cached, retry, logger, last_n_trading_days, safe_float


class GlobalMarketFetcher:
    """港股及海外市场数据抓取器"""

    # ── 1. 港股主要指数 ───────────────────────────────────
    @cached(prefix="global")
    @retry()
    def fetch_hk_indices(self) -> pd.DataFrame:
        """
        恒生指数、恒生科技、恒生国企行情及PE/PB
        """
        hk_map = {
            "恒生指数":  {"em_code": "HSI",    "sina_code": "hkHSI"},
            "恒生科技":  {"em_code": "HSTECH", "sina_code": "hkHTECH"},
            "恒生国企":  {"em_code": "HSCEI",  "sina_code": "hkHSCEI"},
        }
        records = []
        for name, codes in hk_map.items():
            time.sleep(0.8)
            try:
                hist = self._get_hk_index_hist(codes)
                row = {"证券简称": name}
                if hist is not None and len(hist) > 1:
                    hist = hist.sort_values("日期")
                    row["本周涨跌幅%"]  = self._pct_chg(hist, 5)
                    row["上周涨跌幅%"]  = self._prev_week_ret(hist)
                    row["近一月涨跌幅%"] = self._pct_chg(hist, 22)
                    row["近三月涨跌幅%"] = self._pct_chg(hist, 66)
                    row["近半年涨跌幅%"] = self._pct_chg(hist, 132)
                    row["今年以来涨跌幅%"] = self._ytd_ret(hist)
                records.append(row)
            except Exception as e:
                logger.warning(f"港股指数{name}失败: {e}")

        # 港股行业指数
        try:
            df_hk_ind = ak.stock_hk_index_spot_sina()
            if df_hk_ind is not None:
                logger.info(f"港股行业指数: {len(df_hk_ind)}条")
        except Exception:
            pass

        return pd.DataFrame(records)

    def _get_hk_index_hist(self, codes: dict) -> Optional[pd.DataFrame]:
        for source, code in [("em", codes.get("em_code")),
                              ("sina", codes.get("sina_code"))]:
            if not code:
                continue
            try:
                if source == "em":
                    df = ak.stock_hk_index_daily_em(symbol=code)
                    df = df.rename(columns={"date": "日期", "close": "收盘",
                                            "open": "开盘"})
                else:
                    df = ak.index_investing_global(symbol=code)
                    df = df.rename(columns={"日期": "日期", "收盘": "收盘"})
                df["日期"] = pd.to_datetime(df["日期"])
                df = df[df["日期"] >= pd.to_datetime(last_n_trading_days(400))]
                return df
            except Exception:
                continue
        return None

    # ── 2. 海外主要指数 ───────────────────────────────────
    @cached(prefix="global")
    @retry()
    def fetch_global_indices(self) -> pd.DataFrame:
        """
        美欧日韩及亚太主要股指涨跌幅
        """
        global_map = {
            "道琼斯工业指数": "DJI",
            "纳斯达克指数":  "IXIC",
            "标普500":      "SPX",
            "德国DAX":      "GDAXI",
            "法国CAC40":    "FCHI",
            "英国富时100":  "FTSE",
            "日经225":      "N225",
            "韩国综合指数":  "KS11",
            "印度SENSEX30":  "SENSEX",
        }
        records = []
        for name, code in global_map.items():
            time.sleep(0.8)
            try:
                # 优先用东方财富全球指数
                df = ak.stock_us_index_daily_em(symbol=code)
                if df is None or len(df) == 0:
                    raise ValueError("无数据")
                df.rename(columns={"date": "日期", "close": "收盘"}, inplace=True)
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期")
                row = {
                    "地区/国家": self._get_region(name),
                    "证券简称":  name,
                    "本周涨跌幅%":   self._pct_chg(df, 5),
                    "上周涨跌幅%":   self._prev_week_ret(df),
                    "近一月涨跌幅%":  self._pct_chg(df, 22),
                    "近三月涨跌幅%":  self._pct_chg(df, 66),
                    "近半年涨跌幅%":  self._pct_chg(df, 132),
                    "今年以来涨跌幅%": self._ytd_ret(df),
                }
                records.append(row)
            except Exception as e:
                logger.debug(f"全球指数{name}失败: {e}")
                records.append({"证券简称": name, "地区/国家": self._get_region(name)})

        # 备用：investing.com
        if len(records) < 3:
            records = self._fetch_global_from_investing(global_map, records)

        return pd.DataFrame(records)

    def _fetch_global_from_investing(self, global_map: dict, records: list) -> list:
        existing = {r["证券简称"] for r in records if "本周涨跌幅%" in r}
        for name, code in global_map.items():
            if name in existing:
                continue
            time.sleep(1.0)
            try:
                df = ak.index_investing_global(symbol=code,
                                               start_date=last_n_trading_days(400),
                                               end_date=REPORT_DATE)
                if df is None or len(df) == 0:
                    continue
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期")
                records.append({
                    "地区/国家": self._get_region(name),
                    "证券简称":  name,
                    "本周涨跌幅%":   self._pct_chg(df, 5),
                    "上周涨跌幅%":   self._prev_week_ret(df),
                    "近一月涨跌幅%":  self._pct_chg(df, 22),
                    "近三月涨跌幅%":  self._pct_chg(df, 66),
                    "近半年涨跌幅%":  self._pct_chg(df, 132),
                    "今年以来涨跌幅%": self._ytd_ret(df),
                })
            except Exception:
                pass
        return records

    def _get_region(self, name: str) -> str:
        if "恒生" in name or "国企" in name:
            return "香港"
        if "道琼" in name or "纳斯达克" in name or "标普" in name:
            return "美国"
        if "日经" in name:
            return "日本"
        if "韩国" in name:
            return "韩国"
        if "印度" in name:
            return "印度"
        if "DAX" in name or "CAC" in name or "富时" in name:
            return "欧洲"
        return "亚太"

    # ── 3. 南向资金 ───────────────────────────────────────
    @cached(prefix="global")
    @retry()
    def fetch_southbound_flow(self, days: int = 60) -> pd.DataFrame:
        """
        港股通南向资金日度净流入（亿元人民币）
        """
        try:
            # 港股通资金流向
            df = ak.stock_connect_position_em(symbol="港股通沪")
            if df is not None and len(df) > 0:
                return df
        except Exception:
            pass
        try:
            df = ak.stock_hk_connect_put_in_hist_em(symbol="港股通",
                                                    start_date=last_n_trading_days(days),
                                                    end_date=REPORT_DATE)
            return df
        except Exception:
            pass
        try:
            # 备用：从东方财富获取南向资金
            df = ak.stock_southward_flow_na()
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.sort_values("日期").tail(days)
            return df
        except Exception as e:
            logger.warning(f"南向资金数据失败: {e}")
            return pd.DataFrame()

    # ── 汇总 ──────────────────────────────────────────────
    def fetch_all(self) -> Dict[str, pd.DataFrame]:
        logger.info("开始抓取港股及全球市场数据")
        return {
            "hk_indices":       self.fetch_hk_indices(),
            "global_indices":   self.fetch_global_indices(),
            "southbound_flow":  self.fetch_southbound_flow(),
        }

    # ── 辅助方法 ──────────────────────────────────────────
    def _pct_chg(self, df: pd.DataFrame, days: int) -> Optional[float]:
        col = "收盘" if "收盘" in df.columns else ("close" if "close" in df.columns else None)
        if col is None or len(df) < 2:
            return None
        if len(df) > days:
            base = df[col].iloc[-(days + 1)]
            last = df[col].iloc[-1]
        else:
            base, last = df[col].iloc[0], df[col].iloc[-1]
        return (last / base - 1) * 100 if base else None

    def _prev_week_ret(self, df: pd.DataFrame) -> Optional[float]:
        col = "收盘" if "收盘" in df.columns else ("close" if "close" in df.columns else None)
        if col is None or len(df) < 11:
            return None
        return (df[col].iloc[-6] / df[col].iloc[-11] - 1) * 100

    def _ytd_ret(self, df: pd.DataFrame) -> Optional[float]:
        from datetime import datetime
        col = "收盘" if "收盘" in df.columns else ("close" if "close" in df.columns else None)
        if col is None:
            return None
        year_start = f"{datetime.now().year}-01-01"
        sub = df[df["日期"] >= pd.to_datetime(year_start)]
        if len(sub) < 2:
            return None
        return (sub[col].iloc[-1] / sub[col].iloc[0] - 1) * 100
