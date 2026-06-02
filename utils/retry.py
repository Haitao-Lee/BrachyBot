"""
Retry Logic with Exponential Backoff
=====================================
Inspired by OpenCode's retry.ts implementation.

Provides robust retry mechanism for API calls and other operations
that may fail transiently.
"""

import time
import logging
from typing import Callable, TypeVar, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        retryable_exceptions: tuple = (Exception,),
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.retryable_exceptions = retryable_exceptions


# Default configurations for different scenarios
LLM_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    initial_delay=2.0,
    max_delay=30.0,
    backoff_factor=2.0,
    retryable_exceptions=(TimeoutError, ConnectionError, Exception),
)

API_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    initial_delay=1.0,
    max_delay=10.0,
    backoff_factor=2.0,
    retryable_exceptions=(TimeoutError, ConnectionError),
)

SEARCH_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    initial_delay=0.5,
    max_delay=5.0,
    backoff_factor=2.0,
    retryable_exceptions=(TimeoutError, ConnectionError),
)


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay with exponential backoff."""
    delay = config.initial_delay * (config.backoff_factor ** attempt)
    return min(delay, config.max_delay)


def retry_with_backoff(
    func: Callable[..., T],
    config: RetryConfig = None,
    on_retry: Optional[Callable] = None,
) -> T:
    """
    Execute function with retry and exponential backoff.

    Args:
        func: Function to execute
        config: Retry configuration
        on_retry: Callback on each retry (attempt, delay, error)

    Returns:
        Result of function execution

    Raises:
        Last exception if all retries fail
    """
    if config is None:
        config = API_RETRY_CONFIG

    last_error = None

    for attempt in range(config.max_retries + 1):
        try:
            return func()
        except config.retryable_exceptions as e:
            last_error = e

            if attempt == config.max_retries:
                logger.error(f"All {config.max_retries} retries failed: {e}")
                raise

            delay = calculate_delay(attempt, config)
            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")

            if on_retry:
                on_retry(attempt, delay, e)

            time.sleep(delay)

    raise last_error


def retry_decorator(config: RetryConfig = None):
    """
    Decorator for retry with exponential backoff.

    Usage:
        @retry_decorator(LLM_RETRY_CONFIG)
        def call_llm():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return retry_with_backoff(
                lambda: func(*args, **kwargs),
                config=config,
            )
        return wrapper
    return decorator


class RetryableOperation:
    """
    Context manager for retryable operations.

    Usage:
        with RetryableOperation("LLM call", max_retries=3) as op:
            result = call_llm()
    """

    def __init__(self, name: str, config: RetryConfig = None):
        self.name = name
        self.config = config or API_RETRY_CONFIG
        self.attempt = 0
        self.last_error = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            return False

        self.last_error = exc_val
        self.attempt += 1

        if self.attempt > self.config.max_retries:
            logger.error(f"{self.name}: All {self.config.max_retries} retries failed")
            return False

        if not isinstance(exc_val, self.config.retryable_exceptions):
            logger.error(f"{self.name}: Non-retryable error: {exc_val}")
            return False

        delay = calculate_delay(self.attempt - 1, self.config)
        logger.warning(f"{self.name}: Attempt {self.attempt} failed: {exc_val}. Retrying in {delay:.1f}s...")
        time.sleep(delay)

        return True  # Suppress exception and retry

    def execute(self, func: Callable[..., T]) -> T:
        """Execute function with retry."""
        return retry_with_backoff(func, config=self.config)
