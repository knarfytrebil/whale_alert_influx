# Whale Alerts Monitor

A Python application that monitors large cryptocurrency transactions in real-time using the Whale Alert WebSocket API.

## Overview

This application connects to Whale Alert's WebSocket service to receive notifications about significant cryptocurrency transactions (whale movements) across Bitcoin, Ethereum, and Tron blockchains. It specifically tracks BTC and USDT transactions above $100,000 USD.

## Prerequisites

- Python 3.7+
- Whale Alert API key (get one from [whale-alert.io](https://whale-alert.io))

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your API key as an environment variable:
   ```bash
   export WHALE_ALERT_KEY="your_api_key_here"
   ```

3. Run the application:
   ```bash
   python main.py
   ```

## Configuration

The application is currently configured to monitor:
- **Blockchains**: Bitcoin, Ethereum, Tron
- **Symbols**: BTC, USDT
- **Minimum transaction value**: $100,000 USD

To modify these settings, edit the `subscription_msg` dictionary in `main.py`.

## Features

- Real-time WebSocket connection to Whale Alert
- Automatic reconnection handling
- Transaction filtering by blockchain, symbol, and value
- Console output of whale transaction alerts

## Output

The application prints incoming whale alerts to the console, showing transaction details like amount, blockchain, and wallet addresses involved.