import time
from self_healing.supervisor import SupervisorEngine
from self_healing.logger import get_logger
from kotak_api import KotakNeoClient
from market_data import MarketDataPipeline
from workers import CalculationWorkers

logger = get_logger("MainApplication")

class OptionsTradingTerminal:
    def __init__(self):
        # 1. Initialize Supervisor Engine
        self.supervisor = SupervisorEngine()

        # 2. Instantiate core business logic modules, injecting the supervisor
        self.market_data = MarketDataPipeline(self.supervisor)
        self.kotak_client = KotakNeoClient(self.supervisor)
        self.workers = CalculationWorkers(self.supervisor, self.market_data)

    def start(self):
        logger.info("==================================================")
        logger.info("STARTING MFT OPTIONS TRADING TERMINAL")
        logger.info("==================================================")

        # 3. Start the supervisor (validates startup checks)
        self.supervisor.start()

        # 4. Start the broker connection
        self.kotak_client.start()

        # 5. Pre-fetch initial data
        self.market_data.fetch_option_chain()

        # 6. Start background calculation workers
        self.workers.start()

        logger.info("Terminal is running and protected by Self-Healing Engine.")

    def stop(self):
        logger.info("Initiating Graceful Shutdown sequence...")
        try:
            # 1. Stop background processing first so they stop asking for data
            logger.info("Stopping calculation workers...")
            self.workers.stop()

            # 2. Close external connections cleanly
            logger.info("Closing Kotak Neo WebSocket and flushing queues...")
            self.kotak_client.close_stale_socket()

            # 3. Stop the supervisor (cleans up watchdog threads)
            logger.info("Stopping Self-Healing Supervisor...")
            self.supervisor.stop()

            logger.info("Terminal shutdown complete. No zombie processes left behind.")
        except Exception as e:
            logger.critical(f"Error during shutdown sequence: {e}")

if __name__ == "__main__":
    terminal = OptionsTradingTerminal()
    try:
        terminal.start()
        # Main thread keeps the application alive while daemons do the work
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        terminal.stop()
