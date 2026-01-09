"""
/绑定命令处理（符合AstrBot消息事件规范）
"""
from astrbot.api.message import MessageEvent
from typing import AsyncGenerator
from ..storage.user import save_user_api
from ..utils.logger import plugin_logger

async def cmd_bind(
    event: MessageEvent,
    valid_config
) -> AsyncGenerator[str, None]:
    """
    处理/绑定 币安API密钥命令
    用法：/绑定 <API_KEY> <SECRET_KEY>
    """
    try:
        # 解析消息内容
        message_content = event.message_str.strip()
        cmd_parts = message_content.split()
        # 校验参数数量
        if len(cmd_parts) != 3:
            yield event.plain_result("📌 正确用法：/绑定 <币安API_KEY> <币安SECRET_KEY>")
            return

        # 提取参数
        qq_user_id = str(event.user_id)
        api_key = cmd_parts[1].strip()
        secret_key = cmd_parts[2].strip()

        # 校验API密钥非空
        if not api_key or not secret_key:
            yield event.plain_result("❌ API Key和Secret Key不能为空！")
            return

        # 加密保存
        save_user_api(
            qq_user_id=qq_user_id,
            api_key=api_key,
            secret_key=secret_key,
            encrypt_secret=valid_config.encrypt_secret,
            user_data_file=valid_config.user_data_file
        )

        plugin_logger.info(f"用户 {qq_user_id} 币安API绑定成功")
        yield event.plain_result("✅ 币安API密钥已成功绑定（加密存储，安全可靠）")
    except RuntimeError as e:
        yield event.plain_result(f"❌ 绑定失败：{str(e)}")
    except Exception as e:
        plugin_logger.error(f"用户 {str(event.user_id)} 绑定API异常：{str(e)}")
        yield event.plain_result("❌ 绑定异常，请联系管理员查看日志")
