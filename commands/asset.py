from ..storage.user_store import get_user
from ..utils.crypto import decrypt
from ..services.private import BinancePrivateAPI


async def cmd_asset(event, config):
    user = get_user(str(event.user_id))
    if not user:
        yield event.plain_result("❌ 请先使用 /绑定 绑定 API")
        return

    api = BinancePrivateAPI(
        api_key=decrypt(user["api_key"], config["encrypt_secret"]),
        secret_key=decrypt(user["secret_key"], config["encrypt_secret"]),
        base_url=config["binance_base_url"]
    )

    parts = event.message_str.strip().split()

    if len(parts) == 1:
        text = await api.get_asset_overview()
    else:
        t = parts[1]
        if t == "alpha":
            text = await api.get_alpha_assets()
        elif t == "资金":
            text = await api.get_funding_assets()
        elif t == "现货":
            text = await api.get_spot_assets()
        elif t == "合约":
            text = await api.get_future_assets()
        else:
            yield event.plain_result("参数错误：alpha / 资金 / 现货 / 合约")
            return

    yield event.plain_result(text)
