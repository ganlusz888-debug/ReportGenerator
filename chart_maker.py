"""
图表生成模块
复现报告中所有核心图表，输出PNG文件
"""
import os
import logging
from pathlib import Path
from typing import Dict, Optional, List, Tuple

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec
from matplotlib.patches import FancyBboxPatch
import matplotlib.font_manager as fm
import warnings
warnings.filterwarnings("ignore")

from config import CHART_STYLE, REPORT_DIR, REPORT_DATE_CN, REPORT_BRAND

logger = logging.getLogger("market_tracker.charts")

# ── 字体配置（支持中文）─────────────────────────────────────
def _setup_fonts():
    """尝试配置中文字体"""
    candidate_fonts = [
        "PingFang SC", "Heiti TC", "Source Han Sans CN",
        "WenQuanYi Micro Hei", "Noto Sans CJK SC",
        "SimHei", "Microsoft YaHei", "SimSun",
        "Arial Unicode MS",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidate_fonts:
        if font in available:
            plt.rcParams["font.family"] = font
            logger.info(f"使用字体: {font}")
            return
    # 尝试系统字体路径
    system_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in system_paths:
        if os.path.exists(path):
            fm.fontManager.addfont(path)
            prop = fm.FontProperties(fname=path)
            plt.rcParams["font.family"] = prop.get_name()
            logger.info(f"加载字体文件: {path}")
            return
    logger.warning("未找到中文字体，图表中文可能显示为方框")

_setup_fonts()
plt.rcParams.update({
    "axes.unicode_minus":    False,
    "figure.dpi":            CHART_STYLE["figure_dpi"],
    "axes.facecolor":        CHART_STYLE["bg_color"],
    "figure.facecolor":      CHART_STYLE["bg_color"],
    "axes.grid":             True,
    "grid.color":            CHART_STYLE["grid_color"],
    "grid.linewidth":        0.5,
    "axes.spines.top":       False,
    "axes.spines.right":     False,
    "axes.spines.left":      True,
    "axes.spines.bottom":    True,
})

# ── 颜色常量 ──────────────────────────────────────────────
RED    = CHART_STYLE["red_color"]
GREEN  = CHART_STYLE["green_color"]
BLUE   = CHART_STYLE["blue_color"]
ORANGE = CHART_STYLE["orange_color"]
TEAL   = "#26A69A"
NAVY   = "#1A237E"
GRAY   = "#9E9E9E"


# ════════════════════════════════════════════════════════════
# 通用辅助函数
# ════════════════════════════════════════════════════════════

def _save(fig: plt.Figure, filename: str, subdir: str = "") -> Path:
    """保存图表并返回路径"""
    out_dir = REPORT_DIR / REPORT_DATE_CN.replace(".", "") / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=CHART_STYLE["figure_dpi"], bbox_inches="tight",
                facecolor=CHART_STYLE["bg_color"])
    plt.close(fig)
    logger.info(f"已保存: {path.name}")
    return path

def _brand_stamp(fig: plt.Figure, text: str = REPORT_BRAND):
    """在图表右下角添加品牌水印"""
    fig.text(0.99, 0.01, text, ha="right", va="bottom",
             fontsize=7, color=GRAY, alpha=0.6,
             transform=fig.transFigure)

def _color_by_sign(val) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return GRAY
    return RED if float(val) >= 0 else GREEN

def _fmt_date_axis(ax, freq: str = "M"):
    """格式化X轴日期"""
    if freq == "M":
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    elif freq == "W":
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=7)

def _add_ma_lines(ax, series: pd.Series, windows: List[int],
                  colors: List[str] = None, alpha: float = 0.8):
    """在已有图上叠加均线"""
    colors = colors or [ORANGE, TEAL, RED, BLUE]
    for i, w in enumerate(windows):
        ma = series.rolling(w, min_periods=1).mean()
        ax.plot(series.index, ma, color=colors[i % len(colors)],
                linewidth=1.5, alpha=alpha, label=f"MA{w}")


# ════════════════════════════════════════════════════════════
# 1. 中国经济基本面先导指数
# ════════════════════════════════════════════════════════════

