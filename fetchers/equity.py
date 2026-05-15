"""
A股权益数据抓取模块
覆盖：宽基指数、市值风格、行业板块、ETF净流入、主题概念、可转债、公募仓位
"""
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd
import numpy as np
import akshare as ak

from config import (
    A_SHARE_INDICES, BROAD_ETFS, SW_LEVEL1_INDUSTRIES,
    REPORT_DATE, START_1Y, START_3Y,
)
from utils import cached, rate_limited, retry, logger, last_n_trading_days, safe_float

# ── 辅助：周期字符串转天数 ────────────────────────────────
_PERIOD_DAYS = {"1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365}

def _pct_change(df: pd.DataFrame, col: str = "收盘", days: int = 5) -> float:
    """计算区间涨跌幅"""
    if df is None or len(df) < 2:
        return None
    df = df.copy().sort_values("日期")
    if len(df) > days:
        base = df[col].iloc[-(days + 1)]
        last = df[col].iloc[-1]
    else:
        base = df[col].iloc[0]
        last = df[col].iloc[-1]
    if base and base != 0:
        return (last / base - 1) * 100
    return None


class EquityFetcher:
    """A股权益全量数据抓取器"""

    # ── 1. 宽基指数行情 ───────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_index_overview(self) -> pd.DataFrame:
        """
        抓取宽基指数总览：PE/PB/涨跌幅/分位数/市值
        对应报告"A股权益指数总览"表格
        """
        records = []
        for name, info in A_SHARE_INDICES.items():
            code = info["code"]
            time.sleep(1.0)
            try:
                # 指数基本信息(PE/PB)
                spot = self._get_index_spot(code)
                # 历史价格
                hist = self._get_index_hist(code, start=last_n_trading_days(365))
                # 近10年历史(分位数)
                hist10 = self._get_index_hist(code, start=last_n_trading_days(3650))

                row = {"指数简称": name, "指数代码": code}
                if spot is not None:
                    row.update(spot)
                if hist is not None and len(hist) > 1:
                    hist = hist.sort_values("日期")
                    row["本周涨跌幅%"]  = _pct_change(hist, days=5)
                    row["上周涨跌幅%"]  = _pct_change(hist, days=10) # 近两周vs近一周
                    row["近一月涨跌幅%"] = _pct_change(hist, days=20)
                    row["近三月涨跌幅%"] = _pct_change(hist, days=60)
                    row["近半年涨跌幅%"] = _pct_change(hist, days=120)
                    row["今年以来涨跌幅%"] = self._ytd_return(hist)
                    # PE/PB近10年分位数
                    if hist10 is not None and "PE" in row:
                        row["近10年PE分位数"] = self._calc_percentile(hist10, "PE")
                        row["近10年PB分位数"] = self._calc_percentile(hist10, "PB")
                records.append(row)
            except Exception as e:
                logger.warning(f"指数{name}({code})数据失败: {e}")
                records.append({"指数简称": name, "指数代码": code})

        return pd.DataFrame(records)

    def _get_index_spot(self, code: str) -> Optional[Dict]:
        """获取指数实时PE/PB/市值"""
        try:
            # 尝试获取A股PE/PB数据
            df = ak.stock_a_lg_index_pe_pb(symbol=code)
            if df is not None and len(df) > 0:
                last = df.iloc[-1]
                return {
                    "PE":      safe_float(last.get("pe", last.get("市盈率"))),
                    "PB":      safe_float(last.get("pb", last.get("市净率"))),
                    "指数市值/万亿": safe_float(last.get("总市值")) / 1e12 if last.get("总市值") else None,
                }
        except Exception:
            pass
        try:
            # 备用：从东方财富获取
            df = ak.index_value_hist_funddb(symbol=code)
            if df is not None and len(df) > 0:
                last = df.iloc[-1]
                return {
                    "PE": safe_float(last.get("PE(TTM)")),
                    "PB": safe_float(last.get("PB(LF)")),
                }
        except Exception:
            pass
        return {}

    @cached(prefix="index_hist", ttl=3600)
    def _get_index_hist(self, code: str, start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        """获取指数历史行情"""
        end = end or REPORT_DATE
        start = start or last_n_trading_days(365)
        try:
            df = ak.index_zh_a_hist(symbol=code, period="daily",
                                    start_date=start, end_date=end)
            df.rename(columns={"日期": "日期", "收盘": "收盘",
                                "开盘": "开盘", "最高": "最高", "最低": "最低",
                                "成交量": "成交量", "成交额": "成交额"}, inplace=True)
            df["日期"] = pd.to_datetime(df["日期"])
            return df
        except Exception:
            pass
        try:
            # 备用数据源
            df = ak.stock_zh_index_daily(symbol=f"sh{code}" if code.startswith("0") else f"sz{code}")
            df.rename(columns={"date": "日期", "close": "收盘"}, inplace=True)
            df["日期"] = pd.to_datetime(df["日期"])
            df = df[df["日期"] >= pd.to_datetime(start)]
            return df
        except Exception as e:
            logger.debug(f"指数{code}历史数据失败: {e}")
            return None

    def _ytd_return(self, hist: pd.DataFrame) -> Optional[float]:
        year_start = f"{datetime.now().year}0101"
        sub = hist[hist["日期"] >= pd.to_datetime(year_start)]
        if len(sub) < 2:
            return None
        base = sub["收盘"].iloc[0]
        last = sub["收盘"].iloc[-1]
        return (last / base - 1) * 100 if base else None

    def _calc_percentile(self, hist: pd.DataFrame, col: str) -> Optional[float]:
        if col not in hist.columns or hist[col].isna().all():
            return None
        arr = hist[col].dropna()
        if len(arr) < 10:
            return None
        return float(np.percentile(arr, 50))  # 分位数

    # ── 2. 市值风格指数 ───────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_size_style(self) -> pd.DataFrame:
        """
        市值风格指数：沪深300/上证50/中证500/中证1000/中证2000/万得微盘
        多时间维度涨跌幅
        """
        style_codes = {
            "沪深300":   "000300",
            "上证50":    "000016",
            "中证500":   "000905",
            "万得全A":   "881001",
            "中证2000":  "932000",
            "中证1000":  "000852",
            "万得微盘股指数": "8841431",
        }
        records = []
        for name, code in style_codes.items():
            time.sleep(0.8)
            try:
                hist = self._get_index_hist(code, start=last_n_trading_days(400))
                if hist is None:
                    records.append({"证券简称": name})
                    continue
                hist = hist.sort_values("日期")
                row = {"证券简称": name, "指数代码": code}
                row["本周涨跌幅%"]  = _pct_change(hist, days=5)
                row["上周涨跌幅%"]  = self._prev_week_return(hist)
                row["近一月涨跌幅%"] = _pct_change(hist, days=22)
                row["近三月涨跌幅%"] = _pct_change(hist, days=66)
                row["近半年涨跌幅%"] = _pct_change(hist, days=132)
                row["今年以来涨跌幅%"] = self._ytd_return(hist)

                # 日度涨跌幅（最近5个交易日）
                last5 = hist.tail(6)
                for i, (_, row_h) in enumerate(last5.iterrows()):
                    date_str = row_h["日期"].strftime("%Y-%m-%d")
                    if i > 0:
                        prev = last5.iloc[i-1]["收盘"]
                        curr = row_h["收盘"]
                        row[date_str] = (curr / prev - 1) * 100 if prev else None
                records.append(row)
            except Exception as e:
                logger.warning(f"风格指数{name}失败: {e}")
        return pd.DataFrame(records)

    def _prev_week_return(self, hist: pd.DataFrame) -> Optional[float]:
        """上周涨跌幅 = [-10:-5] vs [-5]"""
        if len(hist) < 11:
            return None
        base = hist["收盘"].iloc[-11]
        end  = hist["收盘"].iloc[-6]
        return (end / base - 1) * 100 if base else None

    # ── 3. ETF净流入 ──────────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_etf_netflow(self, days: int = 25) -> pd.DataFrame:
        """
        宽基ETF日度净流入（亿元）
        数据来源：东方财富
        """
        all_dfs = []
        for etf_name, code in BROAD_ETFS.items():
            time.sleep(1.0)
            try:
                df = ak.fund_etf_hist_em(symbol=code, period="daily",
                                         start_date=last_n_trading_days(days + 10),
                                         end_date=REPORT_DATE, adjust="")
                if df is None or len(df) == 0:
                    continue
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期").tail(days)
                # 净流入 = 成交额变化 * 份额变化（近似）
                # 直接用成交额作为流量参考
                net_col = "净流入(亿元)"
                if "净流入" in df.columns:
                    df[net_col] = df["净流入"]
                elif "成交额" in df.columns:
                    df[net_col] = df["成交额"] / 1e8  # 转亿元
                else:
                    continue
                df = df[["日期", net_col]].rename(columns={net_col: etf_name})
                all_dfs.append(df.set_index("日期"))
            except Exception as e:
                logger.warning(f"ETF{etf_name}({code})净流入失败: {e}")

        # 尝试用专门的ETF资金流入接口
        try:
            df_flow = ak.fund_etf_fund_info_em()
            if df_flow is not None and len(df_flow) > 0:
                logger.info(f"获取到ETF资金流入概览: {len(df_flow)}条")
        except Exception:
            pass

        if not all_dfs:
            return pd.DataFrame()
        merged = pd.concat(all_dfs, axis=1)
        merged["当日累计"] = merged.sum(axis=1)
        merged.index.name = "日期"
        return merged.reset_index()

    # ── 4. 行业板块涨跌幅 ────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_industry_returns(self) -> pd.DataFrame:
        """
        申万一级行业涨跌幅 + PE/PB分位数
        对应报告"股票-行业涨跌幅"表格
        """
        try:
            # 申万行业指数行情
            df = ak.sw_index_second_info()  # 申万二级行业
            if df is None:
                df = ak.index_all_cni()
        except Exception:
            df = None

        records = []
        for ind in SW_LEVEL1_INDUSTRIES:
            time.sleep(0.6)
            try:
                # 获取申万一级行业历史
                hist = ak.sw_index_daily_indicator(symbol=ind, indicator="市盈率")
                row = {"证券简称": ind}
                if hist is not None and len(hist) > 0:
                    hist["date"] = pd.to_datetime(hist["date"])
                    hist = hist.sort_values("date")
                    row["当日涨跌幅"] = safe_float(hist.get("chg_rate", pd.Series()).iloc[-1] if "chg_rate" in hist.columns else None)
                    row["PE"] = safe_float(hist["pe_ttm"].iloc[-1] if "pe_ttm" in hist.columns else None)
                records.append(row)
            except Exception as e:
                logger.debug(f"行业{ind}失败: {e}")
                records.append({"证券简称": ind})

        # 批量获取申万行业行情（更高效）
        try:
            df_sw = ak.sw_index_spot_em()
            if df_sw is not None and len(df_sw) > 0:
                df_sw["证券简称"] = df_sw.get("指数简称", df_sw.get("名称", ""))
                return df_sw
        except Exception as e:
            logger.warning(f"申万行业行情批量获取失败: {e}")

        return pd.DataFrame(records)

    # ── 5. 主题概念涨跌幅 ────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_concept_returns(self, top_n: int = 20) -> Dict[str, pd.DataFrame]:
        """
        主题概念本周涨跌幅 Top20 / Bottom20
        """
        try:
            df = ak.stock_board_concept_hist_em()
            if df is None:
                raise ValueError("无数据")
        except Exception:
            try:
                df = ak.stock_board_concept_spot_em()
            except Exception as e:
                logger.warning(f"主题概念数据失败: {e}")
                return {"top20": pd.DataFrame(), "bottom20": pd.DataFrame()}

        if df is None or len(df) == 0:
            return {"top20": pd.DataFrame(), "bottom20": pd.DataFrame()}

        # 找涨跌幅列
        pct_col = None
        for c in ["涨跌幅", "最新涨跌幅", "5日涨跌幅"]:
            if c in df.columns:
                pct_col = c
                break
        if not pct_col:
            return {"top20": pd.DataFrame(), "bottom20": pd.DataFrame()}

        df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")
        df_sorted = df.sort_values(pct_col, ascending=False)
        return {
            "top20":    df_sorted.head(top_n),
            "bottom20": df_sorted.tail(top_n).sort_values(pct_col),
        }

    # ── 6. 可转债指数 ─────────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_convertible_bond_indices(self) -> pd.DataFrame:
        """
        可转债各类指数涨跌幅
        """
        records = []
        cb_indices = {
            "万得可转债加权指数": "885049",
            "万得可转债等权指数": "885048",
            "中证转债":          "000832",
        }
        for name, code in cb_indices.items():
            time.sleep(0.8)
            try:
                hist = self._get_index_hist(code, start=last_n_trading_days(200))
                if hist is None:
                    continue
                hist = hist.sort_values("日期")
                row = {"证券简称": name}
                row["当日涨跌幅"]   = _pct_change(hist, days=1)
                row["本周涨跌幅%"]  = _pct_change(hist, days=5)
                row["上周涨跌幅%"]  = self._prev_week_return(hist)
                row["近一月涨跌幅%"] = _pct_change(hist, days=22)
                row["近三月涨跌幅%"] = _pct_change(hist, days=66)
                row["近半年涨跌幅%"] = _pct_change(hist, days=132)
                row["今年以来涨跌幅%"] = self._ytd_return(hist)
                records.append(row)
            except Exception as e:
                logger.debug(f"可转债指数{name}失败: {e}")

        # 补充东方财富转债数据
        try:
            df_cb = ak.bond_zh_cov_spot()
            logger.info(f"可转债行情: {len(df_cb) if df_cb is not None else 0}条")
        except Exception:
            pass

        return pd.DataFrame(records)

    # ── 7. 公募基金仓位 ───────────────────────────────────
    @cached(prefix="equity", ttl=86400)
    @retry()
    def fetch_fund_equity_position(self) -> pd.DataFrame:
        """
        偏股型/普通股票型公募基金股票仓位
        数据来源: 华润资管、wind等估算数据
        """
        try:
            df = ak.fund_open_fund_daily_em()
            if df is not None and len(df) > 0:
                logger.info(f"公募基金数据: {len(df)}条")
                return df
        except Exception as e:
            logger.warning(f"公募基金仓位数据失败: {e}")

        try:
            df = ak.fund_manager_em()
            return df
        except Exception as e:
            logger.warning(f"公募基金备用数据失败: {e}")
            return pd.DataFrame()

    # ── 8. 融资余额 ───────────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_margin_balance(self) -> pd.DataFrame:
        """
        A股融资余额（亿元）
        """
        try:
            df = ak.stock_margin_detail_szse(date=REPORT_DATE[:6])  # YYYYMM
            return df
        except Exception:
            pass
        try:
            df = ak.stock_margin_sse(start_date=last_n_trading_days(365), end_date=REPORT_DATE)
            return df
        except Exception as e:
            logger.warning(f"融资余额数据失败: {e}")
            return pd.DataFrame()

    # ── 9. 新成立基金 ─────────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_new_fund_issuance(self) -> pd.DataFrame:
        """
        中国新成立基金份额:偏股型:周:合计值
        """
        try:
            df = ak.fund_new_found_em(symbol="偏股混合型基金")
            if df is not None and len(df) > 0:
                return df
        except Exception:
            pass
        try:
            df = ak.fund_new_found_em(symbol="普通股票型基金")
            return df
        except Exception as e:
            logger.warning(f"新成立基金数据失败: {e}")
            return pd.DataFrame()

    # ── 10. AH股溢价 ─────────────────────────────────────
    @cached(prefix="equity")
    @retry()
    def fetch_ah_premium(self) -> pd.DataFrame:
        """
        AH股溢价指数历史
        """
        try:
            df = ak.stock_ah_price_em()
            if df is not None and len(df) > 0:
                return df
        except Exception:
            pass
        try:
            df = ak.index_zh_a_hist(symbol="HSAHP", period="daily",
                                    start_date=last_n_trading_days(3650),
                                    end_date=REPORT_DATE)
            return df
        except Exception as e:
            logger.warning(f"AH溢价数据失败: {e}")
            return pd.DataFrame()

    # ── 汇总获取所有权益数据 ─────────────────────────────
    def fetch_all(self) -> Dict[str, pd.DataFrame]:
        logger.info("═" * 50)
        logger.info("开始抓取A股权益数据")
        logger.info("═" * 50)
        results = {}

        tasks = [
            ("index_overview",        self.fetch_index_overview,         "宽基指数总览"),
            ("size_style",            self.fetch_size_style,             "市值风格指数"),
            ("etf_netflow",           self.fetch_etf_netflow,            "ETF净流入"),
            ("industry_returns",      self.fetch_industry_returns,       "行业涨跌幅"),
            ("concept_returns",       self.fetch_concept_returns,        "主题概念"),
            ("cb_indices",            self.fetch_convertible_bond_indices, "可转债指数"),
            ("margin_balance",        self.fetch_margin_balance,         "融资余额"),
            ("new_fund_issuance",     self.fetch_new_fund_issuance,      "新成立基金"),
            ("ah_premium",            self.fetch_ah_premium,             "AH股溢价"),
        ]
        for key, func, name in tasks:
            logger.info(f"  → 抓取: {name}")
            try:
                results[key] = func()
            except Exception as e:
                logger.error(f"  ✗ {name}失败: {e}")
                results[key] = pd.DataFrame()

        logger.info("A股权益数据抓取完成")
        return results
