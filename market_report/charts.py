"""
charts.py - 图表生成模块
复现报告中所有核心图表，使用 matplotlib
"""

import os
import datetime
import logging
from pathlib import Path
from typing import Optional, Dict, List

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.gridspec import GridSpec

matplotlib.rcParams['font.sans-serif'] = [
    'SimHei', 'Microsoft YaHei', 'PingFang SC', 'Arial Unicode MS', 'DejaVu Sans'
]
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['figure.facecolor'] = 'white'

from config import COLORS, CHART_DIR, A_SHARE_INDICES, BROAD_ETFS

logger = logging.getLogger(__name__)

RED   = COLORS["red"]
GREEN = COLORS["green"]
BLUE  = COLORS["blue"]
GOLD  = COLORS["gold"]

RG_CMAP = LinearSegmentedColormap.from_list(
    "rg", ["#E84B4B", "#FFFFFF", "#31B07B"], N=256
)


def _save(fig, name: str) -> str:
    Path(CHART_DIR).mkdir(parents=True, exist_ok=True)
    path = f"{CHART_DIR}/{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    logger.info(f"  图表已保存: {path}")
    return path


def _series_from_df(df: pd.DataFrame, val_col="close") -> pd.Series:
    """将 DataFrame 转为按日期索引的 Series"""
    df = df.copy().sort_values("date")
    df["date"] = pd.to_datetime(df["date"])
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    return df.set_index("date")[val_col]


def _pct_returns(df: pd.DataFrame, col="pct_chg") -> pd.Series:
    df = df.copy().sort_values("date")
    df["date"] = pd.to_datetime(df["date"])
    df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.set_index("date")[col]


