"""
用户数据管理（AstrBot插件友好，JSON文件持久化，无额外依赖）
自动创建存储文件，支持多用户API密钥加密存储/查询/删除
"""
import json
import os
from typing import Optional, Tuple
from .crypto import encrypt_data, decrypt_data
from ..utils.logger import plugin_logger

def _init_user_data_file(file_path: str) -> None:
    """初始化用户数据JSON文件（不存在则自动创建）"""
    try:
        # 自动创建上级目录
        dir_path = os.path.dirname(file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        # 写入空用户数据结构
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            plugin_logger.debug(f"用户数据文件已创建：{file_path}")
    except Exception as e:
        plugin_logger.error(f"用户数据文件初始化失败：{str(e)}")
        raise RuntimeError(f"无法创建用户数据文件：{file_path}")

def _load_user_data(file_path: str) -> dict:
    """加载用户数据JSON文件"""
    _init_user_data_file(file_path)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        plugin_logger.error("用户数据文件格式损坏，已重置为空结构")
        # 格式损坏时重置文件
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        return {}
    except Exception as e:
        plugin_logger.error(f"加载用户数据失败：{str(e)}")
        raise RuntimeError("无法读取用户数据文件")

def _save_user_data(file_path: str, user_data: dict) -> None:
    """保存用户数据到JSON文件"""
    _init_user_data_file(file_path)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
        plugin_logger.debug("用户数据已保存")
    except Exception as e:
        plugin_logger.error(f"保存用户数据失败：{str(e)}")
        raise RuntimeError("无法写入用户数据文件")

def save_user_api(
    qq_user_id: str,
    api_key: str,
    secret_key: str,
    encrypt_secret: str,
    user_data_file: str
) -> None:
    """
    加密保存用户币安API密钥
    :param qq_user_id: QQ用户ID（字符串格式，避免类型问题）
    :param api_key: 币安API Key（明文）
    :param secret_key: 币安Secret Key（明文）
    :param encrypt_secret: 配置中的加密密钥
    :param user_data_file: 用户数据文件路径
    """
    # 加密API密钥
    encrypted_api_key = encrypt_data(api_key, encrypt_secret)
    encrypted_secret_key = encrypt_data(secret_key, encrypt_secret)
    # 加载现有数据
    user_data = _load_user_data(user_data_file)
    # 更新用户数据
    user_data[qq_user_id] = {
        "api_key": encrypted_api_key,
        "secret_key": encrypted_secret_key
    }
    # 保存数据
    _save_user_data(user_data_file, user_data)

def get_user_api(
    qq_user_id: str,
    encrypt_secret: str,
    user_data_file: str
) -> Optional[Tuple[str, str]]:
    """
    解密获取用户币安API密钥
    :return: (api_key明文, secret_key明文) 或 None（用户未绑定）
    """
    user_data = _load_user_data(user_data_file)
    # 检查用户是否绑定
    if qq_user_id not in user_data:
        return None
    # 获取加密后的密钥
    encrypted_data = user_data[qq_user_id]
    try:
        # 解密
        api_key = decrypt_data(encrypted_data["api_key"], encrypt_secret)
        secret_key = decrypt_data(encrypted_data["secret_key"], encrypt_secret)
        return (api_key, secret_key)
    except Exception as e:
        plugin_logger.error(f"解密用户API密钥失败：{str(e)}")
        raise RuntimeError("获取用户API密钥异常")
