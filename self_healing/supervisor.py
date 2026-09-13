from typing import Optional, Callable
from .enums import Subsystem, HealthState
from .models import DiagnosticLog, RecoveryAction, HealthSignal
from .health_monitor import HealthMonitor
from .watchdog import Watchdog
from .diagnosis_engine import DiagnosisEngine
from .recovery_manager import RecoveryManager
from .state_manager import StateManager
from .validators import ComponentValidators
from .logger import get_logger

class SupervisorEngine:
    """The central Self-Healing Engine tying all components together."""

    def __init__(self):
        self.logger = get_logger("SupervisorEngine")
        self.state_manager = StateManager()
        self.health_monitor = HealthMonitor()
        self.watchdog = Watchdog(self.health_monitor)
        self.diagnosis_engine = DiagnosisEngine(self.health_monitor)
        self.recovery_manager = RecoveryManager(self.health_monitor, self.state_manager)
        self.validators = ComponentValidators()

        # Connect watchdog timeouts to the diagnosis engine
        self.watchdog.register_timeout_callback(self._handle_watchdog_timeout)
        self._is_started = False

    def start(self):
        """Initialize the Supervisor and run startup checks."""
        self.logger.info("Initializing Self-Healing Engine...")
        self._is_started = True

        # Run simulated startup self-checks
        if not self._run_startup_checks():
            self.logger.critical("Startup checks failed. Entering degraded state.")

        self.watchdog.start()
        self.logger.info("Self-Healing Engine started successfully.")

    def stop(self):
        """Clean shutdown of the Self-Healing Engine."""
        self.logger.info("Shutting down Self-Healing Engine...")
        self.watchdog.stop()
        self._is_started = False

    def report_failure(
        self,
        subsystem: Subsystem,
        exception: Optional[Exception],
        error_message: str,
        relevant_instrument: Optional[str] = None
    ) -> RecoveryAction:
        """Entry point for application code to report a failure."""

        if not self._is_started:
            self.logger.warning("Failure reported but Supervisor is not started.")
            return None # type: ignore

        # 1. Diagnose
        diagnostic_log = self.diagnosis_engine.diagnose(
            subsystem, exception, error_message, relevant_instrument
        )

        # 2. Recover
        recovery_action = self.recovery_manager.handle_failure(diagnostic_log)

        return recovery_action

    def report_heartbeat(self, subsystem: Subsystem) -> None:
        """Entry point for application code to report a healthy heartbeat."""
        if not self._is_started:
            return

        self.health_monitor.process_signal(HealthSignal(
            subsystem=subsystem,
            state=HealthState.HEALTHY
        ))

    def _handle_watchdog_timeout(self, subsystem: Subsystem) -> None:
        """Callback for when the watchdog detects a heartbeat timeout."""
        self.report_failure(
            subsystem=subsystem,
            exception=None,
            error_message="Watchdog heartbeat timeout"
        )

    def _run_startup_checks(self) -> bool:
        """Perform initial startup checks before marking the system as healthy."""
        self.logger.info("Running startup self-checks...")

        checks_passed = True
        critical_subsystems = [
            Subsystem.REST_API,
            Subsystem.WEBSOCKET,
            Subsystem.FRONTEND_BACKEND
        ]

        # In a real implementation, this would call actual health-check endpoints.
        # For this architecture implementation, we simulate success and set initial state.
        for sub in critical_subsystems:
             self.health_monitor.process_signal(HealthSignal(
                subsystem=sub,
                state=HealthState.HEALTHY,
                details={"reason": "Startup check passed"}
            ))

        return checks_passed

    def register_recovery_hook(self, name: str, func: Callable) -> None:
        """Expose playbook registration to the main application."""
        self.recovery_manager.playbooks.register_hook(name, func)
