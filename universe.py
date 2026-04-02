"""
universe.py — S&P 500 Symbol Universe
─────────────────────────────────────
Strategy:
  1. Use local cache if < 30 days old  (fastest — just reads a file)
  2. Try GitHub CSV                    (lightweight, ~5KB, ~1 second)
  3. Fall back to hardcoded list       (instant, never fails)

NO Wikipedia. NO pandas HTML parsing.
Cache TTL = 30 days so GCP micro is not hitting the network on every run.
"""

import json
import logging
import requests
import pandas as pd
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

CACHE_FILE      = Path(__file__).parent / "sp500_cache.json"
CACHE_MAX_DAYS  = 30          # Refresh once a month

# ── Hardcoded S&P 500 fallback (as of early 2025) ─────────────────────────────
# This list is used when both the cache and the network are unavailable.
# Update manually once a year if needed — composition barely changes month-to-month.
_SP500_FALLBACK = [
    "MMM","AOS","ABT","ABBV","ACN","ADBE","AMD","AES","AFL","A","APD","ABNB",
    "AKAM","ALB","ARE","ALGN","ALLE","LNT","ALL","GOOGL","GOOG","MO","AMZN",
    "AMCR","AEE","AAL","AEP","AXP","AIG","AMT","AWK","AMP","AME","AMGN","APH",
    "ADI","ANSS","AON","APA","APO","AAPL","AMAT","APTV","ACGL","ADM","ANET",
    "AJG","AIZ","T","ATO","ADSK","ADP","AZO","AVB","AVY","AXON","BKR","BALL",
    "BAC","BK","BBWI","BAX","BDX","BRK-B","BBY","BIO","TECH","BIIB","BLK",
    "BX","BA","BKNG","BWA","BSX","BMY","AVGO","BR","BRO","BF-B","BLDR","CHRW",
    "CDNS","CZR","CPT","CPB","COF","CAH","KMX","CCL","CARR","CTLT","CAT","CBOE",
    "CBRE","CDW","CE","COR","CNC","CNX","CDAY","CF","CRL","SCHW","CHTR","CVX",
    "CMG","CB","CHD","CI","CINF","CTAS","CSCO","C","CFG","CLX","CME","CMS",
    "KO","CTSH","CL","CMCSA","CAG","COP","ED","STZ","CEG","COO","CPRT","GLW",
    "CPAY","CTVA","CSGP","COST","CTRA","CRWD","CCI","CSX","CMI","CVS","DHR",
    "DRI","DVA","DAY","DECK","DE","DELL","DAL","DVN","DXCM","FANG","DLR","DFS",
    "DG","DLTR","D","DPZ","DOV","DOW","DHI","DTE","DUK","DD","EMN","ETN","EBAY",
    "ECL","EIX","EW","EA","ELV","LLY","EMR","ENPH","ETR","EOG","EPAM","EQT",
    "EFX","EQIX","EQR","ERIE","ESS","EL","ETSY","EG","EVRG","ES","EXC","EXPE",
    "EXPD","EXR","XOM","FFIV","FDS","FICO","FAST","FRT","FDX","FIS","FITB",
    "FSLR","FE","FI","FMC","F","FTNT","FTV","FOXA","FOX","BEN","FCX","GRMN",
    "IT","GE","GEHC","GEV","GEN","GNRC","GD","GIS","GM","GPC","GILD","GS","HAL",
    "HIG","HAS","HCA","DOC","HSIC","HSY","HES","HPE","HLT","HOLX","HD","HON",
    "HRL","HST","HWM","HPQ","HUBB","HUM","HBAN","HII","IBM","IEX","IDXX","ITW",
    "INCY","IR","PODD","INTC","ICE","IFF","IP","IPG","INTU","ISRG","IVZ","INVH",
    "IQV","IRM","JBHT","JBL","JKHY","J","JNJ","JCI","JPM","JNPR","K","KVUE",
    "KDP","KEY","KEYS","KMB","KIM","KMI","KKR","KLAC","KHC","KR","LHX","LH",
    "LRCX","LW","LVS","LDOS","LEN","LKQ","LLY","LIN","LYV","LKQ","LMT","L",
    "LOW","LULU","LYB","MTB","MRO","MPC","MKTX","MAR","MMC","MLM","MAS","MA",
    "MTCH","MKC","MCD","MCK","MDT","MRK","META","MET","MTD","MGM","MCHP","MU",
    "MSFT","MAA","MRNA","MHK","MOH","TAP","MDLZ","MPWR","MNST","MCO","MS",
    "MOS","MSI","MSCI","NDAQ","NTAP","NFLX","NEM","NWSA","NWS","NEE","NKE",
    "NI","NDSN","NSC","NTRS","NOC","NCLH","NRG","NUE","NVDA","NVR","NXPI",
    "ORLY","OXY","ODFL","OMC","ON","OKE","ORCL","OTIS","PCAR","PKG","PANW",
    "PH","PAYX","PAYC","PYPL","PNR","PEP","PFE","PCG","PM","PSX","PNW","PNC",
    "POOL","PPG","PPL","PFG","PG","PGR","PLD","PRU","PEG","PTC","PSA","PHM",
    "QRVO","PWR","QCOM","DGX","RL","RJF","RTX","O","REG","REGN","RF","RSG",
    "RMD","RVTY","ROK","ROL","ROP","ROST","RCL","SPGI","CRM","SBAC","SLB",
    "STX","SRE","NOW","SHW","SPG","SWKS","SJM","SW","SNA","SOLV","SO","LUV",
    "SWK","SBUX","STT","STLD","STE","SYK","SMCI","SYF","SNPS","SYY","TMUS",
    "TROW","TTWO","TPR","TRGP","TGT","TEL","TDY","TFX","TER","TSLA","TXN",
    "TXT","TMO","TJX","TSCO","TT","TDG","TRV","TRMB","TFC","TYL","TSN","USB",
    "UBER","UDR","ULTA","UNP","UAL","UPS","URI","UNH","UHS","VLO","VTR","VLTO",
    "VRSN","VRSK","VZ","VRTX","VTRS","VICI","V","VST","VMC","WRB","GWW","WAB",
    "WBA","WMT","DIS","WBD","WM","WAT","WEC","WFC","WELL","WST","WDC","WY",
    "WHR","WMB","WTW","WYNN","XEL","XYL","YUM","ZBRA","ZBH","ZTS",
]


