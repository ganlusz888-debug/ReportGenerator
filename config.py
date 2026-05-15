"""
市场跟踪周报 — 配置文件
"""
from pathlib import Path
from datetime import datetime, timedelta

# ── 目录结构 ──────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
CACHE_DIR   = DATA_DIR / "cache"
OUTPUT_DIR  = BASE_DIR / "output"
REPORT_DIR  = OUTPUT_DIR / "reports"

for _d in [DATA_DIR, CACHE_DIR, OUTPUT_DIR, REPORT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── 日期 ─────────────────────────────────────────────────
TODAY        = datetime.now()
REPORT_DATE  = TODAY.strftime("%Y%m%d")
REPORT_DATE_CN = TODAY.strftime("%Y.%m.%d")
START_1Y     = (TODAY - timedelta(days=365)).strftime("%Y%m%d")
START_3Y     = (TODAY - timedelta(days=365*3)).strftime("%Y%m%d")
START_5Y     = (TODAY - timedelta(days=365*5)).strftime("%Y%m%d")

# ── 网络请求 ──────────────────────────────────────────────
REQUEST_DELAY   = 5   # 秒，请求间隔（防封IP）
MAX_RETRIES     = 3
REQUEST_TIMEOUT = 30
CACHE_TTL       = 6 * 3600  # 6小时缓存

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# ── A股宽基指数 ───────────────────────────────────────────
A_SHARE_INDICES = {
    "沪深300":     {"code": "000300", "em_code": "000300"},
    "上证50":      {"code": "000016", "em_code": "000016"},
    "中证500":     {"code": "000905", "em_code": "000905"},
    "中证1000":    {"code": "000852", "em_code": "000852"},
    "中证2000":    {"code": "932000", "em_code": "932000"},
    "中证A500":    {"code": "000510", "em_code": "000510"},
    "万得全A":     {"code": "881001", "em_code": "881001"},
    "创业板50":    {"code": "399673", "em_code": "399673"},
    "科创50":      {"code": "000688", "em_code": "000688"},
    "科创100":     {"code": "000698", "em_code": "000698"},
    "北证50":      {"code": "899050", "em_code": "899050"},
    "中证红利":    {"code": "000922", "em_code": "000922"},
    "中证转债":    {"code": "000832", "em_code": "000832"},
    "万得可转债等权": {"code": "885049", "em_code": "885049"},
}

# ── 港股/海外指数 ──────────────────────────────────────────
GLOBAL_INDICES = {
    "恒生指数":     "HSI",
    "恒生科技":     "HSTECH",
    "恒生国企":     "HSCEI",
    "道琼斯工业指数": "DJI",
    "纳斯达克指数":  "IXIC",
    "标普500":      "SPX",
    "德国DAX":      "GDAXI",
    "法国CAC40":    "FCHI",
    "英国富时100":   "FTSE",
    "日经225":      "N225",
    "韩国综合指数":  "KS11",
    "印度SENSEX30":  "BSESN",
}

# ── 代表性宽基ETF ──────────────────────────────────────────
BROAD_ETFS = {
    "上证50ETF":    "510050",
    "沪深300ETF":   "510300",
    "中证500ETF":   "510500",
    "中证1000ETF":  "512100",
    "中证2000ETF":  "563300",
    "创业板ETF":    "159915",
    "科创50ETF":    "588000",
}

# ── 申万一级行业 ───────────────────────────────────────────
SW_LEVEL1_INDUSTRIES = [
    "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "家用电器",
    "食品饮料", "纺织服饰", "轻工制造", "医药生物", "公用事业", "交通运输",
    "房地产", "商贸零售", "社会服务", "银行", "非银金融", "综合",
    "建筑材料", "建筑装饰", "电力设备", "机械设备", "国防军工", "计算机",
    "传媒", "通信", "煤炭", "石油石化", "环保", "美容护理",
]

# ── 科技+先进制造细分行业（申万二级/三级）─────────────────
TECH_MFG_INDUSTRIES = [
    "航天装备Ⅱ", "工程机械", "军工电子Ⅱ", "通信设备", "光学光电子",
    "风电设备", "家电零部件Ⅱ", "专用设备", "自动化设备", "电网设备",
    "通用设备", "航空装备Ⅱ", "汽车零部件", "消费电子", "半导体",
    "电子化学品Ⅱ", "电机Ⅱ", "电池", "计算机设备", "元件",
    "影视院线", "轨交装备Ⅱ", "光伏设备", "软件开发", "IT服务Ⅱ",
    "游戏Ⅱ", "数字媒体",
]

# ── 商品品种 ───────────────────────────────────────────────
COMMODITY_CATEGORIES = {
    "贵金属": ["SHFE白银", "SHFE黄金"],
    "能源化工": ["INE原油", "SHFE燃油", "DCE LPG", "SHFE橡胶", "DCE塑料",
                "CZCE PTA", "DCE乙二醇", "DCE聚丙烯", "CZCE尿素", "CZCE纯碱"],
    "黑色": ["DCE焦炭", "DCE焦煤", "CZCE动力煤", "SHFE螺纹钢", "DCE铁矿石",
            "SHFE热轧卷板", "SHFE不锈钢"],
    "有色": ["SHFE铜", "SHFE铝", "SHFE锌", "SHFE锡", "INE国际铜"],
    "农产品": ["DCE豆一", "DCE玉米", "DCE豆油", "CZCE菜油", "CZCE白糖",
              "DCE鸡蛋", "CZCE苹果"],
}

# ── 南华商品指数 ───────────────────────────────────────────
NANHUA_INDICES = {
    "南华贵金属指数": "NH0100.NHF",
    "南华有色金属指数": "NH0200.NHF",
    "南华黑色指数":   "NH0300.NHF",
    "南华工业品指数": "NH0400.NHF",
    "南华农产品指数": "NH0500.NHF",
    "南华能化指数":   "NH0600.NHF",
}

# ── 图表样式 ───────────────────────────────────────────────
CHART_STYLE = {
    "figure_dpi":   150,
    "fig_width":    16,
    "fig_height":   9,
    "bg_color":     "#FFFFFF",
    "grid_color":   "#E8E8E8",
    "text_color":   "#333333",
    "red_color":    "#D94F4F",
    "green_color":  "#4CAF50",
    "blue_color":   "#2196F3",
    "orange_color": "#FF9800",
    "title_font":   {"fontsize": 14, "fontweight": "bold", "color": "#1A1A2E"},
    "label_font":   {"fontsize": 9,  "color": "#555555"},
}

# ── 报告样式 ───────────────────────────────────────────────
REPORT_TITLE = "市场跟踪周报"
REPORT_BRAND = "中钊资本"
