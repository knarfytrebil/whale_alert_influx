# Whale Alerts Monitor with InfluxDB2 Integration

A Python application that monitors large cryptocurrency transactions in real-time using the Whale Alert WebSocket API and stores relevant data in InfluxDB2.

## Overview

This application connects to Whale Alert's WebSocket service to receive notifications about significant cryptocurrency transactions (whale movements) across Bitcoin, Ethereum, and Tron blockchains. It filters transactions to only process those involving known exchanges and stores the data in InfluxDB2 for analysis.

## Prerequisites

- Python 3.7+
- Whale Alert API key (get one from [whale-alert.io](https://whale-alert.io))
- InfluxDB2 instance with token, organization, and bucket configured

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy the example environment file and configure it:
   ```bash
   cp .env.example .env
   ```
   
3. Edit `.env` with your credentials:
   ```env
   WHALE_ALERT_KEY=your_whale_alert_api_key_here
   INFLUXDB_URL=http://localhost:8086
   INFLUXDB_TOKEN=your_influxdb_token_here
   INFLUXDB_ORG=your_org_name
   INFLUXDB_BUCKET=whale_alerts
   ```

4. Run the application:
   ```bash
   python main.py
   ```

## Configuration

The application monitors:
- **Blockchains**: Bitcoin, Ethereum, Tron
- **Symbols**: BTC, USDT
- **Minimum transaction value**: $100,000 USD
- **Exchange filtering**: Only processes transactions involving known exchanges

### Supported Exchanges

The application currently filters for transactions involving:
- Binance, OKEX, Coinbase, Coinbase Institutional
- B2C2, HTX, Kraken, Bitfinex, OKX, BitGet
- Bybit, KuCoin, Huobi, Gate.io, Crypto.com

To add more exchanges, edit the `KNOWN_EXCHANGES` list in `main.py`.

## Features

- **Real-time monitoring**: WebSocket connection to Whale Alert
- **Exchange filtering**: Only processes transactions to/from known exchanges
- **InfluxDB2 integration**: Stores transaction data with detailed metrics
- **New exchange detection**: Logs potential new exchanges for manual review
- **Environment configuration**: Uses .env files for secure credential management
- **Comprehensive logging**: Clear console output showing processed vs filtered transactions

## Data Storage

Transaction data is stored in InfluxDB2 with:
- **Measurement**: `whale_transactions`
- **Tags**: blockchain, symbol, from, to, transaction_type
- **Fields**: amount, value_usd, transaction_hash
- **Timestamp**: Transaction timestamp from Whale Alert

## Output Examples

```
📊 Exchange transaction detected:
   From: unknown wallet
   To: Binance
   Blockchain: ethereum
✓ Sent to InfluxDB: USDT $2,000,000.00

🔍 Potential new exchange detected:
   TO: SomeNewExchange
   Blockchain: bitcoin
   Value: $5,000,000.00

⏭️  Filtered out: unknown wallet → unknown wallet
```

## Querying InfluxDB2

### Query Methods

#### 1. InfluxDB2 Web UI
- Go to `http://localhost:8086` in your browser
- Navigate to **Data Explorer** or **Notebooks**
- Use the visual query builder or write Flux queries directly

#### 2. Command Line (influx CLI)
```bash
# Install InfluxDB CLI
# On macOS: brew install influxdb-cli
# On Linux: wget https://dl.influxdata.com/influxdb/releases/influxdb2-client-linux-amd64.tar.gz

# Query with CLI
influx query 'from(bucket:"whale_alerts") |> range(start: -1h)' \
  --host http://localhost:8086 \
  --token YOUR_TOKEN \
  --org YOUR_ORG
```

#### 3. Python Client
```python
from influxdb_client import InfluxDBClient

client = InfluxDBClient(url="http://localhost:8086", token="YOUR_TOKEN", org="YOUR_ORG")
query_api = client.query_api()

query = '''
from(bucket: "whale_alerts")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
'''

result = query_api.query(query)
for table in result:
    for record in table.records:
        print(record)
```

### Common Flux Queries

#### All Transactions in Last Hour
```flux
from(bucket: "whale_alerts")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
```

#### Transactions Above $1M
```flux
from(bucket: "whale_alerts")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> filter(fn: (r) => r["_field"] == "value_usd")
  |> filter(fn: (r) => r["_value"] > 1000000.0)
```

#### Binance Transactions Only
```flux
from(bucket: "whale_alerts")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> filter(fn: (r) => r["to"] == "Binance")
```

#### Group by Exchange (Sum Volume)
```flux
from(bucket: "whale_alerts")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> filter(fn: (r) => r["_field"] == "value_usd")
  |> group(columns: ["to"])
  |> sum()
```

#### Count Transactions per Hour
```flux
from(bucket: "whale_alerts")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> filter(fn: (r) => r["_field"] == "value_usd")
  |> aggregateWindow(every: 1h, fn: count)
```

#### Latest 10 Transactions
```flux
from(bucket: "whale_alerts")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 10)
```

## Grafana Integration

### Add InfluxDB2 Data Source
1. In Grafana, go to **Configuration** → **Data Sources**
2. Click **Add data source** → **InfluxDB**
3. Configure:
   - **Query Language**: Flux
   - **URL**: `http://localhost:8086`
   - **Organization**: Your InfluxDB org
   - **Token**: Your InfluxDB token
   - **Default Bucket**: `whale_alerts`

### Recommended Dashboard Panels

#### Transaction Volume Over Time
```flux
from(bucket: "whale_alerts")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> filter(fn: (r) => r["_field"] == "value_usd")
  |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
```

#### Top Exchanges by Volume
```flux
from(bucket: "whale_alerts")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> filter(fn: (r) => r["_field"] == "value_usd")
  |> group(columns: ["to"])
  |> sum()
  |> sort(columns: ["_value"], desc: true)
```

#### Transaction Count by Blockchain
```flux
from(bucket: "whale_alerts")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
  |> filter(fn: (r) => r["_field"] == "value_usd")
  |> group(columns: ["blockchain"])
  |> count()
```