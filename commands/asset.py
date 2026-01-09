from ..storage.user import get_user_api
from ..utils.crypto import decrypt_data
from ..services.private import BinancePrivateAPI


async def cmd_asset(event, config):
    user_id = str(event.user_id)
    user_api = get_user_api(user_id, config["encrypt_secret"], config["user_data_file"])
    if not user_api:
        yield event.plain_result("❌ 请先使用 /绑定 绑定 API")
        return

    api_key, secret_key = user_api

    api = BinancePrivateAPI(
        api_key=api_key,
        secret_key=secret_key,
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
