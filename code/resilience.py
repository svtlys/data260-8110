import logging
import random
import time
from dataclasses import dataclass

from sqlalchemy.exc import OperationalError

logger = logging.getLogger("resilience")

TRANSIENT_MYSQL_CODES = {1205, 1213, 2003, 2006, 2013}


class TransientError(Exception):
    """A failure that is worth retrying (real or injected)."""


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3      
    base_delay: float = 0.2   
    max_delay: float = 2.0   
    deadline: float = 5.0     

    def delay_for(self, retry_number: int) -> float:
        """Wait before retry number `retry_number` (1 = first retry)."""
        return min(self.base_delay * (2 ** (retry_number - 1)), self.max_delay)


INTERACTIVE_POLICY = RetryPolicy(max_retries=3, base_delay=0.2, max_delay=2.0, deadline=5.0)
BATCH_POLICY = RetryPolicy(max_retries=6, base_delay=1.0, max_delay=30.0, deadline=300.0)


def is_transient(exc: Exception) -> bool:
    if isinstance(exc, (TransientError, TimeoutError)):
        return True
    if isinstance(exc, OperationalError):
        code = getattr(getattr(exc, "orig", None), "args", (None,))[0]
        return code in TRANSIENT_MYSQL_CODES
    return False


@dataclass
class RetryOutcome:
    ok: bool
    value: object = None
    error: str | None = None
    attempts: int = 0
    elapsed_ms: float = 0.0


def call_with_retry(operation, policy: RetryPolicy = INTERACTIVE_POLICY,
                    sleep=time.sleep, clock=time.monotonic) -> RetryOutcome:
    """Run operation(); retry transient failures per `policy`.

    Returns a RetryOutcome. Transient failures never raise out of here; a
    non-transient exception is re-raised so the caller can turn it into a
    clean error of its own. `sleep` and `clock` can be replaced in tests.
    """
    start = clock()
    attempts = 0
    while True:
        attempts += 1
        try:
            value = operation()
            return RetryOutcome(True, value=value, attempts=attempts,
                                elapsed_ms=(clock() - start) * 1000)
        except Exception as exc:
            if not is_transient(exc):
                raise
            last_error = f"{type(exc).__name__}: {exc}"
            retries_used = attempts - 1
            if retries_used >= policy.max_retries:
                reason = "retries exhausted"
                break
            delay = policy.delay_for(retries_used + 1)
            if (clock() - start) + delay > policy.deadline:
                reason = "time budget reached"
                break
            logger.info("attempt %d failed (%s); retry %d in %.2fs",
                        attempts, last_error, retries_used + 1, delay)
            sleep(delay)

    logger.warning("giving up: %s after %d attempt(s): %s", reason, attempts, last_error)
    return RetryOutcome(False, error=f"{reason} after {attempts} attempt(s): {last_error}",
                        attempts=attempts, elapsed_ms=(clock() - start) * 1000)



class FaultInjector:

    def __init__(self, rate: float, seed: int):
        self.rate = rate
        self._rng = random.Random(seed)
        self.attempts = 0

    def __call__(self):
        self.attempts += 1
        if self._rng.random() < self.rate:
            raise TransientError(f"injected failure (rate {self.rate:.0%}, attempt #{self.attempts})")


class ScriptedFaults:
    """Deterministic faults for demonstrations: attempt i fails when plan[i] is
    True; attempts beyond the plan succeed."""

    def __init__(self, plan):
        self._plan = list(plan)
        self.attempts = 0

    def __call__(self):
        index = self.attempts
        self.attempts += 1
        if index < len(self._plan) and self._plan[index]:
            raise TransientError(f"scripted failure on attempt {index + 1}")