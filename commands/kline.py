from ..services.price_service import PriceService
from ..utils.symbol import normalize_symbol
import aiohttp


async def cmd_kline(event, config):
    parts = event.message_str.strip().split()

    if len(parts) < 2:
        yield event.plain_result("用法：/kline <交易对> [资产类型] [时间间隔]\n例如：/kline BTCUSDT spot 1h\n\n资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)\n时间间隔：1m, 5m, 15m, 30m, 1h, 4h, 1d")
        return

    symbol = parts[1]
    
    # 解析可选参数
    asset_type = "spot"
    interval = "1h"
    
    if len(parts) >= 3:
        asset_type = parts[2].lower()
        
        # 验证资产类型
        valid_asset_types = ["spot", "futures", "margin", "alpha"]
        if asset_type not in valid_asset_types:
            yield event.plain_result(f"无效的资产类型: {asset_type}\n支持的资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)")
            return
    
    if len(parts) >= 4:
        interval = parts[3].lower()
        
        # 验证时间间隔
        valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
        if interval not in valid_intervals:
            yield event.plain_result(f"无效的时间间隔: {interval}\n支持的时间间隔：1m, 5m, 15m, 30m, 1h, 4h, 1d")
            return
    
    try:
        normalized_symbol = normalize_symbol(symbol)
    except ValueError as e:
        yield event.plain_result(f"错误：{e}")
        return
    
    async with aiohttp.ClientSession() as session:
        price_service = PriceService(session, config)
        
        try:
            kline_data = await price_service.get_kline(normalized_symbol, asset_type, interval)
        except Exception as e:
            yield event.plain_result(f"查询失败：{e}")
            return
    
    if not kline_data:
        yield event.plain_result(f"获取K线数据失败，请检查交易对和参数是否正确")
        return
    
    # 格式化K线数据输出
    # 只显示最近5条K线数据（避免输出过长）
    recent_klines = kline_data[-5:]
    output_lines = [f"📊 {normalized_symbol} {asset_type} {interval} K线数据（最近5条）"]
    
    for kline in recent_klines:
        # K线数据结构：[开盘时间, 开盘价, 最高价, 最低价, 收盘价, 成交量, ...]
        timestamp = kline[0]
        open_price = kline[1]
        high_price = kline[2]
        low_price = kline[3]
        close_price = kline[4]
        volume = kline[5]
        
        # 格式化时间（将毫秒时间戳转换为人类可读格式）
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp / 1000)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # 计算涨跌幅
        try:
            change = (float(close_price) - float(open_price)) / float(open_price) * 100
            change_str = f"{'+' if change > 0 else ''}{change:.2f}%"
        except:
            change_str = "N/A"
        
        output_lines.append(f"[{time_str}] O: {open_price} H: {high_price} L: {low_price} C: {close_price} ({change_str}) V: {volume}")
    
    yield event.plain_result("\n".join(output_lines))
