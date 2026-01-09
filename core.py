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
        
        # 设置存储目录
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(self.plugin_dir, "data")
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
            normalized_symbol = normalize_symbol(symbol)
            
            # 根据资产类型选择不同的API域名和端点
            if asset_type == "spot":
                url = f"https://api.binance.com/api/v3/ticker/price"
                params = {"symbol": normalized_symbol}
            elif asset_type == "futures":
                url = f"https://fapi.binance.com/fapi/v1/ticker/price"
                params = {"symbol": normalized_symbol}
            elif asset_type == "margin":
                url = f"https://api.binance.com/sapi/v1/margin/price"
                params = {"symbol": normalized_symbol}
            elif asset_type == "alpha":
                url = f"https://alpha.binance.com/api/v1/ticker/price"
                params = {"symbol": normalized_symbol}
            else:
                logger.error(f"不支持的资产类型: {asset_type}")
                return None
            
            # 发送请求
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data.get("price"))
                else:
                    logger.error(f"获取价格失败，状态码: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"获取价格时发生错误: {str(e)}")
            return None

    async def sign_request(self, params: Dict, secret_key: str) -> Dict:
        """
        为币安API请求生成签名
        :param params: 请求参数字典
        :param secret_key: API密钥的secret
        :return: 包含签名的参数字典
        """
        # 添加时间戳
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
        
        return params

    async def authenticated_request(self, method: str, endpoint: str, params: Dict, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        发送需要身份验证的币安API请求
        :param method: 请求方法，如GET, POST, DELETE等
        :param endpoint: API端点，如/api/v3/account
        :param params: 请求参数字典
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 响应数据字典，或None表示失败
        """
        try:
            # 为请求生成签名
            signed_params = await self.sign_request(params, secret_key)
            
            # 构建完整的请求URL
            url = f"https://api.binance.com{endpoint}"
            
            # 设置请求头
            headers = {
                "X-MBX-APIKEY": api_key
            }
            
            # 发送请求
            if method.upper() == "GET":
                async with self.session.get(url, params=signed_params, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"认证请求失败，状态码: {response.status}")
                        logger.error(f"响应内容: {await response.text()}")
                        return None
            elif method.upper() == "POST":
                async with self.session.post(url, data=signed_params, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"认证请求失败，状态码: {response.status}")
                        logger.error(f"响应内容: {await response.text()}")
                        return None
            elif method.upper() == "DELETE":
                async with self.session.delete(url, params=signed_params, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"认证请求失败，状态码: {response.status}")
                        logger.error(f"响应内容: {await response.text()}")
                        return None
            else:
                logger.error(f"不支持的请求方法: {method}")
                return None
        except Exception as e:
            logger.error(f"发送认证请求时发生错误: {str(e)}")
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
                "/api/v1/alpha/account",
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
                    price = await self.get_price(usdt_symbol, "alpha")
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

    async def get_account_overview(self, api_key: str, secret_key: str) -> Optional[Dict]:
        """
        获取账户总览信息
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 账户总览信息字典，或None表示失败
        """
        try:
            # 获取各个账户的资产信息
            alpha_asset = await self.get_alpha_assets(api_key, secret_key)
            fund_asset = await self.get_fund_assets(api_key, secret_key)
            spot_asset = await self.get_spot_assets(api_key, secret_key)
            futures_asset = await self.get_futures_assets(api_key, secret_key)
            
            # 计算总资产
            total_asset = 0.0
            
            if alpha_asset:
                total_asset += alpha_asset.get("total", 0)
            if fund_asset:
                total_asset += fund_asset.get("total", 0)
            if spot_asset:
                total_asset += spot_asset.get("total", 0)
            if futures_asset:
                total_asset += futures_asset.get("total", 0)
            
            # 计算今日盈亏（简化版本，实际应该使用历史数据）
            today_profit = 0.0
            profit_rate = 0.0
            
            if total_asset > 0:
                # 这里简化处理，实际应该从历史数据中获取昨日总资产
                yesterday_total_asset = total_asset * 0.99  # 假设昨日总资产是今天的99%
                today_profit = total_asset - yesterday_total_asset
                profit_rate = (today_profit / yesterday_total_asset) * 100
            
            return {
                "total_asset": round(total_asset, 2),
                "today_profit": round(today_profit, 2),
                "profit_rate": round(profit_rate, 2),
                "alpha_asset": round(alpha_asset.get("total", 0), 2) if alpha_asset else 0,
                "fund_asset": round(fund_asset.get("total", 0), 2) if fund_asset else 0,
                "spot_asset": round(spot_asset.get("total", 0), 2) if spot_asset else 0,
                "futures_asset": round(futures_asset.get("total", 0), 2) if futures_asset else 0
            }
        except Exception as e:
            logger.error(f"获取账户总览时发生错误: {str(e)}")
            return None

    async def bind_api_key(self, user_id: str, api_key: str, secret_key: str) -> bool:
        """
        绑定用户的币安API密钥
        :param user_id: 用户ID
        :param api_key: API密钥的key
        :param secret_key: API密钥的secret
        :return: 绑定是否成功
        """
        try:
            # 初始化加密密钥
            await self._init_encryption_key()
            
            # 加密API密钥
            encrypted_api_key = await encrypt_data(api_key, self.encryption_key)
            encrypted_secret_key = await encrypt_data(secret_key, self.encryption_key)
            
            # 读取现有的API密钥数据
            user_api_data = {}
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
            
            # 存储加密后的API密钥
            user_api_data[user_id] = {
                "api_key": encrypted_api_key,
                "secret_key": encrypted_secret_key,
                "bind_time": time.time()
            }
            
            # 保存到文件
            with open(self.user_api_file, "w", encoding="utf-8") as f:
                json.dump(user_api_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"绑定API密钥时发生错误: {str(e)}")
            return False

    async def unbind_api_key(self, user_id: str) -> bool:
        """
        解除绑定用户的币安API密钥
        :param user_id: 用户ID
        :return: 解除绑定是否成功
        """
        try:
            # 读取现有的API密钥数据
            user_api_data = {}
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
            
            # 删除用户的API密钥
            if user_id in user_api_data:
                del user_api_data[user_id]
                
                # 保存到文件
                with open(self.user_api_file, "w", encoding="utf-8") as f:
                    json.dump(user_api_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"解除绑定API密钥时发生错误: {str(e)}")
            return False

    async def get_user_api_key(self, user_id: str) -> Optional[Tuple[str, str]]:
        """
        获取用户的币安API密钥
        :param user_id: 用户ID
        :return: 包含API密钥的元组(api_key, secret_key)，或None表示失败
        """
        try:
            # 初始化加密密钥
            await self._init_encryption_key()
            
            # 读取现有的API密钥数据
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
                    
                # 获取用户的加密API密钥
                if user_id in user_api_data:
                    encrypted_api_key = user_api_data[user_id].get("api_key")
                    encrypted_secret_key = user_api_data[user_id].get("secret_key")
                    
                    # 解密API密钥
                    api_key = await decrypt_data(encrypted_api_key, self.encryption_key)
                    secret_key = await decrypt_data(encrypted_secret_key, self.encryption_key)
                    
                    return (api_key, secret_key)
            
            return None
        except Exception as e:
            logger.error(f"获取用户API密钥时发生错误: {str(e)}")
            return None

    async def start_price_monitor(self) -> None:
        """
        启动价格监控定时任务
        """
        if self.price_monitor_task:
            logger.info("价格监控任务已经在运行")
            return
        
        async def monitor_loop():
            while True:
                try:
                    # 读取监控配置
                    monitor_configs = {}
                    if os.path.exists(self.price_monitor_file):
                        with open(self.price_monitor_file, "r", encoding="utf-8") as f:
                            monitor_configs = json.load(f)
                    
                    # 处理每个监控配置
                    for user_id, configs in monitor_configs.items():
                        for config in configs:
                            symbol = config.get("symbol")
                            asset_type = config.get("asset_type", "spot")
                            target_price = config.get("target_price")
                            condition = config.get("condition", "eq")
                            
                            # 获取当前价格
                            current_price = await self.get_price(symbol, asset_type)
                            if current_price:
                                # 检查价格条件
                                trigger = False
                                if condition == "eq" and current_price == target_price:
                                    trigger = True
                                elif condition == "gt" and current_price > target_price:
                                    trigger = True
                                elif condition == "lt" and current_price < target_price:
                                    trigger = True
                                elif condition == "gte" and current_price >= target_price:
                                    trigger = True
                                elif condition == "lte" and current_price <= target_price:
                                    trigger = True
                                
                                # 如果满足条件，发送通知
                                if trigger:
                                    message = f"📊 {symbol} {asset_type} 价格已达到 {current_price} USDT，触发条件：{condition} {target_price} USDT"
                                    # 这里应该调用消息发送API，但需要根据具体的AstrBot API来实现
                                    logger.info(f"发送价格提醒给用户 {user_id}: {message}")
                except Exception as e:
                    logger.error(f"价格监控任务执行错误: {str(e)}")
                
                # 等待下一次检查
                await asyncio.sleep(self.monitor_interval)
        
        # 启动监控任务
        self.price_monitor_task = asyncio.create_task(monitor_loop())
        logger.info("价格监控任务已启动")

    async def stop_price_monitor(self) -> None:
        """
        停止价格监控定时任务
        """
        if self.price_monitor_task:
            self.price_monitor_task.cancel()
            self.price_monitor_task = None
            logger.info("价格监控任务已停止")
        else:
            logger.info("价格监控任务没有在运行")

    async def add_price_monitor(self, user_id: str, symbol: str, asset_type: str, target_price: float, condition: str) -> bool:
        """
        添加价格监控
        :param user_id: 用户ID
        :param symbol: 交易对，如BTCUSDT
        :param asset_type: 资产类型，如spot, futures等
        :param target_price: 目标价格
        :param condition: 触发条件，如eq, gt, lt, gte, lte
        :return: 添加是否成功
        """
        try:
            # 读取现有的监控配置
            monitor_configs = {}
            if os.path.exists(self.price_monitor_file):
                with open(self.price_monitor_file, "r", encoding="utf-8") as f:
                    monitor_configs = json.load(f)
            
            # 创建或更新用户的监控配置
            if user_id not in monitor_configs:
                monitor_configs[user_id] = []
            
            # 添加新的监控配置
            new_config = {
                "symbol": symbol,
                "asset_type": asset_type,
                "target_price": target_price,
                "condition": condition,
                "create_time": time.time()
            }
            
            monitor_configs[user_id].append(new_config)
            
            # 保存到文件
            with open(self.price_monitor_file, "w", encoding="utf-8") as f:
                json.dump(monitor_configs, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"添加价格监控时发生错误: {str(e)}")
            return False

    async def remove_price_monitor(self, user_id: str, index: int) -> bool:
        """
        移除价格监控
        :param user_id: 用户ID
        :param index: 监控配置的索引
        :return: 移除是否成功
        """
        try:
            # 读取现有的监控配置
            monitor_configs = {}
            if os.path.exists(self.price_monitor_file):
                with open(self.price_monitor_file, "r", encoding="utf-8") as f:
                    monitor_configs = json.load(f)
            
            # 检查用户是否有监控配置
            if user_id not in monitor_configs:
                return False
            
            # 检查索引是否有效
            if 0 <= index < len(monitor_configs[user_id]):
                # 移除指定索引的监控配置
                del monitor_configs[user_id][index]
                
                # 保存到文件
                with open(self.price_monitor_file, "w", encoding="utf-8") as f:
                    json.dump(monitor_configs, f, ensure_ascii=False, indent=2)
                
                return True
            
            return False
        except Exception as e:
            logger.error(f"移除价格监控时发生错误: {str(e)}")
            return False

    async def list_price_monitors(self, user_id: str) -> Optional[list]:
        """
        获取用户的所有价格监控配置
        :param user_id: 用户ID
        :return: 监控配置列表，或None表示失败
        """
        try:
            # 读取现有的监控配置
            monitor_configs = {}
            if os.path.exists(self.price_monitor_file):
                with open(self.price_monitor_file, "r", encoding="utf-8") as f:
                    monitor_configs = json.load(f)
            
            return monitor_configs.get(user_id, [])
        except Exception as e:
            logger.error(f"获取价格监控配置时发生错误: {str(e)}")
            return None

    async def handle_price_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理价格查询命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            # 提取命令参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 2:
                return "❌ 请输入正确的命令格式：/price <交易对> [资产类型]"
            
            symbol = parts[1]
            asset_type = parts[2] if len(parts) >= 3 else "spot"
            
            # 验证资产类型
            if asset_type not in ["spot", "futures", "margin", "alpha"]:
                return "❌ 不支持的资产类型，请使用 spot/futures/margin/alpha"
            
            # 获取价格
            price = await self.get_price(symbol, asset_type)
            if price:
                return f"💰 {symbol} ({asset_type}) 当前价格：{price} USDT"
            else:
                return "❌ 获取价格失败，请稍后重试"
        except Exception as e:
            logger.error(f"处理价格命令时发生错误: {str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

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
                return "❌ 您尚未绑定币安API密钥，请先使用绑定命令绑定"
            
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

    async def _format_asset_details(self, asset_data: Dict, asset_name: str, emoji: str) -> str:
        """
        格式化资产详情信息
        
        :param asset_data: 资产数据字典
        :param asset_name: 资产名称
        :param emoji: 资产显示emoji
        :return: 格式化后的资产信息字符串
        """
        if asset_data['details']:
            details = "\n".join([f"{item['symbol']}: {item['amount']} USDT" for item in asset_data['details']])
        else:
            details = "无资产"
        return (
            f"{emoji} {asset_name}资产\n"
            f"总资产：{asset_data['total']} USDT\n"
            f"详细信息：\n{details}"
        )

    async def handle_bind_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理API密钥绑定命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            # 提取命令参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 3:
                return "❌ 请输入正确的命令格式：/bind <API Key> <Secret Key>"
            
            api_key = parts[1]
            secret_key = parts[2]
            
            # 验证API密钥格式（简单验证）
            if len(api_key) < 20 or len(secret_key) < 20:
                return "❌ API密钥格式不正确，请检查后重试"
            
            # 获取用户ID
            user_id = event.get_sender_id()
            
            # 绑定API密钥
            success = await self.bind_api_key(user_id, api_key, secret_key)
            
            if success:
                return "✅ 币安API密钥绑定成功 ✅"
            else:
                return "❌ API密钥绑定失败，请稍后重试"
                
        except Exception as e:
            logger.error(f"处理绑定命令时发生错误：{str(e)}")
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
                return "✅ 币安API密钥解除绑定成功 ✅"
            else:
                return "❌ 解除绑定失败，请稍后重试"
                
        except Exception as e:
            logger.error(f"处理解除绑定命令时发生错误：{str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def handle_monitor_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理价格监控命令
        :param event: 消息事件
        :return: 回复消息
        """
        try:
            # 提取命令参数
            message_content = event.message_str.strip()
            parts = message_content.split()
            
            if len(parts) < 2:
                return "❌ 请输入正确的命令格式：/monitor <add/list/remove> [参数]"
            
            sub_command = parts[1].lower()
            user_id = event.get_sender_id()
            
            if sub_command == "add":
                # 添加价格监控
                if len(parts) < 6:
                    return "❌ 请输入正确的命令格式：/monitor add <交易对> <资产类型> <目标价格> <条件(eq/gt/lt/gte/lte)>"
                
                symbol = parts[2]
                asset_type = parts[3]
                target_price = float(parts[4])
                condition = parts[5]
                
                # 验证资产类型
                if asset_type not in ["spot", "futures", "margin", "alpha"]:
                    return "❌ 不支持的资产类型，请使用 spot/futures/margin/alpha"
                
                # 验证条件
                if condition not in ["eq", "gt", "lt", "gte", "lte"]:
                    return "❌ 不支持的条件，请使用 eq/gt/lt/gte/lte"
                
                # 添加监控
                success = await self.add_price_monitor(user_id, symbol, asset_type, target_price, condition)
                if success:
                    return "✅ 价格监控已添加"
                else:
                    return "❌ 添加价格监控失败"
            
            elif sub_command == "list":
                # 列出价格监控
                monitors = await self.list_price_monitors(user_id)
                if monitors:
                    output = ["📋 您的价格监控列表："]
                    for i, monitor in enumerate(monitors):
                        symbol = monitor.get("symbol")
                        asset_type = monitor.get("asset_type")
                        target_price = monitor.get("target_price")
                        condition = monitor.get("condition")
                        output.append(f"{i+1}. {symbol} ({asset_type}) - 条件: {condition} {target_price} USDT")
                    return "\n".join(output)
                else:
                    return "您还没有设置任何价格监控"
            
            elif sub_command == "remove":
                # 移除价格监控
                if len(parts) < 3:
                    return "❌ 请输入正确的命令格式：/monitor remove <索引>"
                
                try:
                    index = int(parts[2]) - 1  # 转换为0-based索引
                    success = await self.remove_price_monitor(user_id, index)
                    if success:
                        return "✅ 价格监控已移除"
                    else:
                        return "❌ 移除价格监控失败，请检查索引是否正确"
                except ValueError:
                    return "❌ 请输入有效的索引数字"
            
            else:
                return "❌ 不支持的子命令，请使用 add/list/remove"
                
        except Exception as e:
            logger.error(f"处理监控命令时发生错误：{str(e)}")
            return "❌ 处理请求时发生错误，请稍后重试"

    async def handle_help_command(self, event: AstrMessageEvent, *args, **kwargs) -> str:
        """
        处理帮助命令
        :param event: 消息事件
        :return: 帮助信息
        """
        help_text = """📚 币安插件命令帮助\n\n"""
        help_text += "💡 价格查询\n"""
        help_text += "/price <交易对> [资产类型] - 查询交易对价格\n"""
        help_text += "示例：/price BTCUSDT spot\n\n"""
        help_text += " 资产查询\n"""
        help_text += "/asset [查询类型] - 查询账户资产\n"""
        help_text += "查询类型：overview(默认)/alpha/资金/现货/合约\n"""
        help_text += "示例：/asset overview\n\n"""
        help_text += "🔐 API密钥管理\n"""
        help_text += "/bind <API Key> <Secret Key> - 绑定币安API密钥\n"""
        help_text += "/unbind - 解除绑定币安API密钥\n\n"""
        help_text += "📈 价格监控\n"""
        help_text += "/monitor add <交易对> <资产类型> <目标价格> <条件> - 添加价格监控\n"""
        help_text += "/monitor list - 查看价格监控列表\n"""
        help_text += "/monitor remove <索引> - 移除价格监控\n\n"""
        help_text += "条件说明：eq(等于), gt(大于), lt(小于), gte(大于等于), lte(小于等于)\n\n"""
        help_text += "ℹ️ 资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)\n\n"""
        help_text += "📖 帮助\n"""
        help_text += "/help - 查看帮助信息\n"""
        
        return help_text