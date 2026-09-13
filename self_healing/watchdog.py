import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Callable
from .enums import Subsystem, HealthState
from .models import HealthSignal
from .health_monitor import HealthMonitor
from .logger import get_logger

class Watchdog:
    def __init__(self, health_monitor: HealthMonitor):
        self.health_monitor = health_monitor
        self.logger = get_logger("Watchdog")
        self.thresholds: Dict[Subsystem, timedelta] = {
            Subsystem.WEBSOCKET: timedelta(seconds=5),
            Subsystem.MARKET_DATA: timedelta(seconds=10),
            Subsystem.OPTION_CHAIN: timedelta(seconds=15),
            Subsystem.TIMER: timedelta(seconds=5),
        }
        self.default_threshold = timedelta(seconds=30)
        self._running = False
        self._thread = None
        self._on_timeout_callbacks = []

    def register_timeout_callback(self, callback: Callable[[Subsystem], None]) -> None:
        self._on_timeout_callbacks.append(callback)

    def set_threshold(self, subsystem: Subsystem, threshold: timedelta) -> None:
        self.thresholds[subsystem] = threshold

    def start(self, interval_seconds: float = 1.0) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=(interval_seconds,), daemon=True)
        self._thread.start()
        self.logger.info("Watchdog started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self.logger.info("Watchdog stopped")

    def _loop(self, interval_seconds: float) -> None:
        while self._running:
            self.check_heartbeats()
            time.sleep(interval_seconds)

    def check_heartbeats(self) -> None:
        now = datetime.now()
        components = self.health_monitor.get_all_health()

        for subsystem, health in components.items():
            if subsystem == Subsystem.UNKNOWN:
                continue

            threshold = self.thresholds.get(subsystem, self.default_threshold)

            if health.last_heartbeat:
                time_since_heartbeat = now - health.last_heartbeat
                if time_since_heartbeat > threshold and health.state == HealthState.HEALTHY:
                    self.logger.warning(
                        f"Heartbeat timeout for {subsystem.name}. Last heartbeat was {time_since_heartbeat.total_seconds():.1f}s ago.",
                        extra={"subsystem": subsystem.name, "problem": "Heartbeat timeout"}
                    )

                    # Mark as failed in the monitor
                    signal = HealthSignal(
                        subsystem=subsystem,
                        state=HealthState.FAILED,
                        details={"error": "Heartbeat timeout"}
                    )
                    self.health_monitor.process_signal(signal)

                    # Trigger callbacks
                    for callback in self._on_timeout_callbacks:
                        try:
                            callback(subsystem)
                        except Exception as e:
                            self.logger.error(f"Error in watchdog callback: {e}")
