"""
main.py - 市场跟踪周报自动化主入口
══════════════════════════════════════════════════════════
用法：
  python main.py                  # 全量运行（抓取→存储→图表→报告）
  python main.py --skip-fetch     # 跳过抓取，直接用本地数据库生成图表+报告
  python main.py --charts-only    # 只重新生成图表和报告（不抓取、不落库）
  python main.py --report-only    # 只重新渲染 HTML 报告
  python main.py --export-csv     # 额外导出所有表的 CSV
  python main.py --symbols 000300 000905   # 只抓取指定指数
  python main.py --lookback 90    # 修改历史回溯天数（默认 380）
  python main.py --debug             # 开启详细日志

流程：
  1. DataFetcher   → 多接口抓取、随机 UA、指数退避重试
  2. DataStorage   → SQLite 增量存储、防重复写入
  3. ChartMaker    → matplotlib 生成 13 类图表（PNG）
  4. ReportGenerator → Jinja2 渲染 HTML 报告（图片 base64 内嵌）
══════════════════════════════════════════════════════════
"""

import os
import sys
import logging
import argparse
import datetime
import sqlite3
import traceback
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 本地模块 ────────────────────────────────────────────
from config import (
    OUTPUT_DIR, DB_PATH, CHART_DIR, REPORT_DIR,
    A_SHARE_INDICES, BROAD_ETFS,
)
from fetcher import DataFetcher
from storage import DataStorage
from charts import ChartMaker
from report_generator import ReportGenerator


# ════════════════════════════════════════════════════════
#  日志配置
# ════════════════════════════════════════════════════════
def _setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt, datefmt))

    # 文件（按日期滚动）
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    log_file = f"{OUTPUT_DIR}/run_{datetime.date.today():%Y%m%d}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt, datefmt))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(fh)


logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════
#  CLI 参数
# ════════════════════════════════════════════════════════
def _parse_args():
    p = argparse.ArgumentParser(
        description="市场跟踪周报自动化 - 数据抓取 / 图表 / HTML报告",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--skip-fetch", action="store_true",
        help="跳过数据抓取，直接从本地数据库读取数据生成图表和报告",
    )
    p.add_argument(
        "--charts-only", action="store_true",
        help="仅重新生成图表和报告（不抓取，不落库）",
    )
    p.add_argument(
        "--report-only", action="store_true",
        help="仅重新渲染 HTML 报告（图表已存在）",
    )
    p.add_argument(
        "--export-csv", action="store_true",
        help="生成完毕后额外把数据库所有表导出为 CSV",
    )
    p.add_argument(
        "--symbols", nargs="+", metavar="SYM",
        help="只抓取指定指数代码（空格分隔），如 000300 000905",
    )
    p.add_argument(
        "--lookback", type=int, default=380,
        help="历史回溯天数（默认 380）",
    )
    p.add_argument(
        "--debug", action="store_true",
        help="开启 DEBUG 日志",
    )
    p.add_argument(
        "--db", default=DB_PATH,
        help=f"SQLite 数据库路径（默认 {DB_PATH}）",
    )
    return p.parse_args()


