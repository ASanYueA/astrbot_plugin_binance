"""
币安交易对格式标准化工具
"""
def normalize_symbol(symbol: str) -> str:
    """
    标准化交易对格式（兼容多种输入格式，转为币安API要求的大写格式）
    示例：btc-usdt → BTCUSDT，btcusdt → BTCUSDT，BTC-USDT → BTCUSDT
    """
    if not symbol:
        raise ValueError("交易对不能为空")
    # 移除分隔符，转为大写
    normalized = symbol.replace("-", "").replace("_", "").strip().upper()
    # 简单校验（至少包含2个币种标识）
    if len(normalized) < 4:
        raise ValueError(f"无效交易对：{symbol}")
    return normalized
