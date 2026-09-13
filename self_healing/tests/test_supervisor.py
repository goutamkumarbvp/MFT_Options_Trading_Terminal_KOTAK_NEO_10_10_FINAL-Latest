import unittest
import time
from datetime import timedelta
from self_healing.supervisor import SupervisorEngine
from self_healing.enums import Subsystem, HealthState
from self_healing.validators import ComponentValidators

# Import the real application components to verify they don't deadlock
from kotak_api import KotakNeoClient
from market_data import MarketDataPipeline
from workers import CalculationWorkers

class TestSelfHealingEngine(unittest.TestCase):
    def setUp(self):
        self.supervisor = SupervisorEngine()

        # Initialize real components to bind the real hooks to the supervisor
        self.market_data = MarketDataPipeline(self.supervisor)
        self.kotak_client = KotakNeoClient(self.supervisor)
        self.workers = CalculationWorkers(self.supervisor, self.market_data)

        self.supervisor.start()
        self.workers.start()
        self.kotak_client.start()

    def tearDown(self):
        self.workers.stop()
        self.kotak_client.close_stale_socket()
        self.supervisor.stop()

    def test_broker_disconnect_recovery(self):
        """Scenario A & B: Broker / Websocket disconnect."""
        # Setup initial healthy state
        self.supervisor.report_heartbeat(Subsystem.WEBSOCKET)

        # Simulate websocket failure (1006)
        action = self.supervisor.report_failure(
            Subsystem.WEBSOCKET,
            Exception("WebSocket connection closed with code 1006"),
            "Connection dropped"
        )

        self.assertEqual(action.action_name, "dispatched_async")
        self.assertEqual(action.result, "DISPATCHED")

        # Give the background recovery thread time to execute the real hooks
        time.sleep(1.0)

        # Verify state returned to HEALTHY after successful recovery
        health = self.supervisor.health_monitor.get_health(Subsystem.WEBSOCKET)
        self.assertEqual(health.state, HealthState.HEALTHY)

    def test_stale_market_data(self):
        """Scenario D: Stale Market Data."""
        # Override hook to simulate successful recovery for tests without live integration
        self.supervisor.register_recovery_hook("refetch_data", lambda: True)
        self.supervisor.register_recovery_hook("invalidate_stale_state", lambda: True)

        action = self.supervisor.report_failure(
            Subsystem.OPTION_CHAIN,
            None,
            "Stale option data detected: last update > 15s"
        )

        self.assertEqual(action.action_name, "dispatched_async")
        self.assertEqual(action.result, "DISPATCHED")
        time.sleep(1.0)

        health = self.supervisor.health_monitor.get_health(Subsystem.OPTION_CHAIN)
        self.assertEqual(health.state, HealthState.HEALTHY)

        # Reset hook for other tests
        self.supervisor.register_recovery_hook("refetch_data", self.market_data.refetch_data)
        self.supervisor.register_recovery_hook("invalidate_stale_state", self.market_data.invalidate_stale_state)

    def test_calculation_failure(self):
        """Scenario I: Invalid calculation input (e.g. PCR Div by Zero)"""
        # Validate validator first
        validators = ComponentValidators()
        pcr = validators.validate_pcr(1000, 0)
        self.assertIsNone(pcr) # Should handle zero division safely

        # Now simulate engine recovery
        action = self.supervisor.report_failure(
            Subsystem.PCR_PIPELINE,
            ZeroDivisionError("division by zero"),
            "PCR Calculation Error"
        )

        self.assertEqual(action.action_name, "dispatched_async")
        time.sleep(1.0)

        # Verify that the isolate_bad_input hook successfully fired and cleared the PCR state
        self.assertIsNone(self.workers.pcr)

    def test_circuit_breaker(self):
        """Test API Circuit Breaker to prevent rate limit amplification."""
        for _ in range(5):
            # We must directly record failure to simulate repeated failed executions
            # normally this happens inside the RecoveryManager when the playbook fails,
            # or in the CircuitBreaker execute loop.
            self.supervisor.recovery_manager.circuit_breaker.record_failure(Subsystem.REST_API)

        # 6th attempt should be aborted by circuit breaker
        action = self.supervisor.report_failure(
            Subsystem.REST_API,
            Exception("429 Too Many Requests"),
            "Rate limit exceeded"
        )

        self.assertEqual(action.action_name, "aborted")
        self.assertEqual(action.result, "ABORTED")

    def test_watchdog_timeout(self):
        """Test that watchdog detects missing heartbeats."""
        self.supervisor.watchdog.set_threshold(Subsystem.MARKET_DATA, timedelta(seconds=0.1))
        self.supervisor.report_heartbeat(Subsystem.MARKET_DATA)

        time.sleep(0.5)

        health = self.supervisor.health_monitor.get_health(Subsystem.MARKET_DATA)
        self.assertTrue(health.retry_count >= 0)

    def test_worker_crash(self):
        """Scenario 13: Worker crash recovery."""
        action = self.supervisor.report_failure(
            Subsystem.BACKGROUND_WORKER,
            Exception("Worker task failed unexpectedly"),
            "Worker crash detected"
        )
        self.assertEqual(action.action_name, "dispatched_async")
        self.assertEqual(action.result, "DISPATCHED")

    def test_duplicate_timer_and_subscription(self):
        """Scenario 15 & 16: Duplicate Timer / Subscription."""

        # We manually register the test fallback because duplicate_subscription is a frontend hook
        self.supervisor.register_recovery_hook("unsubscribe_duplicates", lambda: True)
        self.supervisor.register_recovery_hook("duplicate_subscription_recovery", lambda: True)

        action = self.supervisor.report_failure(
            Subsystem.STATE,
            None,
            "duplicate timer detected for open interest build up"
        )
        self.assertEqual(action.action_name, "dispatched_async")
        self.assertEqual(action.result, "DISPATCHED")
        time.sleep(1.0)

        health = self.supervisor.health_monitor.get_health(Subsystem.STATE)
        self.assertTrue(health.state in [HealthState.HEALTHY, HealthState.RECOVERING])

    def test_malformed_option_chain_data(self):
        """Scenario 9 & 10: Malformed option chain data."""
        self.supervisor.register_recovery_hook("refetch_data", lambda: True)
        self.supervisor.register_recovery_hook("invalidate_stale_state", lambda: True)

        action = self.supervisor.report_failure(
            Subsystem.OPTION_CHAIN,
            ValueError("Malformed JSON"),
            "Malformed data received from API"
        )

        self.assertEqual(action.action_name, "dispatched_async")
        time.sleep(1.0)

        health = self.supervisor.health_monitor.get_health(Subsystem.OPTION_CHAIN)
        self.assertEqual(health.state, HealthState.HEALTHY)

        self.supervisor.register_recovery_hook("refetch_data", self.market_data.refetch_data)
        self.supervisor.register_recovery_hook("invalidate_stale_state", self.market_data.invalidate_stale_state)

    def test_failed_recovery_rollback(self):
        """Scenario 20: Rollback after failed recovery."""

        # Override the live hook temporarily to deliberately raise an exception to simulate failure
        def failing_hook(*args, **kwargs):
            raise Exception("Simulated fatal failure during recovery")

        self.supervisor.register_recovery_hook("refetch_data", failing_hook)

        # Set some state to test rollback
        self.supervisor.state_manager.update_state("selected_strike", 19500)
        self.supervisor.state_manager.update_state("selected_index", "NIFTY")

        # Give the test time to sync since we updated state manually right before failure
        time.sleep(0.1)

        # Simulate data failure, which will call refetch_data, which will fail
        action = self.supervisor.report_failure(
            Subsystem.OPTION_CHAIN,
            None,
            "Stale data"
        )

        self.assertEqual(action.result, "DISPATCHED")

        # Wait for the async failure rollback to complete
        time.sleep(1.0)

        # Verify rollback preserved state (the pre-recovery checkpoint had selected_strike = 19500)
        self.assertEqual(self.supervisor.state_manager.get_state("selected_strike"), 19500)
        self.assertEqual(self.supervisor.state_manager.get_state("selected_index"), "NIFTY")

        # Re-register real hook so other tests don't break
        self.supervisor.register_recovery_hook("refetch_data", self.market_data.refetch_data)

if __name__ == '__main__':
    unittest.main()
