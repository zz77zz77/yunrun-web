import base64
import json
import time
import secrets
import string
from typing import Dict, Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

PSK = bytes([121, 121, 0, 19, 5, 49, 2, 43, 13, 17, 11, 9, 4, 29, 60, 11])


def generate_random_echo(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def current_timestamp_str() -> str:
    return str(int(time.time()))


def _aes_cbc_encrypt_pkcs7(plaintext_bytes: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    return cipher.encrypt(pad(plaintext_bytes, AES.block_size))


def _aes_cbc_decrypt_pkcs7(ciphertext_bytes: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    return unpad(cipher.decrypt(ciphertext_bytes), AES.block_size)


def encrypt_payload_to_n(payload: Dict[str, Any], iv: bytes | None = None) -> str:
    if iv is None:
        iv = get_random_bytes(16)
    if len(iv) != 16:
        raise ValueError("IV 必须是 16 字节")

    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = _aes_cbc_encrypt_pkcs7(plaintext, PSK, iv)
    return base64.b64encode(iv + ciphertext).decode("ascii")


def generate_x_sign(
    echo: str | None = None,
    timestamp: str | None = None,
    client: str = "web",
    iv: bytes | None = None
) -> str:
    if echo is None:
        echo = generate_random_echo()
    if timestamp is None:
        timestamp = current_timestamp_str()
    payload = {"echo": echo, "timestamp": timestamp, "client": client}
    return encrypt_payload_to_n(payload, iv=iv)
