from typing import Dict, List, Optional
from datetime import datetime
from .enums import Subsystem, HealthState
from .models import ComponentHealth, HealthSignal
from .logger import get_logger

class HealthMonitor:
    def __init__(self):
        self.logger = get_logger("HealthMonitor")
        self._components: Dict[Subsystem, ComponentHealth] = {}
        for subsystem in Subsystem:
            self._components[subsystem] = ComponentHealth(subsystem=subsystem)

    def process_signal(self, signal: HealthSignal) -> None:
        """Process an incoming health signal and update the component state."""
        component = self._components[signal.subsystem]

        # Only log state changes
        if component.state != signal.state:
            self.logger.info(
                f"Component {signal.subsystem.name} state changed: {component.state.name} -> {signal.state.name}",
                extra={"subsystem": signal.subsystem.name, "old_state": component.state.name, "new_state": signal.state.name}
            )

        component.state = signal.state
        if signal.state == HealthState.HEALTHY:
            component.last_heartbeat = signal.timestamp
            component.failure_streak = 0
            component.retry_count = 0
        elif signal.state == HealthState.FAILED:
            component.failure_streak += 1

    def get_health(self, subsystem: Subsystem) -> ComponentHealth:
        """Get the current health of a specific subsystem."""
        return self._components.get(subsystem, ComponentHealth(subsystem=Subsystem.UNKNOWN))

    def get_all_health(self) -> Dict[Subsystem, ComponentHealth]:
        """Get the health of all monitored subsystems."""
        return self._components.copy()

    def update_recovery_state(self, subsystem: Subsystem, action_name: str, result: str) -> None:
        """Update the component state after a recovery action."""
        component = self._components.get(subsystem)
        if component:
            component.last_recovery_action = action_name
            component.retry_count += 1
            component.last_retry_time = datetime.now()

            self.logger.info(
                f"Recovery action {action_name} for {subsystem.name}: {result}",
                extra={"subsystem": subsystem.name, "action": action_name, "result": result}
            )
