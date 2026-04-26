"""Fernet-based encryption for sensitive settings."""

import os
from pathlib import Path

from cryptography.fernet import Fernet

_KEY_FILE = "data/.settings_key"

_FERNET_KEY_HELP = (
    "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
)


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("SETTINGS_ENCRYPTION_KEY")
    if env_key:
        key = env_key.encode()
        try:
            Fernet(key)
        except Exception as exc:
            raise ValueError(
                "SETTINGS_ENCRYPTION_KEY is not a valid Fernet key. " + _FERNET_KEY_HELP,
            ) from exc
        return key
    key_path = Path(_KEY_FILE)
    if key_path.exists():
        key = key_path.read_bytes().strip()
        try:
            Fernet(key)
        except Exception as exc:
            raise ValueError(
                f"Key file {key_path} does not contain a valid Fernet key. " + _FERNET_KEY_HELP,
            ) from exc
        return key
    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = _load_or_create_key()
        try:
            _fernet = Fernet(key)
        except Exception as exc:
            raise ValueError(
                "Could not initialize Fernet for settings encryption. " + _FERNET_KEY_HELP,
            ) from exc
    return _fernet


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def mask_value(value: str, visible_chars: int = 4) -> str:
    if len(value) <= visible_chars * 2:
        return "***"
    return f"{value[:visible_chars]}***{value[-visible_chars:]}"
