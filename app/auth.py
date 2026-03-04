from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
import os

# =========================
# CONFIGURACIÓN
# =========================

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY no está definida")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =========================
# HASHING
# =========================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    print("PASSWORD RECIBIDO:", plain_password)
    print("LARGO EN BYTES:", len(plain_password.encode("utf-8")))
    return pwd_context.verify(plain_password, hashed_password)


# =========================
# JWT
# =========================

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)