"""
币安价格查询服务模块
"""
import aiohttp
from typing import Optional
from astrbot.api import logger
from ..utils.symbol import normalize_symbol


class PriceService:
    """
    价格查询服务类，处理不同类型的价格查询请求
    """
    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config
        self.api_url = self.config.get("binance_api_url", "https://api.binance.com")
        self.timeout = self.config.get("request_timeout", 10)
    
    async def get_price(self, symbol: str, asset_type: str = "spot") -> Optional[float]:
        """
        通过币安公共API查询交易对价格
        :param symbol: 交易对，如BTCUSDT
        :param asset_type: 资产类型，可选值：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)
        :return: 价格，或None表示失败
        """
        logger.info(f"开始查询价格：symbol={symbol}, asset_type={asset_type}")
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
                                    price = float(spot_data.get('price', 0))
                                    logger.info(f"成功获取现货价格作为Alpha价格的后备: {price}")
                                    return price
                                else:
                                    spot_response_text = await spot_response.text()
                                    logger.error(f"现货价格查询也失败，状态码: {spot_response.status}，响应内容: {spot_response_text}")
                        except Exception as e:
                            logger.error(f"获取后备现货价格时发生错误: {str(e)}")
                    
                    logger.info(f"价格查询失败，返回None: symbol={symbol}, asset_type={asset_type}")
                    return None
        except Exception as e:
            logger.error(f"获取{asset_type}价格时发生错误: {str(e)}", exc_info=True)
            return None

    async def get_kline(self, symbol: str, asset_type: str = "spot", interval: str = "1h", limit: int = 200) -> Optional[list]:
        """
        通过币安公共API查询K线数据
        :param symbol: 交易对，如BTCUSDT
        :param asset_type: 资产类型，可选值：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)
        :param interval: 时间间隔，如1m, 5m, 15m, 30m, 1h, 4h, 1d
        :param limit: 返回K线数量，默认200，最大1000
        :return: K线数据列表，或None表示失败
        """
        logger.info(f"开始查询K线：symbol={symbol}, asset_type={asset_type}, interval={interval}, limit={limit}")
        try:
            # 标准化交易对格式
            normalized_symbol = normalize_symbol(symbol)
            
            # 验证时间间隔
            valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
            if interval not in valid_intervals:
                logger.error(f"不支持的时间间隔: {interval}")
                return None
            
            # 限制limit的最大值
            limit = min(limit, 1000)
            
            # 根据资产类型选择不同的API域名和端点
            if asset_type == "spot":
                # 现货API
                api_domain = self.api_url
                url = f"{api_domain}/api/v3/klines"
            elif asset_type == "futures":
                # 永续合约API（使用不同的域名）
                api_futures_url = self.config.get("api_futures_url", "https://fapi.binance.com")
                api_domain = api_futures_url
                url = f"{api_domain}/fapi/v1/klines"
            elif asset_type == "margin":
                # 杠杆API - 杠杆交易使用与现货相同的K线API
                api_domain = self.api_url
                url = f"{api_domain}/api/v3/klines"
            elif asset_type == "alpha":
                # Alpha货币 - 使用现货API
                api_alpha_url = self.config.get("api_alpha_url", self.api_url)
                api_domain = api_alpha_url
                url = f"{api_domain}/api/v3/klines"
            else:
                logger.error(f"不支持的资产类型: {asset_type}")
                return None
            
            params = {
                "symbol": normalized_symbol,
                "interval": interval,
                "limit": limit
            }
            
            logger.debug(f"查询{asset_type}K线：URL={url}, 参数={params}")
            
            async with self.session.get(url, params=params) as response:
                logger.debug(f"API响应状态码: {response.status}, 响应头: {response.headers}")
                
                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"API响应数据: {data}")
                    logger.info(f"成功获取K线数据: symbol={symbol}, asset_type={asset_type}, interval={interval}, 数据条数={len(data)}")
                    return data
                else:
                    response_text = await response.text()
                    logger.error(f"获取{asset_type}K线失败，状态码: {response.status}，响应内容: {response_text}")
                    
                    # 尝试解析错误响应
                    try:
                        error_data = await response.json()
                        if "code" in error_data and "msg" in error_data:
                            logger.error(f"API错误代码: {error_data['code']}, 错误信息: {error_data['msg']}")
                    except Exception:
                        pass
                    
                    logger.info(f"K线查询失败，返回None: symbol={symbol}, asset_type={asset_type}, interval={interval}")
                    return None
        except Exception as e:
            logger.error(f"获取{asset_type}K线时发生错误: {str(e)}", exc_info=True)
            return None
