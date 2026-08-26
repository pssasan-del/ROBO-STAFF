class StrategyParseError(ValueError):
    """Raised when a user strategy cannot be safely converted into supported rules."""


class MarketDataUnavailable(RuntimeError):
    """Raised when live FYERS market data is required but unavailable."""


class UnsupportedUniverseError(ValueError):
    """Raised when a requested scanning universe is not safely available."""
