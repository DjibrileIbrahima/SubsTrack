"""Unit tests for services/encryption.py"""

import pytest
from cryptography.fernet import InvalidToken

import services.encryption as enc
from services.encryption import decrypt, encrypt

_FAKE_KMS_ARN = "arn:aws:kms:us-east-1:123456789012:key/fake"


class _FakeKMS:
    """Stand-in for boto3's KMS client — no network, deterministic blobs."""
    _MARKER = b"FAKEKMS::"

    def encrypt(self, KeyId, Plaintext):
        return {"CiphertextBlob": self._MARKER + Plaintext}

    def decrypt(self, CiphertextBlob, KeyId=None):
        assert CiphertextBlob.startswith(self._MARKER)
        return {"Plaintext": CiphertextBlob[len(self._MARKER):]}


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


class TestKmsScheme:
    def _enable_kms(self, monkeypatch):
        monkeypatch.setattr(enc, "_KMS_KEY_ID", _FAKE_KMS_ARN)
        monkeypatch.setattr(enc, "_kms_client", lambda: _FakeKMS())

    def test_kms_encrypt_is_tagged_and_roundtrips(self, monkeypatch):
        self._enable_kms(monkeypatch)
        ciphertext = enc.encrypt("access-sandbox-xyz")
        assert ciphertext.startswith("kms:v1:")
        assert "access-sandbox-xyz" not in ciphertext
        assert enc.decrypt(ciphertext) == "access-sandbox-xyz"

    def test_legacy_fernet_still_decrypts_after_kms_enabled(self, monkeypatch):
        # A row written under the old Fernet scheme (KMS off)...
        legacy = enc.encrypt("old-token")
        assert not legacy.startswith("kms:v1:")
        # ...must still decrypt once KMS becomes the active scheme.
        self._enable_kms(monkeypatch)
        assert enc.decrypt(legacy) == "old-token"

    def test_reencrypt_migrates_legacy_row_to_kms(self, monkeypatch):
        legacy = enc.encrypt("migrate-me")
        self._enable_kms(monkeypatch)
        migrated = enc.reencrypt(legacy)
        assert migrated.startswith("kms:v1:")
        assert enc.decrypt(migrated) == "migrate-me"


class TestFernetRotation:
    def test_value_from_old_key_decrypts_after_new_key_prepended(self, monkeypatch):
        from cryptography.fernet import Fernet, MultiFernet

        old = Fernet(Fernet.generate_key())
        new = Fernet(Fernet.generate_key())
        token = old.encrypt(b"rotate-me").decode()

        # Active MultiFernet: new key first (used for new writes), old key still
        # available for reads.
        monkeypatch.setattr(enc, "_fernet", MultiFernet([new, old]))
        assert enc.decrypt(token) == "rotate-me"

        # New writes use the new key — the old key alone can't read them.
        fresh = enc.encrypt("fresh")
        with pytest.raises(InvalidToken):
            old.decrypt(fresh.encode())
