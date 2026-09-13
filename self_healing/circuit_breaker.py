import time
from typing import Dict, Any, Callable
from .enums import Subsystem
from .logger import get_logger

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures: Dict[Subsystem, int] = {}
        self.last_failure_time: Dict[Subsystem, float] = {}
        self.logger = get_logger("CircuitBreaker")

    def record_failure(self, subsystem: Subsystem) -> None:
        """Record a failure for a subsystem."""
        self.failures[subsystem] = self.failures.get(subsystem, 0) + 1
        self.last_failure_time[subsystem] = time.time()

        if self.failures[subsystem] >= self.failure_threshold:
            self.logger.warning(
                f"Circuit breaker triggered for {subsystem.name}. Entering cooldown.",
                extra={"subsystem": subsystem.name, "problem": "Circuit breaker OPEN"}
            )

    def record_success(self, subsystem: Subsystem) -> None:
        """Reset failures on success."""
        if self.failures.get(subsystem, 0) > 0:
            self.logger.info(
                f"Circuit breaker reset for {subsystem.name}.",
                extra={"subsystem": subsystem.name, "action": "Circuit breaker CLOSED", "result": "SUCCESS"}
            )
        self.failures[subsystem] = 0

    def is_allowed(self, subsystem: Subsystem) -> bool:
        """Check if an operation is allowed to proceed."""
        current_failures = self.failures.get(subsystem, 0)

        if current_failures < self.failure_threshold:
            return True

        time_since_last_failure = time.time() - self.last_failure_time.get(subsystem, 0)
        if time_since_last_failure > self.recovery_timeout:
            # Half-open state: allow one attempt, but don't reset count until success
            self.logger.info(f"Circuit breaker HALF-OPEN for {subsystem.name}. Allowing retry.")
            return True

        return False

    def execute(self, subsystem: Subsystem, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a function protected by the circuit breaker."""
        if not self.is_allowed(subsystem):
            raise Exception(f"Circuit breaker is OPEN for {subsystem.name}. Operation denied to prevent rate limit amplification.")

        try:
            result = func(*args, **kwargs)
            self.record_success(subsystem)
            return result
        except Exception as e:
            self.record_failure(subsystem)
            raise e