# ════════════════════════════════════════════════
class ChartMaker:
    """所有报告图表的生成入口"""

    def __init__(self):
        self.saved_charts: List[str] = []

    def _reg(self, path: str):
        if path:
            self.saved_charts.append(path)

    # ──────────────────────────────────────────────
    # 1. A股权益指数总览热力表
    # ──────────────────────────────────────────────
    def chart_index_overview(
        self,
        index_data: Dict[str, pd.DataFrame],
        valuation_df: Optional[pd.DataFrame] = None,
    ) -> str:
        rows = []
        for sym, df in index_data.items():
            if df is None or df.empty:
                continue
            name = A_SHARE_INDICES.get(sym, sym)
            df = df.sort_values("date").copy()
            df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")

            # 最新一日 / 本周(近5日) / 上周(前5日)
            last_pct  = df["pct_chg"].iloc[-1] if len(df) else np.nan
            week_pct  = df["pct_chg"].tail(5).sum()
            prev_week = df["pct_chg"].tail(10).head(5).sum()
            mon_pct   = df["pct_chg"].tail(21).sum()
            q3_pct    = df["pct_chg"].tail(63).sum()
            hy_pct    = df["pct_chg"].tail(126).sum()
            ytd_pct   = df["pct_chg"].tail(252).sum()

            rows.append({
                "指数": name,
                "最新日%": round(last_pct, 2),
                "本周%": round(week_pct, 2),
                "上周%": round(prev_week, 2),
                "近1月%": round(mon_pct, 2),
                "近3月%": round(q3_pct, 2),
                "近半年%": round(hy_pct, 2),
                "今年以来%": round(ytd_pct, 2),
            })

        if not rows:
            return ""

        tbl = pd.DataFrame(rows)
        pct_cols = [c for c in tbl.columns if c != "指数"]

        fig, ax = plt.subplots(figsize=(16, max(4, len(tbl) * 0.55 + 1.5)))
        ax.axis("off")

        # 单元格颜色
        cell_colors = []
        for _, row in tbl.iterrows():
            rc = ["#F0F4FF"]  # 指数名称列
            for col in pct_cols:
                v = row[col]
                if pd.isna(v):
                    rc.append("#F5F5F5")
                elif v > 0:
                    intensity = min(v / 5, 1)
                    rc.append(_blend("#E84B4B", "#FFFFFF", intensity))
                elif v < 0:
                    intensity = min(abs(v) / 5, 1)
                    rc.append(_blend("#31B07B", "#FFFFFF", intensity))
                else:
                    rc.append("#FFFFFF")
            cell_colors.append(rc)

        # 格式化
        fmt = tbl.copy()
        for c in pct_cols:
            fmt[c] = fmt[c].apply(lambda x: f"{x:+.2f}" if not pd.isna(x) else "—")

        table = ax.table(
            cellText=fmt.values.tolist(),
            colLabels=list(tbl.columns),
            cellColours=cell_colors,
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.55)

        for j in range(len(tbl.columns)):
            table[(0, j)].set_facecolor(BLUE)
            table[(0, j)].set_text_props(color="white", fontweight="bold")

        ax.set_title("■ A股权益指数涨跌幅总览", fontsize=13, fontweight="bold",
                     color="#1A1A1A", loc="left", pad=10)
        return _save(fig, "01_index_overview")

    # ──────────────────────────────────────────────
    # 2. 市值风格 大小盘轮动
    # ──────────────────────────────────────────────
    def chart_large_small_rotation(
        self, index_data: Dict[str, pd.DataFrame]
    ) -> str:
        large_sym = "000300"   # 沪深300
        small_sym = "932000"   # 中证2000

        if large_sym not in index_data or small_sym not in index_data:
            logger.warning("大小盘轮动：缺少指数数据")
            return ""

        s_large = _series_from_df(index_data[large_sym])
        s_small = _series_from_df(index_data[small_sym])
        common = s_large.index.intersection(s_small.index)
        if len(common) < 20:
            return ""

        ratio = s_large[common] / s_small[common]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
        fig.suptitle("大小盘轮动监控", fontsize=14, fontweight="bold")

        # ── 均线模型 ──
        ax1.plot(ratio.index, ratio, color="dimgray", lw=0.8, label="大/小盘比值")
        ax1.plot(ratio.index, ratio.rolling(20).mean(),  color=GREEN, lw=1.1, label="MA20")
        ax1.plot(ratio.index, ratio.rolling(60).mean(),  color=GOLD,  lw=1.1, label="MA60")
        ax1.plot(ratio.index, ratio.rolling(250).mean(), color=RED,   lw=1.4, label="MA250")
        ax1.set_title("大小盘轮动 - 均线模型", fontsize=11)
        ax1.legend(fontsize=8, loc="upper left")
        ax1.set_ylabel("沪深300 / 中证2000")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))

        # ── 通道模型（布林带） ──
        ma20 = ratio.rolling(20).mean()
        std  = ratio.rolling(20).std()
        ax2.plot(ratio.index, ratio, color=BLUE,  lw=0.9, label="比值")
        ax2.plot(ratio.index, ma20,                color="black", lw=0.8, ls="--", label="MA20")
        ax2.plot(ratio.index, ma20 + 2 * std,      color=RED,   lw=0.8, ls="--", label="上轨+2σ")
        ax2.plot(ratio.index, ma20 - 2 * std,      color=GREEN, lw=0.8, ls="--", label="下轨-2σ")
        ax2.fill_between(ratio.index, (ma20 - 2*std).values,
                         (ma20 + 2*std).values, alpha=0.07, color=BLUE)
        ax2.set_title("大小盘轮动 - 通道模型", fontsize=11)
        ax2.legend(fontsize=8, loc="upper left")
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))

        fig.tight_layout()
        path = _save(fig, "02_large_small_rotation")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 3. 宽基ETF净流入热力表
    # ──────────────────────────────────────────────
    def chart_etf_flows(self, etf_data: Dict[str, pd.DataFrame]) -> str:
        if not etf_data:
            return ""

        # 构建 pivot：行=日期，列=ETF代码，值=涨跌幅（近40天）
        piv_dict: Dict[str, Dict[str, float]] = {}
        for code, df in etf_data.items():
            if df is None or df.empty:
                continue
            name = BROAD_ETFS.get(code, code)
            df = df.copy()
            # 统一列名
            for dc in ["日期", "date"]:
                if dc in df.columns:
                    df["_date"] = pd.to_datetime(df[dc])
                    break
            if "_date" not in df.columns:
                continue
            pct_col = next((c for c in ["涨跌幅", "pct_chg"] if c in df.columns), None)
            if not pct_col:
                continue
            df = df.sort_values("_date").tail(40)
            for _, r in df.iterrows():
                ds = str(r["_date"])[:10]
                piv_dict.setdefault(ds, {})[name] = float(r[pct_col])

        if not piv_dict:
            return ""

        pivot = pd.DataFrame(piv_dict).T.sort_index().tail(25)
        pivot.index.name = "日期"
        pivot["合计"] = pivot.sum(axis=1)

        etf_names = list(pivot.columns)

        fig, ax = plt.subplots(figsize=(len(etf_names) * 1.8 + 3, max(5, len(pivot) * 0.42 + 2)))
        ax.axis("off")

        vals = pivot.values
        fmt_text = [[f"{v:+.2f}" if not np.isnan(v) else "—"
                     for v in row] for row in vals]
        cell_colors = []
        for row in vals:
            rc = []
            for v in row:
                if np.isnan(v):
                    rc.append("#F5F5F5")
                elif v > 0:
                    rc.append(_blend("#E84B4B", "#FFFFFF", min(abs(v)/3, 1)))
                else:
                    rc.append(_blend("#31B07B", "#FFFFFF", min(abs(v)/3, 1)))
            cell_colors.append(rc)

        table = ax.table(
            cellText=fmt_text,
            rowLabels=list(pivot.index),
            colLabels=etf_names,
            cellColours=cell_colors,
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.5)

        for j in range(len(etf_names)):
            table[(0, j)].set_facecolor(BLUE)
            table[(0, j)].set_text_props(color="white", fontweight="bold")

        ax.set_title("■ 代表宽基ETF日度涨跌幅（近25个交易日）",
                     fontsize=12, fontweight="bold", loc="left", pad=10)
        path = _save(fig, "03_etf_flows")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 4. 行业板块涨跌幅热力图
    # ──────────────────────────────────────────────
    def chart_industry_heatmap(self, industry_df: Optional[pd.DataFrame]) -> str:
        if industry_df is None or industry_df.empty:
            return ""

        df = industry_df.copy()
        name_col = next((c for c in ["板块名称", "name", "行业"] if c in df.columns), None)
        pct_col  = next((c for c in ["涨跌幅", "pct_chg", "change"] if c in df.columns), None)
        if not name_col or not pct_col:
            return ""

        df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")
        df = df.dropna(subset=[pct_col]).sort_values(pct_col, ascending=False)

        names = df[name_col].tolist()
        values = df[pct_col].tolist()

        # 热力图（横向条形）
        fig, ax = plt.subplots(figsize=(12, max(6, len(names) * 0.38 + 2)))
        colors = [RED if v >= 0 else GREEN for v in values]
        bars = ax.barh(names, values, color=colors, edgecolor="white", height=0.7)

        # 数值标签
        for bar, v in zip(bars, values):
            x_pos = bar.get_width()
            ax.text(x_pos + (0.05 if v >= 0 else -0.05), bar.get_y() + bar.get_height()/2,
                    f"{v:+.2f}%", va="center", ha="left" if v >= 0 else "right",
                    fontsize=7.5, color="black")

        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("涨跌幅 (%)")
        ax.set_title("■ 申万一级行业涨跌幅（当日）", fontsize=13, fontweight="bold", loc="left")
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.4)
        fig.tight_layout()
        path = _save(fig, "04_industry_heatmap")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 5. 价值/成长/大类行业对比
    # ──────────────────────────────────────────────
    def chart_style_comparison(
        self, index_data: Dict[str, pd.DataFrame]
    ) -> str:
        """沪深300 vs 中证1000 价格比值（成长/价值代理）"""
        growth  = index_data.get("000852")   # 中证1000（成长代理）
        value_s = index_data.get("000016")   # 上证50（价值代理）

        if growth is None or value_s is None:
            return ""

        s_g = _series_from_df(growth)
        s_v = _series_from_df(value_s)
        common = s_g.index.intersection(s_v.index)
        ratio = s_g[common] / s_v[common]

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(ratio.index, ratio, color=RED,  lw=1.0, label="中证1000/上证50（成长/价值）")
        ax.plot(ratio.index, ratio.rolling(60).mean(), color=BLUE, lw=1.2, ls="--", label="60日均线")
        ax.fill_between(ratio.index, ratio.rolling(250).mean(),
                        ratio, where=ratio > ratio.rolling(250).mean(),
                        alpha=0.15, color=RED, label="成长占优区间")
        ax.fill_between(ratio.index, ratio.rolling(250).mean(),
                        ratio, where=ratio < ratio.rolling(250).mean(),
                        alpha=0.15, color=GREEN, label="价值占优区间")
        ax.set_title("■ 成长/价值风格轮动（中证1000/上证50）",
                     fontsize=12, fontweight="bold")
        ax.legend(fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax.grid(alpha=0.4)
        fig.tight_layout()
        path = _save(fig, "05_growth_value_rotation")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 6. A股成交额跟踪
    # ──────────────────────────────────────────────
    def chart_a_share_turnover(
        self, index_data: Dict[str, pd.DataFrame]
    ) -> str:
        df = index_data.get("000985")   # 万得全A
        if df is None or df.empty:
            return ""

        df = df.sort_values("date").copy()
        df["date"]   = pd.to_datetime(df["date"])
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce") / 1e8  # 转为亿元
        df["close"]  = pd.to_numeric(df["close"], errors="coerce")

        fig, ax1 = plt.subplots(figsize=(14, 5))
        ax2 = ax1.twinx()

        ax1.bar(df["date"], df["amount"], color=BLUE, alpha=0.7, width=1, label="成交额（亿元）")
        ax2.plot(df["date"], df["close"], color=RED, lw=1.2, label="万得全A")

        ax1.set_ylabel("成交额（亿元）", color=BLUE)
        ax2.set_ylabel("万得全A指数", color=RED)
        ax1.set_title("■ A股成交额跟踪", fontsize=13, fontweight="bold")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")
        fig.tight_layout()
        path = _save(fig, "06_a_share_turnover")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 7. 南华商品指数走势
    # ──────────────────────────────────────────────
    def chart_nanhua_commodities(
        self, nanhua_data: Dict[str, pd.DataFrame]
    ) -> str:
        if not nanhua_data:
            return ""

        # 找出公共日期列名
        valid = {k: v for k, v in nanhua_data.items() if v is not None and not v.empty}
        if not valid:
            return ""

        n = len(valid)
        cols = 2
        rows_n = (n + 1) // cols
        fig, axes = plt.subplots(rows_n, cols, figsize=(14, rows_n * 3.5))
        if rows_n * cols == 1:
            axes = np.array([[axes]])
        elif rows_n == 1:
            axes = axes.reshape(1, -1)

        color_cycle = [RED, GREEN, BLUE, GOLD, "#9B59B6", "#1ABC9C"]

        for idx, (name, df) in enumerate(valid.items()):
            ax = axes[idx // cols][idx % cols]
            df = df.copy()
            # 找日期列
            date_col = next((c for c in ["日期", "date", "Date"] if c in df.columns), None)
            val_col  = next((c for c in ["收盘", "close", "指数"] if c in df.columns), None)
            if not date_col or not val_col:
                ax.set_visible(False)
                continue
            df[date_col] = pd.to_datetime(df[date_col])
            df[val_col]  = pd.to_numeric(df[val_col], errors="coerce")
            df = df.dropna(subset=[val_col]).sort_values(date_col)

            ax.plot(df[date_col], df[val_col],
                    color=color_cycle[idx % len(color_cycle)], lw=1.2)
            ax.set_title(name, fontsize=10, fontweight="bold")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
            ax.tick_params(axis="x", rotation=30, labelsize=7)
            ax.grid(alpha=0.35)

        # 隐藏多余子图
        for i in range(n, rows_n * cols):
            axes[i // cols][i % cols].set_visible(False)

        fig.suptitle("■ 南华商品指数走势", fontsize=13, fontweight="bold")
        fig.tight_layout()
        path = _save(fig, "07_nanhua_indices")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 8. 黄金 - 原油期货价格
    # ──────────────────────────────────────────────
    def chart_gold_oil(self, macro_data: dict) -> str:
        gold = macro_data.get("gold")
        oil  = macro_data.get("crude_oil")

        if gold is None and oil is None:
            return ""

        fig, ax1 = plt.subplots(figsize=(14, 5))
        ax2 = ax1.twinx()

        def _prep(df):
            df = df.copy()
            dc = next((c for c in ["date","日期","Date"] if c in df.columns), None)
            vc = next((c for c in ["close","收盘","Close"] if c in df.columns), None)
            if not dc or not vc:
                return None
            df[dc] = pd.to_datetime(df[dc])
            df[vc] = pd.to_numeric(df[vc], errors="coerce")
            return df.dropna(subset=[vc]).sort_values(dc)

        if gold is not None:
            g = _prep(gold)
            if g is not None:
                dc = next(c for c in ["date","日期"] if c in g.columns)
                vc = next(c for c in ["close","收盘"] if c in g.columns)
                ax1.plot(g[dc], g[vc], color=RED, lw=1.2, label="COMEX黄金（美元/盎司）")
                ax1.set_ylabel("黄金（美元/盎司）", color=RED)

        if oil is not None:
            o = _prep(oil)
            if o is not None:
                dc = next(c for c in ["date","日期"] if c in o.columns)
                vc = next(c for c in ["close","收盘"] if c in o.columns)
                ax2.plot(o[dc], o[vc], color="black", lw=1.2, label="布伦特原油（美元/桶）")
                ax2.set_ylabel("原油（美元/桶）", color="black")

        ax1.set_title("■ 黄金-原油 期货收盘价", fontsize=13, fontweight="bold")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))

        lines, labels = [], []
        for a in [ax1, ax2]:
            l, lb = a.get_legend_handles_labels()
            lines += l
            labels += lb
        ax1.legend(lines, labels, fontsize=9, loc="upper left")
        fig.tight_layout()
        path = _save(fig, "08_gold_oil")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 9. AH溢价走势
    # ──────────────────────────────────────────────
    def chart_ah_premium(self, ah_df: Optional[pd.DataFrame]) -> str:
        if ah_df is None or ah_df.empty:
            return ""

        df = ah_df.copy()
        dc = next((c for c in ["date","日期"] if c in df.columns), None)
        vc = next((c for c in ["close","收盘"] if c in df.columns), None)
        if not dc or not vc:
            return ""

        df[dc] = pd.to_datetime(df[dc])
        df[vc] = pd.to_numeric(df[vc], errors="coerce")
        df = df.dropna().sort_values(dc)

        fig, ax = plt.subplots(figsize=(14, 5))
        # AH溢价：y轴反转（越高说明A股越贵）
        ax.plot(df[dc], df[vc], color="black", lw=0.9, label="AH溢价指数")
        mean_val = df[vc].mean()
        ax.axhline(mean_val, color=GREEN, lw=1.0, ls="--", label=f"均值 {mean_val:.1f}")

        # 高溢价/低溢价区域
        ax.fill_between(df[dc], df[vc], mean_val,
                        where=df[vc] > mean_val, alpha=0.12, color=GREEN, label="A股溢价")
        ax.fill_between(df[dc], df[vc], mean_val,
                        where=df[vc] < mean_val, alpha=0.12, color=RED, label="H股溢价")

        ax.set_title("■ AH股溢价指数（A股相对H股溢价）", fontsize=12, fontweight="bold")
        ax.legend(fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax.grid(alpha=0.4)
        fig.tight_layout()
        path = _save(fig, "09_ah_premium")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 10. 南向资金流入
    # ──────────────────────────────────────────────
    def chart_southbound_flow(self, sb_df: Optional[pd.DataFrame]) -> str:
        if sb_df is None or sb_df.empty:
            return ""

        df = sb_df.copy()
        dc = next((c for c in ["date","日期","净买入"] if c in df.columns), None)
        vc = next((c for c in ["净买入","net_buy","南向净买入"] if c in df.columns), None)
        if not vc:
            return ""

        df[dc] = pd.to_datetime(df[dc])
        df[vc] = pd.to_numeric(df[vc], errors="coerce")
        df = df.dropna().sort_values(dc)

        fig, ax = plt.subplots(figsize=(14, 5))
        colors = [RED if v >= 0 else GREEN for v in df[vc]]
        ax.bar(df[dc], df[vc], color=colors, width=1, label="南向净买入（亿元）")
        # 5日移动均线
        ma5 = df[vc].rolling(5).mean()
        ax.plot(df[dc], ma5, color=BLUE, lw=1.2, label="5日均线")

        ax.axhline(0, color="black", lw=0.8)
        ax.set_title("■ 港股通 南向资金净流入（亿元）", fontsize=12, fontweight="bold")
        ax.legend(fontsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax.grid(axis="y", alpha=0.4)
        fig.tight_layout()
        path = _save(fig, "10_southbound_flow")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 11. 融资余额
    # ──────────────────────────────────────────────
    def chart_margin_balance(self, sentiment_data: dict) -> str:
        df = sentiment_data.get("margin_balance")
        if df is None or df.empty:
            return ""

        df = df.copy()
        dc = next((c for c in ["date","日期","融资余额"] if c in df.columns), None)
        vc = next((c for c in ["融资余额","balance","value"] if c in df.columns), None)
        if not dc or not vc:
            return ""

        df[dc] = pd.to_datetime(df[dc])
        df[vc] = pd.to_numeric(df[vc], errors="coerce") / 1e4  # 转为万亿
        df = df.dropna().sort_values(dc)

        fig, ax1 = plt.subplots(figsize=(14, 5))
        ax1.plot(df[dc], df[vc], color=RED, lw=1.2, label="融资余额（万亿元）")
        ax1.fill_between(df[dc], 0, df[vc], alpha=0.15, color=RED)
        ax1.set_ylabel("融资余额（万亿元）", color=RED)
        ax1.set_title("■ A股融资余额跟踪", fontsize=13, fontweight="bold")
        ax1.legend(fontsize=9)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax1.grid(alpha=0.4)
        fig.tight_layout()
        path = _save(fig, "11_margin_balance")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 12. 可转债成交额走势
    # ──────────────────────────────────────────────
    def chart_convertible_bond(self, cb_df: Optional[pd.DataFrame]) -> str:
        if cb_df is None or cb_df.empty:
            return ""

        df = cb_df.copy()
        dc = next((c for c in ["date","日期"] if c in df.columns), None)
        if not dc:
            return ""
        df[dc] = pd.to_datetime(df[dc])

        amt_col   = next((c for c in ["成交额","amount"] if c in df.columns), None)
        close_col = next((c for c in ["收盘","close"] if c in df.columns), None)

        fig, ax1 = plt.subplots(figsize=(14, 5))
        ax2 = ax1.twinx()

        if amt_col:
            df[amt_col] = pd.to_numeric(df[amt_col], errors="coerce")
            ax1.bar(df[dc], df[amt_col], color=GOLD, alpha=0.75, width=1, label="成交额（万元）")
            ax1.set_ylabel("成交额（万元）", color=GOLD)

        if close_col:
            df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
            ax2.plot(df[dc], df[close_col], color=BLUE, lw=1.2, label="中证转债指数")
            ax2.set_ylabel("指数", color=BLUE)

        ax1.set_title("■ 中证转债成交额跟踪", fontsize=12, fontweight="bold")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        lines, labels = [], []
        for a in [ax1, ax2]:
            l, lb = a.get_legend_handles_labels()
            lines += l; labels += lb
        ax1.legend(lines, labels, fontsize=9)
        fig.tight_layout()
        path = _save(fig, "12_convertible_bond")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 13. 宏观高频 - 房地产
    # ──────────────────────────────────────────────
    def chart_real_estate(self, macro_data: dict) -> str:
        re_df = macro_data.get("real_estate_sales")
        sh_df = macro_data.get("second_hand_house")

        if re_df is None and sh_df is None:
            return ""

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        for ax, df, title in [
            (axes[0], sh_df, "二手房挂牌价指数"),
            (axes[1], re_df, "30大中城市商品房成交"),
        ]:
            if df is None or df.empty:
                ax.text(0.5, 0.5, "暂无数据", ha="center", va="center",
                        transform=ax.transAxes, fontsize=12)
                ax.set_title(title, fontsize=10)
                continue
            dc = next((c for c in ["date","日期"] if c in df.columns), None)
            vc = next((c for c in df.columns if c not in ["date","日期"]), None)
            if not dc or not vc:
                ax.set_title(title, fontsize=10)
                continue
            df = df.copy()
            df[dc] = pd.to_datetime(df[dc])
            df[vc] = pd.to_numeric(df[vc], errors="coerce")
            df = df.dropna().sort_values(dc)
            ax.plot(df[dc], df[vc], color=BLUE, lw=1.1)
            ax.set_title(title, fontsize=10, fontweight="bold")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
            ax.tick_params(axis="x", rotation=30, labelsize=7)
            ax.grid(alpha=0.4)

        fig.suptitle("■ 宏观高频 - 房地产市场", fontsize=13, fontweight="bold")
        fig.tight_layout()
        path = _save(fig, "13_real_estate")
        self._reg(path)
        return path

    # ──────────────────────────────────────────────
    # 汇总生成所有图表
    # ──────────────────────────────────────────────
    def generate_all_charts(self, data: dict) -> List[str]:
        charts = []

        logger.info("[图表1] 指数总览...")
        p = self.chart_index_overview(
            data.get("index_daily", {}),
            data.get("index_valuation")
        )
        self._reg(p); charts.append(p)

        logger.info("[图表2] 大小盘轮动...")
        p = self.chart_large_small_rotation(data.get("index_daily", {}))
        charts.append(p)

        logger.info("[图表3] ETF净流入...")
        p = self.chart_etf_flows(data.get("etf_flows", {}))
        charts.append(p)

        logger.info("[图表4] 行业热力图...")
        p = self.chart_industry_heatmap(data.get("industry_perf"))
        charts.append(p)

        logger.info("[图表5] 成长/价值轮动...")
        p = self.chart_style_comparison(data.get("index_daily", {}))
        charts.append(p)

        logger.info("[图表6] A股成交额...")
        p = self.chart_a_share_turnover(data.get("index_daily", {}))
        charts.append(p)

        logger.info("[图表7] 南华商品指数...")
        p = self.chart_nanhua_commodities(data.get("nanhua", {}))
        charts.append(p)

        logger.info("[图表8] 黄金原油...")
        p = self.chart_gold_oil(data.get("macro", {}))
        charts.append(p)

        logger.info("[图表9] AH溢价...")
        p = self.chart_ah_premium(data.get("ah_premium"))
        charts.append(p)

        logger.info("[图表10] 南向资金...")
        p = self.chart_southbound_flow(data.get("southbound"))
        charts.append(p)

        logger.info("[图表11] 融资余额...")
        p = self.chart_margin_balance(data.get("sentiment", {}))
        charts.append(p)

        logger.info("[图表12] 可转债...")
        p = self.chart_convertible_bond(data.get("cb_index"))
        charts.append(p)

        logger.info("[图表13] 房地产高频...")
        p = self.chart_real_estate(data.get("macro", {}))
        charts.append(p)

        return [c for c in charts if c]


# ─── 工具函数 ─────────────────────────────────────
def _blend(hex_color: str, target: str = "#FFFFFF", intensity: float = 0.5) -> str:
    """将颜色向目标颜色混合（intensity=0完全目标, 1完全原色）"""
    def _hex2rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _rgb2hex(r):
        return "#" + "".join(f"{int(c):02X}" for c in r)

    c1 = _hex2rgb(hex_color)
    c2 = _hex2rgb(target)
    blended = tuple(c2[i] + intensity * (c1[i] - c2[i]) for i in range(3))
    return _rgb2hex(blended)
