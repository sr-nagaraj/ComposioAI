"""Retry policy primitives."""

from tenacity import retry, stop_after_attempt, wait_exponential_jitter


class TransientAgentError(Exception):
    """Error type for failures that can succeed on retry."""


class PermanentAgentError(Exception):
    """Error type for failures that should not be retried."""


def retry_transient_errors(max_attempts: int):
    """Return a tenacity retry decorator for transient agent failures."""

    return retry(
        retry=lambda retry_state: isinstance(retry_state.outcome.exception(), TransientAgentError)
        if retry_state.outcome
        else False,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(),
        reraise=True,
    )