def plot_leading_index(df: pd.DataFrame) -> Optional[Path]:
    """
    复现报告封面"中国经济基本面先导指数"折线图
    粉色面积 = 先导指数波动区间；蓝线 = 指数；红线 = 250日均线
    """
    if df is None or len(df) < 10:
        logger.warning("先导指数数据不足，跳过绘图")
        return None

    fig, ax = plt.subplots(figsize=(14, 5))
    df = df.sort_values("日期")
    dates = df["日期"]
    idx = df["先导指数"]

    # 面积图
    ax.fill_between(dates, idx, alpha=0.25, color=RED, label="先导指数")
    # 指数线
    ax.plot(dates, idx, color=NAVY, linewidth=1.2, alpha=0.85, label="先导指数")
    # 均线
    if "250日均线" in df.columns:
        ax.plot(dates, df["250日均线"], color=RED, linewidth=2.0, label="250日均线")
    if "60日均线" in df.columns:
        ax.plot(dates, df["60日均线"], color=TEAL, linewidth=1.5, alpha=0.8, label="60日均线")

    # 当前值标注
    last_val = idx.iloc[-1]
    ma250_val = df["250日均线"].iloc[-1] if "250日均线" in df.columns else None
    ax.annotate(f"{last_val:,.0f}", xy=(dates.iloc[-1], last_val),
                xytext=(5, 0), textcoords="offset points",
                fontsize=8, color=NAVY, fontweight="bold")
    if ma250_val:
        ax.annotate(f"{ma250_val:,.0f}", xy=(dates.iloc[-1], ma250_val),
                    xytext=(5, 0), textcoords="offset points",
                    fontsize=8, color=RED)

    ax.set_title(f"{REPORT_BRAND}-中国经济基本面先导指数", **CHART_STYLE["title_font"], pad=12)
    ax.set_ylabel("点", fontsize=9)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.7)
    _fmt_date_axis(ax, "M")
    fig.text(0.5, -0.04, "备注：先导指数高于250日均线表示对经济预期相对乐观，反之则悲观",
             ha="center", fontsize=7, color=GRAY)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "01_leading_index.png")


# ════════════════════════════════════════════════════════════
# 2. A股权益指数总览（热力表格图）
# ════════════════════════════════════════════════════════════

def plot_index_overview_table(df: pd.DataFrame) -> Optional[Path]:
    """
    宽基指数总览热力表格
    涨跌幅正红负绿，PE/PB高分位数标红
    """
    if df is None or len(df) == 0:
        return None

    pct_cols = [c for c in df.columns if "涨跌幅%" in c]
    pe_col   = "PE" if "PE" in df.columns else None
    pb_col   = "PB" if "PB" in df.columns else None

    display_cols = ["指数简称"] + pct_cols[:4]
    if pe_col:
        display_cols.append(pe_col)
    if "近10年PE分位数" in df.columns:
        display_cols.append("近10年PE分位数")
    if pb_col:
        display_cols.append(pb_col)
    if "近10年PB分位数" in df.columns:
        display_cols.append("近10年PB分位数")

    disp = df[[c for c in display_cols if c in df.columns]].fillna("/")

    fig_h = max(4, len(disp) * 0.38 + 1.5)
    fig, ax = plt.subplots(figsize=(14, fig_h))
    ax.axis("off")

    headers = disp.columns.tolist()
    cell_data = disp.values.tolist()

    # 构建颜色矩阵
    cell_colors = []
    for row in disp.itertuples(index=False):
        row_colors = []
        for i, (col, val) in enumerate(zip(headers, row)):
            try:
                fval = float(str(val).replace("%", "").replace("/", "nan"))
            except ValueError:
                fval = float("nan")

            if "涨跌幅" in col:
                if np.isnan(fval):
                    row_colors.append("#F5F5F5")
                elif fval >= 0:
                    alpha = min(0.8, abs(fval) / 5)
                    row_colors.append(f"rgba({int(255*(1-alpha)+217*alpha)},{int(255*(1-alpha)+80*alpha)},{int(255*(1-alpha)+80*alpha)},1)")
                    row_colors[-1] = "#FFEBEE" if fval < 1 else ("#FFCDD2" if fval < 3 else "#EF9A9A")
                else:
                    row_colors.append("#E8F5E9" if fval > -1 else ("#C8E6C9" if fval > -3 else "#A5D6A7"))
            elif "分位数" in col:
                if not np.isnan(fval):
                    row_colors.append("#FFCDD2" if fval > 80 else ("#FFF9C4" if fval > 60 else "#E8F5E9"))
                else:
                    row_colors.append("#F5F5F5")
            else:
                row_colors.append("#FAFAFA" if i % 2 == 0 else "#F5F5F5")

        cell_colors.append(row_colors)

    # 格式化数值
    formatted = []
    for row in cell_data:
        fmt_row = []
        for i, (col, val) in enumerate(zip(headers, row)):
            if val == "/" or val == "nan":
                fmt_row.append("/")
            elif "涨跌幅" in col:
                try:
                    fval = float(val)
                    fmt_row.append(f"+{fval:.2f}%" if fval >= 0 else f"{fval:.2f}%")
                except:
                    fmt_row.append(str(val))
            elif "PE" in col or "PB" in col:
                try:
                    fmt_row.append(f"{float(val):.2f}")
                except:
                    fmt_row.append(str(val))
            else:
                fmt_row.append(str(val))
        formatted.append(fmt_row)

    tbl = ax.table(
        cellText=formatted, colLabels=headers,
        cellLoc="center", loc="center",
        cellColours=cell_colors,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 1.4)

    # 表头样式
    for j in range(len(headers)):
        tbl[0, j].set_facecolor(NAVY)
        tbl[0, j].set_text_props(color="white", fontweight="bold")

    ax.set_title("A股权益指数总览", **CHART_STYLE["title_font"], pad=16)
    fig.text(0.02, 0.02, f"数据截止 {REPORT_DATE_CN}",
             fontsize=7, color=GRAY)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "02_index_overview_table.png")


