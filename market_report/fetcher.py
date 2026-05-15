"""
fetcher.py - 数据抓取模块
功能：
  - AKShare 接口封装，统一加延迟/重试
  - 随机 User-Agent 轮换
  - 指数退避重试（防 IP 封禁）
  - 抓取：A股指数、ETF净流入、行业板块、海外市场、商品期货、宏观高频
"""

import time
import random
import logging
import datetime
from typing import Optional, Dict, List

import pandas as pd
import numpy as np
import requests
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)

import akshare as ak
from config import (
    REQUEST_DELAY_MIN, REQUEST_DELAY_MAX,
    MAX_RETRIES, RETRY_BACKOFF,
    A_SHARE_INDICES, BROAD_ETFS, SW_INDUSTRIES,
    FUTURES_MAP, NANHUA_INDICES, GLOBAL_INDICES,
)

# AKShare 版本适配：记录本版本可用的接口
import akshare as _ak_mod
_AK_ATTRS = set(dir(_ak_mod))

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
#  User-Agent 池
# ────────────────────────────────────────────────
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
]


def _sleep():
    """请求间随机睡眠，规避高频限制"""
    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    time.sleep(delay)


def _random_ua() -> str:
    return random.choice(UA_POOL)


def _retry_decorator():
    """通用 tenacity 重试装饰器"""
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=RETRY_BACKOFF, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=False,
    )


