from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import httpx
import asyncio

BINANCE_BASE = "https://api.binance.com/api/v3/ticker/price"

@register("astrbot_plugin_binance", "your_name", "Binance 查询插件", "0.1.0")
class BinancePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        # 配置对象，可读取 _conf_schema.json 中定义的值
        self.config = config or {}
        self.api_key = self.config.get("api_key", "")
        self.secret_key = self.config.get("secret_key", "")

    async def fetch_price(self, symbol: str) -> str:
        """异步获取币安价格（公开接口）"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                # Binance 公开价格查询
                resp = await client.get(BINANCE_BASE, params={"symbol": symbol.upper()})
                data = resp.json()
                if resp.status_code == 200 and "price" in data:
                    return f"{symbol.upper()} 当前价格: {data['price']} USD"
                return f"未找到 {symbol.upper()} 的价格信息"
            except Exception as e:
                logger.error(f"Binance 查询失败: {e}")
                return f"查询出错: {str(e)}"

    @filter.command("price")
    async def cmd_price(self, event: AstrMessageEvent):
        """
        查询币安价格
        指令: /price BTCUSDT
        """
        msg = event.message_str.strip()
        parts = msg.split()
        if len(parts) < 2:
            yield event.plain_result("请在命令后输入币种，例如: /price BTCUSDT")
            return

        symbol = parts[1]
        result = await self.fetch_price(symbol)
        yield event.plain_result(result)
