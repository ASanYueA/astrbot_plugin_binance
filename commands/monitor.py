from ..services.monitor_service import MonitorService
from ..services.price_service import PriceService
from ..utils.symbol import normalize_symbol
from astrbot.api import logger


async def cmd_monitor(event, config, price_service, monitor_service, *args, **kwargs):
    """
    监控命令主函数，分发处理不同的子命令
    
    :param event: 消息事件对象
    :param config: 配置对象
    :param price_service: 价格服务实例
    :param monitor_service: 监控服务实例
    :return: 生成器，产生处理结果
    """
    logger.info(f"收到监控命令: {event.message_str}")
    try:
        message_content = event.message_str.strip()
        parts = message_content.split()
        logger.debug(f"监控命令参数: {parts}")
        
        if len(parts) < 2:
            yield event.plain_result("❌ 请输入正确的命令格式：/监控 设置/取消/列表 [参数]")
            return
        
        sub_command = parts[1].lower()
        
        if sub_command == "设置":
            async for result in handle_monitor_set(event, parts, monitor_service):
                yield result
        elif sub_command == "取消":
            async for result in handle_monitor_cancel(event, parts, monitor_service):
                yield result
        elif sub_command == "列表":
            async for result in handle_monitor_list(event, monitor_service):
                yield result
        else:
            yield event.plain_result("❌ 不支持的子命令，请使用：设置、取消、列表")
    except Exception as e:
        logger.error(f"处理监控命令时发生错误: {str(e)}")
        yield event.plain_result("❌ 处理监控命令时发生错误，请稍后重试")


async def handle_monitor_set(event, parts, monitor_service, *args, **kwargs):
    """
    处理监控设置命令
    
    :param event: 消息事件对象
    :param parts: 命令参数列表
    :param monitor_service: 监控服务实例
    :return: 生成器，产生处理结果
    """
    try:
        if len(parts) < 6:
            yield event.plain_result("❌ 请输入正确的命令格式：/监控 设置 <交易对> <资产类型> <目标价格> <方向>")
            yield event.plain_result("例如：/监控 设置 BTCUSDT futures 50000 up")
            return
        
        symbol = parts[2]
        asset_type_param = parts[3].lower()
        target_price_str = parts[4]
        direction_param = parts[5].lower()
        
        # 验证资产类型
        if asset_type_param not in ["spot", "futures", "margin", "alpha"]:
            yield event.plain_result("❌ 不支持的资产类型，请使用：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)")
            return
        
        # 验证方向参数
        if direction_param not in ["up", "down"]:
            yield event.plain_result("❌ 不支持的方向，请使用：up(上涨到), down(下跌到)")
            return
        
        # 验证目标价格格式
        try:
            target_price = float(target_price_str)
            if target_price <= 0:
                raise ValueError("价格必须大于0")
        except ValueError:
            yield event.plain_result("❌ 目标价格必须是有效的正数")
            return
        
        # 规范化交易对
        try:
            normalized_symbol = normalize_symbol(symbol)
        except ValueError as e:
            yield event.plain_result(f"❌ {str(e)}")
            return
        
        user_id = event.get_sender_id()
        
        # 设置监控
        logger.info(f"为用户 {user_id} 设置监控：{normalized_symbol} ({asset_type_param}) {direction_param} {target_price}")
        monitor_id = await monitor_service.set_price_monitor(user_id, normalized_symbol, asset_type_param, target_price, direction_param)
        
        if monitor_id:
            yield event.plain_result(f"✅ 价格监控设置成功！监控ID：{monitor_id}")
        else:
            yield event.plain_result("❌ 设置监控失败，请稍后重试")
    except Exception as e:
        logger.error(f"处理监控设置命令时发生错误: {str(e)}")
        yield event.plain_result("❌ 设置监控时发生错误，请稍后重试")


async def handle_monitor_cancel(event, parts, monitor_service, *args, **kwargs):
    """
    处理监控取消命令
    
    :param event: 消息事件对象
    :param parts: 命令参数列表
    :param monitor_service: 监控服务实例
    :return: 生成器，产生处理结果
    """
    try:
        if len(parts) < 3:
            yield event.plain_result("❌ 请输入正确的命令格式：/监控 取消 <监控ID>")
            yield event.plain_result("例如：/监控 取消 1234abcd")
            return
        
        monitor_id = parts[2]
        user_id = event.get_sender_id()
        
        # 取消监控
        logger.info(f"用户 {user_id} 尝试取消监控ID：{monitor_id}")
        success = await monitor_service.cancel_price_monitor(user_id, monitor_id)
        
        if success:
            yield event.plain_result(f"✅ 监控ID为{monitor_id}的价格监控已成功取消")
        else:
            yield event.plain_result("❌ 取消监控失败，请检查监控ID是否正确")
    except Exception as e:
        logger.error(f"处理监控取消命令时发生错误: {str(e)}")
        yield event.plain_result("❌ 取消监控时发生错误，请稍后重试")


async def handle_monitor_list(event, monitor_service, *args, **kwargs):
    """
    处理监控列表查询命令
    
    :param event: 消息事件对象
    :param monitor_service: 监控服务实例
    :return: 生成器，产生处理结果
    """
    try:
        user_id = event.get_sender_id()
        
        # 获取用户监控列表
        logger.info(f"用户 {user_id} 查询监控列表")
        monitors = await monitor_service.get_user_monitors(user_id)
        
        if not monitors:
            yield event.plain_result("✅ 您没有设置任何价格监控")
            return
        
        # 构建监控列表
        monitor_list = []
        for monitor_id, monitor_data in monitors.items():
            symbol = monitor_data["symbol"]
            asset_type = monitor_data["asset_type"]
            target_price = monitor_data["target_price"]
            direction = monitor_data["direction"]
            is_active = monitor_data["is_active"]
            
            # 格式化监控信息
            asset_type_text = {
                "spot": "现货",
                "futures": "合约",
                "margin": "杠杆",
                "alpha": "Alpha货币"
            }[asset_type]
            direction_text = "上涨到" if direction == "up" else "下跌到"
            status_text = "🟢 活跃" if is_active else "🔴 已关闭"
            
            monitor_list.append(f"📌 监控ID：{monitor_id}\n  交易对：{symbol} ({asset_type_text})\n  监控条件：{direction_text} {target_price:.8f} USDT\n  状态：{status_text}")
        
        # 合并为回复消息
        yield event.plain_result(f"📋 您的价格监控列表：\n\n" + "\n\n".join(monitor_list))
    except Exception as e:
        logger.error(f"处理监控列表命令时发生错误: {str(e)}")
        yield event.plain_result("❌ 查询监控列表时发生错误，请稍后重试")
