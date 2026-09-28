"""Persistence-only repository boundaries."""

from backend.app.repositories.identity_repository import IdentityRepository
from backend.app.repositories.stock_repository import StockUploadRepository

__all__ = ["IdentityRepository", "StockUploadRepository"]
