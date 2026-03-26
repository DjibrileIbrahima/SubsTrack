import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

_key = os.getenv("ENCRYPTION_KEY")
if not _key:
    raise RuntimeError("ENCRYPTION_KEY is not set in your .env file. "
                       "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")

fernet = Fernet(_key.encode())


def encrypt(value: str) -> str:
    """Encrypt a plaintext string. Returns a string safe to store in the DB."""
    return fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a stored encrypted string back to plaintext."""
    return fernet.decrypt(value.encode()).decode()
