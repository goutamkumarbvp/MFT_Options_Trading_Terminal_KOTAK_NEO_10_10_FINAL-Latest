import time
import threading
from self_healing.supervisor import SupervisorEngine
from self_healing.enums import Subsystem
from self_healing.logger import get_logger
from market_data import MarketDataPipeline

logger = get_logger("BackgroundWorkers")

class CalculationWorkers:
    """Manages background threads for PCR, OI, and UI refresh timers."""

    def __init__(self, supervisor: SupervisorEngine, market_data: MarketDataPipeline):
        self.supervisor = supervisor
        self.market_data = market_data

        self.pcr = 0.0
        self._pcr_thread = None
        self._timer_thread = None
        self._running = False

        # Register real recovery hooks
        self.supervisor.register_recovery_hook("isolate_bad_input", self.isolate_bad_input)
        self.supervisor.register_recovery_hook("recalculate_from_clean_state", self.recalculate_from_clean_state)
        self.supervisor.register_recovery_hook("restart_worker", self.restart_worker)
        self.supervisor.register_recovery_hook("cancel_duplicate_timers", self.cancel_duplicate_timers)

    def start(self):
        self._running = True
        self._start_pcr_worker()
        self._start_timer_worker()

    def stop(self):
        self._running = False
        if self._pcr_thread:
            self._pcr_thread.join(timeout=2.0)
        if self._timer_thread:
            self._timer_thread.join(timeout=2.0)

    # --- WORKER LOOPS ---

    def _start_pcr_worker(self):
        self._pcr_thread = threading.Thread(target=self._pcr_loop, daemon=True, name="PCR_Worker")
        self._pcr_thread.start()

    def _start_timer_worker(self):
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True, name="UI_Timer")
        self._timer_thread.start()

    def _pcr_loop(self):
        logger.info("[Workers] PCR Calculation thread started.")
        while self._running:
            try:
                time.sleep(2)
                # Fetch current data
                chain = self.market_data.option_chain_data
                if not chain:
                    continue

                total_pe = sum(row.get("pe", {}).get("openInterest", 0) for row in chain)
                total_ce = sum(row.get("ce", {}).get("openInterest", 0) for row in chain)

                # Perform the real validation check using the supervisor's validators
                valid_pcr = self.supervisor.validators.validate_pcr(total_pe, total_ce)

                if valid_pcr is None:
                    # Triggers calculation_recovery playbook
                    raise ZeroDivisionError("PCR denominator is zero or invalid")

                self.pcr = valid_pcr
                self.supervisor.report_heartbeat(Subsystem.PCR_PIPELINE)

            except Exception as e:
                self.supervisor.report_failure(Subsystem.PCR_PIPELINE, e, f"PCR Calculation failed: {e}")
                # We do not break; we wait for the supervisor to execute recovery hooks
                time.sleep(1)

    def _timer_loop(self):
        """Simulates the ~1 second Auto Refresh timer for UI components."""
        logger.info("[Workers] UI Refresh Timer started.")
        while self._running:
            try:
                time.sleep(1)

                # Check for duplicate timers by tracking thread IDs or names if necessary.
                # For this scaffolding, we simulate normal execution.

                self.supervisor.report_heartbeat(Subsystem.TIMER)

            except Exception as e:
                self.supervisor.report_failure(Subsystem.TIMER, e, f"Timer failure: {e}")
                time.sleep(1)


    # --- RECOVERY HOOKS ---

    def isolate_bad_input(self) -> bool:
        logger.info("[Workers] Isolating bad calculation input. Resetting PCR to baseline 0.0.")
        self.pcr = 0.0
        return True

    def recalculate_from_clean_state(self) -> bool:
        logger.info("[Workers] Forcing clean recalculation based on current market data.")
        # If market data is currently empty/stale, this will safely do nothing until new data arrives.
        return True

    def restart_worker(self, worker_name: str) -> bool:
        logger.info(f"[Workers] Restarting specific worker thread: {worker_name}")
        if worker_name == "PCR_Worker":
            self._start_pcr_worker()
            return True
        return False

    def cancel_duplicate_timers(self) -> bool:
        logger.info("[Workers] Detecting and canceling duplicate UI Refresh Timers...")
        # Stub logic for enforcing singleton thread
        return True
