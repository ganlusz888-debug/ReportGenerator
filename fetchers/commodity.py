"""
商品数据抓取模块
覆盖：南华商品指数、各品种期货价格、贵金属/能源/农产品
"""
import time
from typing import Dict, Optional

import pandas as pd
import numpy as np
import akshare as ak

from config import NANHUA_INDICES, COMMODITY_CATEGORIES, REPORT_DATE
from utils import cached, retry, logger, last_n_trading_days, safe_float


# 期货合约映射（品种 -> AKShare代码）
FUTURES_MAP = {
    # 贵金属
    "SHFE白银":  {"ak_symbol": "AG",  "exchange": "SHFE"},
    "SHFE黄金":  {"ak_symbol": "AU",  "exchange": "SHFE"},
    # 能源化工
    "INE原油":   {"ak_symbol": "SC",  "exchange": "INE"},
    "SHFE燃油":  {"ak_symbol": "FU",  "exchange": "SHFE"},
    "DCE LPG":   {"ak_symbol": "PG",  "exchange": "DCE"},
    "SHFE橡胶":  {"ak_symbol": "RU",  "exchange": "SHFE"},
    "INE20号胶": {"ak_symbol": "NR",  "exchange": "INE"},
    "SHFE沥青":  {"ak_symbol": "BU",  "exchange": "SHFE"},
    "SHFE纸浆":  {"ak_symbol": "SP",  "exchange": "SHFE"},
    "DCE塑料":   {"ak_symbol": "L",   "exchange": "DCE"},
    "CZCE PTA":  {"ak_symbol": "TA",  "exchange": "CZCE"},
    "DCE乙二醇": {"ak_symbol": "EG",  "exchange": "DCE"},
    "CZCE甲醇":  {"ak_symbol": "MA",  "exchange": "CZCE"},
    "DCE聚丙烯": {"ak_symbol": "PP",  "exchange": "DCE"},
    "DCE苯乙烯": {"ak_symbol": "EB",  "exchange": "DCE"},
    "CZCE尿素":  {"ak_symbol": "UR",  "exchange": "CZCE"},
    "CZCE纯碱":  {"ak_symbol": "SA",  "exchange": "CZCE"},
    "DCE PVC":   {"ak_symbol": "V",   "exchange": "DCE"},
    "CZCE玻璃":  {"ak_symbol": "FG",  "exchange": "CZCE"},
    "CZCE短纤":  {"ak_symbol": "PF",  "exchange": "CZCE"},
    # 黑色
    "DCE焦炭":   {"ak_symbol": "J",   "exchange": "DCE"},
    "DCE焦煤":   {"ak_symbol": "JM",  "exchange": "DCE"},
    "CZCE动力煤": {"ak_symbol": "ZC", "exchange": "CZCE"},
    "SHFE螺纹钢": {"ak_symbol": "RB", "exchange": "SHFE"},
    "DCE铁矿石":  {"ak_symbol": "I",  "exchange": "DCE"},
    "SHFE热轧卷板": {"ak_symbol": "HC", "exchange": "SHFE"},
    "SHFE线材":   {"ak_symbol": "WR", "exchange": "SHFE"},
    "CZCE硅铁":  {"ak_symbol": "SF",  "exchange": "CZCE"},
    "CZCE锰硅":  {"ak_symbol": "SM",  "exchange": "CZCE"},
    "SHFE不锈钢": {"ak_symbol": "SS", "exchange": "SHFE"},
    # 有色
    "SHFE铜":    {"ak_symbol": "CU",  "exchange": "SHFE"},
    "SHFE铝":    {"ak_symbol": "AL",  "exchange": "SHFE"},
    "SHFE铅":    {"ak_symbol": "PB",  "exchange": "SHFE"},
    "SHFE锌":    {"ak_symbol": "ZN",  "exchange": "SHFE"},
    "SHFE镍":    {"ak_symbol": "NI",  "exchange": "SHFE"},
    "SHFE锡":    {"ak_symbol": "SN",  "exchange": "SHFE"},
    "INE国际铜":  {"ak_symbol": "BC", "exchange": "INE"},
    "GFEX工业硅": {"ak_symbol": "SI", "exchange": "GFEX"},
    "GFEX碳酸锂": {"ak_symbol": "LC", "exchange": "GFEX"},
    "SHFE氧化铝": {"ak_symbol": "AO", "exchange": "SHFE"},
    # 农产品
    "DCE豆一":   {"ak_symbol": "A",   "exchange": "DCE"},
    "DCE豆二":   {"ak_symbol": "B",   "exchange": "DCE"},
    "DCE玉米":   {"ak_symbol": "C",   "exchange": "DCE"},
    "DCE豆粕":   {"ak_symbol": "M",   "exchange": "DCE"},
    "DCE豆油":   {"ak_symbol": "Y",   "exchange": "DCE"},
    "CZCE菜油":  {"ak_symbol": "OI",  "exchange": "CZCE"},
    "DCE棕榈油": {"ak_symbol": "P",   "exchange": "DCE"},
    "CZCE棉花":  {"ak_symbol": "CF",  "exchange": "CZCE"},
    "CZCE白糖":  {"ak_symbol": "SR",  "exchange": "CZCE"},
    "DCE鸡蛋":   {"ak_symbol": "JD",  "exchange": "DCE"},
    "CZCE菜粕":  {"ak_symbol": "RM",  "exchange": "CZCE"},
    "CZCE强麦":  {"ak_symbol": "WH",  "exchange": "CZCE"},
    "CZCE玉米淀粉": {"ak_symbol": "CS", "exchange": "DCE"},
    "CZCE苹果":  {"ak_symbol": "AP",  "exchange": "CZCE"},
    "CZCE红枣":  {"ak_symbol": "CJ",  "exchange": "CZCE"},
    "DCE棉纱":   {"ak_symbol": "CY",  "exchange": "CZCE"},
    "DCE纤维板": {"ak_symbol": "FB",  "exchange": "DCE"},
    "DCE胶合板": {"ak_symbol": "BB",  "exchange": "DCE"},
    "CZCE菜籽":  {"ak_symbol": "RS",  "exchange": "CZCE"},
    "DCE生猪":   {"ak_symbol": "LH",  "exchange": "DCE"},
    "DCE花生":   {"ak_symbol": "PK",  "exchange": "CZCE"},
}