# ════════════════════════════════════════════════════════════
# 3. 市值风格指数 - 多时间段涨跌幅
# ════════════════════════════════════════════════════════════

def plot_size_style_bar(df: pd.DataFrame) -> Optional[Path]:
    """
    市值风格指数区间涨跌幅分组柱状图
    """
    if df is None or len(df) == 0:
        return None

    periods = ["本周涨跌幅%", "上周涨跌幅%", "近一月涨跌幅%", "近三月涨跌幅%", "近半年涨跌幅%"]
    periods = [p for p in periods if p in df.columns]
    if not periods:
        return None

    fig, axes = plt.subplots(1, len(periods), figsize=(16, 5), sharey=False)
    if len(periods) == 1:
        axes = [axes]

    names = df["证券简称"].tolist()
    x = np.arange(len(names))

    for ax, period in zip(axes, periods):
        vals = pd.to_numeric(df[period], errors="coerce").fillna(0).tolist()
        colors = [RED if v >= 0 else GREEN for v in vals]
        bars = ax.barh(x, vals, color=colors, alpha=0.85, height=0.65)
        ax.axvline(0, color=GRAY, linewidth=0.8)
        ax.set_yticks(x)
        ax.set_yticklabels(names, fontsize=8)
        ax.set_title(period.replace("涨跌幅%", ""), fontsize=9, fontweight="bold")
        for bar, val in zip(bars, vals):
            ax.text(bar.get_width() + 0.05 * np.sign(val) + (0.05 if val == 0 else 0),
                    bar.get_y() + bar.get_height()/2,
                    f"{val:+.2f}%" if val != 0 else "0%",
                    va="center", ha="left" if val >= 0 else "right", fontsize=7)

    fig.suptitle("市值风格指数区间涨跌幅", **CHART_STYLE["title_font"], y=1.02)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "03_size_style_bar.png")


# ════════════════════════════════════════════════════════════
# 4. 大小盘轮动
# ════════════════════════════════════════════════════════════

