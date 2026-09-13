from datetime import datetime
from typing import Dict, Any, Optional
from .enums import FailureCategory, Subsystem, HealthState, RecoveryLevel
from .models import DiagnosticLog, RecoveryAction, HealthSignal
from .health_monitor import HealthMonitor
from .circuit_breaker import CircuitBreaker
from .recovery_playbooks import RecoveryPlaybooks
from .state_manager import StateManager
from .logger import get_logger

class RecoveryManager:
    """Orchestrates progressive recovery actions based on diagnostics."""

    def __init__(self, health_monitor: HealthMonitor, state_manager: StateManager):
        self.health_monitor = health_monitor
        self.state_manager = state_manager
        self.playbooks = RecoveryPlaybooks(state_manager)
        self.circuit_breaker = CircuitBreaker()
        self.logger = get_logger("RecoveryManager")

    def handle_failure(self, diagnostic_log: DiagnosticLog) -> RecoveryAction:
        """Decide and execute the appropriate recovery strategy."""

        subsystem = diagnostic_log.subsystem
        category = diagnostic_log.failure_category

        # Mark as recovering
        self.health_monitor.process_signal(HealthSignal(
            subsystem=subsystem,
            state=HealthState.RECOVERING,
            details={"reason": f"Handling failure: {category.name}"}
        ))

        # Ensure rate limit resets if failure is not circuit breaking
        if not (category in [FailureCategory.API, FailureCategory.WEBSOCKET, FailureCategory.BROKER_CONNECTION, FailureCategory.NETWORK]):
             self.circuit_breaker.record_success(subsystem)

        # Check circuit breaker before attempting external recovery
        if category in [FailureCategory.API, FailureCategory.WEBSOCKET, FailureCategory.BROKER_CONNECTION, FailureCategory.NETWORK]:
            if not self.circuit_breaker.is_allowed(subsystem):
                return self._abort_recovery(subsystem, "Circuit breaker OPEN. Recovery delayed.")

        # Determine Progressive Recovery Level based on retry count
        health = self.health_monitor.get_health(subsystem)
        level = self._determine_escalation_level(health.retry_count)

        self.logger.info(f"Attempting {level.name} recovery for {subsystem.name}")

        success = False
        action_name = "unknown"

        try:
            # Create a backup checkpoint before mutating state
            checkpoint_name = f"pre_recovery_{subsystem.name}_{int(datetime.now().timestamp())}"
            self.state_manager.create_checkpoint(checkpoint_name)

            # Execute mapped playbook based on category
            if category == FailureCategory.NETWORK:
                action_name = "network_recovery"
                success = self.playbooks.recover_network()
            elif category == FailureCategory.WEBSOCKET:
                action_name = "websocket_recovery"
                success = self.playbooks.recover_websocket()
            elif category == FailureCategory.AUTHENTICATION:
                action_name = "auth_recovery"
                success = self.playbooks.recover_broker_session()
            elif category == FailureCategory.DATA:
                action_name = "data_recovery"
                success = self.playbooks.recover_stale_data()
            elif category == FailureCategory.CALCULATION:
                action_name = "calculation_recovery"
                success = self.playbooks.recover_calculation()
            elif category == FailureCategory.FRONTEND:
                action_name = "frontend_recovery"
                success = self.playbooks.recover_frontend()
            elif category == FailureCategory.STATE:
                # E.g. Duplicate subscriptions/timers
                if "duplicate" in diagnostic_log.error_message.lower():
                    if "timer" in diagnostic_log.error_message.lower():
                        action_name = "duplicate_timer_recovery"
                        success = self.playbooks.recover_duplicate_timer()
                    else:
                        action_name = "duplicate_subscription_recovery"
                        success = self.playbooks.recover_duplicate_subscription()
                else:
                    action_name = "generic_rebuild"
                    success = True # Placeholder for generic rebuild
            else:
                action_name = f"generic_{level.name.lower()}"
                success = True # Placeholder for generic progressive retry

            if success:
                self.state_manager.clear_checkpoint(checkpoint_name)
                self.circuit_breaker.record_success(subsystem)
            else:
                # Rollback if recovery failed and modified state
                self.logger.warning(f"Recovery failed. Rolling back to {checkpoint_name}")
                self.state_manager.rollback_to_checkpoint(checkpoint_name)
                self.circuit_breaker.record_failure(subsystem)

        except Exception as e:
            self.logger.error(f"Error during recovery playbook execution: {e}")
            self.circuit_breaker.record_failure(subsystem)
            success = False

        # Update monitor
        result_str = "SUCCESS" if success else "FAILED"
        self.health_monitor.update_recovery_state(subsystem, action_name, result_str)

        if success:
             self.health_monitor.process_signal(HealthSignal(
                subsystem=subsystem,
                state=HealthState.HEALTHY,
                details={"reason": "Recovery successful"}
            ))
        else:
             self.health_monitor.process_signal(HealthSignal(
                subsystem=subsystem,
                state=HealthState.FAILED,
                details={"reason": "Recovery failed"}
            ))

        return RecoveryAction(
            subsystem=subsystem,
            level=level,
            action_name=action_name,
            result=result_str
        )

    def _determine_escalation_level(self, retry_count: int) -> RecoveryLevel:
        """Progressive escalation logic."""
        if retry_count == 0:
            return RecoveryLevel.LEVEL_1
        elif retry_count == 1:
            return RecoveryLevel.LEVEL_2
        elif retry_count == 2:
            return RecoveryLevel.LEVEL_3
        elif retry_count == 3:
            return RecoveryLevel.LEVEL_4
        elif retry_count == 4:
            return RecoveryLevel.LEVEL_5
        else:
            return RecoveryLevel.LEVEL_6

    def _abort_recovery(self, subsystem: Subsystem, reason: str) -> RecoveryAction:
        """Return an aborted recovery action (e.g., due to circuit breaker)."""
        self.health_monitor.process_signal(HealthSignal(
            subsystem=subsystem,
            state=HealthState.FAILED,
            details={"reason": reason}
        ))

        return RecoveryAction(
            subsystem=subsystem,
            level=RecoveryLevel.LEVEL_1,
            action_name="aborted",
            result="ABORTED"
        )
