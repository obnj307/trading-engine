"""POC Strategy Backtester V1 - research only, no live orders.
Input CSV: timestamp,open,high,low,close,volume (UTC timestamps, 3-minute bars).
Run: python backtest.py candles.csv --fee-bps 6 --slippage-bps 2
"""
import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np


def parse_time(value):
    v = value.strip()
    if v.isdigit():
        n = int(v)
        return datetime.fromtimestamp(n / (1000 if n > 10**11 else 1), tz=timezone.utc)
    return datetime.fromisoformat(v.replace('Z', '+00:00')).replace(tzinfo=timezone.utc) if datetime.fromisoformat(v.replace('Z', '+00:00')).tzinfo is None else datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(timezone.utc)


def read_bars(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    bars = []
    for r in rows:
        bars.append(dict(t=parse_time(r['timestamp']), o=float(r['open']), h=float(r['high']), l=float(r['low']), c=float(r['close']), v=float(r['volume'])))
    bars.sort(key=lambda b: b['t'])
    for i, b in enumerate(bars):
        if b['l'] > min(b['o'], b['c']) or b['h'] < max(b['o'], b['c']) or b['v'] < 0:
            raise ValueError(f'Invalid OHLCV at row {i+2}')
        if i and b['t'] <= bars[i-1]['t']:
            raise ValueError('Duplicate timestamps')
        if i and b['t']-bars[i-1]['t'] != timedelta(minutes=3):
            raise ValueError(f'Missing/non-3m candle at {b["t"]}; continuous 3m history required')
    return bars


def profile(bars, bins=60):
    """Approximation: distribute each candle volume evenly across overlapped price bins."""
    lo = min(b['l'] for b in bars)
    hi = max(b['h'] for b in bars)
    if hi <= lo:
        return lo
    edges = np.linspace(lo, hi, bins + 1)
    hist = np.zeros(bins)
    for b in bars:
        if b['h'] == b['l']:
            hist[min(bins-1, np.searchsorted(edges, b['c'], side='right')-1)] += b['v']
            continue
        widths = np.maximum(0, np.minimum(edges[1:], b['h']) - np.maximum(edges[:-1], b['l']))
        hist += b['v'] * widths / (b['h']-b['l'])
    return float((edges[np.argmax(hist)] + edges[np.argmax(hist)+1])/2)


def atr_series(bars, period=14):
    tr = []
    for i, b in enumerate(bars):
        prev = bars[i-1]['c'] if i else b['c']
        tr.append(max(b['h']-b['l'], abs(b['h']-prev), abs(b['l']-prev)))
    result = [None] * len(bars)
    for i in range(period-1, len(bars)):
        result[i] = float(np.mean(tr[i-period+1:i+1]))
    return result


def signals(bars, pocs, atr):
    """Signals on closed candle i, entries at open of candle i+1."""
    output = defaultdict(list)
    for i in range(2, len(bars)-1):
        b, prev = bars[i], bars[i-1]
        day = b['t'].date()
        if day not in pocs or atr[i] is None:
            continue
        p = pocs[day]
        # Bounce: wick touches POC and closes back on original side.
        if prev['c'] > p and b['l'] <= p and b['c'] > p:
            output['bounce'].append((i, 1))
        if prev['c'] < p and b['h'] >= p and b['c'] < p:
            output['bounce'].append((i, -1))
        # Breakout: completed close crosses POC.
        if prev['c'] <= p < b['c']:
            output['breakout'].append((i, 1))
        if prev['c'] >= p > b['c']:
            output['breakout'].append((i, -1))
        # Retest: previous close above/below, earlier close on opposite side,
        # then current wick tests POC while close stays beyond it.
        old = bars[i-2]
        if old['c'] <= p < prev['c'] and b['l'] <= p < b['c']:
            output['retest'].append((i, 1))
        if old['c'] >= p > prev['c'] and b['h'] >= p > b['c']:
            output['retest'].append((i, -1))
    return output


def simulate(bars, candidates, atr, sl_mult, tp_mult, max_hold, fee_bps, slip_bps):
    trades = []
    available = 0
    for i, direction in candidates:
        j = i + 1
        if j < available or j >= len(bars):
            continue
        entry = bars[j]['o'] * (1 + direction*slip_bps/10000)
        distance = atr[i]*sl_mult
        if distance <= 0:
            continue
        stop = entry - direction*distance
        target = entry + direction*atr[i]*tp_mult
        exit_i = min(j+max_hold-1, len(bars)-1)
        exit_price = None
        reason = 'time'
        for k in range(j, exit_i+1):
            b = bars[k]
            stop_hit = b['l'] <= stop if direction == 1 else b['h'] >= stop
            target_hit = b['h'] >= target if direction == 1 else b['l'] <= target
            if stop_hit:
                # Conservatively assume stop first if both stop and target touched.
                exit_price = min(stop, b['o']) if direction == 1 else max(stop, b['o'])
                reason = 'stop'
            elif target_hit:
                exit_price = target
                reason = 'target'
            if exit_price is not None:
                exit_i = k
                break
        if exit_price is None:
            exit_price = bars[exit_i]['c']
        exit_price *= 1 - direction*slip_bps/10000
        gross = direction*(exit_price-entry)/entry
        net = gross - 2*fee_bps/10000
        trades.append(dict(signal=bars[i]['t'].isoformat(), entry=bars[j]['t'].isoformat(), exit=bars[exit_i]['t'].isoformat(), side='LONG' if direction==1 else 'SHORT', entry_price=entry, exit_price=exit_price, net_pct=net*100, reason=reason))
        available = exit_i+1
    return trades


def report(trades):
    if not trades:
        return 'No trades'
    r = np.array([x['net_pct'] for x in trades])
    wins = r[r>0].sum()
    losses = -r[r<0].sum()
    # Non-compounded unit-notional trade returns; equity curve assumes one unit invested per trade.
    curve = np.cumsum(np.r_[0, r])
    drawdown = np.max(np.maximum.accumulate(curve)-curve)
    pf = wins/losses if losses > 0 else float('inf')
    return f'trades={len(r)}, winrate={np.mean(r>0)*100:.1f}%, mean={r.mean():+.3f}%/trade, PF={pf:.2f}, maxDD={drawdown:.2f} percentage points'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv_path')
    ap.add_argument('--fee-bps', type=float, default=6, help='Fee per side, basis points (placeholder)')
    ap.add_argument('--slippage-bps', type=float, default=2, help='Slippage per side, basis points (placeholder)')
    ap.add_argument('--sl-atr', type=float, default=1)
    ap.add_argument('--tp-atr', type=float, default=2)
    ap.add_argument('--hold-bars', type=int, default=20)
    ap.add_argument('--out', default='trades')
    args = ap.parse_args()
    bars = read_bars(args.csv_path)
    days = defaultdict(list)
    for b in bars:
        days[b['t'].date()].append(b)
    ordered = sorted(days)
    pocs = {}
    for idx in range(1, len(ordered)):
        prev = days[ordered[idx-1]]
        if len(prev) == 480 and (ordered[idx]-ordered[idx-1]).days == 1:
            pocs[ordered[idx]] = profile(prev)
    if not pocs:
        raise SystemExit('Need at least one complete previous UTC day (480 3m candles) and following day')
    atr = atr_series(bars)
    sig = signals(bars, pocs, atr)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    for name in ('bounce','breakout','retest'):
        trades = simulate(bars, sig[name], atr, args.sl_atr, args.tp_atr, args.hold_bars, args.fee_bps, args.slippage_bps)
        with open(Path(args.out)/f'{name}.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['signal','entry','exit','side','entry_price','exit_price','net_pct','reason'])
            writer.writeheader()
            writer.writerows(trades)
        print(f'{name:9s}: {report(trades)}')
    print(f'POC days: {len(pocs)}. Outputs: {args.out}/')

if __name__ == '__main__':
    main()
