import pyotp

from services.encryption import decrypt, encrypt


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="SubsTrack")


def verify_totp(encrypted_secret: str, code: str) -> bool:
    secret = decrypt(encrypted_secret)
    # valid_window=1 allows one 30-second step of clock drift
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def encrypt_secret(raw_secret: str) -> str:
    return encrypt(raw_secret)
