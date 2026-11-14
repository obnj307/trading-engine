# POC Strategy Backtester V1

Research-only, no exchange connectivity and no live orders.

## Input
CSV containing `timestamp,open,high,low,close,volume`, strictly consecutive 3-minute UTC candles. Timestamp is ISO-8601 UTC, Unix seconds, or Unix milliseconds. At least one complete UTC day (480 candles) plus the next day required. For robust results use months of data.

## Run
```
pip install -r requirements.txt
python backtest.py btcusdt_3m.csv --fee-bps 6 --slippage-bps 2
```
Outputs trade logs in `trades/` and summary statistics in terminal. The default fees and slippage are illustrative; replace with actual Bitget account costs. Candle volume profile is approximated by allocating each candle's volume uniformly over its high-low range; it is **not** true trade-by-price volume. Daily POC is derived only from previous complete UTC day.

## Methodology and limitations
Signals use closed bars and enter at next bar's open. One open trade per strategy. Fixed 1 ATR stop, 2 ATR target, 20 bars maximum; ATR(14) from available history. If a stop and target are both hit in the same bar, stop wins conservatively. Gaps through stops use opening price, while target exits are limited to target price. Fee and slippage per side are modeled, no funding, liquidation, market impact, leverage or partial fills. Limit orders are not yet modeled. Metrics are trade-unit percentage points, not compounded account returns. Signals are preliminary test hypotheses, not validated profitable strategies. For trustworthy results, split chronologically into development/holdout data and test across coins and market regimes.
