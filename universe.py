import logging
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.requests import StockSnapshotRequest
from alpaca.data.requests import MostActivesRequest
from broker import data_client
import config

log = logging.getLogger(__name__)

# ScreenerClient handles the "most actives" endpoint (moved in newer alpaca-py)
screener_client = ScreenerClient(config.API_KEY, config.SECRET_KEY)


def get_liquid_universe() -> list[str]:
    """
    Fetches top UNIVERSE_SIZE (default 100) most active stocks.
    Filters by price >= MIN_PRICE and volume >= MIN_AVG_VOLUME.
    Larger universe = more signals; quality filter keeps it clean.
    """
    try:
        request = MostActivesRequest(top=config.UNIVERSE_SIZE, by="volume")
        actives = screener_client.get_most_actives(request)
        raw_symbols = [asset.symbol for asset in actives.most_actives]

        snap_req  = StockSnapshotRequest(symbol_or_symbols=raw_symbols)
        snapshots = data_client.get_stock_snapshot(snap_req)

        filtered = []
        for sym, snap in snapshots.items():
            if snap.latest_trade is None:
                continue
            price  = snap.latest_trade.price
            volume = snap.daily_bar.volume if snap.daily_bar else 0

            if price >= config.MIN_PRICE and volume >= config.MIN_AVG_VOLUME:
                filtered.append(sym)

        log.info(f"Universe: {len(filtered)} symbols (from top {len(raw_symbols)})")
        return filtered

    except Exception as e:
        log.error(f"Universe fetch failed: {e}")
        return []


def check_vix_safe(current_vix: float) -> bool:
    safe = current_vix < config.VIX_MAX
    if not safe:
        log.warning(f"VIX {current_vix:.1f} > ceiling {config.VIX_MAX} — trading paused.")
    return safe