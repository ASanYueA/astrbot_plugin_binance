"""
AstrBot 币安插件入口文件
严格遵循官方规范
"""
import asyncio
from astrbot.api.star import register, Context, Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger

# 导入核心模块
from .core import BinanceCore

# 导出插件类
@register("astrbot_plugin_binance", "Binance Plugin Developer", "币安现货价格查询与API绑定插件", "1.0.0")
class BinancePlugin(Star):
    def __init__(self, context: Context, *args, **kwargs):
        super().__init__(context, *args, **kwargs)
        # 初始化核心模块
        self.binance_core = BinanceCore(context)
        logger.info("币安插件初始化成功")
        # 启动价格监控任务
        asyncio.create_task(self.binance_core.start_price_monitor())

    @filter.command("price")
    async def handle_price(self, event: AstrMessageEvent, *args, **kwargs):
        """查询币安资产价格，使用方法：/price <交易对> [资产类型]，例如：/price BTCUSDT futures
资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)"""
        logger.info(f"开始处理价格命令: {event.message_str}")
        try:
            result = await self.binance_core.handle_price_command(event)
            logger.info(f"价格命令处理结果: {result}")
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"处理价格命令时发生错误: {str(e)}")
            yield event.plain_result(f"处理请求时发生错误: {str(e)}")

    @filter.command("绑定")
    async def handle_bind(self, event: AstrMessageEvent, *args, **kwargs):
        """绑定币安API密钥，使用方法：/绑定 <API_KEY> <SECRET_KEY>"""
        logger.info(f"开始处理绑定命令: {event.message_str}")
        try:
            result = await self.binance_core.handle_bind_command(event)
            logger.info(f"绑定命令处理结果: {result}")
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"处理绑定命令时发生错误: {str(e)}")
            yield event.plain_result(f"处理请求时发生错误: {str(e)}")

    @filter.command("资产")
    async def handle_asset(self, event: AstrMessageEvent, *args, **kwargs):
        """查询币安账户资产，使用方法：/资产 [查询类型]
查询类型：alpha/资金/现货/合约，不输入则查询总览"""
        logger.info(f"开始处理资产命令: {event.message_str}")
        try:
            result = await self.binance_core.handle_asset_command(event)
            logger.info(f"资产命令处理结果: {result}")
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"处理资产命令时发生错误: {str(e)}")
            yield event.plain_result(f"处理请求时发生错误: {str(e)}")

    @filter.command("解除绑定")
    async def handle_unbind(self, event: AstrMessageEvent, *args, **kwargs):
        """解除绑定币安API密钥，使用方法：/解除绑定"""
        logger.info(f"开始处理解除绑定命令: {event.message_str}")
        try:
            result = await self.binance_core.handle_unbind_command(event)
            logger.info(f"解除绑定命令处理结果: {result}")
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"处理解除绑定命令时发生错误: {str(e)}")
            yield event.plain_result(f"处理请求时发生错误: {str(e)}")

    @filter.command("bahelp")
    async def handle_help(self, event: AstrMessageEvent, *args, **kwargs):
        """显示币安插件的帮助信息，使用方法：/bahelp"""
        logger.info(f"开始处理帮助命令: {event.message_str}")
        try:
            result = await self.binance_core.handle_help_command(event)
            logger.info(f"帮助命令处理结果: {result}")
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"处理帮助命令时发生错误: {str(e)}")
            yield event.plain_result(f"处理请求时发生错误: {str(e)}")

    @filter.command("kline")
    async def handle_kline(self, event: AstrMessageEvent, *args, **kwargs):
        """查询K线数据，使用方法：/kline <交易对> [资产类型] [时间间隔]
        资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)
        时间间隔：1m, 5m, 15m, 30m, 1h, 4h, 1d
        示例：/kline BTCUSDT spot 1h"""
        logger.info(f"开始处理K线命令: {event.message_str}")
        try:
            # 调用核心处理方法，获取结果
            result = await self.binance_core.handle_kline_command(event)
            
            # 检查结果类型
            if isinstance(result, tuple) and len(result) == 2 and result[0] == "image":
                # 如果是图片结果，发送图片
                image_path = result[1]
                if hasattr(event, "image_result"):
                    yield event.image_result(image_path)
                else:
                    # 回退到文本结果
                    yield event.plain_result("无法发送图片，请检查框架版本支持")
            else:
                # 文本结果，直接发送
                yield event.plain_result(result)
        except Exception as e:
            logger.error(f"处理K线命令时发生错误: {str(e)}")
            yield event.plain_result(f"处理请求时发生错误: {str(e)}")

    @filter.command("监控")
    async def handle_monitor(self, event: AstrMessageEvent, *args, **kwargs):
        """价格监控命令，使用方法：
/监控 设置 <交易对> <资产类型> <目标价格> <方向> - 设置价格监控
/监控 取消 <监控ID> - 取消指定的价格监控
/监控 列表 - 查看您的所有价格监控
资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)
方向：up(上涨到), down(下跌到)
示例：/监控 设置 BTCUSDT futures 50000 up"""
        logger.info(f"开始处理监控命令: {event.message_str}")
        try:
            # 导入监控命令处理函数
            from .commands.monitor import cmd_monitor
            # 处理监控命令，使用已经配置好的服务实例
            async for result in cmd_monitor(event, self.context.get_config(), self.binance_core.price_service, self.binance_core.monitor_service):
                logger.info(f"监控命令处理结果: {result}")
                yield result
        except Exception as e:
            logger.error(f"处理监控命令时发生异常: {str(e)}")
            yield event.plain_result(f"处理请求时发生错误: {str(e)}")

    async def terminate(self, *args, **kwargs):
        """插件被卸载/停用时调用"""
        # 关闭核心模块的资源
        if hasattr(self, 'binance_core'):
            await self.binance_core.close()
        logger.info("币安插件已停止")
