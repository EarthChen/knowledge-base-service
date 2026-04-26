"""Tests for settings encryption helpers."""

from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def crypto_mod(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)
    import services.settings_crypto as mod

    importlib.reload(mod)
    yield mod


def test_encrypt_decrypt_roundtrip(crypto_mod):
    plain = "secret-value-123"
    enc = crypto_mod.encrypt_value(plain)
    assert enc != plain
    assert crypto_mod.decrypt_value(enc) == plain


def test_mask_value_short(crypto_mod):
    assert crypto_mod.mask_value("tiny") == "***"


def test_mask_value_long(crypto_mod):
    s = "abcdefghijklmnop"
    assert crypto_mod.mask_value(s) == "abcd***mnop"


def test_mask_value_medium(crypto_mod):
    s = "123456789"
    assert crypto_mod.mask_value(s) == "1234***6789"


def test_invalid_env_key_raises(monkeypatch):
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "not-a-fernet-key")
    import services.settings_crypto as mod

    importlib.reload(mod)
    with pytest.raises(ValueError, match="not a valid Fernet key"):
        mod.encrypt_value("x")
