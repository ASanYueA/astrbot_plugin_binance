import httpx


class BinancePublicAPI:
    def __init__(self, base_url: str, timeout: int):
        self.base_url = base_url
        self.timeout = timeout

    async def get_spot_price(self, symbol: str) -> str:
        url = f"{self.base_url}/api/v3/ticker/price"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params={"symbol": symbol})
            data = resp.json()

            if "price" not in data:
                raise RuntimeError("返回数据异常")

            return data["price"]
