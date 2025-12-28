"""
币安API密钥管理服务模块
"""
import os
import json
import secrets
from typing import Dict, Optional, Tuple
from astrbot.api import logger
from ..utils.crypto import encrypt_data, decrypt_data


class ApiKeyService:
    """
    API密钥管理服务类，处理API密钥的加密存储、获取和删除
    """
    def __init__(self, plugin_dir: str):
        self.plugin_dir = plugin_dir
        self.data_dir = os.path.join(self.plugin_dir, "data")
        self.encryption_key_file = os.path.join(self.data_dir, "encryption_key.json")
        self.user_api_file = os.path.join(self.data_dir, "user_api_keys.json")
        
        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 加密密钥
        self.encryption_key = None
        self.encryption_key_initialized = False
    
    async def _init_encryption_key(self):
        """
        初始化加密密钥：
        1. 优先从文件系统中获取
        2. 如果没有，生成一个新的随机密钥并存储到文件
        """
        if self.encryption_key_initialized:
            return
        
        # 从文件系统中获取加密密钥
        try:
            if os.path.exists(self.encryption_key_file):
                with open(self.encryption_key_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.encryption_key = data.get("encryption_key")
        except Exception as e:
            logger.error(f"从文件系统获取加密密钥失败: {str(e)}")
        
        # 如果没有获取到密钥，生成一个新的随机密钥
        if not self.encryption_key or len(self.encryption_key) < 16:
            try:
                # 生成32位的随机字符串作为加密密钥
                self.encryption_key = secrets.token_hex(16)  # 32个字符的十六进制字符串
                # 存储加密密钥到文件
                with open(self.encryption_key_file, "w", encoding="utf-8") as f:
                    json.dump({"encryption_key": self.encryption_key}, f, ensure_ascii=False, indent=2)
                logger.info("已生成并存储新的加密密钥")
            except Exception as e:
                logger.error(f"生成或存储加密密钥失败: {str(e)}")
                # 如果生成密钥失败，使用一个默认的不安全密钥（仅作为最后的 fallback）
                self.encryption_key = "default_fallback_key_12345678"
        
        self.encryption_key_initialized = True
    
    async def bind_api_key(self, user_id: str, api_key: str, secret_key: str) -> bool:
        """
        绑定用户的币安API密钥（加密存储）
        :param user_id: 用户ID
        :param api_key: 币安API密钥
        :param secret_key: 币安Secret密钥
        :return: 是否绑定成功
        """
        try:
            # 确保加密密钥已初始化
            await self._init_encryption_key()
            
            # 加密API密钥
            encrypted_api_key = encrypt_data(api_key, self.encryption_key)
            encrypted_secret_key = encrypt_data(secret_key, self.encryption_key)
            
            # 存储加密后的API密钥到文件
            user_api_data = {}
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
            
            user_api_data[user_id] = {
                "api_key": encrypted_api_key,
                "secret_key": encrypted_secret_key
            }
            
            with open(self.user_api_file, "w", encoding="utf-8") as f:
                json.dump(user_api_data, f, ensure_ascii=False, indent=2)
                
            return True
        except Exception as e:
            logger.error(f"绑定API密钥失败: {str(e)}")
            return False
    
    async def unbind_api_key(self, user_id: str) -> bool:
        """
        解除绑定用户的币安API密钥
        :param user_id: 用户ID
        :return: 是否解除绑定成功
        """
        try:
            # 从文件中删除用户的API密钥
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
                
                if user_id in user_api_data:
                    del user_api_data[user_id]
                    
                    # 保存更新后的数据
                    with open(self.user_api_file, "w", encoding="utf-8") as f:
                        json.dump(user_api_data, f, ensure_ascii=False, indent=2)
                    
                    return True
            return False
        except Exception as e:
            logger.error(f"解除绑定API密钥失败: {str(e)}")
            return False
    
    async def get_api_key(self, user_id: str) -> Optional[Tuple[str, str]]:
        """
        获取用户绑定的币安API密钥（解密）
        :param user_id: 用户ID
        :return: (api_key, secret_key)元组，或None表示未绑定
        """
        try:
            # 确保加密密钥已初始化
            await self._init_encryption_key()
            
            # 从文件中获取加密的API密钥
            user_api_data = {}
            if os.path.exists(self.user_api_file):
                with open(self.user_api_file, "r", encoding="utf-8") as f:
                    user_api_data = json.load(f)
            
            # 检查用户是否存在API密钥
            if user_id not in user_api_data:
                return None
            
            encrypted_api_key = user_api_data[user_id].get("api_key")
            encrypted_secret_key = user_api_data[user_id].get("secret_key")
            
            if not encrypted_api_key or not encrypted_secret_key:
                return None
            
            # 解密API密钥
            api_key = decrypt_data(encrypted_api_key, self.encryption_key)
            secret_key = decrypt_data(encrypted_secret_key, self.encryption_key)
            
            return (api_key, secret_key)
        except Exception as e:
            logger.error(f"获取用户API密钥失败: {str(e)}")
            return None
