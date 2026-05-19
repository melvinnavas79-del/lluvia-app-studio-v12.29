"""
crypto_utils.py - Cifrado AES-GCM para credenciales sensibles (SSH keys, tokens).

Uso:
  from crypto_utils import encrypt_str, decrypt_str
  enc = encrypt_str("mi ssh key privada")
  dec = decrypt_str(enc)

Master key vive en VPS_ENCRYPTION_KEY del .env. Si no existe, se genera y se
escribe en .env automaticamente al primer uso (idempotente).
"""

import os
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_master_key() -> bytes:
    """Devuelve la master key, generandola la primera vez si no existe."""
    key_hex = os.environ.get("VPS_ENCRYPTION_KEY", "").strip()
    if not key_hex or len(key_hex) < 32:
        # Generar nueva clave y persistirla en .env (write-once)
        key = secrets.token_bytes(32)
        key_hex = key.hex()
        os.environ["VPS_ENCRYPTION_KEY"] = key_hex
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        try:
            with open(env_path, "a") as f:
                f.write(f"\nVPS_ENCRYPTION_KEY={key_hex}\n")
        except Exception:
            pass  # Si .env es read-only, igual lo guardamos en memoria
        return key
    try:
        return bytes.fromhex(key_hex)
    except ValueError:
        # Si el valor del env no es hex valido, lo regeneramos
        return secrets.token_bytes(32)


def encrypt_str(plaintext: str) -> str:
    """Cifra un string con AES-GCM. Devuelve base64(nonce + ciphertext)."""
    if not plaintext:
        return ""
    key = _get_master_key()
    aes = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_str(ciphertext_b64: str) -> str:
    """Descifra. Devuelve el plaintext original."""
    if not ciphertext_b64:
        return ""
    key = _get_master_key()
    aes = AESGCM(key)
    raw = base64.b64decode(ciphertext_b64.encode("ascii"))
    nonce, ct = raw[:12], raw[12:]
    pt = aes.decrypt(nonce, ct, None)
    return pt.decode("utf-8")
