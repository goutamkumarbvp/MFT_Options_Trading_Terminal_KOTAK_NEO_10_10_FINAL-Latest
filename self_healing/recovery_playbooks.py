import time
from typing import Callable, Any, Dict
from .enums import Subsystem, FailureCategory, RecoveryLevel
from .logger import get_logger
from .state_manager import StateManager

class RecoveryPlaybooks:
    """Implementations of specific recovery strategies."""

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.logger = get_logger("RecoveryPlaybooks")

        # In a real system, these would be injected implementations
        # For the engine, we accept callbacks that hook into the actual application
        self._hooks: Dict[str, Callable] = {}

    def register_hook(self, name: str, func: Callable) -> None:
        """Register a recovery action hook."""
        self._hooks[name] = func

    def _execute_hook(self, name: str, *args, **kwargs) -> Any:
        if name in self._hooks:
            return self._hooks[name](*args, **kwargs)
        self.logger.warning(f"Hook not registered: {name}")
        return False # Honestly fail if the integration hook is missing

    def recover_network(self) -> bool:
        """Network recovery playbook."""
        self.logger.info("Executing NETWORK recovery playbook: waiting and retrying...")
        time.sleep(2) # Backoff

        success = self._execute_hook("verify_network")
        if not success:
             self.logger.error("NETWORK recovery verification failed.")
        return success

    def recover_websocket(self) -> bool:
        """WebSocket recovery playbook."""
        self.logger.info("Executing WEBSOCKET recovery playbook: cleaning and reconnecting...")

        self._execute_hook("close_stale_socket")

        # Restore active subscriptions from StateManager
        active_subs = self.state_manager.get_state("active_subscriptions")

        success = self._execute_hook("create_clean_connection")
        if not success:
             self.logger.error("WEBSOCKET recovery failed: Could not create clean connection.")
             return False

        if active_subs:
            success = self._execute_hook("resubscribe", active_subs)
            if not success:
                 self.logger.error("WEBSOCKET recovery failed: Could not restore active subscriptions.")
                 return False

        # Explicitly verify the connection is truly healthy (live heartbeat parsing)
        verified = self._execute_hook("verify_websocket_health")
        if not verified:
             self.logger.error("WEBSOCKET recovery verification failed: No fresh heartbeat detected after reconnect.")
             return False

        return True

    def recover_broker_session(self) -> bool:
        """Broker authentication recovery playbook."""
        self.logger.info("Executing BROKER_SESSION recovery playbook: refreshing token...")
        return self._execute_hook("refresh_session")

    def recover_stale_data(self) -> bool:
        """Stale Data recovery playbook."""
        self.logger.info("Executing STALE_DATA recovery playbook: invalidating and refetching...")
        self._execute_hook("invalidate_stale_state")
        return self._execute_hook("refetch_data")

    def recover_calculation(self) -> bool:
        """Calculation failure playbook."""
        self.logger.info("Executing CALCULATION recovery playbook: rebuilding from clean state...")

        # Ensure we don't propagate NaNs. We drop back to a known good state or rebuild.
        self._execute_hook("isolate_bad_input")
        return self._execute_hook("recalculate_from_clean_state")

    def recover_duplicate_timer(self) -> bool:
        """Timer duplication recovery playbook."""
        self.logger.info("Executing DUPLICATE_TIMER recovery playbook...")
        return self._execute_hook("cancel_duplicate_timers")

    def recover_duplicate_subscription(self) -> bool:
        """Duplicate subscription playbook."""
        self.logger.info("Executing DUPLICATE_SUBSCRIPTION recovery playbook...")
        return self._execute_hook("unsubscribe_duplicates")

    def recover_worker(self, worker_name: str) -> bool:
        """Background worker recovery playbook."""
        self.logger.info(f"Executing WORKER recovery playbook for: {worker_name}")
        return self._execute_hook("restart_worker", worker_name)

    def recover_frontend(self) -> bool:
        """Frontend communication recovery playbook."""
        self.logger.info("Executing FRONTEND recovery playbook: reconnecting channel...")
        return self._execute_hook("reconnect_frontend_channel")
