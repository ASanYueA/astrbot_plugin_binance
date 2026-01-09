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

# 导入工具函数
from .utils.symbol import normalize_symbol
from .utils.crypto import encrypt_data, decrypt_data

class BinanceCore:
    def __init__(self, context: Context):
        self.context = context
        self.config = context.get_config()
        self.api_url = self.config.get("binance_api_url", "https://api.binance.com")
        self.timeout = self.config.get("request_timeout", 10)
        
        # 加密密钥将在第一次使用时初始化
        self.encryption_key = None
        self.encryption_key_initialized = False
        
        # 设置存储目录 - 使用相对路径
        self.data_dir = "data"
        self.encryption_key_file = os.path.join(self.data_dir, "encryption_key.json")
        self.user_api_file = os.path.join(self.data_dir, "user_api_keys.json")
        self.price_monitor_file = os.path.join(self.data_dir, "price_monitors.json")
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 创建aiohttp客户端会话
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        
        # 价格监控定时任务
        self.price_monitor_task = None
        self.monitor_interval = 60  # 默认每分钟检查一次
    
    async def _init_encryption_key(self):
        """
        初始化加密密钥：
        1. 优先从文件系统中获取
        2. 如果没有，生成一个新的随机密钥并存储到文件
        """
        if self.encryption_key_initialized:
            return
        
        # 从文件系统中获取加密密钥
        try:
            if os.path.exists(self.encryption_key_file):
                with open(self.encryption_key_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.encryption_key = data.get("encryption_key")
        except Exception as e:
            logger.error(f"从文件系统获取加密密钥失败: {str(e)}")
        
        # 如果没有获取到密钥，生成一个新的随机密钥
        if not self.encryption_key or len(self.encryption_key) < 16:
            import secrets
            try:
                # 生成32位的随机字符串作为加密密钥
                self.encryption_key = secrets.token_hex(16)  # 32个字符的十六进制字符串
                # 存储加密密钥到文件
                with open(self.encryption_key_file, "w", encoding="utf-8") as f:
                    json.dump({"encryption_key": self.encryption_key}, f, ensure_ascii=False, indent=2)
                logger.info("已生成并存储新的加密密钥")
            except Exception as e:
                logger.error(f"生成或存储加密密钥失败: {str(e)}")
                # 如果生成密钥失败，使用一个默认的不安全密钥（仅作为最后的 fallback）
                self.encryption_key = "default_fallback_key_12345678"
        
        self.encryption_key_initialized = True

    async def close(self):
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
            try:
                normalized_symbol = normalize_symbol(symbol)
            except ValueError as e:
                logger.error(f"获取{asset_type}价格时发生错误: {str(e)}")
                return None
            
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
                # Alpha货币 - 使用币安Alpha API
                api_alpha_url = self.config.get("api_alpha_url", "https://api.binance.com")
                api_domain = api_alpha_url
                url = f"{api_domain}/sapi/v1/alpha/ticker/price"
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
        try:
            # 确保加密密钥已初始化
            await self._init_encryption_key()
            
            # 加密API密钥
            encrypted_api_key = encrypt_data(api_key, self.encryption_key)
            encrypted_secret_key = encrypt_data(secret_key, self.encryption_key)
            
            # 存储加密后的API密钥到文件
            user_api_data = {}
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
            
            user_api_data[user_id] = {
                "api_key": encrypted_api_key,
                "secret_key": encrypted_secret_key
            }
            
            with open(self.user_api_file, "w", encoding="utf-8") as f:
                json.dump(user_api_data, f, ensure_ascii=False, indent=2)
                
            return True
        except Exception as e:
            logger.error(f"绑定API密钥失败: {str(e)}")
            return False

    async def get_user_api_key(self, user_id: str) -> Optional[Tuple[str, str]]:
        """
        获取用户绑定的币安API密钥（解密）
        :param user_id: QQ用户ID
        :return: (api_key, secret_key)元组，或None表示未绑定
        """
        try:
            # 确保加密密钥已初始化
            await self._init_encryption_key()
            
            # 从文件中获取加密的API密钥
            user_api_data = {}
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
            
            # 检查用户是否存在API密钥
            if user_id not in user_api_data:
                return None
            
            encrypted_api_key = user_api_data[user_id].get("api_key")
            encrypted_secret_key = user_api_data[user_id].get("secret_key")
            
            if not encrypted_api_key or not encrypted_secret_key:
                return None
            
            # 解密API密钥
            api_key = decrypt_data(encrypted_api_key, self.encryption_key)
            secret_key = decrypt_data(encrypted_secret_key, self.encryption_key)
            
            return (api_key, secret_key)
        except Exception as e:
            logger.error(f"获取用户API密钥失败: {str(e)}")
            return None

    async def handle_price_command(self, event: AstrMessageEvent) -> str:
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
            
            symbol = parts[1]
            
            # 解析资产类型参数（可选）
            asset_type = "spot"  # 默认现货
            if len(parts) >= 3:
                asset_type_param = parts[2].lower()
                if asset_type_param in ["spot", "futures", "margin", "alpha"]:
                    asset_type = asset_type_param
                else:
                    return f"❌ 不支持的资产类型：{asset_type_param}，支持的类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)"
            
            # 查询价格
            price = await self.get_price(symbol, asset_type)
            
            if price:
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

    async def unbind_api_key(self, user_id: str) -> bool:
        """
        解除绑定用户的币安API密钥
        :param user_id: QQ用户ID
        :return: 是否解除绑定成功
        """
        try:
            # 从文件中删除用户的API密钥
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
                
                # 如果用户存在，删除其API密钥
                if user_id in user_api_data:
                    del user_api_data[user_id]
                    
                    # 将更新后的数据写回文件
                    with open(self.user_api_file, "w", encoding="utf-8") as f:
                        json.dump(user_api_data, f, ensure_ascii=False, indent=2)
                    
                    return True
            
            return False
        except Exception as e:
            logger.error(f"解除绑定API密钥失败: {str(e)}")
            return False

    async def handle_bind_command(self, event: AstrMessageEvent) -> str:
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
            
            # 验证API密钥格式（简单验证）
            if len(api_key) < 20 or len(secret_key) < 20:
                return "❌ API密钥格式不正确，请检查后重试"
            
            # 绑定API密钥
            success = await self.bind_api_key(user_id, api_key, secret_key)
            
            if success:
                return "✅ 币安API密钥绑定成功！"
            else:
                return "❌ API密钥绑定失败，请稍后重试"
                
        except Exception as e:
            logger.error(f"处理绑定命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def handle_unbind_command(self, event: AstrMessageEvent) -> str:
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
            # 确保目录存在
            os.makedirs(os.path.dirname(self.price_monitor_file), exist_ok=True)
            with open(self.price_monitor_file, "w", encoding="utf-8") as f:
                json.dump(monitors, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存价格监控数据失败: {str(e)}")
            return False

    async def handle_monitor_set_command(self, event: AstrMessageEvent) -> str:
        """
        处理监控设置命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            import uuid
            
            # 解析命令参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 6:
                return "❌ 请输入正确的命令格式：/监控 设置 <交易对> <资产类型> <目标价格> <方向>，例如：/监控 设置 BTCUSDT futures 50000 up"
            
            symbol = parts[2]
            asset_type_param = parts[3].lower()
            target_price_str = parts[4]
            direction_param = parts[5].lower()
            
            # 验证资产类型
            if asset_type_param not in ["spot", "futures", "margin", "alpha"]:
                return "❌ 不支持的资产类型，请使用：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)"
            
            # 验证方向参数
            if direction_param not in ["up", "down"]:
                return "❌ 不支持的方向，请使用：up(上涨到), down(下跌到)"
            
            # 验证目标价格格式
            try:
                target_price = float(target_price_str)
                if target_price <= 0:
                    raise ValueError("价格必须大于0")
            except ValueError:
                return "❌ 目标价格必须是有效的正数"
            
            # 规范化交易对
            try:
                normalized_symbol = normalize_symbol(symbol)
            except ValueError as e:
                return f"❌ {str(e)}"
            
            # 生成唯一监控ID
            monitor_id = str(uuid.uuid4())[:8]  # 使用UUID的前8位作为监控ID
            user_id = event.get_sender_id()
            
            # 加载现有监控数据
            monitors = await self.load_price_monitors()
            
            # 创建用户监控目录（如果不存在）
            if user_id not in monitors:
                monitors[user_id] = {}
            
            # 创建监控记录
            monitor_data = {
                "symbol": normalized_symbol,
                "asset_type": asset_type_param,
                "target_price": target_price,
                "direction": direction_param,
                "created_at": time.time(),
                "is_active": True
            }
            
            # 保存监控记录
            monitors[user_id][monitor_id] = monitor_data
            
            # 保存到文件
            if await self.save_price_monitors(monitors):
                # 获取当前价格进行参考
                current_price = await self.get_price(normalized_symbol, asset_type_param)
                current_price_str = f"当前价格：{current_price:.8f} USDT" if current_price else "当前价格：无法获取"
                
                direction_text = "上涨到" if direction_param == "up" else "下跌到"
                asset_type_text = {
                    "spot": "现货",
                    "futures": "合约",
                    "margin": "杠杆",
                    "alpha": "Alpha货币"
                }[asset_type_param]
                
                return f"✅ 价格监控设置成功！\n监控ID：{monitor_id}\n交易对：{normalized_symbol} ({asset_type_text})\n监控条件：{direction_text} {target_price} USDT\n{current_price_str}"
            else:
                return "❌ 监控设置失败，请稍后重试"
                
        except Exception as e:
            logger.error(f"处理监控设置命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def handle_monitor_cancel_command(self, event: AstrMessageEvent) -> str:
        """
        处理监控取消命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            # 解析命令参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 3:
                return "❌ 请输入正确的命令格式：/监控 取消 <监控ID>，例如：/监控 取消 1234abcd"
            
            monitor_id = parts[2]
            user_id = event.get_sender_id()
            
            # 加载现有监控数据
            monitors = await self.load_price_monitors()
            
            # 检查用户是否有监控记录
            if user_id not in monitors:
                return "❌ 您没有设置任何价格监控"
            
            # 检查监控ID是否存在
            if monitor_id not in monitors[user_id]:
                return "❌ 无效的监控ID，请检查您的监控列表"
            
            # 删除监控记录
            del monitors[user_id][monitor_id]
            
            # 如果用户没有其他监控记录，删除用户目录
            if not monitors[user_id]:
                del monitors[user_id]
            
            # 保存到文件
            if await self.save_price_monitors(monitors):
                return f"✅ 监控ID为{monitor_id}的价格监控已成功取消"
            else:
                return "❌ 取消监控失败，请稍后重试"
                
        except Exception as e:
            logger.error(f"处理监控取消命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def handle_monitor_list_command(self, event: AstrMessageEvent) -> str:
        """
        处理监控列表查询命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            user_id = event.get_sender_id()
            
            # 加载现有监控数据
            monitors = await self.load_price_monitors()
            
            # 检查用户是否有监控记录
            if user_id not in monitors or not monitors[user_id]:
                return "✅ 您没有设置任何价格监控"
            
            # 构建监控列表
            monitor_list = []
            for monitor_id, monitor_data in monitors[user_id].items():
                symbol = monitor_data["symbol"]
                asset_type = monitor_data["asset_type"]
                target_price = monitor_data["target_price"]
                direction = monitor_data["direction"]
                is_active = monitor_data["is_active"]
                
                # 获取当前价格
                current_price = await self.get_price(symbol, asset_type)
                current_price_str = f"{current_price:.8f}" if current_price else "无法获取"
                
                # 格式化监控信息
                asset_type_text = {
                    "spot": "现货",
                    "futures": "合约",
                    "margin": "杠杆",
                    "alpha": "Alpha货币"
                }[asset_type]
                direction_text = "上涨到" if direction == "up" else "下跌到"
                status_text = "🟢 活跃" if is_active else "🔴 已关闭"
                
                monitor_list.append(f"📌 监控ID：{monitor_id}\n  交易对：{symbol} ({asset_type_text})\n  监控条件：{direction_text} {target_price:.8f} USDT\n  当前价格：{current_price_str} USDT\n  状态：{status_text}")
            
            # 合并为回复消息
            return f"📋 您的价格监控列表：\n\n" + "\n\n".join(monitor_list)
            
        except Exception as e:
            logger.error(f"处理监控列表命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def start_price_monitor(self) -> None:
        """
        启动价格监控定时任务
        """
        if self.price_monitor_task is None or self.price_monitor_task.done():
            self.price_monitor_task = asyncio.create_task(self._price_monitor_task())
            logger.info("价格监控任务已启动")

    async def stop_price_monitor(self) -> None:
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
                    current_price = await self.get_price(symbol, asset_type)
                    
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
                            
                            # TODO: 实现通过事件系统发送通知，需要框架支持
                            # 由于在定时任务中没有event实例，暂时使用日志记录
                            # 实际项目中应使用框架提供的消息发送接口
                            
                            # 触发后关闭监控，避免重复提醒
                            monitor_data["is_active"] = False
                            monitors[user_id][monitor_id] = monitor_data
            
            # 保存更新后的监控数据
            await self.save_price_monitors(monitors)
            
        except Exception as e:
            logger.error(f"检查价格监控时发生错误: {str(e)}")

    async def handle_help_command(self, event: AstrMessageEvent) -> str:
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
        获取Alpha资产信息
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: Alpha资产信息字典，或None表示失败
        """
        try:
            # 获取Alpha资产信息
            alpha_data = await self.authenticated_request(
                "GET",
                "/sapi/v1/alpha/asset",
                {},
                api_key,
                secret_key
            )
            if not alpha_data:
                return None
            
            # 计算Alpha资产总资产
            total_asset = 0.0
            details = []
            
            # 处理每个资产
            for asset in alpha_data.get("balances", []):
                symbol = asset.get("asset")
                free = float(asset.get("free", "0"))
                locked = float(asset.get("locked", "0"))
                total = free + locked
                
                if total > 0:
                    # 获取资产的USDT价格
                    usdt_symbol = f"{symbol}USDT"
                    price = await self.get_price(usdt_symbol, "spot")
                    if price:
                        asset_value = total * price
                        total_asset += asset_value
                        details.append({"symbol": symbol, "amount": asset_value})
            
            return {
                "total": round(total_asset, 2),
                "details": details
            }
        except Exception as e:
            logger.error(f"获取Alpha资产时发生错误: {str(e)}")
            return None

    async def get_fund_assets(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取资金账户资产信息
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 资金账户资产信息字典，或None表示失败
        """
        try:
            # 获取资金账户信息
            fund_data = await self.authenticated_request(
                "GET",
                "/sapi/v1/fund/account",
                {},
                api_key,
                secret_key
            )
            if not fund_data:
                return None
            
            # 计算资金账户总资产
            total_asset = 0.0
            details = []
            
            # 处理每个资产
            for asset in fund_data.get("balances", []):
                symbol = asset.get("asset")
                free = float(asset.get("free", "0"))
                locked = float(asset.get("locked", "0"))
                total = free + locked
                
                if total > 0:
                    # 如果是USDT，直接相加
                    if symbol == "USDT":
                        total_asset += total
                        details.append({"symbol": symbol, "amount": total})
                    else:
                        # 获取其他资产的USDT价格
                        usdt_symbol = f"{symbol}USDT"
                        price = await self.get_price(usdt_symbol, "spot")
                        if price:
                            asset_value = total * price
                            total_asset += asset_value
                            details.append({"symbol": symbol, "amount": asset_value})
            
            return {
                "total": round(total_asset, 2),
                "details": details
            }
        except Exception as e:
            logger.error(f"获取资金账户资产时发生错误: {str(e)}")
            return None

    async def get_account_info(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取币安账户信息
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 账户信息字典，或None表示失败
        """
        try:
            # 调用币安API获取账户信息
            account_data = await self.authenticated_request(
                "GET",
                "/api/v3/account",
                {},
                api_key,
                secret_key
            )
            
            return account_data
        except Exception as e:
            logger.error(f"获取账户信息时发生错误: {str(e)}")
            return None

    async def get_futures_account_info(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取合约账户信息
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 合约账户信息字典，或None表示失败
        """
        try:
            # 构建签名参数
            params = {}
            params["timestamp"] = int(time.time() * 1000)
            
            # 生成查询字符串
            query_string = "&".join([f"{key}={value}" for key, value in sorted(params.items())])
            
            # 生成HMAC-SHA256签名
            signature = hmac.new(
                secret_key.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            # 将签名添加到参数中
            params["signature"] = signature
            
            # 发送请求
            url = "https://fapi.binance.com/fapi/v2/account"
            headers = {
                "X-MBX-APIKEY": api_key
            }
            
            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"获取合约账户信息失败，状态码: {response.status}")
                    logger.error(f"响应内容: {await response.text()}")
                    return None
        except Exception as e:
            logger.error(f"获取合约账户信息时发生错误: {str(e)}")
            return None

    async def get_spot_assets(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取现货账户资产信息
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 现货账户资产信息字典，或None表示失败
        """
        try:
            # 获取账户信息
            account_data = await self.get_account_info(api_key, secret_key)
            if not account_data:
                return None
            
            # 计算现货账户总资产（使用USDT计价）
            total_asset = 0.0
            details = []
            
            # 处理每个资产
            for asset in account_data.get("balances", []):
                symbol = asset.get("asset")
                free = float(asset.get("free", "0"))
                locked = float(asset.get("locked", "0"))
                total = free + locked
                
                if total > 0:
                    # 如果是USDT，直接相加
                    if symbol == "USDT":
                        total_asset += total
                        details.append({"symbol": symbol, "amount": total})
                    else:
                        # 获取其他资产的USDT价格
                        usdt_symbol = f"{symbol}USDT"
                        price = await self.get_price(usdt_symbol, "spot")
                        if price:
                            asset_value = total * price
                            total_asset += asset_value
                            details.append({"symbol": symbol, "amount": asset_value})
            
            return {
                "total": round(total_asset, 2),
                "details": details
            }
        except Exception as e:
            logger.error(f"获取现货账户资产时发生错误: {str(e)}")
            return None

    async def get_futures_assets(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取合约账户资产信息
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 合约账户资产信息字典，或None表示失败
        """
        try:
            # 获取合约账户信息
            futures_data = await self.get_futures_account_info(api_key, secret_key)
            if not futures_data:
                return None
            
            # 计算合约账户总资产
            total_asset = float(futures_data.get("totalWalletBalance", "0"))
            
            # 获取所有持仓信息
            positions = futures_data.get("positions", [])
            details = []
            
            # 处理每个持仓
            for position in positions:
                symbol = position.get("symbol")
                positionAmt = float(position.get("positionAmt", "0"))
                
                if abs(positionAmt) > 0:
                    # 获取当前价格
                    price = await self.get_price(symbol, "futures")
                    if price:
                        # 计算持仓价值
                        position_value = abs(positionAmt) * price
                        details.append({"symbol": symbol, "amount": position_value})
            
            return {
                "total": round(total_asset, 2),
                "details": details
            }
        except Exception as e:
            logger.error(f"获取合约账户资产时发生错误: {str(e)}")
            return None

    async def handle_asset_command(self, event: AstrMessageEvent) -> str:
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
                        f"💰 币安账户资产总览\n"\
                        f"预估总资产：{account_data['total_asset']} USDT ≈ ¥{account_data['total_asset'] * 7.0:.2f}\n"\
                        f"今日盈亏：{account_data['today_profit']} USDT ({account_data['profit_rate']}%)\n"\
                        f"\n"\
                        f"币种\t\t账户\n"\
                        f"Alpha\t\t{account_data['alpha_asset']} USDT\n"\
                        f"资金\t\t{account_data['fund_asset']} USDT\n"\
                        f"现货\t\t{account_data['spot_asset']} USDT\n"\
                        f"合约\t\t{account_data['futures_asset']} USDT"
                    )
                else:
                    return "❌ 获取账户总览失败"
            elif query_type == "alpha":
                # 获取Alpha资产
                alpha_data = await self.get_alpha_assets(api_key, secret_key)
                if alpha_data:
                    if alpha_data['details']:
                        details = "\n".join([f"{item['symbol']}: {item['amount']} USDT" for item in alpha_data['details']])
                    else:
                        details = "无"
                    return (
                        f"📊 Alpha货币资产\n"\
                        f"总资产：{alpha_data['total']} USDT\n"\
                        f"详细信息：\n{details}"
                    )
                else:
                    return "❌ 获取Alpha资产失败"
            elif query_type == "资金":
                # 获取资金账户资产
                fund_data = await self.get_fund_assets(api_key, secret_key)
                if fund_data:
                    if fund_data['details']:
                        details = "\n".join([f"{item['symbol']}: {item['amount']} USDT" for item in fund_data['details']])
                    else:
                        details = "无"
                    return (
                        f"💵 资金账户资产\n"\
                        f"总资产：{fund_data['total']} USDT\n"\
                        f"详细信息：\n{details}"
                    )
                else:
                    return "❌ 获取资金账户资产失败"
            elif query_type == "现货":
                # 获取现货账户资产
                spot_data = await self.get_spot_assets(api_key, secret_key)
                if spot_data:
                    if spot_data['details']:
                        details = "\n".join([f"{item['symbol']}: {item['amount']} USDT" for item in spot_data['details']])
                    else:
                        details = "无"
                    return (
                        f"📈 现货账户资产\n"\
                        f"总资产：{spot_data['total']} USDT\n"\
                        f"详细信息：\n{details}"
                    )
                else:
                    return "❌ 获取现货账户资产失败"
            elif query_type == "合约":
                # 获取合约账户资产
                futures_data = await self.get_futures_assets(api_key, secret_key)
                if futures_data:
                    if futures_data['details']:
                        details = "\n".join([f"{item['symbol']}: {item['amount']} USDT" for item in futures_data['details']])
                    else:
                        details = "无"
                    return (
                        f"🎯 合约账户资产\n"\
                        f"总资产：{futures_data['total']} USDT\n"\
                        f"详细信息：\n{details}"
                    )
                else:
                    return "❌ 获取合约账户资产失败"
            else:
                return "❌ 不支持的查询类型，请使用 alpha/资金/现货/合约"
                
        except Exception as e:
            logger.error(f"处理资产命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"
