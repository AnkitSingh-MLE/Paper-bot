import pandas as pd
import requests
import logging

log = logging.getLogger(__name__)

def get_liquid_universe():
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(response.text)
        df = tables[0]
        symbols = df['Symbol'].tolist()
        # Clean symbols for Alpaca (e.g., BRK.B -> BRK-B)
        return [str(s).replace('.', '-') for s in symbols]
    except Exception as e:
        log.error(f"Wiki List Scrape failed: {e}. Using core fallback.")
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"]
