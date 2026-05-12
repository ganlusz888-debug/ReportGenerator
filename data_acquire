import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ==================== 配置 ====================
end_date = '20251206'  # 周报截止日期，格式 YYYYMMDD
start_date_week = (datetime.strptime(end_date, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')

print(f"数据截止: {end_date}")

# ==================== 1. 主要宽基指数行情 & 涨跌幅 ====================
index_list = {
    '沪深300': '000300', '上证50': '000016', '中证500': '000905',
    '创业板指': '399006', '科创50': '000688', '中证1000': '000852',
    '中证2000': '000852',  # 可能需调整
    '万得全A': '000001'    # 上证或全A近似
}

def get_index_returns(symbols, period='daily'):
    data = []
    for name, code in symbols.items():
        try:
            df = ak.stock_index_info(symbol=code)  # 或用其他接口
            # 推荐：ak.index_zh_a_hist(symbol=code, period="daily", start_date=..., end_date=...)
            hist = ak.index_zh_a_hist(symbol=code, period="daily", start_date=start_date_week, end_date=end_date)
            if not hist.empty:
                latest = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist)>1 else latest
                week_ret = ((latest['收盘'] / hist.iloc[0]['收盘']) - 1) * 100
                data.append({
                    '指数': name,
                    '代码': code,
                    '最新收盘': latest['收盘'],
                    '本周涨跌幅%': round(week_ret, 2),
                    # ... 添加上周、月等
                })
        except Exception as e:
            print(f"{name} 出错: {e}")
    return pd.DataFrame(data)

idx_df = get_index_returns(index_list)
print(idx_df)

# ==================== 2. PE/PB 估值 (AKShare 乐咕乐股或东方财富) ====================
# A股整体/指数估值
pe_pb = ak.stock_market_pe_lg()  # 或 stock_index_pe_lg
print(pe_pb.head())

# 指数市盈率
try:
    index_pe = ak.stock_index_pe_lg()
    print(index_pe)
except:
    print("使用备用估值接口")

# ==================== 3. ETF 资金流 (宽基ETF净流入) ====================
# 示例：沪深300ETF 等
etf_list = ['510300.SH', '510050.SH', '510500.SH']  # 根据报告调整

def get_etf_flow(etf_codes, days=20):
    flows = []
    for code in etf_codes:
        try:
            df = ak.fund_etf_fund_daily_em(symbol=code)
            df = df.sort_values('日期').tail(days)
            df['净流入'] = df['成交额']  # 实际用资金流接口或计算
            flows.append(df)
        except:
            pass
    return pd.concat(flows) if flows else pd.DataFrame()

etf_flow = get_etf_flow(etf_list)
print(etf_flow)

# ==================== 4. 行业/风格/细分板块涨跌幅 ====================
# 申万行业指数（AKShare 支持部分）
try:
    sw_index = ak.stock_index_sw()  # 或具体行业
    print(sw_index)
except:
    print("申万数据可用其他接口")

# 主题概念
concept = ak.stock_board_concept_info()
print(concept.head())

# ==================== 5. 复现报告表格 (示例：A股权益指数总览) ====================
# 手动构造或批量获取后合并
report_data = {
    '指数简称': ['创业板50', '沪深300', ...],
    '本周涨跌幅%': [...],
    'PE': [...],
    '近10年PE分位数': [...],
    # PB、市值同理
}
df_report = pd.DataFrame(report_data)
df_report.to_excel('市场跟踪周报_复现.xlsx', index=False)

# ==================== 6. 图表复现 (Leading Index 等) ====================
import matplotlib.pyplot as plt
# 示例：指数走势
df_hist = ak.index_zh_a_hist(symbol='000300', period="daily", start_date='20250101', end_date=end_date)
df_hist['收盘'].plot(title='沪深300')
plt.show()
