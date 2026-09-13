# Self-Healing Options Trading Terminal

## Project Purpose
A structural implementation of an MFT Options Trading Terminal backed by a robust, autonomous Self-Healing Engine. It detects, diagnoses, safely recovers from, and rollbacks runtime failures (like dropped WebSockets, calculation errors, or timer crashes) without manual intervention.

## Architecture
The terminal runs via `main.py`, orchestrating `KotakNeoClient`, `MarketDataPipeline`, and `CalculationWorkers`. The dedicated `self_healing` package acts as the Supervisor, maintaining a `Watchdog`, `HealthMonitor`, `DiagnosisEngine`, `RecoveryManager`, `CircuitBreaker`, and `StateManager`.

## Installation & Dependencies
This project uses standard Python 3 libraries (`threading`, `urllib`, `json`, `unittest`).
No external dependencies are required for the base Self-Healing Engine.

```bash
pip install -r requirements.txt
```

## Environment Variables
Copy `.env.example` to `.env` and fill in your details:
- `KOTAK_SESSION_TOKEN`: Real session token for live Kotak REST API
- `KOTAK_API_URL`: Base URL for the broker

*WARNING: Credentials must never be committed to source control.*

## Exact Startup Command
```bash
python3 main.py
```

## Exact Shutdown Procedure
Send a `SIGINT` (Ctrl+C). The terminal will execute a Graceful Shutdown sequence, stopping workers, flushing queues, closing WebSockets cleanly, and stopping the Supervisor to ensure no zombie processes remain.

## Self-Healing Behavior & Health States
The engine automatically transitions components through `UNKNOWN`, `HEALTHY`, `FAILED`, and `RECOVERING` states.
- A failing component will trigger a progressive recovery playbook (e.g., Level 1 Retry, Level 2 Reinitialize).
- The `CircuitBreaker` protects against rate-limit storms.
- The `StateManager` ensures a safe checkpoint rollback if recovery fails.

## Logging & Troubleshooting
Logs are generated locally via the `SelfHealingJSONFormatter`, which explicitly sanitizes sensitive configuration values. Watch the terminal output for `DiagnosisEngine` events classifying errors and `RecoveryManager` actions.

## Live Kotak Neo Configuration
Without valid environment variables, the system honestly falls back to a safe `FAILED` state to avoid spoofing live market data.

## Release Information
**MFT Options Trading Terminal**
*Production Self-Healing Release*
Build Date: September 2026
Test Status: All Fault-Injection Tests Passing