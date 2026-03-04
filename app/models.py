from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# =========================
# FAMILIES
# =========================
class Family(Base):
    __tablename__ = "families"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="family", cascade="all, delete")
    messages = relationship("Message", back_populates="family", cascade="all, delete")


# =========================
# USERS
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    family_id = Column(Integer, ForeignKey("families.id"), nullable=False)

    username = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    family = relationship("Family", back_populates="users")
    messages = relationship("Message", back_populates="user", cascade="all, delete")
    devices = relationship("Device", back_populates="user", cascade="all, delete")


# =========================
# MESSAGES
# =========================
class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    family_id = Column(Integer, ForeignKey("families.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    content = Column(Text, nullable=True)       # Texto del mensaje
    audio_url = Column(Text, nullable=True)     # Ruta del audio en servidor

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    family = relationship("Family", back_populates="messages")
    user = relationship("User", back_populates="messages")


# =========================
# DEVICES (Push Notifications)
# =========================
class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    fcm_token = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="devices")