"""
加密工具模块
使用AES算法加密和解密用户API密钥
"""
import base64
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding


def encrypt_data(data: str, key: str) -> str:
    """
    使用AES加密数据
    :param data: 要加密的数据
    :param key: 加密密钥（至少16位）
    :return: 加密后的Base64编码字符串（包含IV和密文）
    """
    try:
        # 确保密钥长度为16、24或32位
        key = key.ljust(32, '0')[:32].encode()
        
        # 使用PKCS7填充
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data.encode()) + padder.finalize()
        
        # 生成随机IV
        iv = os.urandom(16)  # 使用随机IV提高安全性
        
        # 创建AES-CBC加密器
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        # 加密数据
        encrypted = encryptor.update(padded_data) + encryptor.finalize()
        
        # 将IV和密文组合后返回Base64编码
        return base64.b64encode(iv + encrypted).decode()
    except Exception as e:
        raise ValueError(f"加密失败: {str(e)}")


def decrypt_data(encrypted_data: str, key: str) -> str:
    """
    使用AES解密数据
    :param encrypted_data: Base64编码的加密数据（包含IV和密文）
    :param key: 解密密钥（与加密密钥相同）
    :return: 解密后的数据
    """
    try:
        # 确保密钥长度为16、24或32位
        key = key.ljust(32, '0')[:32].encode()
        
        # 解码Base64数据
        encrypted = base64.b64decode(encrypted_data)
        
        # 分离IV和密文
        iv = encrypted[:16]  # 前16字节是IV
        ciphertext = encrypted[16:]  # 剩余部分是密文
        
        # 创建AES-CBC解密器
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        
        # 解密数据
        decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
        
        # 移除填充
        unpadder = padding.PKCS7(128).unpadder()
        decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
        
        return decrypted.decode()
    except Exception as e:
        raise ValueError(f"解密失败: {str(e)}")
