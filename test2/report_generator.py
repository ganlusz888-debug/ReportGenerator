"""
report_generator.py - HTML 周报自动生成
将所有图表和数据表格组合为完整的 HTML 报告
"""

import os
import base64
import datetime
import logging
from pathlib import Path
from typing import Optional, Dict, List

import numpy as np
import pandas as pd
from jinja2 import Template

from config import (
    REPORT_DIR, REPORT_TITLE, REPORT_SUBTITLE,
    A_SHARE_INDICES, BROAD_ETFS, COLORS
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
#  HTML 模板（内联 CSS，无需外部依赖）
# ─────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }} - {{ report_date }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Microsoft YaHei', '微软雅黑', SimHei, Arial, sans-serif;
    background: #F0F2F5;
    color: #1A1A2E;
    font-size: 13px;
  }
  .page { max-width: 1280px; margin: 0 auto; padding: 20px; }

  /* ── 封面 ── */
  .cover {
    background: linear-gradient(135deg, #1A3A6B 0%, #0E2040 60%, #1A1A2E 100%);
    color: white;
    border-radius: 12px;
    padding: 40px 50px;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .cover h1 { font-size: 28px; letter-spacing: 3px; }
  .cover h2 { font-size: 14px; opacity: 0.7; margin-top: 6px; font-weight: normal; }
  .cover .meta { text-align: right; opacity: 0.8; font-size: 12px; line-height: 1.8; }
  .cover .tag {
    display: inline-block; background: #E84B4B; color: white;
    padding: 2px 10px; border-radius: 3px; font-size: 11px;
    margin-top: 8px;
  }

  /* ── 板块标题 ── */
  .section-title {
    font-size: 15px; font-weight: bold;
    color: #1A3A6B;
    border-left: 4px solid #E84B4B;
    padding-left: 10px;
    margin: 24px 0 12px;
  }

  /* ── 卡片 ── */
  .card {
    background: white;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }

  /* ── 图片容器 ── */
  .chart-wrap {
    background: white;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }
  .chart-wrap img { width: 100%; border-radius: 4px; }

  /* ── 两列布局 ── */
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

  /* ── 数据表格 ── */
  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  .data-table th {
    background: #1A3A6B;
    color: white;
    padding: 6px 10px;
    text-align: center;
    font-weight: normal;
  }
  .data-table td {
    padding: 5px 10px;
    text-align: center;
    border-bottom: 1px solid #F0F0F0;
  }
  .data-table tr:nth-child(even) td { background: #F8F9FB; }
  .up   { color: #E84B4B; font-weight: 500; }
  .down { color: #31B07B; font-weight: 500; }

  /* ── 摘要卡片 ── */
  .summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
  }
  .kpi-card {
    background: white;
    border-radius: 8px;
    padding: 14px 18px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    border-top: 3px solid #1A3A6B;
  }
  .kpi-card .label { font-size: 11px; color: #666; margin-bottom: 4px; }
  .kpi-card .value { font-size: 20px; font-weight: bold; color: #1A3A6B; }
  .kpi-card .change { font-size: 11px; margin-top: 2px; }

  /* ── 脚注 ── */
  .footer {
    text-align: center;
    color: #999;
    font-size: 11px;
    padding: 20px 0;
    border-top: 1px solid #E8E8E8;
    margin-top: 30px;
  }
</style>
</head>
<body>
<div class="page">

  <!-- 封面 -->
  <div class="cover">
    <div>
      <h1>■ {{ title }}</h1>
      <h2>{{ subtitle }}</h2>
      <div class="tag">数据截止 {{ report_date }}</div>
    </div>
    <div class="meta">
      <div>生成时间：{{ gen_time }}</div>
      <div>数据来源：AKShare / Wind</div>
      <div>报告版本：v1.0</div>
    </div>
  </div>

  <!-- ══ 一、中国经济基本面 ══ -->
  <div class="section-title">中国经济基本面先导指数</div>
  <div class="card">
    <p style="color:#666;font-size:12px;margin-bottom:10px;">
      备注：先导指数拟合了多个强经济相关期货品种，高度反映中国经济基本面情况。
      先导指数高于250日均线，表示对经济预期相对乐观，反之悲观。
    </p>
    {% if charts.large_small %}
    <div class="chart-wrap"><img src="{{ charts.large_small }}" alt="大小盘轮动"></div>
    {% endif %}
  </div>

  <!-- ══ 二、A股权益指数总览 ══ -->
  <div class="section-title">A股权益指数总览</div>
  <div class="card">
    {% if index_table %}
    <table class="data-table">
      <thead>
        <tr>
          {% for col in index_table.columns %}
          <th>{{ col }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in index_table.values %}
        <tr>
          {% for i, val in enumerate(row) %}
          <td class="{{ 'up' if (loop.index0 > 0 and val != '—' and val|float > 0) else ('down' if (loop.index0 > 0 and val != '—' and val|float < 0) else '') }}">
            {{ val }}
          </td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </div>
  {% if charts.index_overview %}
  <div class="chart-wrap"><img src="{{ charts.index_overview }}" alt="指数总览"></div>
  {% endif %}

  <!-- ══ 三、市场风格及板块跟踪 ══ -->
  <div class="section-title">市场风格及板块跟踪</div>
  <div class="grid2">
    {% if charts.large_small %}
    <div class="chart-wrap"><img src="{{ charts.large_small }}" alt="大小盘轮动"></div>
    {% endif %}
    {% if charts.growth_value %}
    <div class="chart-wrap"><img src="{{ charts.growth_value }}" alt="成长价值轮动"></div>
    {% endif %}
  </div>

  <!-- ETF净流入 -->
  <div class="section-title">代表宽基ETF净流入</div>
  {% if charts.etf_flows %}
  <div class="chart-wrap"><img src="{{ charts.etf_flows }}" alt="ETF净流入"></div>
  {% endif %}

  <!-- ══ 四、行业板块 ══ -->
  <div class="section-title">股票-行业涨跌幅</div>
  {% if industry_table %}
  <div class="card">
    <table class="data-table">
      <thead>
        <tr>
          {% for col in industry_table.columns %}
          <th>{{ col }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in industry_table.values %}
        <tr>
          {% for val in row %}
          <td class="{{ 'up' if (val != '—' and val is not string and val > 0) else ('down' if (val != '—' and val is not string and val < 0) else '') }}">
            {{ val }}
          </td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
  {% if charts.industry %}
  <div class="chart-wrap"><img src="{{ charts.industry }}" alt="行业热力图"></div>
  {% endif %}

  <!-- ══ 五、可转债 ══ -->
  <div class="section-title">可转债市场</div>
  {% if charts.cb %}
  <div class="chart-wrap"><img src="{{ charts.cb }}" alt="可转债走势"></div>
  {% endif %}

  <!-- ══ 六、香港及海外市场 ══ -->
  <div class="section-title">香港及海外市场</div>
  {% if global_table %}
  <div class="card">
    <table class="data-table">
      <thead>
        <tr>{% for col in global_table.columns %}<th>{{ col }}</th>{% endfor %}</tr>
      </thead>
      <tbody>
        {% for row in global_table.values %}
        <tr>
          {% for val in row %}
          <td>{{ val }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
  <div class="grid2">
    {% if charts.ah %}
    <div class="chart-wrap"><img src="{{ charts.ah }}" alt="AH溢价"></div>
    {% endif %}
    {% if charts.southbound %}
    <div class="chart-wrap"><img src="{{ charts.southbound }}" alt="南向资金"></div>
    {% endif %}
  </div>

  <!-- ══ 七、商品指数 ══ -->
  <div class="section-title">商品指数</div>
  {% if commodity_table %}
  <div class="card">
    <table class="data-table">
      <thead>
        <tr>{% for col in commodity_table.columns %}<th>{{ col }}</th>{% endfor %}</tr>
      </thead>
      <tbody>
        {% for row in commodity_table.values %}
        <tr>{% for val in row %}<td>{{ val }}</td>{% endfor %}</tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
  {% if charts.nanhua %}
  <div class="chart-wrap"><img src="{{ charts.nanhua }}" alt="南华商品指数"></div>
  {% endif %}
  {% if charts.gold_oil %}
  <div class="chart-wrap"><img src="{{ charts.gold_oil }}" alt="黄金原油"></div>
  {% endif %}

  <!-- ══ 八、市场情绪 ══ -->
  <div class="section-title">市场情绪</div>
  <div class="grid2">
    {% if charts.turnover %}
    <div class="chart-wrap"><img src="{{ charts.turnover }}" alt="A股成交额"></div>
    {% endif %}
    {% if charts.margin %}
    <div class="chart-wrap"><img src="{{ charts.margin }}" alt="融资余额"></div>
    {% endif %}
  </div>

  <!-- ══ 九、宏观高频 ══ -->
  <div class="section-title">宏观高频数据</div>
  {% if charts.real_estate %}
  <div class="chart-wrap"><img src="{{ charts.real_estate }}" alt="房地产高频"></div>
  {% endif %}

  <!-- 脚注 -->
  <div class="footer">
    本报告数据来源于公开市场数据，仅供参考，不构成投资建议。
    &copy; {{ year }} 市场跟踪周报自动化系统
  </div>
</div>
</body>
</html>
"""


# ════════════════════════════════════════════════
class ReportGenerator:

    def __init__(self):
        Path(REPORT_DIR).mkdir(parents=True, exist_ok=True)

    # ─── 图片转 base64 ────────────────────────────
    @staticmethod
    def _img_to_b64(path: str) -> str:
        """将图片文件转为 base64 data URI，以便内嵌 HTML"""
        if not path or not os.path.exists(path):
            return ""
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{b64}"

    # ─── 构建索引摘要表 ──────────────────────────
    def _build_index_table(
        self, index_data: Dict[str, pd.DataFrame]
    ) -> Optional[pd.DataFrame]:
        rows = []
        for sym, df in index_data.items():
            if df is None or df.empty:
                continue
            name = A_SHARE_INDICES.get(sym, sym)
            df = df.sort_values("date").copy()
            df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")

            def _sum(n): return round(df["pct_chg"].tail(n).sum(), 2)

            rows.append({
                "指数简称": name,
                "本周涨跌%": _sum(5),
                "上周涨跌%": df["pct_chg"].tail(10).head(5).sum().round(2),
                "近1月%": _sum(21),
                "近3月%": _sum(63),
                "近半年%": _sum(126),
                "今年以来%": _sum(252),
            })
        if not rows:
            return None
        tbl = pd.DataFrame(rows)
        # 格式化为字符串
        for c in tbl.columns:
            if c != "指数简称":
                tbl[c] = tbl[c].apply(lambda x: f"{x:+.2f}" if not pd.isna(x) else "—")
        return tbl

    # ─── 构建行业表 ──────────────────────────────
    def _build_industry_table(
        self, industry_df: Optional[pd.DataFrame]
    ) -> Optional[pd.DataFrame]:
        if industry_df is None or industry_df.empty:
            return None
        df = industry_df.copy()
        name_col = next((c for c in ["板块名称","name","行业"] if c in df.columns), None)
        pct_col  = next((c for c in ["涨跌幅","pct_chg"] if c in df.columns), None)
        if not name_col or not pct_col:
            return None
        df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")
        df = df.sort_values(pct_col, ascending=False)
        out = pd.DataFrame({
            "行业名称":  df[name_col].values,
            "当日涨跌%": df[pct_col].apply(lambda x: f"{x:+.2f}" if not pd.isna(x) else "—").values,
        })
        return out

    # ─── 构建商品表 ──────────────────────────────
    def _build_commodity_table(
        self, nanhua_data: Dict[str, pd.DataFrame]
    ) -> Optional[pd.DataFrame]:
        rows = []
        for name, df in nanhua_data.items():
            if df is None or df.empty:
                continue
            val_col = next((c for c in ["收盘","close","指数"] if c in df.columns), None)
            if not val_col:
                continue
            df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
            df = df.dropna(subset=[val_col])
            if len(df) < 2:
                continue
            latest = df[val_col].iloc[-1]
            prev   = df[val_col].iloc[-2]
            chg    = (latest - prev) / prev * 100 if prev != 0 else np.nan
            rows.append({"指数名称": name, "最新值": f"{latest:.2f}",
                         "日涨跌%": f"{chg:+.2f}" if not np.isnan(chg) else "—"})
        if not rows:
            return None
        return pd.DataFrame(rows)

    # ─── 构建海外市场表 ──────────────────────────
    def _build_global_table(
        self, global_data: Dict[str, pd.DataFrame]
    ) -> Optional[pd.DataFrame]:
        rows = []
        for sym, df in global_data.items():
            if df is None or df.empty:
                continue
            name = df["name"].iloc[-1] if "name" in df.columns else sym
            pct_col = next((c for c in ["涨跌幅","pct_chg","change"] if c in df.columns), None)
            if not pct_col:
                continue
            latest_pct = pd.to_numeric(df[pct_col].iloc[-1], errors="coerce")
            rows.append({"市场": name,
                         "当日涨跌%": f"{latest_pct:+.2f}" if not np.isnan(latest_pct) else "—"})
        return pd.DataFrame(rows) if rows else None

    # ─── 主入口 ──────────────────────────────────
    def generate(
        self,
        data: dict,
        chart_paths: List[str],
    ) -> str:
        today = datetime.date.today().strftime("%Y.%m.%d")
        gen_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        year = datetime.date.today().year

        # 将图表路径列表映射为名称 -> b64
        def _get(partial_name: str) -> str:
            for p in chart_paths:
                if p and partial_name in os.path.basename(p):
                    return self._img_to_b64(p)
            return ""

        charts_ctx = {
            "index_overview": _get("01_index"),
            "large_small":    _get("02_large"),
            "etf_flows":      _get("03_etf"),
            "industry":       _get("04_industry"),
            "growth_value":   _get("05_growth"),
            "turnover":       _get("06_a_share"),
            "nanhua":         _get("07_nanhua"),
            "gold_oil":       _get("08_gold"),
            "ah":             _get("09_ah"),
            "southbound":     _get("10_south"),
            "margin":         _get("11_margin"),
            "cb":             _get("12_conv"),
            "real_estate":    _get("13_real"),
        }

        # 构建数据表
        index_table    = self._build_index_table(data.get("index_daily", {}))
        industry_table = self._build_industry_table(data.get("industry_perf"))
        commodity_table = self._build_commodity_table(data.get("nanhua", {}))
        global_table   = self._build_global_table(data.get("global_indices", {}))

        # Jinja2 不支持 enumerate，需自定义
        template = Template(HTML_TEMPLATE)
        # 注入 enumerate 为全局
        template.globals["enumerate"] = enumerate

        html = template.render(
            title=REPORT_TITLE,
            subtitle=REPORT_SUBTITLE,
            report_date=today,
            gen_time=gen_time,
            year=year,
            charts=charts_ctx,
            index_table=index_table,
            industry_table=industry_table,
            commodity_table=commodity_table,
            global_table=global_table,
        )

        out_path = f"{REPORT_DIR}/market_report_{today.replace('.','')}.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"HTML报告已生成: {out_path}")
        return out_path
