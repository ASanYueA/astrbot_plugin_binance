from ..services.public import BinancePublicAPI
from ..utils.symbol import normalize_symbol


async def cmd_price(event, config):
    parts = event.message_str.strip().split()

    if len(parts) < 2:
        yield event.plain_result("用法：/price BTCUSDT")
        return

    symbol = normalize_symbol(parts[1])

    api = BinancePublicAPI(
        base_url=config["binance_base_url"],
        timeout=config["timeout"]
    )

    try:
        price = await api.get_spot_price(symbol)
    except Exception as e:
        yield event.plain_result(f"查询失败：{e}")
        return

    yield event.plain_result(
        f"📈 {symbol}\n现货价格：{price} USDT"
    )
