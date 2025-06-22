# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python application that connects to the Whale Alert WebSocket API to receive real-time cryptocurrency transaction alerts. The application monitors large transactions (whales) on Bitcoin, Ethereum, and Tron blockchains for BTC and USDT transfers above $100,000 USD.

## Architecture

- **main.py**: Single-file application containing the WebSocket client that:
  - Connects to Whale Alert's WebSocket API using API key authentication
  - Subscribes to alerts for specific blockchains and symbols with minimum value filtering
  - Handles incoming messages in an async loop with connection management

## Environment Setup

Required environment variable:
- `WHALE_ALERT_KEY`: API key for Whale Alert service

## Development Commands

Install dependencies:
```bash
pip install -r requirements.txt
```

Run the application:
```bash
python main.py
```

## Key Dependencies

- `websockets==15.0.1`: WebSocket client library
- `asyncio==3.4.3`: Async I/O support (built into Python 3.7+)

## API Configuration

The application is configured to:
- Monitor blockchains: bitcoin, ethereum, tron
- Track symbols: BTC, USDT
- Alert threshold: $100,000 USD minimum transaction value