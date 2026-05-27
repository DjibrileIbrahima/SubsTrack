"""Unit tests for services/encryption.py"""

import pytest
from cryptography.fernet import InvalidToken

from services.encryption import decrypt, encrypt


class TestEncryption:
    def test_roundtrip_short_string(self):
        plaintext = "access-sandbox-abc123"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_roundtrip_long_string(self):
        plaintext = "a" * 500
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_roundtrip_special_characters(self):
        plaintext = "access-token/with+special=chars&more"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_encrypt_produces_different_output_each_time(self):
        plaintext = "same-input"
        e1 = encrypt(plaintext)
        e2 = encrypt(plaintext)
        # Fernet uses a random IV, so two encryptions of the same value differ
        assert e1 != e2
        # But both decrypt to the same value
        assert decrypt(e1) == decrypt(e2) == plaintext

    def test_encrypted_value_is_not_plaintext(self):
        plaintext = "super-secret-token"
        assert plaintext not in encrypt(plaintext)

    def test_decrypt_invalid_data_raises(self):
        with pytest.raises((InvalidToken, Exception)):
            decrypt("this-is-not-encrypted-data")

    def test_decrypt_garbled_ciphertext_raises(self):
        valid = encrypt("some-token")
        garbled = valid[:-10] + "XXXXXXXXXX"
        with pytest.raises((InvalidToken, Exception)):
            decrypt(garbled)
