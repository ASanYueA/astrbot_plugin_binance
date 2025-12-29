"""
币安插件核心功能模块
包含配置管理、API客户端和核心业务逻辑
"""
import asyncio
import aiohttp
import hashlib
import hmac
import time
import os
import json
from typing import Dict, Optional, Tuple
from astrbot.api import logger
from astrbot.api.star import Context
from astrbot.api.event import AstrMessageEvent

# 导入工具函数和服务
from .utils.symbol import normalize_symbol
from .utils.crypto import encrypt_data, decrypt_data
from .services.monitor_service import MonitorService
from .services.price_service import PriceService
from .services.api_key_service import ApiKeyService
from .services.chart_service import ChartService

class BinanceCore:
    def __init__(self, context: Context):
        self.context = context
        self.config = context.get_config()
        self.api_url = self.config.get("binance_api_url", "https://api.binance.com")
        self.timeout = self.config.get("request_timeout", 10)
        
        # 设置存储目录 - 使用官方推荐的plugin_data目录
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        import pathlib
        
        self.name = "astrbot_plugin_binance"  # 插件名称
        # 先将 get_astrbot_data_path() 返回的字符串转换为 Path 对象
        base_path = pathlib.Path(get_astrbot_data_path())
        self.data_dir = base_path / "plugin_data" / self.name
        
        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建aiohttp客户端会话
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        
        # 初始化服务
        self.price_service = PriceService(self.session, self.config)
        
        # 初始化服务，使用官方推荐的plugin_data目录
        # 通知回调函数将在MonitorService中使用
        self.monitor_service = MonitorService(self.price_service, str(self.data_dir), notification_callback=self._send_notification)
        self.api_key_service = ApiKeyService(str(self.data_dir))
        self.chart_service = ChartService(str(self.data_dir))

    async def _send_notification(self, message: str) -> None:
        """
        发送通知消息的回调函数
        
        :param message: 要发送的通知消息
        """
        try:
            # 在实际项目中，这里应该通过框架提供的API发送消息
            # 由于当前在定时任务中没有event实例，我们记录日志并将通知存储到文件
            logger.info(f"发送通知：{message}")
            
            # 保存通知到文件，以便后续查询或处理
            notifications_file = os.path.join(str(self.data_dir), "notifications.json")
            notifications = []
            
            # 加载现有通知
            if os.path.exists(notifications_file):
                with open(notifications_file, "r", encoding="utf-8") as f:
                    notifications = json.load(f)
            
            # 添加新通知
            notification_entry = {
                "timestamp": time.time(),
                "message": message
            }
            notifications.append(notification_entry)
            
            # 只保留最近100条通知
            if len(notifications) > 100:
                notifications = notifications[-100:]
            
            # 保存通知
            with open(notifications_file, "w", encoding="utf-8") as f:
                json.dump(notifications, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"发送通知时发生错误: {str(e)}")
    
    async def close(self, *args, **kwargs):
        """关闭aiohttp会话"""
        if self.session:
            await self.session.close()

    async def get_price(self, symbol: str, asset_type: str = "spot") -> Optional[float]:
        """
        通过币安公共API查询交易对价格
        :param symbol: 交易对，如BTCUSDT
        :param asset_type: 资产类型，可选值：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)
        :return: 价格，或None表示失败
        """
        try:
            # 标准化交易对格式
            normalized_symbol = normalize_symbol(symbol)
            
            # 根据资产类型选择不同的API域名和端点
            if asset_type == "spot":
                # 现货API
                api_domain = self.api_url
                url = f"{api_domain}/api/v3/ticker/price"
            elif asset_type == "futures":
                # 永续合约API（使用不同的域名）
                api_futures_url = self.config.get("api_futures_url", "https://fapi.binance.com")
                api_domain = api_futures_url
                url = f"{api_domain}/fapi/v1/ticker/price"
            elif asset_type == "margin":
                # 杠杆API
                api_domain = self.api_url
                url = f"{api_domain}/sapi/v1/margin/market-price"
            elif asset_type == "alpha":
                # Alpha货币 - 目前没有公开的价格API，返回对应现货价格
                # 从配置中获取Alpha API域名，如果没有则使用默认值
                api_alpha_url = self.config.get("api_alpha_url", self.api_url)
                api_domain = api_alpha_url
                url = f"{api_domain}/api/v3/ticker/price"
            else:
                logger.error(f"不支持的资产类型: {asset_type}")
                return None
            
            params = {"symbol": normalized_symbol}
            
            logger.debug(f"查询{asset_type}价格：URL={url}, 参数={params}")
            
            async with self.session.get(url, params=params) as response:
                logger.debug(f"API响应状态码: {response.status}, 响应头: {response.headers}")
                
                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"API响应数据: {data}")
                    # 不同API的返回字段可能略有不同
                    if asset_type == "margin":
                        return float(data.get("price", 0))
                    else:
                        return float(data.get("price", 0))
                else:
                    response_text = await response.text()
                    logger.error(f"获取{asset_type}价格失败，状态码: {response.status}，响应内容: {response_text}")
                    
                    # 尝试解析错误响应
                    try:
                        error_data = await response.json()
                        if "code" in error_data and "msg" in error_data:
                            logger.error(f"API错误代码: {error_data['code']}, 错误信息: {error_data['msg']}")
                    except Exception:
                        pass
                    
                    # 如果是Alpha类型查询失败，尝试使用现货价格作为后备
                    if asset_type == "alpha":
                        logger.info(f"Alpha价格查询失败，尝试使用现货价格作为后备")
                        try:
                            spot_url = f"{self.api_url}/api/v3/ticker/price"
                            async with self.session.get(spot_url, params=params) as spot_response:
                                if spot_response.status == 200:
                                    spot_data = await spot_response.json()
                                    logger.info(f"成功获取现货价格作为Alpha价格的后备: {spot_data.get('price')}")
                                    return float(spot_data.get('price', 0))
                                else:
                                    spot_response_text = await spot_response.text()
                                    logger.error(f"现货价格查询也失败，状态码: {spot_response.status}，响应内容: {spot_response_text}")
                        except Exception as e:
                            logger.error(f"获取后备现货价格时发生错误: {str(e)}")
                    
                    return None
        except Exception as e:
            logger.error(f"获取{asset_type}价格时发生错误: {str(e)}")
            return None

    async def bind_api_key(self, user_id: str, api_key: str, secret_key: str) -> bool:
        """
        绑定用户的币安API密钥（加密存储）
        :param user_id: QQ用户ID
        :param api_key: 币安API密钥
        :param secret_key: 币安Secret密钥
        :return: 是否绑定成功
        """
        return await self.api_key_service.bind_api_key(user_id, api_key, secret_key)

    async def get_user_api_key(self, user_id: str) -> Optional[Tuple[str, str]]:
        """
        获取用户绑定的币安API密钥（解密）
        :param user_id: QQ用户ID
        :return: (api_key, secret_key)元组，或None表示未绑定
        """
        return await self.api_key_service.get_api_key(user_id)

    async def handle_price_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理价格查询命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            # 提取交易对参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 2:
                return "❌ 请输入正确的命令格式：/price <交易对> [资产类型]，例如：/price BTCUSDT futures"
            
            symbol = parts[1].strip().upper()  # 标准化为大写
            
            # 增强交易对验证
            if not symbol or len(symbol) < 4:
                return "❌ 交易对格式不正确，请检查后重试（如 BTCUSDT、ETHUSDT）"
            
            # 验证交易对字符合法性（通常只包含字母）
            import re
            if not re.match(r'^[A-Z]+$', symbol):
                return "❌ 交易对只能包含字母，请检查后重试"
            
            # 解析资产类型参数（可选）
            asset_type = "spot"  # 默认现货
            valid_asset_types = ["spot", "futures", "margin", "alpha"]
            if len(parts) >= 3:
                asset_type_param = parts[2].lower()
                if asset_type_param in valid_asset_types:
                    asset_type = asset_type_param
                else:
                    return f"❌ 不支持的资产类型：{asset_type_param}，支持的类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)"
            
            # 查询价格
            price = await self.get_price(symbol, asset_type)
            
            if price is not None and price > 0:
                normalized_symbol = normalize_symbol(symbol)
                # 资产类型显示名称映射
                asset_type_names = {
                    "spot": "现货",
                    "futures": "合约",
                    "margin": "杠杆",
                    "alpha": "Alpha货币"
                }
                return f"✅ {normalized_symbol} ({asset_type_names[asset_type]}) 当前价格：{price:.8f} USDT"
            else:
                # 提供更详细的错误提示
                return f"❌ 价格查询失败，请检查：\n1. 交易对是否正确（如 BTCUSDT、ETHUSDT）\n2. 该交易对是否支持{('该资产类型' if asset_type != 'spot' else '')}查询\n3. 网络连接是否正常"
                
        except ValueError as e:
            return f"❌ {str(e)}"
        except Exception as e:
            logger.error(f"处理价格命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def handle_kline_command(self, event: AstrMessageEvent, *args, **kwargs) -> str or Tuple[str, str]:
        """
        处理K线图查询命令
        :param event: 消息事件
        :return: 回复消息（字符串或图片路径元组）
        """
        try:
            # 提取命令参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 2:
                return "用法：/kline <交易对> [资产类型] [时间间隔]\n例如：/kline BTCUSDT spot 1h\n\n资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)\n时间间隔：1m, 5m, 15m, 30m, 1h, 4h, 1d"

            symbol = parts[1]
            
            # 解析可选参数
            asset_type = "spot"
            interval = "1h"
            
            if len(parts) >= 3:
                asset_type = parts[2].lower()
                
                # 验证资产类型
                valid_asset_types = ["spot", "futures", "margin", "alpha"]
                if asset_type not in valid_asset_types:
                    return f"无效的资产类型: {asset_type}\n支持的资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)"
            
            if len(parts) >= 4:
                interval = parts[3].lower()
                
                # 验证时间间隔
                valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
                if interval not in valid_intervals:
                    return f"无效的时间间隔: {interval}\n支持的时间间隔：1m, 5m, 15m, 30m, 1h, 4h, 1d"
            
            try:
                normalized_symbol = normalize_symbol(symbol)
            except ValueError as e:
                return f"❌ {str(e)}"
            
            # 查询K线数据
            kline_data = await self.price_service.get_kline(normalized_symbol, asset_type, interval)
            
            if not kline_data:
                return f"❌ 获取K线数据失败，请检查交易对和参数是否正确"
            
            # 生成K线图表
            chart_path = self.chart_service.create_kline_chart(normalized_symbol, kline_data, interval, asset_type)
            
            if chart_path:
                # 返回图片结果
                return ("image", chart_path)
            else:
                # 如果生成图片失败，回退到文本结果
                # 格式化K线数据输出（只显示最近5条）
                recent_klines = kline_data[-5:]
                output_lines = [f"📊 {normalized_symbol} {asset_type} {interval} K线数据（最近5条）"]
                
                for kline in recent_klines:
                    # K线数据结构：[开盘时间, 开盘价, 最高价, 最低价, 收盘价, 成交量, ...]
                    timestamp = kline[0]
                    open_price = kline[1]
                    high_price = kline[2]
                    low_price = kline[3]
                    close_price = kline[4]
                    volume = kline[5]
                    
                    # 格式化时间（将毫秒时间戳转换为人类可读格式）
                    from datetime import datetime
                    dt = datetime.fromtimestamp(timestamp / 1000)
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 计算涨跌幅
                    try:
                        change = (float(close_price) - float(open_price)) / float(open_price) * 100
                        change_str = f"{'+' if change > 0 else ''}{change:.2f}%"
                    except:
                        change_str = "N/A"
                    
                    output_lines.append(f"[{time_str}] O: {open_price} H: {high_price} L: {low_price} C: {close_price} ({change_str}) V: {volume}")
                
                return "\n".join(output_lines)
                
        except Exception as e:
            logger.error(f"处理K线命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def unbind_api_key(self, user_id: str) -> bool:
        """
        解除绑定用户的币安API密钥
        :param user_id: QQ用户ID
        :return: 是否解除绑定成功
        """
        return await self.api_key_service.unbind_api_key(user_id)

    async def handle_bind_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理API密钥绑定命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            # 提取参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 3:
                return "❌ 请输入正确的命令格式：/绑定 <API_KEY> <SECRET_KEY>"
            
            api_key = parts[1]
            secret_key = parts[2]
            user_id = event.get_sender_id()
            
            # 增强API密钥格式验证
            if not api_key or not secret_key:
                return "❌ API密钥和Secret密钥不能为空"
                
            if len(api_key) < 20 or len(secret_key) < 20:
                return "❌ API密钥或Secret密钥长度不足，请检查后重试"
            
            # 验证API密钥字符合法性（通常只包含字母、数字和特殊字符）
            import re
            if not re.match(r'^[A-Za-z0-9-_]+$', api_key) or not re.match(r'^[A-Za-z0-9-_]+$', secret_key):
                return "❌ API密钥或Secret密钥包含非法字符，请检查后重试"
            
            # 绑定API密钥
            success = await self.bind_api_key(user_id, api_key, secret_key)
            
            if success:
                return "✅ 币安API密钥绑定成功！"
            else:
                return "❌ API密钥绑定失败，请稍后重试"
                
        except Exception as e:
            logger.error(f"处理绑定命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def handle_unbind_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理API密钥解除绑定命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            user_id = event.get_sender_id()
            
            # 检查用户是否已绑定API密钥
            api_keys = await self.get_user_api_key(user_id)
            if not api_keys:
                return "❌ 您尚未绑定币安API密钥，无需解除绑定"
            
            # 解除绑定API密钥
            success = await self.unbind_api_key(user_id)
            
            if success:
                return "✅ 币安API密钥解除绑定成功！"
            else:
                return "❌ 解除绑定失败，请稍后重试"
                
        except Exception as e:
            logger.error(f"处理解除绑定命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def start_price_monitor(self, *args, **kwargs) -> None:
        """
        启动价格监控定时任务
        """
        await self.monitor_service.start_price_monitor()

    async def stop_price_monitor(self, *args, **kwargs) -> None:
        """
        停止价格监控定时任务
        """
        await self.monitor_service.stop_price_monitor()

    async def handle_help_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理帮助命令，显示所有可用命令
        :param event: 消息事件
        :return: 帮助信息
        """
        help_text = (
            "📚 币安插件命令列表\n"
            "=================\n"
            "/price <交易对> [资产类型] - 查询币安资产价格\n"
            "  资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)\n"
            "  示例：/price BTCUSDT futures\n"
            "\n"
            "/绑定 <API_KEY> <SECRET_KEY> - 绑定币安API密钥\n"
            "  示例：/绑定 abcdef123456 abcdef123456\n"
            "\n"
            "/解除绑定 - 解除绑定币安API密钥\n"
            "\n"
            "/资产 [查询类型] - 查询账户资产（需先绑定API）\n"
            "  查询类型：alpha/资金/现货/合约，不输入则查询总览\n"
            "  示例：/资产 alpha\n"
            "\n"
            "/监控 设置 <交易对> <资产类型> <目标价格> <方向> - 设置价格监控\n"
            "  资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)\n"
            "  方向：up(上涨到), down(下跌到)\n"
            "  示例：/监控 设置 BTCUSDT futures 50000 up\n"
            "\n"
            "/监控 取消 <监控ID> - 取消指定的价格监控\n"
            "  示例：/监控 取消 1\n"
            "\n"
            "/监控 列表 - 查看您的所有价格监控\n"
            "\n"
            "/kline <交易对> [资产类型] [时间间隔] - 查询K线数据\n"
            "  资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)\n"
            "  时间间隔：1m, 5m, 15m, 30m, 1h, 4h, 1d\n"
            "  示例：/kline BTCUSDT spot 1h\n"
            "\n"
            "/bahelp - 显示本帮助信息\n"
            "=================\n"
            "注：API密钥加密存储，确保安全\n"
        )
        return help_text

    async def _get_private_api_signature(self, params: Dict, secret_key: str) -> str:
        """
        生成币安API签名
        :param params: 请求参数
        :param secret_key: 用户的secret_key
        :return: 签名后的字符串
        """
        # 添加时间戳
        params["timestamp"] = int(time.time() * 1000)
        # 对参数进行排序并拼接
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        # 使用HMAC-SHA256进行签名
        signature = hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()
        return signature

    async def _call_private_api(self, api_path: str, api_key: str, secret_key: str, params: Dict = None, is_futures: bool = False) -> Optional[Dict]:
        """
        调用币安私有API
        :param api_path: API路径
        :param api_key: 用户的api_key
        :param secret_key: 用户的secret_key
        :param params: 请求参数
        :param is_futures: 是否是合约API
        :return: API响应数据或None
        """
        try:
            if params is None:
                params = {}
            
            # 生成签名
            signature = await self._get_private_api_signature(params, secret_key)
            params["signature"] = signature
            
            # 根据是否是合约API选择不同的基础URL
            if is_futures:
                base_url = f"{self.api_url}/fapi"
            else:
                base_url = f"{self.api_url}/api"
            
            url = f"{base_url}{api_path}"
            
            headers = {
                "X-MBX-APIKEY": api_key
            }
            
            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"调用私有API失败，状态码: {response.status}，响应: {await response.text()}")
                    return None
        except Exception as e:
            logger.error(f"调用私有API时发生错误: {str(e)}")
            return None

    async def get_account_overview(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取账户总览（模拟数据）
        :param api_key: 用户的api_key
        :param secret_key: 用户的secret_key
        :return: 账户总览数据
        """
        # 实际项目中应该调用真实的API
        # account_data = await self._call_private_api("/v3/account", api_key, secret_key)
        
        # 模拟数据
        return {
            "total_asset": 14.4,
            "today_profit": -1.74,
            "profit_rate": -10.75,
            "alpha_asset": 14.37,
            "fund_asset": 0.03146084,
            "spot_asset": 0.00,
            "futures_asset": 0.00
        }

    async def get_alpha_assets(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取Alpha资产（模拟数据）
        :param api_key: 用户的api_key
        :param secret_key: 用户的secret_key
        :return: Alpha资产数据
        """
        return {
            "total": 14.37,
            "details": [
                {"symbol": "USDT", "amount": 14.37}
            ]
        }

    async def get_fund_assets(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取资金账户资产（模拟数据）
        :param api_key: 用户的api_key
        :param secret_key: 用户的secret_key
        :return: 资金账户资产数据
        """
        return {
            "total": 0.03146084,
            "details": [
                {"symbol": "USDT", "amount": 0.03146084}
            ]
        }

    async def get_spot_assets(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取现货账户资产（模拟数据）
        :param api_key: 用户的api_key
        :param secret_key: 用户的secret_key
        :return: 现货账户资产数据
        """
        return {
            "total": 0.00,
            "details": []
        }

    async def get_futures_assets(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取合约账户资产（模拟数据）
        :param api_key: 用户的api_key
        :param secret_key: 用户的secret_key
        :return: 合约账户资产数据
        """
        return {
            "total": 0.00,
            "details": []
        }

    async def _format_asset_details(self, asset_data: Dict, asset_name: str, emoji: str) -> str:
        """
        格式化资产详情信息
        
        :param asset_data: 资产数据字典
        :param asset_name: 资产名称
        :param emoji: 资产显示的 emoji
        :return: 格式化后的资产信息字符串
        """
        if asset_data['details']:
            details = "\n".join([f"{item['symbol']}: {item['amount']} USDT" for item in asset_data['details']])
        else:
            details = "无"
        return (
            f"{emoji} {asset_name}资产\n"
            f"总资产：{asset_data['total']} USDT\n"
            f"详细信息：\n{details}"
        )
    
    async def handle_asset_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理资产查询命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            # 获取用户ID
            user_id = event.get_sender_id()
            
            # 检查用户是否绑定了API密钥
            api_keys = await self.get_user_api_key(user_id)
            if not api_keys:
                return "❌ 您尚未绑定币安API密钥，请先使用/绑定命令绑定"
            
            api_key, secret_key = api_keys
            
            # 提取命令参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            # 确定查询类型
            query_type = "overview"  # 默认查询总览
            if len(parts) >= 2:
                query_param = parts[1].lower()
                if query_param in ["alpha", "资金", "现货", "合约"]:
                    query_type = query_param
            
            # 根据查询类型获取资产信息
            if query_type == "overview":
                # 获取账户总览
                account_data = await self.get_account_overview(api_key, secret_key)
                if account_data:
                    return (
                        f"💰 币安账户资产总览\n"
                        f"预估总资产：{account_data['total_asset']} USDT ≈ ¥{account_data['total_asset'] * 7.0:.2f}\n"
                        f"今日盈亏：{account_data['today_profit']} USDT ({account_data['profit_rate']}%)\n"
                        f"\n"
                        f"币种\t\t账户\n"
                        f"Alpha\t\t{account_data['alpha_asset']} USDT\n"
                        f"资金\t\t{account_data['fund_asset']} USDT\n"
                        f"现货\t\t{account_data['spot_asset']} USDT\n"
                        f"合约\t\t{account_data['futures_asset']} USDT"
                    )
                else:
                    return "❌ 获取账户总览失败"
            elif query_type == "alpha":
                # 获取Alpha资产
                alpha_data = await self.get_alpha_assets(api_key, secret_key)
                if alpha_data:
                    return await self._format_asset_details(alpha_data, "Alpha货币", "📊")
                else:
                    return "❌ 获取Alpha资产失败"
            elif query_type == "资金":
                # 获取资金账户资产
                fund_data = await self.get_fund_assets(api_key, secret_key)
                if fund_data:
                    return await self._format_asset_details(fund_data, "资金账户", "💵")
                else:
                    return "❌ 获取资金账户资产失败"
            elif query_type == "现货":
                # 获取现货账户资产
                spot_data = await self.get_spot_assets(api_key, secret_key)
                if spot_data:
                    return await self._format_asset_details(spot_data, "现货账户", "📈")
                else:
                    return "❌ 获取现货账户资产失败"
            elif query_type == "合约":
                # 获取合约账户资产
                futures_data = await self.get_futures_assets(api_key, secret_key)
                if futures_data:
                    return await self._format_asset_details(futures_data, "合约账户", "🎯")
                else:
                    return "❌ 获取合约账户资产失败"
            else:
                return "❌ 不支持的查询类型，请使用 alpha/资金/现货/合约"
                
        except Exception as e:
            logger.error(f"处理资产命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"
