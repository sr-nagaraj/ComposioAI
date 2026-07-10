"""Rate limiting helpers."""

from aiolimiter import AsyncLimiter


def build_rate_limiter(requests_per_second: int) -> AsyncLimiter:
    """Build a one-second window async limiter."""

    return AsyncLimiter(requests_per_second, time_period=1)
