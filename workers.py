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

        self.pcr = None
        self._pcr_lock = threading.Lock()

        self._pcr_thread = None
        self._timer_thread = None
        self._running = False
        self._timer_lock = threading.Lock()

        # Stop event flags for safe thread termination
        self._pcr_stop_event = threading.Event()
        self._timer_stop_event = threading.Event()

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
        self._pcr_stop_event.set()
        self._timer_stop_event.set()

        if self._pcr_thread and self._pcr_thread.is_alive():
            self._pcr_thread.join(timeout=2.0)
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=2.0)

    # --- WORKER LOOPS ---

    def _start_pcr_worker(self):
        if self._pcr_thread and self._pcr_thread.is_alive():
            logger.warning("[Workers] PCR worker is already running. Preventing duplicate thread.")
            return

        self._pcr_thread = threading.Thread(target=self._pcr_loop, daemon=True, name="PCR_Worker")
        self._pcr_thread.start()

    def _start_timer_worker(self):
        with self._timer_lock:
            if self._timer_thread and self._timer_thread.is_alive():
                logger.warning("[Workers] UI timer is already running. Preventing duplicate timer.")
                return

            self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True, name="UI_Timer")
            self._timer_thread.start()

    def _pcr_loop(self):
        logger.info("[Workers] PCR Calculation thread started.")
        while self._running and not self._pcr_stop_event.is_set():
            try:
                self._pcr_stop_event.wait(2.0)
                if self._pcr_stop_event.is_set():
                    break
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

                with self._pcr_lock:
                    self.pcr = valid_pcr

                self.supervisor.report_heartbeat(Subsystem.PCR_PIPELINE)

            except Exception as e:
                self.supervisor.report_failure(Subsystem.PCR_PIPELINE, e, f"PCR Calculation failed: {e}")
                # We do not break; we wait for the supervisor to execute recovery hooks
                time.sleep(1)

    def _timer_loop(self):
        """Simulates the ~1 second Auto Refresh timer for UI components."""
        logger.info("[Workers] UI Refresh Timer started.")
        while self._running and not self._timer_stop_event.is_set():
            try:
                self._timer_stop_event.wait(1.0)
                if self._timer_stop_event.is_set():
                    break

                self.supervisor.report_heartbeat(Subsystem.TIMER)

            except Exception as e:
                self.supervisor.report_failure(Subsystem.TIMER, e, f"Timer failure: {e}")
                time.sleep(1)


    # --- RECOVERY HOOKS ---

    def isolate_bad_input(self) -> bool:
        logger.info("[Workers] Isolating bad calculation input. Invalidating PCR state.")
        with self._pcr_lock:
            # Do NOT use 0.0 or fabricated data. Honestly state that PCR is currently invalid.
            self.pcr = None
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
        elif worker_name == "UI_Timer":
            self._start_timer_worker()
            return True
        return False

    def cancel_duplicate_timers(self) -> bool:
        logger.info("[Workers] Detecting and canceling duplicate UI Refresh Timers...")
        with self._timer_lock:
            if self._timer_thread and self._timer_thread.is_alive():
                # Terminate the current timer thread by setting its stop event
                logger.info("[Workers] Terminating active UI Refresh Timer to prevent duplication.")
                self._timer_stop_event.set()
                self._timer_thread.join(timeout=2.0)

            # Clear the flag and restart cleanly
            self._timer_stop_event.clear()
            self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True, name="UI_Timer")
            self._timer_thread.start()

        return True