# ────────────────────────────────────────────────
#  工具函数
# ────────────────────────────────────────────────
def get_date_range(lookback_days: int = 365) -> tuple[str, str]:
    """返回 (start_date, end_date) 格式 YYYYMMDD"""
    end = datetime.date.today()
    start = end - datetime.timedelta(days=lookback_days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def get_10yr_start() -> str:
    end = datetime.date.today()
    start = end.replace(year=end.year - 10)
    return start.strftime("%Y%m%d")


# ════════════════════════════════════════════════
#  DataFetcher 主类
# ════════════════════════════════════════════════
class DataFetcher:
    """统一数据抓取接口"""

    def __init__(self):
        self._session = self._make_session()

    # ─── session 配置 ───────────────────────────
    def _make_session(self) -> requests.Session:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=3, backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504]
            )
        )
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update({"User-Agent": _random_ua()})
        return s

    def _refresh_ua(self):
        self._session.headers.update({"User-Agent": _random_ua()})

    # ════════════════════════════════════════════
    #  1. A股宽基指数日线数据（近1年）
    # ════════════════════════════════════════════
    def fetch_index_daily(
        self,
        symbol: str,
        period: str = "daily",
        lookback_days: int = 380,
    ) -> Optional[pd.DataFrame]:
        """抓取单只指数日K线（多接口降级）"""
        start, end = get_date_range(lookback_days)

        # ── 接口1：东方财富（需外网） ──
        try:
            _sleep()
            self._refresh_ua()
            df = ak.index_zh_a_hist(
                symbol=symbol, period=period,
                start_date=start, end_date=end,
            )
            if df is not None and not df.empty:
                return self._normalize_index_df(df, symbol)
        except Exception as e:
            logger.warning(f"index_zh_a_hist {symbol} 失败，尝试备用: {e}")

        # ── 接口2：新浪 index_zh_a_hist_csindex（部分指数） ──
        try:
            _sleep()
            df = ak.index_zh_a_hist_csindex(symbol=symbol, indicator="总收益",
                                             start_date=start, end_date=end)
            if df is not None and not df.empty:
                return self._normalize_index_df(df, symbol)
        except Exception:
            pass

        logger.error(f"fetch_index_daily {symbol} 全部接口失败")
        return None

    def _normalize_index_df(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """统一列名"""
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low",
            "成交量": "volume", "成交额": "amount",
            "涨跌幅": "pct_chg", "涨跌额": "chg",
            "换手率": "turnover",
        })
        df["date"] = pd.to_datetime(df["date"])
        df["symbol"] = symbol
        return df.sort_values("date").reset_index(drop=True)

    def fetch_all_indices(self) -> Dict[str, pd.DataFrame]:
        """批量抓取所有宽基指数"""
        result = {}
        for sym, name in A_SHARE_INDICES.items():
            logger.info(f"  抓取指数: {name}({sym})")
            df = self.fetch_index_daily(sym)
            if df is not None:
                df["name"] = name
                result[sym] = df
        return result

    # ════════════════════════════════════════════
    #  2. 指数估值 PE/PB（当前 + 历史分位）
    # ════════════════════════════════════════════
    def fetch_index_valuation(self) -> Optional[pd.DataFrame]:
        """
        抓取主要指数 PE/PB（多接口适配）
        优先用 stock_zh_index_value_csindex，fallback 用 index_value_hist_em
        """
        # ── 接口1：中证官网 PE/PB（需外网） ──
        results = []
        for sym, name in A_SHARE_INDICES.items():
            try:
                _sleep()
                df = ak.stock_zh_index_value_csindex(symbol=sym)
                if df is not None and not df.empty:
                    latest = df.iloc[-1].to_dict()
                    latest["symbol"] = sym
                    latest["name"] = name
                    results.append(latest)
            except Exception:
                pass

        if results:
            return pd.DataFrame(results)

        # ── 接口2：东方财富估值（需外网） ──
        try:
            _sleep()
            df = ak.index_value_hist_em(symbol="沪深300")
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"index_value_hist_em 失败: {e}")

        logger.error("fetch_index_valuation 全部接口失败")
        return None

    def fetch_index_pe_history(self, index_name: str, lookback_years: int = 10) -> Optional[pd.DataFrame]:
        """抓取单个指数PE历史"""
        try:
            _sleep()
            # 正确接口名：index_value_hist_funddb → 已不存在，改用 stock_zh_index_value_csindex
            df = ak.stock_zh_index_value_csindex(symbol=index_name)
            if df is not None and not df.empty:
                if "日期" in df.columns:
                    df["date"] = pd.to_datetime(df["日期"])
                    cutoff = datetime.date.today() - datetime.timedelta(days=lookback_years * 365)
                    df = df[df["date"] >= pd.Timestamp(cutoff)]
                return df
        except Exception as e:
            logger.warning(f"fetch_index_pe_history {index_name} 失败: {e}")
        return None

    # ════════════════════════════════════════════
    #  3. 宽基ETF 净流入
    # ════════════════════════════════════════════
    def fetch_etf_flow(self, fund_code: str, lookback_days: int = 60) -> Optional[pd.DataFrame]:
        """抓取ETF日度净流入（东方财富数据）"""
        try:
            _sleep()
            self._refresh_ua()
            df = ak.fund_etf_fund_info_em(fund=fund_code, dtype="单位净值走势")
            if df is None or df.empty:
                return None
            # 净流入需要另一个接口
            df2 = ak.fund_etf_hist_em(symbol=fund_code, period="daily", adjust="")
            if df2 is not None and not df2.empty:
                df2.columns = [c.strip() for c in df2.columns]
                return df2
            return None
        except Exception as e:
            logger.warning(f"fetch_etf_flow {fund_code} 失败: {e}")
            return self._fetch_etf_flow_fallback(fund_code, lookback_days)

    def _fetch_etf_flow_fallback(self, fund_code: str, lookback_days: int = 60) -> Optional[pd.DataFrame]:
        """ETF 数据多接口降级：em → sina → etf_spot"""
        start, end = get_date_range(lookback_days)

        # ── 接口1：东方财富历史（需外网）──
        try:
            _sleep()
            df = ak.fund_etf_hist_em(
                symbol=fund_code, period="daily",
                start_date=start, end_date=end, adjust=""
            )
            if df is not None and not df.empty:
                df.columns = [c.strip() for c in df.columns]
                return df
        except Exception as e:
            logger.debug(f"fund_etf_hist_em {fund_code} 失败: {e}")

        # ── 接口2：新浪 ETF 历史（sh/sz前缀）──
        try:
            _sleep()
            # 判断交易所前缀
            prefix = "sh" if fund_code.startswith(("5", "1")) else "sz"
            # 深交所ETF(159xxx)用sz，上交所(51xxxx/58xxxx)用sh
            if fund_code.startswith("159"):
                prefix = "sz"
            df = ak.fund_etf_hist_sina(symbol=f"{prefix}{fund_code}")
            if df is not None and not df.empty:
                df.columns = [c.strip() for c in df.columns]
                return df
        except Exception as e:
            logger.debug(f"fund_etf_hist_sina {fund_code} 失败: {e}")

        logger.error(f"ETF {fund_code} 全部接口失败")
        return None

    def fetch_all_etf_flows(self) -> Dict[str, pd.DataFrame]:
        """批量抓取所有宽基ETF数据"""
        result = {}
        for code, name in BROAD_ETFS.items():
            logger.info(f"  抓取ETF: {name}({code})")
            df = self._fetch_etf_flow_fallback(code)
            if df is not None:
                df["code"] = code
                df["name"] = name
                result[code] = df
        return result

    # ════════════════════════════════════════════
    #  4. 申万行业板块涨跌幅
    # ════════════════════════════════════════════
    def fetch_industry_performance(self, lookback_days: int = 180) -> Optional[pd.DataFrame]:
        """
        抓取申万一级行业板块涨跌数据
        返回：行业名、当日涨跌幅、本周/上周/近1月/近3月/近半年/今年以来
        """
        try:
            _sleep()
            self._refresh_ua()
            # 东方财富板块行情
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                return None
            logger.info(f"  行业板块原始列: {list(df.columns)}")
            return df
        except Exception as e:
            logger.error(f"fetch_industry_performance 失败: {e}")
            return None

    def fetch_industry_hist(self, industry: str, lookback_days: int = 30) -> Optional[pd.DataFrame]:
        """抓取单个行业的历史日线"""
        try:
            _sleep()
            start, end = get_date_range(lookback_days)
            df = ak.stock_board_industry_hist_em(
                symbol=industry, period="daily",
                start_date=start, end_date=end, adjust=""
            )
            if df is None or df.empty:
                return None
            df.columns = [c.strip() for c in df.columns]
            return df
        except Exception as e:
            logger.warning(f"fetch_industry_hist {industry} 失败: {e}")
            return None

    # ════════════════════════════════════════════
    #  5. 可转债指数
    # ════════════════════════════════════════════
    def fetch_convertible_bond_indices(self, lookback_days: int = 60) -> Optional[pd.DataFrame]:
        """抓取可转债各类指数行情"""
        try:
            _sleep()
            # 中证转债指数
            start, end = get_date_range(lookback_days)
            df = ak.index_zh_a_hist(
                symbol="000832", period="daily",
                start_date=start, end_date=end
            )
            if df is not None and not df.empty:
                df["name"] = "中证转债"
                df = df.rename(columns={"日期": "date", "收盘": "close", "涨跌幅": "pct_chg"})
                df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.error(f"fetch_convertible_bond_indices 失败: {e}")
            return None

    def fetch_cb_market_overview(self) -> Optional[pd.DataFrame]:
        """可转债市场概览（价格分布、溢价率等）"""
        try:
            _sleep()
            df = ak.bond_zh_cov_value_analysis()
            return df
        except Exception as e:
            logger.warning(f"fetch_cb_market_overview 失败: {e}")
            return None

    # ════════════════════════════════════════════
    #  6. 海外市场指数
    # ════════════════════════════════════════════
    def fetch_global_indices(self) -> Dict[str, pd.DataFrame]:
        """抓取香港及海外市场主要指数"""
        result = {}

        # 香港恒生指数
        hk_map = {
            "HSI":    "恒生指数",
            "HSCEI":  "恒生国企",
            "HSTECH": "恒生科技",
        }
        for sym, name in hk_map.items():
            try:
                _sleep()
                df = ak.stock_hk_index_daily_em(symbol=sym)
                if df is not None and not df.empty:
                    df["symbol"] = sym
                    df["name"] = name
                    result[sym] = df
                    logger.info(f"  HK指数: {name} 获取成功")
            except Exception as e:
                logger.warning(f"  HK指数 {name} 失败: {e}")

        # 美股三大指数
        us_map = {
            ".DJI": "道琼斯工业",
            ".IXIC": "纳斯达克",
            ".SPX": "标普500",
        }
        for sym, name in us_map.items():
            try:
                _sleep()
                df = ak.index_investing_global_hist(
                    symbol=sym, period="日k",
                    start_date=get_date_range(380)[0],
                    end_date=get_date_range(380)[1]
                )
                if df is not None and not df.empty:
                    df["symbol"] = sym
                    df["name"] = name
                    result[sym] = df
                    logger.info(f"  US指数: {name} 获取成功")
            except Exception as e:
                logger.warning(f"  US指数 {name} 失败: {e}")

        return result

    # ════════════════════════════════════════════
    #  7. 商品期货（南华指数 + 主力合约）
    # ════════════════════════════════════════════
    def fetch_nanhua_indices(self, lookback_days: int = 380) -> Dict[str, pd.DataFrame]:
        """抓取南华商品指数历史"""
        result = {}
        start, end = get_date_range(lookback_days)
        for name in NANHUA_INDICES:
            try:
                _sleep()
                df = ak.futures_index_ccidx(symbol=name)
                if df is not None and not df.empty:
                    df["index_name"] = name
                    result[name] = df
                    logger.info(f"  南华指数: {name} 获取成功")
            except Exception as e:
                logger.warning(f"  南华指数 {name} 失败，尝试备用接口: {e}")
                try:
                    _sleep()
                    df = ak.index_value_hist_funddb(name=name)
                    if df is not None and not df.empty:
                        df["index_name"] = name
                        result[name] = df
                except Exception as e2:
                    logger.error(f"  南华指数 {name} 全部接口失败: {e2}")
        return result

    def fetch_futures_main(self, lookback_days: int = 60) -> Dict[str, pd.DataFrame]:
        """抓取主要期货品种主力合约日线"""
        result = {}
        start, end = get_date_range(lookback_days)
        for code, (sector, name) in FUTURES_MAP.items():
            try:
                _sleep()
                df = ak.futures_zh_daily_sina(symbol=code)
                if df is not None and not df.empty:
                    df["code"] = code
                    df["sector"] = sector
                    df["name"] = name
                    result[code] = df
            except Exception as e:
                logger.warning(f"  期货 {name}({code}) 失败: {e}")
        return result

    # ════════════════════════════════════════════
    #  8. 市场情绪数据
    # ════════════════════════════════════════════
    def fetch_market_sentiment(self) -> Dict[str, Optional[pd.DataFrame]]:
        """
        抓取市场情绪相关数据：
        - A股日成交额
        - 融资融券余额
        - 涨跌家数
        """
        result = {}

        # A股成交额（使用指数成交量代替）
        try:
            _sleep()
            start, end = get_date_range(250)
            df = ak.index_zh_a_hist(symbol="000985", period="daily", start_date=start, end_date=end)
            if df is not None and not df.empty:
                df = df.rename(columns={"日期": "date", "成交额": "amount", "收盘": "close"})
                df["date"] = pd.to_datetime(df["date"])
                result["a_share_amount"] = df[["date", "amount", "close"]]
                logger.info("  A股成交额获取成功")
        except Exception as e:
            logger.error(f"fetch A股成交额失败: {e}")
            result["a_share_amount"] = None

        # 融资余额
        try:
            _sleep()
            df = ak.stock_margin_account_info()
            if df is not None and not df.empty:
                result["margin_balance"] = df
                logger.info("  融资余额获取成功")
        except Exception as e:
            logger.warning(f"fetch 融资余额失败: {e}")
            result["margin_balance"] = None

        # 上涨/下跌家数（用万得全A数据推算）
        try:
            _sleep()
            df = ak.stock_market_activity_legu()
            if df is not None and not df.empty:
                result["market_activity"] = df
                logger.info("  市场活跃度获取成功")
        except Exception as e:
            logger.warning(f"fetch 市场活跃度失败: {e}")
            result["market_activity"] = None

        return result

    # ════════════════════════════════════════════
    #  9. 宏观高频数据
    # ════════════════════════════════════════════
    def fetch_macro_high_freq(self) -> Dict[str, Optional[pd.DataFrame]]:
        """抓取宏观高频数据"""
        result = {}

        # 黄金价格（SHFE）
        try:
            _sleep()
            df = ak.futures_zh_daily_sina(symbol="AU0")
            if df is not None and not df.empty:
                result["gold"] = df
                logger.info("  黄金期货获取成功")
        except Exception as e:
            logger.warning(f"黄金期货失败: {e}")
            result["gold"] = None

        # 原油价格
        try:
            _sleep()
            df = ak.futures_zh_daily_sina(symbol="SC0")
            if df is not None and not df.empty:
                result["crude_oil"] = df
                logger.info("  原油期货获取成功")
        except Exception as e:
            logger.warning(f"原油期货失败: {e}")
            try:
                _sleep()
                df = ak.macro_cons_gold()
                result["gold_spot"] = df
            except Exception:
                result["crude_oil"] = None

        # 房地产：30大中城市商品房成交
        try:
            _sleep()
            df = ak.macro_china_real_estate_sales()
            if df is not None and not df.empty:
                result["real_estate_sales"] = df
                logger.info("  商品房成交获取成功")
        except Exception as e:
            logger.warning(f"商品房成交失败: {e}")
            result["real_estate_sales"] = None

        # 二手房挂牌价指数
        try:
            _sleep()
            df = ak.macro_china_second_hand_house_index()
            if df is not None and not df.empty:
                result["second_hand_house"] = df
                logger.info("  二手房指数获取成功")
        except Exception as e:
            logger.warning(f"二手房指数失败: {e}")
            result["second_hand_house"] = None

        # 乘用车日均销量
        try:
            _sleep()
            df = ak.car_market_meco()
            if df is not None and not df.empty:
                result["car_sales"] = df
                logger.info("  乘用车销量获取成功")
        except Exception as e:
            logger.warning(f"乘用车销量失败: {e}")
            result["car_sales"] = None

        # 猪肉批发价
        try:
            _sleep()
            df = ak.macro_china_pork_price()
            if df is not None and not df.empty:
                result["pork_price"] = df
                logger.info("  猪肉价格获取成功")
        except Exception as e:
            logger.warning(f"猪肉价格失败: {e}")
            result["pork_price"] = None

        # 集装箱运价指数 SCFI
        try:
            _sleep()
            df = ak.index_investing_global(symbol="中国出口集装箱运价指数")
            if df is not None and not df.empty:
                result["container_freight"] = df
        except Exception as e:
            logger.warning(f"集装箱运价失败: {e}")
            result["container_freight"] = None

        return result

    # ════════════════════════════════════════════
    #  10. AH股溢价
    # ════════════════════════════════════════════
    def fetch_ah_premium(self, lookback_days: int = 500) -> Optional[pd.DataFrame]:
        """抓取AH股溢价指数"""
        try:
            _sleep()
            start, end = get_date_range(lookback_days)
            # 恒生AH溢价指数
            df = ak.index_zh_a_hist(symbol="900905", period="daily",
                                     start_date=start, end_date=end)
            if df is not None and not df.empty:
                df = df.rename(columns={"日期": "date", "收盘": "close"})
                df["date"] = pd.to_datetime(df["date"])
                return df
        except Exception as e:
            logger.warning(f"AH溢价失败: {e}")
        return None

    # ════════════════════════════════════════════
    #  11. 南向资金（港股通）
    # ════════════════════════════════════════════
    def fetch_southbound_flow(self, lookback_days: int = 60) -> Optional[pd.DataFrame]:
        """抓取港股通南向资金净流入"""
        try:
            _sleep()
            df = ak.stock_hsgt_south_money_sina()
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"南向资金失败: {e}")
        return None

    # ════════════════════════════════════════════
    #  完整数据抓取入口
    # ════════════════════════════════════════════
    def fetch_all(self) -> dict:
        """
        一键抓取所有报告所需数据，返回字典
        键：数据类型，值：DataFrame 或 dict
        """
        logger.info("=" * 60)
        logger.info("开始全量数据抓取...")
        logger.info("=" * 60)
        data = {}

        logger.info("[1/11] 抓取 A股宽基指数日线...")
        data["index_daily"] = self.fetch_all_indices()

        logger.info("[2/11] 抓取 指数PE/PB估值...")
        data["index_valuation"] = self.fetch_index_valuation()

        logger.info("[3/11] 抓取 宽基ETF净流入...")
        data["etf_flows"] = self.fetch_all_etf_flows()

        # logger.info("[4/11] 抓取 申万行业板块...")
        # data["industry_perf"] = self.fetch_industry_performance()
        #
        # logger.info("[5/11] 抓取 可转债市场...")
        # data["cb_index"] = self.fetch_convertible_bond_indices()
        # data["cb_overview"] = self.fetch_cb_market_overview()

        logger.info("[6/11] 抓取 海外市场...")
        data["global_indices"] = self.fetch_global_indices()

        # logger.info("[7/11] 抓取 南华商品指数...")
        # data["nanhua"] = self.fetch_nanhua_indices()
        #
        # logger.info("[8/11] 抓取 市场情绪数据...")
        # data["sentiment"] = self.fetch_market_sentiment()
        #
        # logger.info("[9/11] 抓取 宏观高频数据...")
        # data["macro"] = self.fetch_macro_high_freq()
        #
        # logger.info("[10/11] 抓取 AH溢价...")
        # data["ah_premium"] = self.fetch_ah_premium()
        #
        # logger.info("[11/11] 抓取 南向资金...")
        # data["southbound"] = self.fetch_southbound_flow()

        logger.info("=" * 60)
        logger.info("数据抓取完成！")
        return data
