"""
宏观高频数据抓取模块
覆盖：房地产成交、钢铁产量、化工开工率、消费价格、汽车销量、电影票房、
      港口吞吐、地铁客运量、集装箱运价、招聘/求职搜索指数
"""
import time
from typing import Dict, Optional

import pandas as pd
import akshare as ak

from config import REPORT_DATE
from utils import cached, retry, logger, last_n_trading_days


class MacroFetcher:
    """宏观高频数据抓取器"""

    # ── 1. 房地产高频 ─────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_real_estate(self) -> Dict[str, pd.DataFrame]:
        """
        二手房挂牌价指数、7城/30城成交面积、100大中城市土地成交
        """
        results = {}

        # 30大中城市商品房成交面积
        try:
            df = ak.macro_china_commercial_estate_sales()
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                results["commercial_sales_30"] = df
                logger.info(f"30城商品房成交: {len(df)}条")
        except Exception as e:
            logger.warning(f"30城商品房数据失败: {e}")

        # 7城二手房成交套数
        try:
            df = ak.macro_china_second_hand_house_7()
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                results["second_hand_7"] = df
                logger.info(f"7城二手房成交: {len(df)}条")
        except Exception as e:
            logger.warning(f"7城二手房数据失败: {e}")

        # 100大中城市土地成交
        try:
            df = ak.macro_china_land_transaction()
            if df is not None and len(df) > 0:
                results["land_transaction_100"] = df
        except Exception as e:
            logger.warning(f"100城土地成交失败: {e}")

        # 北上深二手房成交 (7天移动平均)
        for city_name, city_code in [("上海", "sh"), ("北京", "bj"), ("深圳", "sz")]:
            try:
                df = ak.macro_china_second_hand_house(city=city_name)
                if df is not None and len(df) > 0:
                    df["日期"] = pd.to_datetime(df["日期"])
                    results[f"second_hand_{city_code}"] = df
            except Exception:
                pass

        return results

    # ── 2. 钢铁/工业生产 ─────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_steel_production(self) -> Dict[str, pd.DataFrame]:
        """
        粗钢日均产量、钢材日均产量、螺纹钢产量、铁矿石港口库存
        """
        results = {}

        # 粗钢产量（重点企业）
        try:
            df = ak.macro_china_steel_output()
            if df is not None and len(df) > 0:
                results["crude_steel"] = df
                logger.info(f"粗钢产量: {len(df)}条")
        except Exception as e:
            logger.warning(f"粗钢产量失败: {e}")

        # 全国钢铁产量（国家统计局）
        try:
            df = ak.macro_china_output_data_monthly()
            if df is not None and "钢材" in str(df.columns.tolist()):
                results["steel_output_nbs"] = df
        except Exception:
            pass

        # 铁矿石港口库存
        try:
            df = ak.futures_inventory(variety="i")
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                results["iron_ore_inventory"] = df
        except Exception as e:
            logger.warning(f"铁矿石库存失败: {e}")

        return results

    # ── 3. 化工开工率 ─────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_chemical_capacity(self) -> Dict[str, pd.DataFrame]:
        """
        纯碱/石油沥青/对苯二甲酸开工率
        """
        results = {}
        capacity_map = {
            "纯碱开工率":     lambda: ak.macro_china_soda_ash_capacity_utilization(),
            "沥青装置开工率":  lambda: ak.macro_china_bitumen_capacity_utilization(),
        }
        for name, func in capacity_map.items():
            time.sleep(0.8)
            try:
                df = func()
                if df is not None and len(df) > 0:
                    results[name] = df
                    logger.info(f"{name}: {len(df)}条")
            except Exception as e:
                logger.warning(f"{name}失败: {e}")

        # 水泥发运率
        try:
            df = ak.macro_china_cement_shipment_rate()
            if df is not None:
                results["水泥发运率"] = df
        except Exception:
            pass

        return results

    # ── 4. 消费高频 ───────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_consumption(self) -> Dict[str, pd.DataFrame]:
        """
        猪肉/水果批发价、豆油价格、化肥价格指数
        """
        results = {}

        # 猪肉价格
        try:
            df = ak.macro_china_pork_price()
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                results["pork_price"] = df
                logger.info(f"猪肉价格: {len(df)}条")
        except Exception as e:
            logger.warning(f"猪肉价格失败: {e}")

        # 水果批发价（6种重点监测）
        try:
            df = ak.macro_china_fruit_price()
            if df is not None and len(df) > 0:
                df["日期"] = pd.to_datetime(df["日期"])
                results["fruit_price"] = df
        except Exception as e:
            logger.warning(f"水果价格失败: {e}")

        # 豆油价格
        try:
            df = ak.macro_china_bean_oil_price()
            if df is not None and len(df) > 0:
                results["bean_oil_price"] = df
        except Exception:
            pass

        # 化肥综合指数
        try:
            df = ak.macro_china_fertilizer_price()
            if df is not None and len(df) > 0:
                results["fertilizer_price"] = df
        except Exception:
            pass

        return results

    # ── 5. 汽车销量 ───────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_auto_sales(self) -> pd.DataFrame:
        """
        乘用车日均销量
        """
        try:
            df = ak.macro_china_car_retail()
            if df is not None and len(df) > 0:
                logger.info(f"汽车销量: {len(df)}条")
                return df
        except Exception as e:
            logger.warning(f"汽车销量失败: {e}")
        try:
            df = ak.macro_china_passenger_car_retail()
            return df
        except Exception as e:
            logger.warning(f"乘用车销量备用失败: {e}")
            return pd.DataFrame()

    # ── 6. 电影票房 ───────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_box_office(self) -> pd.DataFrame:
        """
        中国电影票房收入:当周值
        """
        try:
            df = ak.movie_boxoffice_weekly_em(year=str(pd.Timestamp.now().year))
            if df is not None and len(df) > 0:
                logger.info(f"电影票房: {len(df)}条")
                return df
        except Exception as e:
            logger.warning(f"电影票房失败: {e}")
        try:
            df = ak.movie_boxoffice_daily_em()
            return df
        except Exception as e:
            return pd.DataFrame()

    # ── 7. 城市地铁客运量 ─────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_metro_traffic(self) -> pd.DataFrame:
        """
        北上广深地铁客运量（7日移动平均）
        """
        try:
            df = ak.macro_china_subway_passenger_volume()
            if df is not None and len(df) > 0:
                logger.info(f"地铁客运量: {len(df)}条")
                return df
        except Exception as e:
            logger.warning(f"地铁客运量失败: {e}")
            return pd.DataFrame()

    # ── 8. 国内航班数 ─────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_flight_data(self) -> pd.DataFrame:
        """
        中国执行航班:国内航班(不含港澳台):7日移动平均
        """
        try:
            df = ak.macro_china_flight_domestic()
            if df is not None and len(df) > 0:
                return df
        except Exception as e:
            logger.warning(f"国内航班数据失败: {e}")
            return pd.DataFrame()

    # ── 9. 集装箱运价 ─────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_shipping_index(self) -> pd.DataFrame:
        """
        中国出口集装箱运价指数（CCFI/SCFI）
        """
        try:
            df = ak.shipping_ccfi()
            if df is not None and len(df) > 0:
                logger.info(f"集装箱运价: {len(df)}条")
                return df
        except Exception:
            pass
        try:
            df = ak.futures_main_sina(symbol="shipping", start_date=last_n_trading_days(400))
            return df
        except Exception as e:
            logger.warning(f"运价指数失败: {e}")
            return pd.DataFrame()

    # ── 10. 干散货运价 ────────────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_dry_bulk_index(self) -> pd.DataFrame:
        """
        中国进口干散货运价指数（CDFI/BDI）
        """
        try:
            df = ak.shipping_bdi_daily()
            if df is not None and len(df) > 0:
                return df
        except Exception as e:
            logger.warning(f"干散货运价失败: {e}")
            return pd.DataFrame()

    # ── 11. 招聘/求职搜索指数 ────────────────────────────
    @cached(prefix="macro")
    @retry()
    def fetch_job_search_index(self) -> Dict[str, pd.DataFrame]:
        """
        互联网招聘/找工作搜索指数（百度指数代理）
        """
        results = {}
        try:
            df_hire = ak.baidu_search_index(word="招聘",
                                            start_date=last_n_trading_days(400),
                                            end_date=REPORT_DATE)
            if df_hire is not None:
                results["招聘"] = df_hire
        except Exception as e:
            logger.warning(f"招聘搜索指数失败: {e}")

        try:
            df_job = ak.baidu_search_index(word="找工作",
                                           start_date=last_n_trading_days(400),
                                           end_date=REPORT_DATE)
            if df_job is not None:
                results["找工作"] = df_job
        except Exception as e:
            logger.warning(f"求职搜索指数失败: {e}")

        return results

    # ── 汇总 ──────────────────────────────────────────────
    def fetch_all(self) -> Dict:
        logger.info("开始抓取宏观高频数据")
        results = {
            "real_estate":    self.fetch_real_estate(),
            "steel":          self.fetch_steel_production(),
            "chemical":       self.fetch_chemical_capacity(),
            "consumption":    self.fetch_consumption(),
            "auto_sales":     self.fetch_auto_sales(),
            "box_office":     self.fetch_box_office(),
            "metro":          self.fetch_metro_traffic(),
            "flight":         self.fetch_flight_data(),
            "shipping_ccfi":  self.fetch_shipping_index(),
            "dry_bulk_bdi":   self.fetch_dry_bulk_index(),
            "job_index":      self.fetch_job_search_index(),
        }
        logger.info("宏观高频数据抓取完成")
        return results