def _is_cache_valid() -> bool:
    if not CACHE_FILE.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(CACHE_FILE.stat().st_mtime)
    return age < timedelta(days=CACHE_MAX_DAYS)


def _load_cache() -> list:
    try:
        with open(CACHE_FILE) as f:
            return json.load(f).get("symbols", [])
    except Exception as e:
        log.warning(f"Cache load failed: {e}")
        return []


def _save_cache(symbols: list):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"symbols": symbols, "cached_at": datetime.now().isoformat()}, f)
        log.info(f"S&P 500 cache saved ({len(symbols)} symbols)")
    except Exception as e:
        log.warning(f"Cache save failed: {e}")


def _fetch_from_github() -> list:
    """Fetch S&P 500 CSV from GitHub datasets (~5KB, fast)."""
    url = (
        "https://raw.githubusercontent.com/"
        "datasets/s-and-p-500-companies/master/data/constituents.csv"
    )
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    symbols = [str(s).replace(".", "-") for s in df["Symbol"].tolist()]
    return symbols


def get_liquid_universe() -> list:
    """
    Returns the S&P 500 symbol list.
    Priority: local cache (30d TTL) → GitHub CSV → hardcoded fallback.
    """
    # 1. Cache hit
    if _is_cache_valid():
        symbols = _load_cache()
        if symbols:
            log.info(f"Universe: cache hit ({len(symbols)} symbols)")
            return symbols

    # 2. Network fetch — GitHub only (no Wikipedia)
    try:
        log.info("Universe: fetching from GitHub...")
        symbols = _fetch_from_github()
        _save_cache(symbols)
        log.info(f"Universe: GitHub OK ({len(symbols)} symbols)")
        return symbols
    except Exception as e:
        log.warning(f"Universe: GitHub fetch failed ({e}), using fallback list")

    # 3. Hardcoded fallback — always works, zero latency
    log.info(f"Universe: using hardcoded fallback ({len(_SP500_FALLBACK)} symbols)")
    return list(_SP500_FALLBACK)