class CommodityFetcher:
    """商品数据抓取器"""

    # ── 1. 南华商品指数 ───────────────────────────────────
    @cached(prefix="commodity")
    @retry()
    def fetch_nanhua_indices(self) -> pd.DataFrame:
        """
        南华商品指数各板块涨跌幅
        """
        records = []
        nh_symbols = {
            "南华贵金属指数": "贵金属",
            "南华有色金属指数": "有色金属",
            "南华黑色指数":   "黑色",
            "南华工业品指数": "工业品",
            "南华农产品指数": "农产品",
            "南华能化指数":   "能化",
        }
        try:
            df_all = ak.futures_commodity_index_hist_em()
            if df_all is not None and len(df_all) > 0:
                logger.info(f"南华商品指数: {len(df_all)}条")
                return df_all
        except Exception:
            pass

        for name, category in nh_symbols.items():
            time.sleep(0.8)
            try:
                df = ak.futures_index_zh_sina(symbol=category)
                if df is None or len(df) == 0:
                    continue
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期").tail(400)
                row = {
                    "证券简称":    name,
                    "板块":       category,
                    "本周涨跌幅%": self._pct_chg(df, 5),
                    "上周涨跌幅%": self._pct_chg(df, 10),
                    "近一月涨跌幅%": self._pct_chg(df, 22),
                    "近三月涨跌幅%": self._pct_chg(df, 66),
                    "近半年涨跌幅%": self._pct_chg(df, 132),
                    "今年以来涨跌幅%": self._ytd_ret(df),
                }
                records.append(row)
            except Exception as e:
                logger.debug(f"南华指数{name}失败: {e}")

        return pd.DataFrame(records)

    # ── 2. 期货品种行情 ───────────────────────────────────
    @cached(prefix="commodity")
    @retry()
    def fetch_futures_spot(self) -> pd.DataFrame:
        """
        期货各品种即时行情 + 涨跌幅统计
        """
        try:
            # 全市场期货行情
            df = ak.futures_zh_spot(var="", market="CF", period="5")
            if df is not None and len(df) > 0:
                logger.info(f"期货行情: {len(df)}条")
                return self._enrich_futures_data(df)
        except Exception:
            pass

        # 逐品种抓取
        return self._fetch_futures_by_symbol()

    def _fetch_futures_by_symbol(self) -> pd.DataFrame:
        """按品种逐一抓取期货历史"""
        records = []
        for name, info in FUTURES_MAP.items():
            time.sleep(0.8)
            try:
                sym = info["ak_symbol"].lower()
                df = ak.futures_main_sina(symbol=sym, start_date=last_n_trading_days(400))
                if df is None or len(df) == 0:
                    continue
                df.rename(columns={"date": "日期", "close": "收盘"}, inplace=True)
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期")
                # 板块
                category = next(
                    (cat for cat, items in COMMODITY_CATEGORIES.items() if name in items),
                    "其他"
                )
                records.append({
                    "品种简称":    name,
                    "板块":       category,
                    "本周涨跌幅%": self._pct_chg(df, 5),
                    "上周涨跌幅%": self._pct_chg(df, 10),
                    "近一月涨跌幅%": self._pct_chg(df, 22),
                    "近三月涨跌幅%": self._pct_chg(df, 66),
                    "今年以来涨跌幅%": self._ytd_ret(df),
                })
            except Exception as e:
                logger.debug(f"期货{name}失败: {e}")

        return pd.DataFrame(records)

    def _enrich_futures_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """为即时行情数据添加板块分类"""
        def get_category(name):
            for cat, items in COMMODITY_CATEGORIES.items():
                if any(kw in str(name) for kw in items):
                    return cat
            return "其他"
        df["板块"] = df.apply(lambda r: get_category(r.get("品种名称", "")), axis=1)
        return df

    # ── 3. 黄金/原油行情 ─────────────────────────────────
    @cached(prefix="commodity")
    @retry()
    def fetch_gold_oil(self) -> Dict[str, pd.DataFrame]:
        """
        COMEX黄金 & 布伦特原油期货收盘价历史
        """
        results = {}
        # 黄金
        try:
            df_gold = ak.futures_foreign_hist(symbol="GC")
            if df_gold is not None and len(df_gold) > 0:
                df_gold["日期"] = pd.to_datetime(df_gold["date"])
                results["gold"] = df_gold[["日期", "close"]].rename(columns={"close": "黄金价格(美元/盎司)"})
        except Exception:
            pass
        # 布伦特原油
        try:
            df_oil = ak.futures_foreign_hist(symbol="BZ")
            if df_oil is not None and len(df_oil) > 0:
                df_oil["日期"] = pd.to_datetime(df_oil["date"])
                results["brent"] = df_oil[["日期", "close"]].rename(columns={"close": "布伦特原油(美元/桶)"})
        except Exception as e:
            logger.warning(f"原油数据失败: {e}")

        # 备用：国内期货数据
        if "gold" not in results:
            try:
                df = ak.futures_main_sina(symbol="au", start_date=last_n_trading_days(400))
                df["日期"] = pd.to_datetime(df["date"])
                results["gold_cny"] = df[["日期", "close"]].rename(columns={"close": "黄金(元/克)"})
            except Exception:
                pass

        return results

    # ── 汇总 ──────────────────────────────────────────────
    def fetch_all(self) -> Dict:
        logger.info("开始抓取商品数据")
        gold_oil = self.fetch_gold_oil()
        return {
            "nanhua_indices":  self.fetch_nanhua_indices(),
            "futures_spot":    self.fetch_futures_spot(),
            "gold":            gold_oil.get("gold"),
            "oil":             gold_oil.get("brent"),
        }

    # ── 辅助 ──────────────────────────────────────────────
    def _pct_chg(self, df: pd.DataFrame, days: int,
                  col: str = "收盘") -> Optional[float]:
        if col not in df.columns:
            col = "close"
        if col not in df.columns or len(df) < 2:
            return None
        n = min(days + 1, len(df))
        base = df[col].iloc[-n]
        last = df[col].iloc[-1]
        return (last / base - 1) * 100 if base else None

    def _ytd_ret(self, df: pd.DataFrame, col: str = "收盘") -> Optional[float]:
        from datetime import datetime
        if col not in df.columns:
            col = "close"
        if col not in df.columns:
            return None
        date_col = "日期" if "日期" in df.columns else "date"
        if date_col not in df.columns:
            return None
        year_start = f"{datetime.now().year}-01-01"
        sub = df[df[date_col] >= pd.to_datetime(year_start)]
        if len(sub) < 2:
            return None
        return (sub[col].iloc[-1] / sub[col].iloc[0] - 1) * 100