# ════════════════════════════════════════════════════════
#  从数据库重建 data 字典（skip-fetch 模式使用）
# ════════════════════════════════════════════════════════
def _load_data_from_db(storage: DataStorage, lookback: int = 380) -> dict:
    """从 SQLite 读取已有数据，组装成与 fetcher.fetch_all() 相同结构的 dict"""
    logger.info("从本地数据库加载数据...")
    data: dict = {}
    conn = storage.conn

    # ── A股指数日线 ──────────────────────────────
    index_daily: dict = {}
    try:
        df_all = pd.read_sql_query(
            "SELECT * FROM index_daily ORDER BY date",
            conn
        )
        if not df_all.empty:
            cutoff = (datetime.date.today() - datetime.timedelta(days=lookback)).strftime("%Y-%m-%d")
            df_all = df_all[df_all["date"] >= cutoff]
            for sym, grp in df_all.groupby("symbol"):
                grp = grp.copy()
                grp["date"] = pd.to_datetime(grp["date"])
                index_daily[sym] = grp
            logger.info(f"  index_daily: {len(index_daily)} 只指数")
    except Exception as e:
        logger.warning(f"读取 index_daily 失败: {e}")
    data["index_daily"] = index_daily

    # ── ETF 日线 ─────────────────────────────────
    etf_flows: dict = {}
    try:
        df_etf = pd.read_sql_query("SELECT * FROM etf_daily ORDER BY date", conn)
        if not df_etf.empty:
            for code, grp in df_etf.groupby("code"):
                etf_flows[code] = grp.copy()
            logger.info(f"  etf_daily: {len(etf_flows)} 只ETF")
    except Exception as e:
        logger.warning(f"读取 etf_daily 失败: {e}")
    data["etf_flows"] = etf_flows

    # ── 行业板块 ──────────────────────────────────
    try:
        data["industry_perf"] = pd.read_sql_query(
            "SELECT * FROM industry_perf WHERE date=(SELECT MAX(date) FROM industry_perf)",
            conn
        )
        logger.info(f"  industry_perf: {len(data['industry_perf'])} 行")
    except Exception as e:
        logger.warning(f"读取 industry_perf 失败: {e}")
        data["industry_perf"] = None

    # ── 海外市场 ─────────────────────────────────
    global_indices: dict = {}
    try:
        df_g = pd.read_sql_query("SELECT * FROM global_indices ORDER BY date", conn)
        if not df_g.empty:
            for sym, grp in df_g.groupby("symbol"):
                global_indices[sym] = grp.copy()
            logger.info(f"  global_indices: {len(global_indices)} 个市场")
    except Exception as e:
        logger.warning(f"读取 global_indices 失败: {e}")
    data["global_indices"] = global_indices

    # ── 商品 ─────────────────────────────────────
    nanhua: dict = {}
    try:
        df_c = pd.read_sql_query("SELECT * FROM commodity ORDER BY date", conn)
        if not df_c.empty:
            for code, grp in df_c.groupby("code"):
                nanhua[code] = grp.copy()
            logger.info(f"  commodity: {len(nanhua)} 个品种")
    except Exception as e:
        logger.warning(f"读取 commodity 失败: {e}")
    data["nanhua"] = nanhua

    # ── 其他字段给空值，避免 KeyError ────────────
    data.setdefault("index_valuation", None)
    data.setdefault("cb_index", None)
    data.setdefault("cb_overview", None)
    data.setdefault("sentiment", {})
    data.setdefault("macro", {})
    data.setdefault("ah_premium", None)
    data.setdefault("southbound", None)

    return data


# ════════════════════════════════════════════════════════
#  收集已存在的图表路径（report-only 模式使用）
# ════════════════════════════════════════════════════════
def _collect_existing_charts() -> list:
    chart_dir = Path(CHART_DIR)
    if not chart_dir.exists():
        return []
    paths = sorted(chart_dir.glob("*.png"))
    logger.info(f"已发现 {len(paths)} 张图表")
    return [str(p) for p in paths]


