"""Download recent completed Bitget USDT perpetual 3-minute candles for research."""
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

URL = 'https://api.bitget.com/api/v2/mix/market/history-candles'
SYMBOL = 'BTCUSDT'
GRANULARITY = '3m'
DAYS = 5
now = datetime.now(timezone.utc)
end_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
start_day = end_day - timedelta(days=DAYS)
start_ms = int(start_day.timestamp() * 1000)
end_ms = int(end_day.timestamp() * 1000)
rows = {}
cursor = end_ms - 1
session = requests.Session()

for page in range(80):
    params = dict(symbol=SYMBOL, productType='USDT-FUTURES', granularity=GRANULARITY,
                  endTime=str(cursor), limit='200')
    response = session.get(URL, params=params, timeout=25)
    response.raise_for_status()
    payload = response.json()
    if payload.get('code') != '00000':
        raise RuntimeError(f'Bitget API error: {payload}')
    batch = payload.get('data') or []
    if not batch:
        break
    timestamps = []
    for item in batch:
        ts = int(item[0])
        timestamps.append(ts)
        if start_ms <= ts < end_ms:
            rows[ts] = [ts, item[1], item[2], item[3], item[4], item[5]]
    oldest = min(timestamps)
    if oldest <= start_ms:
        break
    if oldest >= cursor:
        raise RuntimeError('Pagination did not advance')
    cursor = oldest - 1
    time.sleep(0.12)

ordered = [rows[k] for k in sorted(rows)]
expected = DAYS * 480
if len(ordered) != expected:
    raise RuntimeError(f'Expected {expected} complete candles, got {len(ordered)}; aborting to avoid invalid backtest')
for i, row in enumerate(ordered):
    if int(row[0]) != start_ms + i * 180000:
        raise RuntimeError(f'Missing or misaligned candle at index {i}')

path = Path('data/BTCUSDT_3m.csv')
path.parent.mkdir(parents=True, exist_ok=True)
with path.open('w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    writer.writerows(ordered)
print(f'Saved {len(ordered)} candles to {path}; UTC {start_day.date()} through {(end_day-timedelta(days=1)).date()}')
