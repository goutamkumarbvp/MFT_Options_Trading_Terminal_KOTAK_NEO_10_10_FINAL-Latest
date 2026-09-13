import copy
from typing import Dict, Any, Optional
from .logger import get_logger

class StateManager:
    """Manages application state checkpoints and rollbacks."""

    def __init__(self):
        self.logger = get_logger("StateManager")
        self._current_state: Dict[str, Any] = {
            "selected_index": None,
            "selected_expiry": None,
            "selected_strike": None,
            "active_subscriptions": set(),
            "nifty50_symbols": set(),
            "calculation_baselines": {}
        }
        self._checkpoints: Dict[str, Dict[str, Any]] = {}

    def update_state(self, key: str, value: Any) -> None:
        """Update a specific state parameter."""
        self._current_state[key] = copy.deepcopy(value)

    def get_state(self, key: str) -> Any:
        """Retrieve a specific state parameter."""
        return copy.deepcopy(self._current_state.get(key))

    def get_full_state(self) -> Dict[str, Any]:
        return copy.deepcopy(self._current_state)

    def create_checkpoint(self, name: str) -> None:
        """Create a snapshot of the current state."""
        self._checkpoints[name] = copy.deepcopy(self._current_state)
        self.logger.info(f"Created state checkpoint: {name}")

    def rollback_to_checkpoint(self, name: str) -> bool:
        """Rollback to a previously saved checkpoint."""
        if name in self._checkpoints:
            self._current_state = copy.deepcopy(self._checkpoints[name])
            self.logger.info(
                f"Successfully rolled back to checkpoint: {name}",
                extra={"subsystem": "STATE", "action": "Rollback", "result": "SUCCESS"}
            )
            return True
        else:
            self.logger.error(f"Checkpoint not found: {name}")
            return False

    def clear_checkpoint(self, name: str) -> None:
        if name in self._checkpoints:
            del self._checkpoints[name]
