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
@register("astrbot_plugin_binance", "Binance Plugin Developer", "币安现货价格查询与API绑定插件", "1.0.0", logo="logo.png")
class BinancePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 初始化核心模块
        self.binance_core = BinanceCore(context)
        logger.info("币安插件初始化成功")
        # 启动价格监控任务
        asyncio.create_task(self.binance_core.start_price_monitor())

    @filter.command("price")
    async def handle_price(self, event: AstrMessageEvent):
        """查询币安资产价格，使用方法：/price <交易对> [资产类型]，例如：/price BTCUSDT futures\n资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)"""
        result = await self.binance_core.handle_price_command(event)
        yield event.plain_result(result)

    @filter.command("绑定")
    async def handle_bind(self, event: AstrMessageEvent):
        """绑定币安API密钥，使用方法：/绑定 <API_KEY> <SECRET_KEY>"""
        result = await self.binance_core.handle_bind_command(event)
        yield event.plain_result(result)

    @filter.command("资产")
    async def handle_asset(self, event: AstrMessageEvent):
        """查询币安账户资产，使用方法：/资产 [查询类型]
查询类型：alpha/资金/现货/合约，不输入则查询总览"""
        result = await self.binance_core.handle_asset_command(event)
        yield event.plain_result(result)

    @filter.command("解除绑定")
    async def handle_unbind(self, event: AstrMessageEvent):
        """解除绑定币安API密钥，使用方法：/解除绑定"""
        result = await self.binance_core.handle_unbind_command(event)
        yield event.plain_result(result)

    @filter.command("bahelp")
    async def handle_help(self, event: AstrMessageEvent):
        """显示币安插件的帮助信息，使用方法：/bahelp"""
        result = await self.binance_core.handle_help_command(event)
        yield event.plain_result(result)

    @filter.command("监控")
    async def handle_monitor(self, event: AstrMessageEvent):
        """价格监控命令，使用方法：
/监控 设置 <交易对> <资产类型> <目标价格> <方向> - 设置价格监控
/监控 取消 <监控ID> - 取消指定的价格监控
/监控 列表 - 查看您的所有价格监控
资产类型：spot(现货), futures(合约), margin(杠杆), alpha(Alpha货币)
方向：up(上涨到), down(下跌到)
示例：/监控 设置 BTCUSDT futures 50000 up"""
        # 导入监控命令处理函数
        from .commands.monitor import cmd_monitor
        # 传递必要的属性
        event.plugin_dir = self.context.plugin_dir
        # 处理监控命令
        async for result in cmd_monitor(event, self.context.get_config()):
            yield result

    async def terminate(self):
        """插件被卸载/停用时调用"""
        # 关闭核心模块的资源
        if hasattr(self, 'binance_core'):
            await self.binance_core.close()
        logger.info("币安插件已停止")
