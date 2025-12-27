import base64


def encrypt(text, key):
    raw = f"{key}:{text}".encode()
    return base64.b64encode(raw).decode()


def decrypt(text, key):
    raw = base64.b64decode(text).decode()
    return raw.split(":", 1)[1]