def plot_size_rotation(df: pd.DataFrame) -> Optional[Path]:
    """
    大小盘轮动（均线+通道模型）
    """
    if df is None or len(df) < 20:
        return None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    df = df.sort_values("日期")
    dates = df["日期"]
    ratio = df["大盘/小盘比值"]

    # 上图：均线模型
    ax1.plot(dates, ratio, color="#424242", linewidth=1.0, alpha=0.8, label="大/小盘比值")
    if "20日均线" in df.columns:
        ax1.plot(dates, df["20日均线"], color=GREEN, linewidth=1.5, label="MA20")
    if "60日均线" in df.columns:
        ax1.plot(dates, df["60日均线"], color=ORANGE, linewidth=1.5, label="MA60")
    if "250日均线" in df.columns:
        ax1.plot(dates, df["250日均线"], color=RED, linewidth=2.0, label="MA250")
    ax1.set_title("大小盘轮动-均线模型", fontsize=10, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=8, ncol=4)
    ax1.set_ylabel("比值", fontsize=9)

    # 下图：通道模型（±1σ布林带）
    ma20 = ratio.rolling(20, min_periods=1).mean()
    std20 = ratio.rolling(20, min_periods=1).std()
    upper = ma20 + std20
    lower = ma20 - std20

    ax2.plot(dates, ratio, color=NAVY, linewidth=1.2, label="大/小盘比值")
    ax2.plot(dates, ma20, color="#424242", linewidth=1.0, linestyle="--", alpha=0.7, label="MA20")
    ax2.plot(dates, upper, color=RED, linewidth=0.8, linestyle="--", alpha=0.6, label="+1σ")
    ax2.plot(dates, lower, color=TEAL, linewidth=0.8, linestyle="--", alpha=0.6, label="-1σ")
    ax2.fill_between(dates, lower, upper, alpha=0.08, color=BLUE)
    ax2.set_title("大小盘轮动-通道模型", fontsize=10, fontweight="bold")
    ax2.legend(loc="upper left", fontsize=8, ncol=4)
    ax2.set_ylabel("比值", fontsize=9)

    _fmt_date_axis(ax2, "M")
    fig.suptitle("大小盘轮动分析（沪深300/中证1000）",
                 **CHART_STYLE["title_font"], y=1.01)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "05_size_rotation.png")


# ════════════════════════════════════════════════════════════
# 5. ETF净流入热力图
# ════════════════════════════════════════════════════════════

def plot_etf_netflow(df: pd.DataFrame) -> Optional[Path]:
    """
    宽基ETF日度净流入热力表格（最近25个交易日）
    """
    if df is None or len(df) == 0:
        return None

    etf_cols = [c for c in df.columns if "ETF" in c or "当日累计" in c]
    date_col = "日期"
    if date_col not in df.columns or not etf_cols:
        return None

    disp = df.tail(25)[[date_col] + etf_cols].copy()
    disp[date_col] = pd.to_datetime(disp[date_col]).dt.strftime("%Y-%m-%d")
    disp = disp.sort_values(date_col, ascending=False)

    num_rows, num_cols = len(disp), len(etf_cols)
    fig, ax = plt.subplots(figsize=(max(12, num_cols * 1.8), max(6, num_rows * 0.38 + 1.5)))
    ax.axis("off")

    values = disp[etf_cols].values.astype(float)

    # 颜色映射
    def _flow_color(v):
        if np.isnan(v) or v == 0:
            return "#F5F5F5"
        if v > 0:
            return "#FFCDD2" if v < 10 else ("#EF9A9A" if v < 30 else "#E57373")
        else:
            return "#C8E6C9" if v > -10 else ("#A5D6A7" if v > -30 else "#81C784")

    cell_colors = []
    for i, row in enumerate(disp[[date_col] + etf_cols].values):
        row_colors = ["#EEEEEE"]  # 日期列
        for v in row[1:]:
            try:
                row_colors.append(_flow_color(float(v)))
            except:
                row_colors.append("#F5F5F5")
        cell_colors.append(row_colors)

    fmt_values = []
    for row in disp[[date_col] + etf_cols].values:
        fmt_row = [str(row[0])]
        for v in row[1:]:
            try:
                fv = float(v)
                fmt_row.append(f"{fv:+.2f}" if not np.isnan(fv) else "/")
            except:
                fmt_row.append("/")
        fmt_values.append(fmt_row)

    tbl = ax.table(
        cellText=fmt_values,
        colLabels=[date_col] + etf_cols,
        cellLoc="center", loc="center",
        cellColours=cell_colors,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1, 1.35)

    for j in range(len([date_col] + etf_cols)):
        tbl[0, j].set_facecolor(NAVY)
        tbl[0, j].set_text_props(color="white", fontweight="bold")

    ax.set_title("代表宽基ETF日度净流入额/亿元（正=流入红，负=流出绿）",
                 **CHART_STYLE["title_font"], pad=16)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "04_etf_netflow.png")


