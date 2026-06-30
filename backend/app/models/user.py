"""
User model for authentication and role-based access control.

Roles (in order of privilege):
  OWNER       – full access, including user management
  MANAGER     – full operational access (alerts, reports, cameras)
  SECURITY    – real-time view, acknowledge alerts, view persons
  INVESTIGATOR – read-only access to history and analytics
"""
import uuid
from sqlalchemy import Column, String, Boolean, DateTime, func
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username    = Column(String(64), unique=True, nullable=False, index=True)
    email       = Column(String(255), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=False)

    # Role: OWNER | MANAGER | SECURITY | INVESTIGATOR
    role        = Column(String(32), nullable=False, default="SECURITY")

    is_active   = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)

    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=True)
    last_login  = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "id":         self.id,
            "username":   self.username,
            "email":      self.email,
            "role":       self.role,
            "is_active":  self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }
