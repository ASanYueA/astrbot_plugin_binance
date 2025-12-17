import hmac
import hashlib
import time
import json
import httpx
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from astrbot.api import logger

BINANCE_BASE = "https://api.binance.com/api/v3"

@register("astrbot_plugin_binance", "YourName", "Binance 查询插件扩展版", "0.2.0")
class BinancePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.api_key = self.config.get("api_key", "")
        self.secret_key = self.config.get("secret_key", "")
        self.push_interval = self.config.get("push_interval", 0)
        self.push_symbol = self.config.get("push_symbol", "BTCUSDT")
        if self.push_interval > 0:
            asyncio.create_task(self._push_loop())

    async def fetch_price(self, symbol: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{BINANCE_BASE}/ticker/price", params={"symbol": symbol.upper()})
                data = resp.json()
                if "price" in data:
                    return f"{symbol.upper()} 当前价格: {data['price']} USD"
                return f"未找到 {symbol.upper()} 的价格信息"
            except Exception as e:
                logger.error(f"Binance 查询失败: {e}")
                return f"查询出错: {e}"

    async def fetch_prices_bulk(self, symbols: list) -> str:
        results = []
        for s in symbols:
            r = await self.fetch_price(s)
            results.append(r)
        return "\n".join(results)

    # Binance 签名请求
    def _sign(self, params: dict) -> str:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def get_account_info(self) -> str:
        if not self.api_key or not self.secret_key:
            return "请在配置中填写 Binance API Key 和 Secret 才能查询账户资产"
        ts = int(time.time() * 1000)
        params = {"timestamp": ts}
        params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{BINANCE_BASE}/account", params=params, headers=headers)
                data = resp.json()
                if "balances" in data:
                    assets = [f"{b['asset']}: {b['free']}" for b in data['balances'] if float(b['free']) > 0]
                    return "账户资产:\n" + "\n".join(assets)
                return f"账户信息查询失败: {data}"
            except Exception as e:
                logger.error(f"Binance账户查询失败: {e}")
                return f"查询出错: {e}"

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 10) -> str:
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{BINANCE_BASE}/klines", params=params)
                data = resp.json()
                result = [f"时间: {time.strftime('%Y-%m-%d %H:%M', time.localtime(k[0]/1000))}, 收盘价: {k[4]}" for k in data]
                return "\n".join(result)
            except Exception as e:
                logger.error(f"K线查询失败: {e}")
                return f"K线查询失败: {e}"

    async def _push_loop(self):
        while True:
            await asyncio.sleep(self.push_interval)
            result = await self.fetch_prices_bulk(self.push_symbol.split(","))
            await self.context.send(result)

    @filter.command("price")
    async def cmd_price(self, event: AstrMessageEvent):
        msg = event.message_str.strip()
        parts = msg.split()
        if len(parts) < 2:
            yield event.plain_result("请在命令后输入币种，例如: /price BTCUSDT 或 /price BTCUSDT,ETHUSDT")
            return
        symbols = parts[1].split(",")
        result = await self.fetch_prices_bulk(symbols)
        yield event.plain_result(result)

    @filter.command("account")
    async def cmd_account(self, event: AstrMessageEvent):
        """查询账户资产"""
        result = await self.get_account_info()
        yield event.plain_result(result)

    @filter.command("kline")
    async def cmd_kline(self, event: AstrMessageEvent):
        """
        查询 K线
        /kline BTCUSDT 1h 5
        """
        msg = event.message_str.strip()
        parts = msg.split()
        if len(parts) < 2:
            yield event.plain_result("请在命令后输入币种，间隔，数量，例如: /kline BTCUSDT 1h 5")
            return
        symbol = parts[1]
        interval = parts[2] if len(parts) > 2 else "1h"
        limit = int(parts[3]) if len(parts) > 3 else 10
        result = await self.get_klines(symbol, interval, limit)
        yield event.plain_result(result)
