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
from datetime import datetime
from typing import Optional
from astrbot.api import logger

class ChartService:
    """
    图表服务类，负责生成K线图
    """
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.temp_dir = os.path.join(self.data_dir, 'temp')
        
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
            # 参数验证
            if not symbol or not isinstance(symbol, str):
                logger.error(f"交易对参数无效: {symbol}")
                return None
            
            if not kline_data or not isinstance(kline_data, list) or len(kline_data) == 0:
                logger.error("K线数据为空或格式无效，无法生成图表")
                return None
            
            if not interval or not isinstance(interval, str):
                logger.error(f"时间间隔参数无效: {interval}")
                return None
            
            if not asset_type or not isinstance(asset_type, str):
                logger.error(f"资产类型参数无效: {asset_type}")
                return None
            
            # 转换K线数据为DataFrame格式
            df = self._convert_to_dataframe(kline_data)
            
            if df is None or df.empty:
                logger.error("转换K线数据失败，无法生成图表")
                return None
            
            # 设置图表样式，模拟专业交易软件风格
            mc = mpf.make_marketcolors(
                up='#FF3B30',  # 鲜艳的红色上涨K线
                down='#34C759',  # 鲜艳的绿色下跌K线
                edge='inherit',
                wick='#8E8E93',  # 灰色的蜡烛芯
                volume='#FF3B30',  # 上涨成交量为红色
                ohlc='inherit'
            )
            
            s = mpf.make_mpf_style(
                marketcolors=mc,
                base_mpf_style='nightclouds',  # 深色背景
                gridstyle=':',  # 虚线网格
                rc={
                    'font.size': 10,
                    'figure.facecolor': '#000000',  # 黑色背景
                    'axes.facecolor': '#121212',  # 深灰色坐标轴背景
                    'axes.grid': True,  # 显示网格
                    'axes.grid.axis': 'both',  # 显示X和Y轴网格
                    'axes.labelsize': 10,  # 坐标轴标签大小
                    'axes.titlesize': 12,  # 标题大小
                    'xtick.labelsize': 8,  # X轴刻度大小
                    'ytick.labelsize': 8,  # Y轴刻度大小
                    'text.color': '#FFFFFF',  # 文本颜色为白色
                    'axes.labelcolor': '#FFFFFF',  # 坐标轴标签颜色
                    'xtick.color': '#8E8E93',  # X轴刻度颜色
                    'ytick.color': '#8E8E93',  # Y轴刻度颜色
                    'grid.color': '#2C2C2E',  # 网格颜色
                    'savefig.transparent': False  # 保存时不透明
                }
            )
            
            # 创建临时文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(self.temp_dir, f"kline_{symbol}_{asset_type}_{interval}_{timestamp}.png")
            
            # 资产类型显示名称映射
            asset_type_names = {
                "spot": "现货",
                "futures": "合约",
                "margin": "杠杆",
                "alpha": "Alpha货币"
            }
            display_name = asset_type_names.get(asset_type, asset_type)
            
            # 绘制图表
            mpf.plot(
                df,
                type='candle',  # 蜡烛图类型
                style=s,  # 使用自定义样式
                volume=True,  # 显示成交量
                title=f'{symbol} {display_name} {interval} K线图',  # 图表标题
                ylabel='价格 (USDT)',  # Y轴标签
                ylabel_lower='成交量',  # 成交量标签
                datetime_format='%Y-%m-%d %H:%M',  # 日期时间格式
                figsize=(12, 8),  # 图表尺寸
                tight_layout=True,  # 紧凑布局
                show_nontrading=False,  # 不显示非交易时间
                scale_width_adjustment=dict(volume=0.35, candle=1.0),  # 调整蜡烛图和成交量的宽度比例
                savefig=dict(
                    fname=file_path,  # 保存路径
                    dpi=300,  # 高分辨率
                    pad_inches=0.2,  # 边距
                    bbox_inches='tight'  # 紧凑的边界框
                )
            )
            
            # 验证文件是否生成成功
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logger.info(f"K线图表生成成功: {file_path}")
                return file_path
            else:
                logger.error(f"图表文件生成失败或为空: {file_path}")
                return None
            
        except ValueError as e:
            logger.error(f"生成K线图表时参数错误: {str(e)}")
            return None
        except ImportError as e:
            logger.error(f"生成K线图表时导入错误: {str(e)}")
            return None
        except MemoryError as e:
            logger.error(f"生成K线图表时内存不足: {str(e)}")
            return None
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
