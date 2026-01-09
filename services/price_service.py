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
        :param asset_type: 资产类型，可选值：spot(现货), futures(合约), margin(杠杆)
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
                    
                    return None
        except Exception as e:
            logger.error(f"获取{asset_type}价格时发生错误: {str(e)}")
            return None
