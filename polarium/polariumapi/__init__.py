"""Cliente Python isolado para a API da Polarium Broker."""

from .client import PolariumClient
from .exceptions import AuthenticationError, PolariumAPIError, RequestError
from .google_auth import GoogleAuthenticator, GoogleSession
from .models import Account, AccountMode, Candle, CandleColor, Direction, OperationResult, PatternStats, Signal

__all__ = [
    "Account",
    "AccountMode",
    "AuthenticationError",
    "Candle",
    "CandleColor",
    "Direction",
    "GoogleAuthenticator",
    "GoogleSession",
    "OperationResult",
    "PatternStats",
    "PolariumAPIError",
    "PolariumClient",
    "RequestError",
    "Signal",
]
