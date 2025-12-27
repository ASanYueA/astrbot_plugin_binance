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
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 创建aiohttp客户端会话
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
    
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
                # 现货API
                api_domain = self.api_url
                url = f"{api_domain}/api/v3/ticker/price"
            elif asset_type == "futures":
                # 永续合约API（使用不同的域名）
                api_domain = "https://fapi.binance.com"
                url = f"{api_domain}/fapi/v1/ticker/price"
            elif asset_type == "margin":
                # 杠杆API
                api_domain = self.api_url
                url = f"{api_domain}/sapi/v1/margin/market-price"
            elif asset_type == "alpha":
                # Alpha货币API（使用现货API端点）
                api_domain = self.api_url
                url = f"{api_domain}/api/v3/ticker/price"
            else:
                logger.error(f"不支持的资产类型: {asset_type}")
                return None
            
            params = {"symbol": normalized_symbol}
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    # 不同API的返回字段可能略有不同
                    if asset_type == "margin":
                        return float(data.get("price", 0))
                    else:
                        return float(data.get("price", 0))
                else:
                    logger.error(f"获取{asset_type}价格失败，状态码: {response.status}")
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
                return "❌ 价格查询失败，请检查交易对是否正确"
                
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

    async def handle_help_command(self, event: AstrMessageEvent) -> str:
        """
        处理帮助命令，显示所有可用命令
        :param event: 消息事件
        :return: 帮助信息
        """
        help_text = (
            "📚 币安插件命令列表\n"\
            "=================\n"\
            "/price <交易对> [资产类型] - 查询币安资产价格\n"\
            "  资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)\n"\
            "  示例：/price BTCUSDT futures\n"\
            "\n"\
            "/绑定 <API_KEY> <SECRET_KEY> - 绑定币安API密钥\n"\
            "  示例：/绑定 abcdef123456 abcdef123456\n"\
            "\n"\
            "/解除绑定 - 解除绑定币安API密钥\n"\
            "\n"\
            "/资产 [查询类型] - 查询账户资产（需先绑定API）\n"\
            "  查询类型：alpha/资金/现货/合约，不输入则查询总览\n"\
            "  示例：/资产 alpha\n"\
            "\n"\
            "/help - 显示本帮助信息\n"\
            "=================\n"\
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