# ════════════════════════════════════════════════════════════
# 6. 行业涨跌幅热力表
# ════════════════════════════════════════════════════════════

def plot_industry_heatmap(df: pd.DataFrame, title: str = "行业涨跌幅",
                          filename: str = "industry_heatmap.png") -> Optional[Path]:
    """
    行业涨跌幅热力表格（通用）
    """
    if df is None or len(df) == 0:
        return None

    name_col = None
    for c in ["证券简称", "指数简称", "名称", "品种简称"]:
        if c in df.columns:
            name_col = c
            break
    if not name_col:
        return None

    pct_cols = [c for c in df.columns if "涨跌幅" in c or "当日涨跌" in c]
    display_cols = [name_col] + pct_cols[:6]
    if "PE" in df.columns:
        display_cols.append("PE")
    if "PB" in df.columns:
        display_cols.append("PB")

    disp = df[[c for c in display_cols if c in df.columns]].copy()

    # 排序
    if pct_cols:
        sort_col = pct_cols[0]
        disp[sort_col] = pd.to_numeric(disp[sort_col], errors="coerce")
        disp = disp.sort_values(sort_col, ascending=False)

    fig_h = max(5, len(disp) * 0.32 + 1.8)
    fig, ax = plt.subplots(figsize=(14, fig_h))
    ax.axis("off")

    def cell_color(col, val):
        if "涨跌" in col:
            try:
                v = float(val)
                if v >= 3: return "#EF5350"
                if v >= 1: return "#FFCDD2"
                if v >= 0: return "#FFEBEE"
                if v >= -1: return "#E8F5E9"
                if v >= -3: return "#C8E6C9"
                return "#81C784"
            except:
                return "#F5F5F5"
        return "#FAFAFA"

    cols = disp.columns.tolist()
    cell_colors = [
        [cell_color(col, val) for col, val in zip(cols, row)]
        for row in disp.values
    ]

    def fmt_val(col, val):
        if pd.isna(val) or val == "/":
            return "/"
        if "涨跌" in col:
            try:
                return f"{float(val):+.2f}%"
            except:
                return str(val)
        return str(val)

    fmt_data = [
        [fmt_val(col, val) for col, val in zip(cols, row)]
        for row in disp.values
    ]

    tbl = ax.table(cellText=fmt_data, colLabels=cols,
                   cellLoc="center", loc="center",
                   cellColours=cell_colors)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1, 1.3)
    for j in range(len(cols)):
        tbl[0, j].set_facecolor(NAVY)
        tbl[0, j].set_text_props(color="white", fontweight="bold")

    ax.set_title(title, **CHART_STYLE["title_font"], pad=14)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, filename, subdir="industry")


# ════════════════════════════════════════════════════════════
# 7. 商品指数走势
# ════════════════════════════════════════════════════════════

