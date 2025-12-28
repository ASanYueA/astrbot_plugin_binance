"""
币安插件图表服务模块
负责将K线数据转换为可视化图表
"""
import os
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import mplfinance as mpf
import pandas as pd
import numpy as np
import tempfile
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class ChartService:
    """
    图表服务类，负责生成K线图
    """
    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        self.temp_dir = os.path.join(self.plugin_dir, 'temp')
        
        # 确保临时目录存在
        os.makedirs(self.temp_dir, exist_ok=True)
    
    def create_kline_chart(self, symbol: str, kline_data: list, interval: str, asset_type: str) -> Optional[str]:
        """
        将K线数据转换为可视化图表
        :param symbol: 交易对
        :param kline_data: K线数据列表
        :param interval: 时间间隔
        :param asset_type: 资产类型
        :return: 图表文件路径，或None表示失败
        """
        try:
            if not kline_data or len(kline_data) == 0:
                logger.error("K线数据为空，无法生成图表")
                return None
            
            # 转换K线数据为DataFrame格式
            df = self._convert_to_dataframe(kline_data)
            
            if df is None or df.empty:
                logger.error("转换K线数据失败，无法生成图表")
                return None
            
            # 设置图表样式，模拟币安APP风格
            mc = mpf.make_marketcolors(
                up='red',  # 上涨K线为红色
                down='green',  # 下跌K线为绿色
                edge='inherit',
                wick='inherit',
                volume='inherit'
            )
            
            s = mpf.make_mpf_style(
                marketcolors=mc,
                base_mpf_style='nightclouds',  # 深色背景
                gridstyle=':',
                rc={'font.size': 8, 'figure.facecolor': '#121212'}
            )
            
            # 创建临时文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(self.temp_dir, f"kline_{symbol}_{asset_type}_{interval}_{timestamp}.png")
            
            # 绘制图表
            mpf.plot(
                df,
                type='candle',
                style=s,
                volume=True,
                title=f'{symbol} {asset_type} {interval}',
                ylabel='价格',
                ylabel_lower='成交量',
                datetime_format='%Y-%m-%d %H:%M',
                figsize=(10, 6),
                tight_layout=True,
                savefig=dict(fname=file_path, dpi=300, pad_inches=0.1)
            )
            
            logger.info(f"K线图表生成成功: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"生成K线图表时发生错误: {str(e)}")
            return None
    
    def _convert_to_dataframe(self, kline_data: list) -> Optional[pd.DataFrame]:
        """
        将K线数据转换为pandas DataFrame
        :param kline_data: K线数据列表
        :return: DataFrame对象，或None表示失败
        """
        try:
            # K线数据结构：[时间戳, 开盘价, 最高价, 最低价, 收盘价, 成交量, ...]
            data = []
            for kline in kline_data:
                timestamp = int(kline[0]) / 1000  # 转换为秒级时间戳
                open_price = float(kline[1])
                high_price = float(kline[2])
                low_price = float(kline[3])
                close_price = float(kline[4])
                volume = float(kline[5])
                
                data.append([timestamp, open_price, high_price, low_price, close_price, volume])
            
            # 创建DataFrame
            df = pd.DataFrame(
                data,
                columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']
            )
            
            # 设置时间戳为索引
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='s')
            df.set_index('Timestamp', inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"转换K线数据为DataFrame时发生错误: {str(e)}")
            return None
    
    def cleanup_temp_files(self):
        """
        清理临时生成的图表文件
        """
        try:
            if os.path.exists(self.temp_dir):
                for file in os.listdir(self.temp_dir):
                    if file.endswith('.png'):
                        file_path = os.path.join(self.temp_dir, file)
                        os.remove(file_path)
                        logger.info(f"清理临时图表文件: {file_path}")
        except Exception as e:
            logger.error(f"清理临时文件时发生错误: {str(e)}")