# ════════════════════════════════════════════════════════
#  打印运行摘要
# ════════════════════════════════════════════════════════
def _print_summary(
    data: dict,
    chart_paths: list,
    report_path: Optional[str],
    elapsed: float,
):
    sep = "═" * 60
    logger.info(sep)
    logger.info("  ✅ 市场跟踪周报生成完毕")
    logger.info(sep)
    # 数据概况
    n_idx = len(data.get("index_daily", {}))
    n_etf = len(data.get("etf_flows", {}))
    n_ind = len(data["industry_perf"]) if isinstance(data.get("industry_perf"), pd.DataFrame) else 0
    n_glo = len(data.get("global_indices", {}))
    logger.info(f"  数据概况：指数{n_idx}只 | ETF{n_etf}只 | 行业{n_ind}个 | 海外{n_glo}个")
    # 图表
    n_charts = len([c for c in chart_paths if c and os.path.exists(c)])
    logger.info(f"  图表数量：{n_charts} 张 → {CHART_DIR}/")
    # 报告
    if report_path and os.path.exists(report_path):
        size_kb = os.path.getsize(report_path) // 1024
        logger.info(f"  HTML报告：{report_path}  ({size_kb} KB)")
    # 耗时
    logger.info(f"  总耗时  ：{elapsed:.1f} 秒")
    logger.info(sep)


# ════════════════════════════════════════════════════════
#  主函数
# ════════════════════════════════════════════════════════
def main():
    t0 = datetime.datetime.now()
    args = _parse_args()
    _setup_logging(args.debug)

    logger.info("=" * 60)
    logger.info(f"  市场跟踪周报自动化系统  |  {datetime.date.today()}")
    logger.info("=" * 60)

    # 初始化存储（所有模式都需要）
    storage = DataStorage(db_path=args.db)

    # ── 模式1：仅渲染报告 ─────────────────────────
    if args.report_only:
        logger.info("模式: report-only（仅重新渲染HTML）")
        data = _load_data_from_db(storage, args.lookback)
        chart_paths = _collect_existing_charts()
        report_gen = ReportGenerator()
        report_path = report_gen.generate(data, chart_paths)
        elapsed = (datetime.datetime.now() - t0).total_seconds()
        _print_summary(data, chart_paths, report_path, elapsed)
        storage.close()
        return report_path

    # ── 模式2：仅图表+报告（不抓取） ─────────────
    if args.charts_only or args.skip_fetch:
        mode = "charts-only" if args.charts_only else "skip-fetch"
        logger.info(f"模式: {mode}（从数据库读取，不重新抓取）")
        data = _load_data_from_db(storage, args.lookback)

        logger.info("\n[Step 2/2] 生成图表...")
        chart_maker = ChartMaker()
        chart_paths = chart_maker.generate_all_charts(data)

        logger.info("\n[Step 3/3] 生成HTML报告...")
        report_gen = ReportGenerator()
        report_path = report_gen.generate(data, chart_paths)

        if args.export_csv:
            logger.info("导出 CSV...")
            storage.export_all_csv()

        elapsed = (datetime.datetime.now() - t0).total_seconds()
        _print_summary(data, chart_paths, report_path, elapsed)
        storage.close()
        return report_path

    # ── 模式3（默认）：全量运行 ───────────────────
    logger.info("模式: 全量运行（抓取 → 存储 → 图表 → 报告）")

    # ── Step 1: 数据抓取 ──────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("[Step 1/4] 数据抓取")
    logger.info("─" * 50)

    fetcher = DataFetcher()

    # 若指定了 --symbols，只抓取指定指数，其余正常
    if args.symbols:
        logger.info(f"仅抓取指定指数: {args.symbols}")
        custom_indices = {s: A_SHARE_INDICES.get(s, s) for s in args.symbols}
        # 临时修改 fetcher 内部映射
        import config as _cfg
        _original = _cfg.A_SHARE_INDICES.copy()
        _cfg.A_SHARE_INDICES.clear()
        _cfg.A_SHARE_INDICES.update(custom_indices)

    data = {}
    try:
        data = fetcher.fetch_all()
    except KeyboardInterrupt:
        logger.warning("用户中断抓取，使用已获取的数据继续...")
    except Exception as e:
        logger.error(f"抓取阶段发生异常: {e}")
        logger.debug(traceback.format_exc())
        logger.info("尝试从数据库补充已有数据...")
        data = _load_data_from_db(storage, args.lookback)
    finally:
        if args.symbols:
            # 恢复原始配置
            import config as _cfg
            _cfg.A_SHARE_INDICES.clear()
            _cfg.A_SHARE_INDICES.update(_original)

    if not data:
        logger.warning("未获取到任何数据，尝试从数据库读取...")
        data = _load_data_from_db(storage, args.lookback)

    # ── Step 2: 数据存储 ──────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("[Step 2/4] 数据存储（SQLite）")
    logger.info("─" * 50)
    try:
        storage.save_all(data)
        if args.export_csv:
            logger.info("导出 CSV...")
            storage.export_all_csv()
    except Exception as e:
        logger.error(f"存储阶段异常: {e}")
        logger.debug(traceback.format_exc())

    # ── Step 3: 图表生成 ──────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("[Step 3/4] 图表生成（matplotlib）")
    logger.info("─" * 50)
    chart_paths = []
    try:
        chart_maker = ChartMaker()
        chart_paths = chart_maker.generate_all_charts(data)
        logger.info(f"共生成 {len([p for p in chart_paths if p])} 张图表")
    except Exception as e:
        logger.error(f"图表生成异常: {e}")
        logger.debug(traceback.format_exc())
        chart_paths = _collect_existing_charts()

    # ── Step 4: 报告生成 ──────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("[Step 4/4] HTML 报告生成")
    logger.info("─" * 50)
    report_path = None
    try:
        report_gen = ReportGenerator()
        report_path = report_gen.generate(data, chart_paths)
    except Exception as e:
        logger.error(f"报告生成异常: {e}")
        logger.debug(traceback.format_exc())

    # ── 摘要 ──────────────────────────────────────
    elapsed = (datetime.datetime.now() - t0).total_seconds()
    _print_summary(data, chart_paths, report_path, elapsed)

    storage.close()
    return report_path