def plot_commodity_indices(df: pd.DataFrame) -> Optional[Path]:
    """
    南华商品指数板块走势（6个子图）
    """
    if df is None or len(df) == 0:
        return None

    # 如果是宽格式（品种为列），尝试画多条线
    date_col = None
    for c in ["日期", "date", "Date"]:
        if c in df.columns:
            date_col = c
            break
    if not date_col:
        return None

    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)

    # 尝试识别指数列
    index_cols = [c for c in df.columns if any(
        kw in c for kw in ["贵金属", "有色", "黑色", "工业", "农产", "能化"]
    )]
    if not index_cols:
        index_cols = [c for c in df.columns if c != date_col][:6]

    n = len(index_cols)
    cols_per_row = 3
    rows = (n + cols_per_row - 1) // cols_per_row

    fig, axes = plt.subplots(rows, cols_per_row,
                             figsize=(14, 4.5 * rows), squeeze=False)
    colors = [RED, BLUE, GREEN, ORANGE, TEAL, NAVY]

    for i, col in enumerate(index_cols):
        ax = axes[i // cols_per_row][i % cols_per_row]
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        sub_dates = df.loc[series.index, date_col]
        ax.plot(sub_dates, series, color=colors[i % len(colors)], linewidth=1.5)
        ax.fill_between(sub_dates, series, alpha=0.1, color=colors[i % len(colors)])
        ax.set_title(col, fontsize=9, fontweight="bold")
        _fmt_date_axis(ax, "M")
        ax.set_ylabel("点", fontsize=8)

    # 隐藏多余子图
    for i in range(n, rows * cols_per_row):
        axes[i // cols_per_row][i % cols_per_row].set_visible(False)

    fig.suptitle("南华商品指数-走势", **CHART_STYLE["title_font"], y=1.01)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "07_commodity_indices.png")


# ════════════════════════════════════════════════════════════
# 8. 黄金-原油走势
# ════════════════════════════════════════════════════════════

def plot_gold_oil(gold_df: pd.DataFrame, oil_df: pd.DataFrame) -> Optional[Path]:
    """
    黄金-原油期货收盘价走势（双Y轴）
    """
    if (gold_df is None or len(gold_df) == 0) and (oil_df is None or len(oil_df) == 0):
        return None

    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax2 = ax1.twinx()

    if gold_df is not None and len(gold_df) > 0:
        gcol = [c for c in gold_df.columns if "黄金" in c or "close" in c.lower()][0]
        gold_df["日期"] = pd.to_datetime(gold_df.get("日期", gold_df.get("date", gold_df.index)))
        ax1.plot(gold_df["日期"], gold_df[gcol], color=RED, linewidth=1.5, label="COMEX黄金")
        ax1.set_ylabel("美元/盎司", color=RED, fontsize=9)
        ax1.tick_params(axis="y", labelcolor=RED)

    if oil_df is not None and len(oil_df) > 0:
        ocol = [c for c in oil_df.columns if "原油" in c or "close" in c.lower()][0]
        oil_df["日期"] = pd.to_datetime(oil_df.get("日期", oil_df.get("date", oil_df.index)))
        ax2.plot(oil_df["日期"], oil_df[ocol], color="#424242", linewidth=1.2, label="布伦特原油")
        ax2.set_ylabel("美元/桶", color="#424242", fontsize=9)
        ax2.tick_params(axis="y", labelcolor="#424242")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)

    ax1.set_title("黄金-原油-期货收盘价", **CHART_STYLE["title_font"], pad=12)
    _fmt_date_axis(ax1, "M")
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "08_gold_oil.png", subdir="macro")


# ════════════════════════════════════════════════════════════
# 9. A股成交量
# ════════════════════════════════════════════════════════════

def plot_market_volume(df: pd.DataFrame) -> Optional[Path]:
    """
    A股成交金额跟踪（柱状+指数折线）
    """
    if df is None or len(df) < 5:
        return None

    df = df.sort_values("日期")
    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax2 = ax1.twinx()

    vol_col = "成交额(亿元)" if "成交额(亿元)" in df.columns else "成交额"
    idx_col = "收盘"

    ax1.bar(df["日期"], df[vol_col], color=BLUE, alpha=0.6, label="成交额(亿元)", width=1.5)
    ax2.plot(df["日期"], df[idx_col], color=RED, linewidth=1.5, label="万得全A")

    # 最新值标注
    last = df.iloc[-1]
    ax1.annotate(f"{last[vol_col]:,.0f}亿元",
                 xy=(last["日期"], last[vol_col]),
                 xytext=(0, 8), textcoords="offset points",
                 fontsize=8, color=BLUE, ha="center")

    ax1.set_ylabel("成交额(亿元)", fontsize=9)
    ax2.set_ylabel("万得全A指数", fontsize=9, color=RED)
    ax2.tick_params(axis="y", labelcolor=RED)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    ax1.set_title("A股成交金额跟踪", **CHART_STYLE["title_font"], pad=12)
    _fmt_date_axis(ax1, "M")
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "09_market_volume.png")


