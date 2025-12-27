import time
import hmac
import hashlib
import httpx
from urllib.parse import urlencode


class BinancePrivateAPI:
    def __init__(self, api_key, secret_key, base_url):
        self.api_key = api_key
        self.secret_key = secret_key.encode()
        self.base_url = base_url
        self.headers = {"X-MBX-APIKEY": api_key}

    def _sign(self, params):
        query = urlencode(params)
        sig = hmac.new(self.secret_key, query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    async def _get(self, path, params):
        params["timestamp"] = int(time.time() * 1000)
        params = self._sign(params)
        async with httpx.AsyncClient() as c:
            r = await c.get(self.base_url + path, params=params, headers=self.headers)
            return r.json()

    async def get_asset_overview(self):
        spot = await self.get_spot_assets(raw=True)
        funding = await self.get_funding_assets(raw=True)

        total = 0.0
        for a in spot + funding:
            total += float(a.get("free", 0) or a.get("balance", 0))

        return f"📊 资产总览\n预估总资产：{total:.4f} USDT"

    async def get_spot_assets(self, raw=False):
        data = await self._get("/api/v3/account", {})
        assets = [a for a in data["balances"] if float(a["free"]) > 0]
        if raw:
            return assets
        return "📦 现货账户\n" + "\n".join(f'{a["asset"]}: {a["free"]}' for a in assets)

    async def get_funding_assets(self, raw=False):
        data = await self._get("/sapi/v1/asset/get-funding-asset", {})
        assets = [a for a in data if float(a["free"]) > 0]
        if raw:
            return assets
        return "💰 资金账户\n" + "\n".join(f'{a["asset"]}: {a["free"]}' for a in assets)

    async def get_alpha_assets(self):
        data = await self._get("/sapi/v1/asset/assetDetail", {})
        assets = []
        for k, v in data.items():
            bal = v.get("availableBalance", "0")
            if float(bal) > 0:
                assets.append(f"{k}: {bal}")
        return "🅰 Alpha 账户\n" + ("\n".join(assets) if assets else "无资产")

    async def get_future_assets(self):
        data = await self._get("/fapi/v2/account", {})
        assets = [a for a in data["assets"] if float(a["walletBalance"]) > 0]
        return "📉 合约账户\n" + "\n".join(
            f'{a["asset"]}: {a["walletBalance"]}' for a in assets
        )
