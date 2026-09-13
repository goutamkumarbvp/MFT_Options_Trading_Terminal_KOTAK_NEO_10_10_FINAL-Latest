from datetime import datetime
import traceback
from typing import Optional, Any
from .enums import FailureCategory, Subsystem, HealthState
from .models import DiagnosticLog
from .health_monitor import HealthMonitor
from .logger import get_logger

class DiagnosisEngine:
    def __init__(self, health_monitor: HealthMonitor):
        self.health_monitor = health_monitor
        self.logger = get_logger("DiagnosisEngine")

    def diagnose(
        self,
        subsystem: Subsystem,
        exception: Optional[Exception],
        error_message: str,
        relevant_instrument: Optional[str] = None
    ) -> DiagnosticLog:
        """Classify a failure and create a diagnostic log."""

        health = self.health_monitor.get_health(subsystem)
        category = self._classify_failure(subsystem, exception, error_message)

        exception_type = type(exception).__name__ if exception else None

        log = DiagnosticLog(
            timestamp=datetime.now(),
            subsystem=subsystem,
            exception_type=exception_type,
            error_message=error_message,
            recent_health_state=health.state,
            last_successful_heartbeat=health.last_heartbeat,
            connection_state=None, # To be populated by specific subsystem integrations
            api_response_state=None,
            relevant_instrument=relevant_instrument,
            retry_count=health.retry_count,
            recovery_action_attempted=None,
            recovery_result=None,
            failure_category=category
        )

        self.logger.error(
            f"Diagnosis: {category.name} in {subsystem.name} - {error_message}",
            extra={
                "subsystem": subsystem.name,
                "problem": error_message,
                "diagnostic_data": {
                    "category": category.name,
                    "exception": exception_type,
                    "retry_count": health.retry_count,
                    "last_heartbeat": str(health.last_heartbeat) if health.last_heartbeat else None
                }
            }
        )

        return log

    def _classify_failure(self, subsystem: Subsystem, exception: Optional[Exception], error_message: str) -> FailureCategory:
        """Map exception types and error messages to FailureCategories."""

        error_lower = error_message.lower()
        exc_str = str(exception).lower() if exception else ""
        exc_type_str = type(exception).__name__.lower() if exception else ""

        # Network / Connection
        if any(term in error_lower or term in exc_str for term in ["timeout", "connection reset", "broken pipe", "network is unreachable", "connection refused"]):
            return FailureCategory.NETWORK

        # Authentication
        if subsystem == Subsystem.KOTAK_NEO_AUTH or "unauthorized" in error_lower or "401" in error_lower or "expired" in error_lower or "invalid token" in error_lower:
            return FailureCategory.AUTHENTICATION

        # WebSocket
        if subsystem == Subsystem.WEBSOCKET or "websocket" in error_lower or "1006" in error_lower:
            return FailureCategory.WEBSOCKET

        # Data / API
        if "jsondecodeerror" in exc_type_str or "malformed" in error_lower or "empty response" in error_lower or "stale" in error_lower:
            return FailureCategory.DATA

        # Rate Limiting
        if "429" in error_lower or "too many requests" in error_lower or "rate limit" in error_lower:
            return FailureCategory.API

        # Calculation
        if "zerodivisionerror" in exc_type_str or "valueerror" in exc_type_str or "nan" in error_lower:
            if subsystem in [Subsystem.PCR_PIPELINE, Subsystem.OI_PIPELINE]:
                return FailureCategory.CALCULATION

        # Subsystem based defaults
        if subsystem in [Subsystem.REST_API, Subsystem.KOTAK_NEO_AUTH]:
            return FailureCategory.API
        if subsystem in [Subsystem.FRONTEND_BACKEND]:
            return FailureCategory.FRONTEND
        if subsystem == Subsystem.STATE:
            return FailureCategory.STATE

        return FailureCategory.UNKNOWN
