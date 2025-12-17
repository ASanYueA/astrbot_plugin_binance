import hmac
import hashlib
import time
from io import BytesIO
import base64

import httpx
import pandas as pd
import mplfinance as mpf

from astrbot.api.event import filter
from astrbot.api.star import Star, Context, register
from astrbot.api import logger

BINANCE_BASE = "https://api.binance.com/api/v3"
SAPI_BASE = "https://api.binance.com/sapi/v1"


@register("astrbot_plugin_binance", "YourName", "Binance 全功能插件（Aiocqhttp/OneBot 适配）", "1.3.0")
class BinancePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.api_key = self.config.get("api_key", "")
        self.secret_key = self.config.get("secret_key", "")
        self.push_interval = self.config.get("push_interval", 0)
        self.push_symbol = self.config.get("push_symbol", "BTCUSDT")
        if self.push_interval > 0:
            import asyncio
            asyncio.create_task(self._push_loop())

    # -------------------- 币价查询 --------------------
    async def fetch_price(self, symbol: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{BINANCE_BASE}/ticker/price", params={"symbol": symbol.upper()})
                data = resp.json()
                if "price" in data:
                    return f"{symbol.upper()} 当前价格: {data['price']} USD"
                return f"未找到 {symbol.upper()} 的价格信息"
            except Exception as e:
                logger.error(f"查询币价失败: {e}")
                return f"查询出错: {e}"

    async def fetch_prices_bulk(self, symbols: list) -> str:
        results = []
        for s in symbols:
            r = await self.fetch_price(s)
            results.append(r)
        return "\n".join(results)

    # -------------------- 签名 --------------------
    def _sign(self, params: dict) -> str:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    # -------------------- 账户资产查询 --------------------
    async def get_all_assets(self) -> str:
        if not self.api_key or not self.secret_key:
            return "请配置 Binance API Key 和 Secret"

        ts = int(time.time() * 1000)
        headers = {"X-MBX-APIKEY": self.api_key}
        results = []

        async with httpx.AsyncClient(timeout=10) as client:
            # 现货账户
            try:
                spot_params = {"timestamp": ts}
                spot_params["signature"] = self._sign(spot_params)
                resp = await client.get(f"{BINANCE_BASE}/account", params=spot_params, headers=headers)
                spot_data = resp.json()
                spot_assets = [f"{b['asset']}: {b['free']}" for b in spot_data.get("balances", []) if float(b['free']) > 0]
                results.append("现货账户:\n" + "\n".join(spot_assets))
            except Exception as e:
                results.append(f"现货账户查询失败: {e}")

            # 杠杆账户
            try:
                margin_params = {"timestamp": ts}
                margin_params["signature"] = self._sign(margin_params)
                resp = await client.get(f"{SAPI_BASE}/margin/account", params=margin_params, headers=headers)
                margin_data = resp.json()
                margin_assets = [f"{b['asset']}: {b['free']}" for b in margin_data.get("userAssets", []) if float(b['free']) > 0]
                results.append("杠杆账户:\n" + "\n".join(margin_assets))
            except Exception as e:
                results.append(f"杠杆账户查询失败: {e}")

            # Alpha账户（资产明细）
            try:
                alpha_params = {"timestamp": ts}
                alpha_params["signature"] = self._sign(alpha_params)
                resp = await client.get(f"{SAPI_BASE}/asset/assetDetail", params=alpha_params, headers=headers)
                alpha_data = resp.json()
                alpha_assets = [f"{k}: {v['availableBalance']}" for k, v in alpha_data.items() if float(v['availableBalance']) > 0]
                results.append("Alpha账户:\n" + "\n".join(alpha_assets))
            except Exception as e:
                results.append(f"Alpha账户查询失败: {e}")

        return "\n\n".join(results)

    # -------------------- K线生成图片 --------------------
    async def get_kline_image(self, symbol: str, interval: str = "1h", limit: int = 50) -> BytesIO:
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{BINANCE_BASE}/klines", params=params)
            data = resp.json()

        # 12列
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades",
            "taker_buy_base","taker_buy_quote","ignore"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"], unit='ms')
        df.set_index("open_time", inplace=True)
        df = df[["open","high","low","close","volume"]].astype(float)

        buf = BytesIO()
        mpf.plot(df, type='candle', style='yahoo', volume=True, savefig=buf)
        buf.seek(0)
        return buf

    # -------------------- 自动定时推送 --------------------
    async def _push_loop(self):
        import asyncio
        while True:
            await asyncio.sleep(self.push_interval)
            result = await self.fetch_prices_bulk(self.push_symbol.split(","))
            await self.context.send(result)

    # -------------------- AstrBot 命令 --------------------
    @filter.command("price")
    async def cmd_price(self, event):
        msg = event.message_str.strip()
        parts = msg.split()
        if len(parts) < 2:
            yield event.plain_result("请在命令后输入币种，例如: /price BTCUSDT,ETHUSDT")
            return
        symbols = parts[1].split(",")
        result = await self.fetch_prices_bulk(symbols)
        yield event.plain_result(result)

    @filter.command("account")
    async def cmd_account(self, event):
        result = await self.get_all_assets()
        yield event.plain_result(result)

    @filter.command("kline")
    async def cmd_kline(self, event):
        msg = event.message_str.strip()
        parts = msg.split()
        if len(parts) < 2:
            yield event.plain_result("请在命令后输入币种，间隔，数量，例如: /kline BTCUSDT 1h 50")
            return
        symbol = parts[1]
        interval = parts[2] if len(parts) > 2 else "1h"
        limit = int(parts[3]) if len(parts) > 3 else 50

        buf = await self.get_kline_image(symbol, interval, limit)
        img_bytes = buf.getvalue()
        b64_data = base64.b64encode(img_bytes).decode()
        cq_code = f"[CQ:image,file=base64://{b64_data}]"
        await event.reply(cq_code)
