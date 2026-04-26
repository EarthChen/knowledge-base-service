"""Fernet-based encryption for sensitive settings."""

import os
from pathlib import Path

from cryptography.fernet import Fernet

_KEY_FILE = "data/.settings_key"


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("SETTINGS_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()
    key_path = Path(_KEY_FILE)
    if key_path.exists():
        return key_path.read_bytes().strip()
    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    return key


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def mask_value(value: str, visible_chars: int = 4) -> str:
    if len(value) <= visible_chars * 2:
        return "***"
    return f"{value[:visible_chars]}***{value[-visible_chars:]}"