# ════════════════════════════════════════════════════════════
# 10. 融资余额
# ════════════════════════════════════════════════════════════

def plot_margin_balance(df: pd.DataFrame) -> Optional[Path]:
    """
    A股融资余额走势
    """
    if df is None or len(df) < 5:
        return None

    df = df.sort_values("日期") if "日期" in df.columns else df

    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax2 = ax1.twinx()

    # 融资余额
    bal_col = next((c for c in df.columns if "融资余额" in c or "融资" in c and "买入" not in c), None)
    chg_col = next((c for c in df.columns if "变化" in c or "净买入" in c or "融资买入" in c), None)
    date_col = "日期" if "日期" in df.columns else df.columns[0]

    if bal_col:
        ax1.plot(df[date_col], pd.to_numeric(df[bal_col], errors="coerce"),
                 color=RED, linewidth=2.0, label="融资余额(亿元)")
        last_val = pd.to_numeric(df[bal_col], errors="coerce").iloc[-1]
        ax1.set_ylabel("融资余额(亿元)", color=RED, fontsize=9)
        ax1.tick_params(axis="y", labelcolor=RED)
        ax1.annotate(f"{last_val:,.0f}亿元",
                     xy=(df[date_col].iloc[-1], last_val),
                     xytext=(5, 0), textcoords="offset points", fontsize=8, color=RED)

    if chg_col:
        chg = pd.to_numeric(df[chg_col], errors="coerce")
        colors = [RED if v >= 0 else GREEN for v in chg]
        ax2.bar(df[date_col], chg, color=colors, alpha=0.5, width=1.5, label="日变化(亿元)")
        ax2.set_ylabel("日变化(亿元)", fontsize=9)
        ax2.axhline(0, color=GRAY, linewidth=0.8)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    ax1.set_title("A股融资余额", **CHART_STYLE["title_font"], pad=12)
    _fmt_date_axis(ax1, "M")
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "10_margin_balance.png")


# ════════════════════════════════════════════════════════════
# 11. 宏观高频多子图（房产/钢铁/消费/汽车）
# ════════════════════════════════════════════════════════════

def plot_macro_real_estate(data: Dict) -> Optional[Path]:
    """
    房地产高频数据四格图：挂牌价、7城成交、土地成交、30城商品房
    """
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    axes = axes.flatten()

    panels = [
        ("second_hand_7",    "7城二手房成交套数（7日移动平均）", BLUE),
        ("commercial_sales_30", "30大中城市商品房成交面积", RED),
        ("land_transaction_100", "100大中城市土地成交面积", ORANGE),
        ("second_hand_sh",   "北上深二手房成交（7日移动平均）", TEAL),
    ]
    plotted = 0
    for ax, (key, title, color) in zip(axes, panels):
        df = data.get(key)
        if df is None or len(df) == 0:
            ax.set_visible(False)
            continue
        date_col = next((c for c in df.columns if "日期" in c or "date" in str(c).lower()), None)
        val_col  = next((c for c in df.columns if c != date_col), None)
        if not date_col or not val_col:
            ax.set_visible(False)
            continue
        df[date_col] = pd.to_datetime(df[date_col])
        series = pd.to_numeric(df[val_col], errors="coerce")
        ax.plot(df[date_col], series, color=color, linewidth=1.5)
        ax.fill_between(df[date_col], series, alpha=0.12, color=color)
        ax.set_title(title, fontsize=9, fontweight="bold")
        _fmt_date_axis(ax, "M")
        plotted += 1

    if plotted == 0:
        plt.close(fig)
        return None

    fig.suptitle("宏观高频-房地产市场", **CHART_STYLE["title_font"], y=1.01)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "11_macro_realestate.png", subdir="macro")


