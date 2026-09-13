from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from .enums import HealthState, Subsystem, FailureCategory, RecoveryLevel

@dataclass
class HealthSignal:
    subsystem: Subsystem
    timestamp: datetime = field(default_factory=datetime.now)
    state: HealthState = HealthState.HEALTHY
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ComponentHealth:
    subsystem: Subsystem
    state: HealthState = HealthState.UNKNOWN
    last_heartbeat: Optional[datetime] = None
    last_recovery_action: Optional[str] = None
    retry_count: int = 0
    failure_streak: int = 0
    last_retry_time: Optional[datetime] = None

@dataclass
class DiagnosticLog:
    timestamp: datetime
    subsystem: Subsystem
    exception_type: Optional[str]
    error_message: str
    recent_health_state: HealthState
    last_successful_heartbeat: Optional[datetime]
    connection_state: Optional[str]
    api_response_state: Optional[str]
    relevant_instrument: Optional[str]
    retry_count: int
    recovery_action_attempted: Optional[str]
    recovery_result: Optional[str]
    failure_category: FailureCategory = FailureCategory.UNKNOWN

@dataclass
class RecoveryAction:
    subsystem: Subsystem
    level: RecoveryLevel
    action_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    result: Optional[str] = None
