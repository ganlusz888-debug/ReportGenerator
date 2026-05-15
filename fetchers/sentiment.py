"""
市场情绪数据抓取模块
覆盖：首板/连板成交、涨跌家数、成交量、融资余额、先导指数
"""
import time
from typing import Dict, Optional

import pandas as pd
import numpy as np
import akshare as ak

from config import REPORT_DATE, COMMODITY_CATEGORIES
from utils import cached, retry, logger, last_n_trading_days


# 先导指数中的18个期货品种（与报告一致）
LEADING_INDEX_FUTURES = [
    "RB", "I",  "CU", "AL", "ZN",   # 工业金属
    "AU", "AG",                       # 贵金属
    "SC", "FU",                       # 能源
    "A",  "C",  "SR", "CF",          # 农产品
    "TA", "PP", "L",                  # 化工
    "J",  "JM",                       # 黑色
]


class SentimentFetcher:
    """市场情绪数据抓取器"""

    # ── 1. 中国经济基本面先导指数（复现）────────────────────
    @cached(prefix="sentiment")
    @retry()
    def fetch_leading_index(self, start: str = None) -> pd.DataFrame:
        """
        复现报告中的"中国经济基本面先导指数"
        思路：抓取18个强经济相关期货品种的价格，做等权综合
        再计算250日移动平均线
        """
        start = start or last_n_trading_days(700)
        all_series = {}
        for sym in LEADING_INDEX_FUTURES:
            time.sleep(0.5)
            try:
                df = ak.futures_main_sina(symbol=sym.lower(), start_date=start)
                if df is None or len(df) == 0:
                    continue
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")["close"].rename(sym)
                all_series[sym] = df
            except Exception as e:
                logger.debug(f"期货{sym}先导指数失败: {e}")

        if not all_series:
            return pd.DataFrame()

        # 合并 → 标准化 → 等权加总
        combined = pd.DataFrame(all_series).dropna(how="all")
        combined = combined.fillna(method="ffill")

        # Z-score标准化到基准值
        normalized = combined.apply(lambda s: (s / s.iloc[0]) * 1000, axis=0)
        leading = normalized.mean(axis=1).rename("先导指数")

        # 250日移动平均
        ma250 = leading.rolling(250, min_periods=1).mean().rename("250日均线")

        # 60日均线（辅助）
        ma60 = leading.rolling(60, min_periods=1).mean().rename("60日均线")

        result = pd.concat([leading, ma250, ma60], axis=1)
        result.index.name = "日期"
        result = result.reset_index()
        result["日期"] = pd.to_datetime(result["日期"])
        return result

    # ── 2. A股成交量 ──────────────────────────────────────
    @cached(prefix="sentiment")
    @retry()
    def fetch_market_volume(self, days: int = 250) -> pd.DataFrame:
        """
        A股总成交额（万得全A成交量）
        """
        try:
            df = ak.stock_zh_a_hist(symbol="000001", period="daily",
                                    start_date=last_n_trading_days(days),
                                    end_date=REPORT_DATE, adjust="")
            # 这只是上证指数的成交，需要获取全市场
            # 用万得全A代替
            df = ak.index_zh_a_hist(symbol="881001", period="daily",
                                    start_date=last_n_trading_days(days),
                                    end_date=REPORT_DATE)
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                df["成交额(亿元)"] = df["成交额"] / 1e8
                return df[["日期", "收盘", "成交额(亿元)"]].sort_values("日期")
        except Exception as e:
            logger.warning(f"市场成交量失败: {e}")
            return pd.DataFrame()

    # ── 3. 涨跌家数 ───────────────────────────────────────
    @cached(prefix="sentiment")
    @retry()
    def fetch_advance_decline(self) -> pd.DataFrame:
        """
        万得全A上涨/下跌数量（近期）
        """
        try:
            df = ak.stock_market_activity_lgu()
            if df is not None and len(df) > 0:
                logger.info(f"涨跌家数: {len(df)}条")
                return df
        except Exception as e:
            logger.warning(f"涨跌家数失败: {e}")

        try:
            # 备用：每日涨跌统计
            df = ak.stock_advance_decline_em(date=REPORT_DATE)
            return df
        except Exception as e:
            logger.warning(f"涨跌家数备用失败: {e}")
            return pd.DataFrame()

    # ── 4. 首板/连板成交 ─────────────────────────────────
    @cached(prefix="sentiment")
    @retry()
    def fetch_limit_up_stats(self) -> pd.DataFrame:
        """
        每日首板/连板成交金额
        """
        try:
            df = ak.stock_zt_pool_em(date=REPORT_DATE.replace("-", ""))
            if df is not None and len(df) > 0:
                logger.info(f"涨停板数据: {len(df)}条")
                return df
        except Exception as e:
            logger.warning(f"涨停板数据失败: {e}")

        try:
            df = ak.stock_zt_pool_strong_em(date=REPORT_DATE.replace("-", ""))
            return df
        except Exception as e:
            return pd.DataFrame()

    # ── 5. 融资余额历史 ───────────────────────────────────
    @cached(prefix="sentiment")
    @retry()
    def fetch_margin_history(self, days: int = 250) -> pd.DataFrame:
        """
        A股融资融券余额历史
        """
        try:
            df = ak.stock_margin_sse(start_date=last_n_trading_days(days),
                                     end_date=REPORT_DATE)
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期")
                return df
        except Exception as e:
            logger.warning(f"融资余额(上交所)失败: {e}")

        try:
            df = ak.stock_margin_szse(start_date=last_n_trading_days(days),
                                      end_date=REPORT_DATE)
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期")
                return df
        except Exception as e:
            logger.warning(f"融资余额(深交所)失败: {e}")
            return pd.DataFrame()

    # ── 6. 大小盘轮动指标 ────────────────────────────────
    @cached(prefix="sentiment")
    @retry()
    def fetch_size_rotation(self) -> pd.DataFrame:
        """
        大小盘轮动：沪深300/中证1000价格比值 + 均线
        """
        try:
            df_300 = ak.index_zh_a_hist(symbol="000300", period="daily",
                                        start_date=last_n_trading_days(400),
                                        end_date=REPORT_DATE)
            df_1000 = ak.index_zh_a_hist(symbol="000852", period="daily",
                                         start_date=last_n_trading_days(400),
                                         end_date=REPORT_DATE)
            if df_300 is None or df_1000 is None:
                return pd.DataFrame()

            df_300["日期"] = pd.to_datetime(df_300["日期"])
            df_1000["日期"] = pd.to_datetime(df_1000["日期"])
            df_300 = df_300.set_index("日期")["收盘"].rename("沪深300")
            df_1000 = df_1000.set_index("日期")["收盘"].rename("中证1000")

            ratio = (df_300 / df_1000).rename("大盘/小盘比值")
            ma20 = ratio.rolling(20, min_periods=1).mean().rename("20日均线")
            ma60 = ratio.rolling(60, min_periods=1).mean().rename("60日均线")
            ma250 = ratio.rolling(250, min_periods=1).mean().rename("250日均线")

            result = pd.concat([ratio, ma20, ma60, ma250], axis=1).reset_index()
            result["日期"] = pd.to_datetime(result["日期"])
            return result
        except Exception as e:
            logger.warning(f"大小盘轮动指标失败: {e}")
            return pd.DataFrame()

    # ── 汇总 ──────────────────────────────────────────────
    def fetch_all(self) -> Dict:
        logger.info("开始抓取市场情绪数据")
        return {
            "leading_index":   self.fetch_leading_index(),
            "market_volume":   self.fetch_market_volume(),
            "advance_decline": self.fetch_advance_decline(),
            "limit_up":        self.fetch_limit_up_stats(),
            "margin_history":  self.fetch_margin_history(),
            "size_rotation":   self.fetch_size_rotation(),
        }
