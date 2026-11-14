"""Fetch 5 complete UTC days of Bitget BTCUSDT perpetual 3m candles.
Uses overlapping, time-bounded windows to avoid cursor pagination gaps.
Fails safely if the exchange does not return every expected candle.
"""
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

URL = 'https://api.bitget.com/api/v2/mix/market/history-candles'
SYMBOL = 'BTCUSDT'
DAYS = 5
STEP = 180_000  # 3 minutes in milliseconds
now = datetime.now(timezone.utc)
end = now.replace(hour=0, minute=0, second=0, microsecond=0)
start = end - timedelta(days=DAYS)
start_ms = int(start.timestamp() * 1000)
end_ms = int(end.timestamp() * 1000)
expected_times = list(range(start_ms, end_ms, STEP))
rows = {}
session = requests.Session()


def fetch_window(first_ms, last_ms):
    # 100 bars per window, plus one bar overlap at both edges.
    params = {
        'symbol': SYMBOL, 'productType': 'USDT-FUTURES', 'granularity': '3m',
        'startTime': str(first_ms - STEP), 'endTime': str(last_ms + STEP),
        'limit': '200',
    }
    for attempt in range(5):
        try:
            response = session.get(URL, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if payload.get('code') != '00000':
                raise RuntimeError(f'Bitget response: {payload}')
            return payload.get('data') or []
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            if attempt == 4:
                raise RuntimeError(f'Failed fetching window {first_ms}..{last_ms}') from exc
            time.sleep(min(2 ** attempt, 8))


def merge(batch):
    for item in batch:
        ts = int(item[0])
        if start_ms <= ts < end_ms and (ts - start_ms) % STEP == 0:
            rows[ts] = [ts, item[1], item[2], item[3], item[4], item[5]]


# Explicit time windows rather than exclusive cursor pagination.
for offset in range(0, len(expected_times), 100):
    chunk = expected_times[offset:offset + 100]
    merge(fetch_window(chunk[0], chunk[-1]))
    time.sleep(0.15)

# Retry any missing candle with a small, overlapping time window.
for attempt in range(3):
    missing = [ts for ts in expected_times if ts not in rows]
    if not missing:
        break
    print(f'Retry {attempt + 1}: {len(missing)} missing candles', flush=True)
    for ts in missing:
        merge(fetch_window(ts - 2 * STEP, ts + 2 * STEP))
        time.sleep(0.15)

missing = [ts for ts in expected_times if ts not in rows]
if missing:
    examples = [datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat() for ts in missing[:12]]
    raise RuntimeError(f'Incomplete 3m history: {len(missing)} candles missing. First gaps (UTC): {examples}')

path = Path('data/BTCUSDT_3m.csv')
path.parent.mkdir(parents=True, exist_ok=True)
with path.open('w', newline='', encoding='utf-8') as handle:
    writer = csv.writer(handle)
    writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    writer.writerows(rows[ts] for ts in expected_times)
print(f'Saved {len(expected_times)} continuous candles to {path}: {start.isoformat()} to {end.isoformat()} (exclusive)')
