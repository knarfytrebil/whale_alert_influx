# Instructions for Claude Code: Enhancing Whale Alert Data Analysis Script

## Objective
Modify the provided Python script to detect potential signals for significant market movements (big rises or falls) by analyzing deposit and withdrawal data from the Whale Alert WebSocket feed. The script should leverage the existing infrastructure to capture and store transaction data in InfluxDB and introduce new logic to identify patterns in fund flows that may indicate impending market volatility.

## Background Assumptions
1. **Fiat Exchanges (Kraken, Coinbase)**: These exchanges typically have strong fiat liquidity and are commonly used for on/off-ramping (converting between fiat and crypto). Large deposits to these exchanges may indicate intent to buy crypto (bullish signal), while large withdrawals may suggest cashing out (bearish signal).
2. **USDT-Based Exchanges (Binance, OKX, etc.)**: These exchanges have high spot and derivatives liquidity, where most trading activity occurs. Significant inflows of USDT or BTC to these exchanges may signal upcoming trading activity or hedging.
3. **Market Makers (MMs) and OTC Desks**: MMs (e.g., MatrixPort, Galaxy Digital) often internalize flows for profit but may place orders on exchanges when facing liquidity issues. Large transfers from MMs to exchanges could indicate hedging or liquidity provisioning, potentially preceding market movements.

## Requirements
Enhance the script to:
1. **Track Fund Flow Patterns**: Identify significant inflows/outflows to/from fiat exchanges, USDT-based exchanges, and MMs, focusing on BTC and USDT transactions.
2. **Detect Pre-Movement Signals**:
   - **Bullish Signals**: Large BTC/USDT inflows to fiat exchanges (potential buying pressure) or USDT inflows to USDT-based exchanges (preparing for trading).
   - **Bearish Signals**: Large BTC/USDT outflows from fiat exchanges (cashing out) or BTC inflows to USDT-based exchanges (potential selling pressure).
   - **MM Activity**: Large transfers from MMs to exchanges, indicating possible hedging or liquidity provisioning.
3. **Aggregate and Analyze Data**: Calculate rolling metrics (e.g., net flows over a time window) to identify unusual activity that may precede market movements.
4. **Alert on Signals**: Log potential signals to the console and store them in InfluxDB for further analysis.
5. **Maintain Existing Functionality**: Preserve the script’s current functionality (WebSocket connection, InfluxDB storage, entity classification) while adding new features.

## Specific Modifications
### 1. Enhance Data Storage in InfluxDB
- **Add Net Flow Metrics**: For each entity type (fiat_exchange, usdt_exchange, market_maker), calculate and store net flows (inflows minus outflows) for BTC and USDT over a rolling time window (e.g., 1 hour).
- **Store Signal Events**: Create a new measurement in InfluxDB (`market_signals`) to store detected signals with relevant metadata (e.g., signal type, confidence score, timestamp).

### 2. Implement Signal Detection Logic
- **Rolling Net Flow Calculation**:
  - Track net flows for each entity type and symbol (BTC, USDT) over a configurable time window (default: 1 hour).
  - Use a threshold (e.g., $10M net inflow/outflow) to flag significant movements.
- **Signal Rules**:
  - **Bullish Signals**:
    - Net BTC/USDT inflow to fiat exchanges > $10M in 1 hour.
    - Net USDT inflow to USDT-based exchanges > $10M in 1 hour.
  - **Bearish Signals**:
    - Net BTC/USDT outflow from fiat exchanges > $10M in 1 hour.
    - Net BTC inflow to USDT-based exchanges > $10M in 1 hour.
  - **MM Hedging Signal**:
    - Large transfer (> $5M) from market_maker to usdt_exchange or fiat_exchange.
- **Confidence Scoring**: Assign a confidence score to each signal based on the magnitude of the flow (e.g., scale from 0 to 1, where $10M = 0.5, $20M = 1.0).
- **Time Decay**: Prioritize recent transactions by applying a decay factor to older data in the rolling window.

### 3. Add Alerting Mechanism
- Log detected signals to the console with details (e.g., signal type, entity types involved, flow amount, confidence score).
- Store signals in InfluxDB under the `market_signals` measurement with tags (signal_type, entity_type, symbol) and fields (amount_usd, confidence_score).

### 4. Optimize Performance
- Use an in-memory cache (e.g., Python dictionary or pandas DataFrame) to track recent transactions for rolling net flow calculations.
- Batch InfluxDB writes to reduce overhead, especially for high-frequency data.
- Handle WebSocket disconnections gracefully with automatic reconnection logic.

### 5. Configuration
- Add environment variables for:
  - `ROLLING_WINDOW_MINUTES`: Time window for net flow calculations (default: 60).
  - `NET_FLOW_THRESHOLD_USD`: Threshold for significant net flows (default: 10000000).
  - `MM_TRANSFER_THRESHOLD_USD`: Threshold for MM transfers (default: 5000000).
- Allow customization of signal thresholds and time windows via `.env` file.

### 6. Preserve Existing Functionality
- Retain the existing WebSocket connection logic, entity classification (`get_entity_type`, `is_relevant_transaction`, `get_flow_direction`), and InfluxDB writing (`send_to_influxdb`).
- Ensure backward compatibility with the current `.env` configuration (e.g., `WHALE_ALERT_KEY`, `INFLUXDB_URL`).

## Implementation Notes
- **Dependencies**: Add `pandas` for efficient rolling window calculations, if not already present. Ensure compatibility with existing dependencies (`websockets`, `influxdb_client`, `python-dotenv`).
- **InfluxDB Schema**:
  - `whale_flows`: Continue storing individual transaction data (unchanged).
  - `flow_metrics`: Enhance to include net flow calculations per entity type and symbol.
  - `market_signals`: New measurement for storing detected signals.
- **Error Handling**: Add robust error handling for InfluxDB writes, WebSocket reconnects, and JSON parsing errors.
- **Logging**: Use Python’s `logging` module instead of `print` statements for better control and debugging.
- **Testing**: Suggest adding unit tests for signal detection logic and net flow calculations using a mock WebSocket feed.

## Example Signal Output
Console log example:
```
🚨 Bullish Signal Detected: Net USDT inflow to usdt_exchange (Binance)
   Amount: $12,500,000 | Confidence: 0.75 | Time Window: 2025-06-24 10:00 - 11:00
   Blockchain: Ethereum | Symbol: USDT
```

InfluxDB `market_signals` entry:
```
market_signals,symbol=USDT,entity_type=usdt_exchange,signal_type=bullish amount_usd=12500000,confidence_score=0.75 1719219600000000000
```

## Constraints
- Ensure the script remains compatible with Pyodide if intended for browser-based execution (no local file I/O, no network calls outside WebSocket).
- Avoid introducing dependencies that conflict with the existing setup.
- Keep the script modular and maintainable, with clear separation of concerns (e.g., data ingestion, signal detection, storage).

## Deliverable
Provide the modified Python script with all enhancements, ensuring it:
- Integrates seamlessly with the existing codebase.
- Includes clear comments explaining the new signal detection and net flow logic.
- Uses the same file structure and `.env` configuration as the original script.
- Is wrapped in an appropriate artifact tag for consistency.