# ════════════════════════════════════════════════════════
#  快速验证：检查依赖、目录、数据库连通性
# ════════════════════════════════════════════════════════
def check_env():
    """运行前环境自检，打印检查结果"""
    print("\n── 环境自检 ─────────────────────────────────")

    # 1. Python 版本
    import sys
    v = sys.version_info
    ok = v.major >= 3 and v.minor >= 9
    print(f"  Python {v.major}.{v.minor}.{v.micro}  {'✅' if ok else '❌ 需要 ≥ 3.9'}")

    # 2. 依赖包
    pkgs = ["akshare", "pandas", "numpy", "matplotlib",
            "requests", "tenacity", "jinja2", "openpyxl"]
    for pkg in pkgs:
        try:
            __import__(pkg)
            print(f"  {pkg:<18} ✅")
        except ImportError:
            print(f"  {pkg:<18} ❌ 未安装  →  pip install {pkg}")

    # 3. 目录
    for d in [OUTPUT_DIR, CHART_DIR, REPORT_DIR]:
        Path(d).mkdir(parents=True, exist_ok=True)
        print(f"  目录 {d:<30} ✅")

    # 4. 数据库
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        print(f"  SQLite {DB_PATH:<25} ✅")
    except Exception as e:
        print(f"  SQLite                         ❌ {e}")

    # 5. 网络（AKShare 接口快速 ping）
    try:
        import akshare as ak
        df = ak.stock_zh_index_spot_em()
        ok_net = df is not None and not df.empty
        print(f"  AKShare 网络连通性             {'✅' if ok_net else '❌ 请检查网络'}")
    except Exception as e:
        print(f"  AKShare 网络连通性             ❌ {e}")

    print("────────────────────────────────────────────\n")


# ════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════
if __name__ == "__main__":
    # 特殊子命令：python main.py check
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        check_env()
        sys.exit(0)

    try:
        result = main()
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n⚠️  已手动中断运行。")
        sys.exit(130)
    except Exception as e:
        logging.getLogger(__name__).critical(f"致命错误: {e}", exc_info=True)
        sys.exit(1)
