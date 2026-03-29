import math
import config
from broker import get_open_positions

def _position_size_calc(entry: float, strategy: str) -> float:
    """Calculates whole shares based on a max $5,000 position size."""
    max_dollars = config.MAX_POSITION_SIZE
    qty = math.floor(max_dollars / entry)
    return max(1, qty)

def _pre_trade_guards(symbol: str, entry: float):
    positions = get_open_positions()
    if len(positions) >= config.MAX_OPEN_POSITIONS:
        return False, 0
    
    deployed = sum(float(p.market_value) for p in positions)
    if deployed + config.MAX_POSITION_SIZE > config.MAX_DEPLOYED_CAPITAL:
        return False, 0
        
    return True, _position_size_calc(entry, "swing")