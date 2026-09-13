import math
from typing import Dict, List, Any, Optional, Tuple
from .logger import get_logger

class ComponentValidators:
    """Self-validation checks for data integrity and business rules."""

    def __init__(self):
        self.logger = get_logger("ComponentValidators")

    def validate_pcr(self, total_pe_oi: float, total_ce_oi: float) -> Optional[float]:
        """Validate PCR calculation (PE OI / CE OI)."""
        try:
            if not isinstance(total_pe_oi, (int, float)) or not isinstance(total_ce_oi, (int, float)):
                raise ValueError("PCR inputs must be numeric")

            if total_ce_oi == 0:
                self.logger.warning("PCR validation failed: Denominator (CE OI) is zero.")
                return None

            if math.isnan(total_pe_oi) or math.isnan(total_ce_oi):
                raise ValueError("PCR inputs contain NaN")

            pcr = total_pe_oi / total_ce_oi

            if math.isinf(pcr):
                raise ValueError("PCR calculation resulted in Infinity")

            return pcr

        except Exception as e:
            self.logger.error(f"PCR validation error: {e}")
            return None

    def validate_oi_support_resistance(
        self,
        current_spot: float,
        option_chain: List[Dict[str, Any]]
    ) -> Tuple[Optional[float], Optional[float]]:
        """Validate Support (Highest OI OTM PE) and Resistance (Highest OI OTM CE)."""

        highest_pe_oi = -1.0
        support_strike = None

        highest_ce_oi = -1.0
        resistance_strike = None

        for row in option_chain:
            strike = row.get("strikePrice")
            if strike is None:
                continue

            # OTM PE (Strike < Spot)
            if strike < current_spot:
                pe_oi = row.get("pe", {}).get("openInterest", 0)
                if pe_oi > highest_pe_oi:
                    highest_pe_oi = pe_oi
                    support_strike = strike

            # OTM CE (Strike > Spot)
            if strike > current_spot:
                ce_oi = row.get("ce", {}).get("openInterest", 0)
                if ce_oi > highest_ce_oi:
                    highest_ce_oi = ce_oi
                    resistance_strike = strike

        # Simple sanity check
        if support_strike and resistance_strike:
            if support_strike >= current_spot or resistance_strike <= current_spot:
                self.logger.error("OI Support/Resistance validation failed: ITM strikes were selected.")
                return None, None

        return support_strike, resistance_strike

    def validate_nifty50_gainers(self, data: List[Dict[str, Any]]) -> bool:
        """Validate the Top 10 Nifty 50 OI Gainer structure."""
        if not data:
            self.logger.warning("Nifty 50 OI Gainers data is empty.")
            return False

        if len(data) > 10:
            self.logger.warning("Nifty 50 OI Gainers data exceeds 10 items.")
            return False

        for item in data:
            if 'symbol' not in item or 'oi_change_percent' not in item:
                self.logger.error("Nifty 50 OI Gainers missing required fields.")
                return False
            if not isinstance(item['oi_change_percent'], (int, float)):
                self.logger.error("Nifty 50 OI Gainers contains non-numeric OI change.")
                return False

        # Validate sorting (descending)
        for i in range(len(data) - 1):
            if data[i]['oi_change_percent'] < data[i+1]['oi_change_percent']:
                self.logger.error("Nifty 50 OI Gainers data is not sorted correctly.")
                return False

        return True
