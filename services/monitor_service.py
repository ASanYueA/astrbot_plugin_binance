"""
币安价格监控服务模块
"""
import os
import json
import asyncio
import time
import uuid
from typing import Dict, Optional
from astrbot.api import logger
from .price_service import PriceService
from ..utils.symbol import normalize_symbol


class MonitorService:
    """
    价格监控服务类，处理价格监控的设置、取消、检查等功能
    """
    def __init__(self, price_service: PriceService, data_dir: str, notification_callback=None):
        self.price_service = price_service
        self.data_dir = data_dir
        self.price_monitor_file = os.path.join(self.data_dir, "price_monitors.json")
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 价格监控定时任务
        self.price_monitor_task = None
        self.monitor_interval = 60  # 默认每分钟检查一次
        
        # 通知回调函数
        self.notification_callback = notification_callback
    
    async def load_price_monitors(self) -> Dict[str, Dict]:
        """
        加载价格监控数据
        :return: 监控数据字典，格式为 {user_id: {monitor_id: monitor_data}}
        """
        try:
            if os.path.exists(self.price_monitor_file):
                with open(self.price_monitor_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"加载价格监控数据失败: {str(e)}")
            return {}
    
    async def save_price_monitors(self, monitors: Dict[str, Dict]) -> bool:
        """
        保存价格监控数据
        :param monitors: 监控数据字典
        :return: 是否保存成功
        """
        try:
            with open(self.price_monitor_file, "w", encoding="utf-8") as f:
                json.dump(monitors, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存价格监控数据失败: {str(e)}")
            return False
    
    async def set_price_monitor(self, user_id: str, symbol: str, asset_type: str, 
                               target_price: float, direction: str) -> Optional[str]:
        """
        设置价格监控
        :param user_id: 用户ID
        :param symbol: 交易对
        :param asset_type: 资产类型
        :param target_price: 目标价格
        :param direction: 方向 (up/down)
        :return: 监控ID或None（失败时）
        """
        try:
            # 规范化交易对
            normalized_symbol = normalize_symbol(symbol)
            
            # 生成唯一监控ID
            monitor_id = str(uuid.uuid4())[:8]  # 使用UUID的前8位作为监控ID
            
            # 加载现有监控数据
            monitors = await self.load_price_monitors()
            
            # 创建用户监控目录（如果不存在）
            if user_id not in monitors:
                monitors[user_id] = {}
            
            # 创建监控记录
            monitor_data = {
                "symbol": normalized_symbol,
                "asset_type": asset_type,
                "target_price": target_price,
                "direction": direction,
                "created_at": time.time(),
                "is_active": True
            }
            
            # 保存监控记录
            monitors[user_id][monitor_id] = monitor_data
            
            # 保存到文件
            if await self.save_price_monitors(monitors):
                return monitor_id
            else:
                return None
        except Exception as e:
            logger.error(f"设置价格监控失败: {str(e)}")
            return None
    
    async def cancel_price_monitor(self, user_id: str, monitor_id: str) -> bool:
        """
        取消价格监控
        :param user_id: 用户ID
        :param monitor_id: 监控ID
        :return: 是否取消成功
        """
        try:
            # 加载现有监控数据
            monitors = await self.load_price_monitors()
            
            # 检查用户是否有监控记录
            if user_id not in monitors:
                return False
            
            # 检查监控ID是否存在
            if monitor_id not in monitors[user_id]:
                return False
            
            # 删除监控记录
            del monitors[user_id][monitor_id]
            
            # 如果用户没有其他监控记录，删除用户目录
            if not monitors[user_id]:
                del monitors[user_id]
            
            # 保存到文件
            return await self.save_price_monitors(monitors)
        except Exception as e:
            logger.error(f"取消价格监控失败: {str(e)}")
            return False
    
    async def get_user_monitors(self, user_id: str) -> Dict[str, Dict]:
        """
        获取用户的所有价格监控
        :param user_id: 用户ID
        :return: 用户的监控字典
        """
        try:
            monitors = await self.load_price_monitors()
            return monitors.get(user_id, {})
        except Exception as e:
            logger.error(f"获取用户监控列表失败: {str(e)}")
            return {}
    
    async def _check_all_monitors(self) -> None:
        """
        检查所有用户的价格监控设置
        """
        try:
            # 加载所有监控数据
            monitors = await self.load_price_monitors()
            
            for user_id, user_monitors in monitors.items():
                for monitor_id, monitor_data in list(user_monitors.items()):
                    # 跳过非活跃监控
                    if not monitor_data["is_active"]:
                        continue
                    
                    symbol = monitor_data["symbol"]
                    asset_type = monitor_data["asset_type"]
                    target_price = monitor_data["target_price"]
                    direction = monitor_data["direction"]
                    
                    # 获取当前价格
                    current_price = await self.price_service.get_price(symbol, asset_type)
                    
                    if current_price is not None:
                        # 检查价格是否满足监控条件
                        if (direction == "up" and current_price >= target_price) or \
                           (direction == "down" and current_price <= target_price):
                            # 生成通知消息
                            asset_type_text = {
                                "spot": "现货",
                                "futures": "合约",
                                "margin": "杠杆",
                                "alpha": "Alpha货币"
                            }[asset_type]
                            direction_text = "上涨到" if direction == "up" else "下跌到"
                            
                            # 价格监控触发，准备发送@用户通知
                            notification_message = f"@{user_id} 您设置的{symbol} ({asset_type_text}) {direction_text} {target_price} USDT的监控已触发，当前价格为{current_price:.8f} USDT"
                            
                            # 记录日志
                            logger.info(f"价格监控触发：{notification_message}")
                            
                            # 通过回调函数发送通知
                            if self.notification_callback:
                                try:
                                    await self.notification_callback(notification_message)
                                except Exception as e:
                                    logger.error(f"发送通知失败：{str(e)}")
                            
                            # 触发后关闭监控，避免重复提醒
                            monitor_data["is_active"] = False
                            monitors[user_id][monitor_id] = monitor_data
            
            # 保存更新后的监控数据
            await self.save_price_monitors(monitors)
            
        except Exception as e:
            logger.error(f"检查价格监控时发生错误: {str(e)}")
    
    async def _price_monitor_task(self) -> None:
        """
        价格监控定时任务的实际执行函数
        """
        while True:
            try:
                await self._check_all_monitors()
                await asyncio.sleep(self.monitor_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"价格监控任务执行出错: {str(e)}")
                await asyncio.sleep(self.monitor_interval)  # 出错后仍继续执行
    
    async def start_price_monitor(self, *args, **kwargs) -> None:
        """
        启动价格监控定时任务
        """
        if self.price_monitor_task is None or self.price_monitor_task.done():
            self.price_monitor_task = asyncio.create_task(self._price_monitor_task())
            logger.info("价格监控任务已启动")
    
    async def stop_price_monitor(self, *args, **kwargs) -> None:
        """
        停止价格监控定时任务
        """
        if self.price_monitor_task is not None and not self.price_monitor_task.done():
            self.price_monitor_task.cancel()
            try:
                await self.price_monitor_task
            except asyncio.CancelledError:
                logger.info("价格监控任务已取消")
            except Exception as e:
                logger.error(f"停止价格监控任务时发生错误: {str(e)}")
            finally:
                self.price_monitor_task = None