def plot_macro_consumption(data: Dict) -> Optional[Path]:
    """
    消费高频：猪肉/水果价格、豆油、汽车销量
    """
    keys_titles = [
        ("pork_price",  "中国平均批发价:猪肉",  RED),
        ("fruit_price", "中国平均批发价:水果(6种)",  ORANGE),
        ("bean_oil_price", "中国平均价:豆油", GREEN),
        ("auto_sales",  "中国乘用车日均销量", BLUE),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    axes = axes.flatten()
    plotted = 0
    for ax, (key, title, color) in zip(axes, keys_titles):
        df = data.get(key)
        if df is None or len(df) == 0:
            ax.set_visible(False)
            continue
        date_col = next((c for c in df.columns if "日期" in c or "date" in str(c).lower()), None)
        val_col  = next((c for c in df.columns if c != date_col), None)
        if not date_col or not val_col:
            ax.set_visible(False)
            continue
        df[date_col] = pd.to_datetime(df[date_col])
        series = pd.to_numeric(df[val_col], errors="coerce")
        ax.plot(df[date_col], series, color=color, linewidth=1.5)
        ax.fill_between(df[date_col], series, alpha=0.1, color=color)
        ax.set_title(title, fontsize=9, fontweight="bold")
        _fmt_date_axis(ax, "M")
        plotted += 1

    if plotted == 0:
        plt.close(fig)
        return None

    fig.suptitle("宏观高频-消费价格", **CHART_STYLE["title_font"], y=1.01)
    _brand_stamp(fig)
    fig.tight_layout()
    return _save(fig, "12_macro_consumption.png", subdir="macro")


# ════════════════════════════════════════════════════════════
# 主函数：生成所有图表
# ════════════════════════════════════════════════════════════

def generate_all_charts(data: Dict) -> Dict[str, Optional[Path]]:
    """
    统一入口：根据抓取到的数据生成所有图表
    返回 {图表名: 文件路径} 字典
    """
    logger.info("═" * 50)
    logger.info("开始生成图表")
    paths = {}

    # 先导指数
    if "leading_index" in data.get("sentiment", {}):
        paths["leading_index"] = plot_leading_index(data["sentiment"]["leading_index"])

    # 权益指数总览
    if "index_overview" in data.get("equity", {}):
        paths["index_overview"] = plot_index_overview_table(data["equity"]["index_overview"])

    # 市值风格
    if "size_style" in data.get("equity", {}):
        paths["size_style"] = plot_size_style_bar(data["equity"]["size_style"])

    # ETF净流入
    if "etf_netflow" in data.get("equity", {}):
        paths["etf_netflow"] = plot_etf_netflow(data["equity"]["etf_netflow"])

    # 大小盘轮动
    if "size_rotation" in data.get("sentiment", {}):
        paths["size_rotation"] = plot_size_rotation(data["sentiment"]["size_rotation"])

    # 行业涨跌幅
    if "industry_returns" in data.get("equity", {}):
        paths["industry"] = plot_industry_heatmap(
            data["equity"]["industry_returns"],
            title="股票-行业涨跌幅（申万一级）",
            filename="06_industry_returns.png"
        )

    # 商品指数
    if "nanhua_indices" in data.get("commodity", {}):
        paths["commodity"] = plot_commodity_indices(data["commodity"]["nanhua_indices"])

    # 黄金原油
    paths["gold_oil"] = plot_gold_oil(
        data.get("commodity", {}).get("gold"),
        data.get("commodity", {}).get("oil"),
    )

    # A股成交
    if "market_volume" in data.get("sentiment", {}):
        paths["market_volume"] = plot_market_volume(data["sentiment"]["market_volume"])

    # 融资余额
    if "margin_history" in data.get("sentiment", {}):
        paths["margin"] = plot_margin_balance(data["sentiment"]["margin_history"])

    # 宏观高频
    if "macro" in data:
        paths["realestate"] = plot_macro_real_estate(data["macro"].get("real_estate", {}))
        paths["consumption"] = plot_macro_consumption({
            "pork_price":  data["macro"].get("consumption", {}).get("pork_price"),
            "fruit_price": data["macro"].get("consumption", {}).get("fruit_price"),
            "bean_oil_price": data["macro"].get("consumption", {}).get("bean_oil_price"),
            "auto_sales":  data["macro"].get("auto_sales"),
        })

    # 汇总输出
    success = sum(1 for v in paths.values() if v is not None)
    logger.info(f"图表生成完成: {success}/{len(paths)} 成功")
    return paths
