from typing import Dict, Any, List
from .supervisor import SupervisorEngine
from .enums import Subsystem, HealthState

class HealthReporter:
    """Provides a unified view of the system health for the dashboard."""

    def __init__(self, supervisor: SupervisorEngine):
        self.supervisor = supervisor

    def get_dashboard_state(self) -> Dict[str, Any]:
        """Generate the health state summary for the UI."""
        health_data = self.supervisor.health_monitor.get_all_health()

        dashboard = {}
        for subsystem, component in health_data.items():
            if subsystem == Subsystem.UNKNOWN:
                continue

            dashboard[subsystem.name] = {
                "state": component.state.name,
                "last_heartbeat": component.last_heartbeat.isoformat() if component.last_heartbeat else None,
                "last_recovery_action": component.last_recovery_action,
                "retry_count": component.retry_count
            }

        return dashboard

    def format_dashboard_text(self) -> str:
        """Format the dashboard state as plain text (e.g. for CLI/Logs)."""
        dashboard = self.get_dashboard_state()

        lines = ["=== SELF-HEALING DASHBOARD ==="]
        for name, data in dashboard.items():
            state = data["state"]

            # Simple terminal coloring logic placeholder
            if state == "HEALTHY":
                marker = "● HEALTHY"
            elif state == "RECOVERING":
                marker = "● RECOVERING"
            elif state == "DEGRADED":
                marker = "● DEGRADED"
            elif state == "FAILED":
                marker = "● FAILED"
            else:
                marker = f"○ {state}"

            lines.append(f"{name.ljust(20)} : {marker}")
            if data["last_recovery_action"]:
                lines.append(f"  └─ Last Action: {data['last_recovery_action']} (Retries: {data['retry_count']})")

        return "\n".join(lines)
