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