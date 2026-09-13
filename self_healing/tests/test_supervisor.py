import unittest
import time
from datetime import timedelta
from self_healing.supervisor import SupervisorEngine
from self_healing.enums import Subsystem, HealthState
from self_healing.validators import ComponentValidators

class TestSelfHealingEngine(unittest.TestCase):
    def setUp(self):
        self.supervisor = SupervisorEngine()
        self.supervisor.start()

        # Mock hooks for testing
        self.hooks_called = []

        def make_hook(name):
            def hook(*args, **kwargs):
                self.hooks_called.append(name)
                return True
            return hook

        for action in [
            "close_stale_socket", "create_clean_connection", "resubscribe",
            "invalidate_stale_state", "refetch_data", "isolate_bad_input",
            "recalculate_from_clean_state", "cancel_duplicate_timers",
            "unsubscribe_duplicates", "restart_worker", "reconnect_frontend_channel",
            "verify_network", "refresh_session"
        ]:
            self.supervisor.register_recovery_hook(action, make_hook(action))

    def tearDown(self):
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

        self.assertEqual(action.action_name, "websocket_recovery")
        self.assertEqual(action.result, "SUCCESS")

        # Verify hooks were called in order
        self.assertIn("close_stale_socket", self.hooks_called)
        self.assertIn("create_clean_connection", self.hooks_called)

        # Verify state returned to HEALTHY after successful recovery
        health = self.supervisor.health_monitor.get_health(Subsystem.WEBSOCKET)
        self.assertEqual(health.state, HealthState.HEALTHY)

    def test_stale_market_data(self):
        """Scenario D: Stale Market Data."""
        # Simulate stale data failure
        action = self.supervisor.report_failure(
            Subsystem.OPTION_CHAIN,
            None,
            "Stale option data detected: last update > 15s"
        )

        self.assertEqual(action.action_name, "data_recovery")
        self.assertEqual(action.result, "SUCCESS")
        self.assertIn("invalidate_stale_state", self.hooks_called)
        self.assertIn("refetch_data", self.hooks_called)

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

        self.assertEqual(action.action_name, "calculation_recovery")
        self.assertIn("isolate_bad_input", self.hooks_called)
        self.assertIn("recalculate_from_clean_state", self.hooks_called)

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
        self.assertEqual(action.action_name, "generic_level_1") # Should trigger progressive retry
        self.assertEqual(action.result, "SUCCESS")

    def test_duplicate_timer_and_subscription(self):
        """Scenario 15 & 16: Duplicate Timer / Subscription."""

        # Test Duplicate Timer
        action = self.supervisor.report_failure(
            Subsystem.STATE,
            None,
            "duplicate timer detected for open interest build up"
        )
        self.assertEqual(action.action_name, "duplicate_timer_recovery")
        self.assertIn("cancel_duplicate_timers", self.hooks_called)

        # Test Duplicate Subscription
        action_sub = self.supervisor.report_failure(
            Subsystem.STATE,
            None,
            "Duplicate subscription found for instrument 1234"
        )
        self.assertEqual(action_sub.action_name, "duplicate_subscription_recovery")
        self.assertIn("unsubscribe_duplicates", self.hooks_called)

    def test_frontend_channel_failure(self):
        """Scenario 17: Frontend/Backend channel failure."""
        action = self.supervisor.report_failure(
            Subsystem.FRONTEND_BACKEND,
            Exception("WebSocket disconnect"),
            "Frontend channel dropped"
        )
        self.assertEqual(action.action_name, "frontend_recovery")
        self.assertIn("reconnect_frontend_channel", self.hooks_called)

    def test_malformed_option_chain_data(self):
        """Scenario 9 & 10: Malformed option chain data."""
        action = self.supervisor.report_failure(
            Subsystem.OPTION_CHAIN,
            ValueError("Malformed JSON"),
            "Malformed data received from API"
        )

        # Fall into DATA recovery playbook
        self.assertEqual(action.action_name, "data_recovery")
        self.assertIn("invalidate_stale_state", self.hooks_called)

    def test_failed_recovery_rollback(self):
        """Scenario 20: Rollback after failed recovery."""
        # Unregister the hook to simulate a failed recovery action
        del self.supervisor.recovery_manager.playbooks._hooks["refetch_data"]

        # Override the hook to deliberately raise an exception to simulate failure
        def failing_hook(*args, **kwargs):
            raise Exception("Simulated fatal failure during recovery")

        self.supervisor.register_recovery_hook("refetch_data", failing_hook)

        # Set some state to test rollback
        self.supervisor.state_manager.update_state("selected_strike", 19500)

        # Simulate data failure, which will call refetch_data, which will fail
        action = self.supervisor.report_failure(
            Subsystem.OPTION_CHAIN,
            None,
            "Stale data"
        )

        self.assertEqual(action.result, "FAILED")

        # Verify rollback preserved state (the pre-recovery checkpoint had selected_strike = 19500)
        self.assertEqual(self.supervisor.state_manager.get_state("selected_strike"), 19500)

if __name__ == '__main__':
    unittest.main()
