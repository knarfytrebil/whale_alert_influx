import os
import asyncio
import websockets
import json
from datetime import datetime
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

WHALE_ALERT_KEY = os.environ["WHALE_ALERT_KEY"]
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ["INFLUXDB_BUCKET"]

# Known exchanges to filter for
KNOWN_EXCHANGES = [
    "Binance",
    "OKEX",
    "Coinbase",
    "Coinbase Institutional",
    "B2C2",
    "HTX",
    "Kraken",
    "Bitfinex",
    "OKX",
    "BitGet",
    "Bybit",
    "KuCoin",
    "Huobi",
    "Gate.io",
    "Crypto.com",
]


def is_exchange_transaction(from_wallet, to_wallet):
    """Check if transaction involves a known exchange"""
    for exchange in KNOWN_EXCHANGES:
        if (
            exchange.lower() in from_wallet.lower()
            or exchange.lower() in to_wallet.lower()
        ):
            return True
    return False


def send_to_influxdb(transaction_data):
    """Send transaction data to InfluxDB2"""
    try:
        with InfluxDBClient(
            url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
        ) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)

            # Create point for each amount in the transaction
            for amount_data in transaction_data["amounts"]:
                point = (
                    Point("whale_transactions")
                    .tag("blockchain", transaction_data["blockchain"])
                    .tag("symbol", amount_data["symbol"])
                    .tag("from", transaction_data["from"])
                    .tag("to", transaction_data["to"])
                    .tag("transaction_type", transaction_data["transaction_type"])
                    .field("amount", float(amount_data["amount"]))
                    .field("value_usd", float(amount_data["value_usd"]))
                    .field("transaction_hash", transaction_data["transaction"]["hash"])
                    .time(datetime.fromtimestamp(transaction_data["timestamp"]))
                )

                write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)

        print(
            f"✓ Sent to InfluxDB: {amount_data['symbol']} ${amount_data['value_usd']:,.2f}"
        )

    except Exception as e:
        print(f"✗ Error sending to InfluxDB: {e}")


async def connect():
    # The WebSocket API URL with the API key included
    url = f"wss://leviathan.whale-alert.io/ws?api_key={WHALE_ALERT_KEY}"

    # The subscription message
    subscription_msg = {
        "type": "subscribe_alerts",
        "blockchains": ["bitcoin", "ethereum", "tron"],
        "symbols": ["BTC", "USDT"],
        "min_value_usd": 100000,
    }

    # Connect to the WebSocket server
    async with websockets.connect(url) as ws:
        # Send the subscription message
        await ws.send(json.dumps(subscription_msg))

        # Wait for a response
        response = await ws.recv()

        # Print the response
        print(f"Received: {response}")

        # Continue to handle incoming messages
        while True:
            try:
                # Wait for a new message
                message = await asyncio.wait_for(ws.recv(), timeout=None)

                # Parse the JSON message
                try:
                    data = json.loads(message)

                    # Check if this is a transaction alert (not a subscription response)
                    if "from" in data and "to" in data:
                        from_wallet = data["from"]
                        to_wallet = data["to"]

                        # Filter for exchange transactions only
                        if is_exchange_transaction(from_wallet, to_wallet):
                            print(f"📊 Exchange transaction detected:")
                            print(f"   From: {from_wallet}")
                            print(f"   To: {to_wallet}")
                            print(f"   Blockchain: {data['blockchain']}")

                            # Send to InfluxDB
                            send_to_influxdb(data)
                        else:
                            # Check if 'to' wallet is a potential new exchange
                            if to_wallet.lower() != "unknown wallet" and not any(
                                exchange.lower() in to_wallet.lower()
                                for exchange in KNOWN_EXCHANGES
                            ):
                                print(f"🔍 Potential new exchange detected:")
                                print(f"   TO: {to_wallet}")
                                print(f"   Blockchain: {data['blockchain']}")
                                print(
                                    f"   Value: ${sum(float(amt['value_usd']) for amt in data['amounts']):,.2f}"
                                )
                                print()
                            else:
                                print(f"⏭️  Filtered out: {from_wallet} → {to_wallet}")
                    else:
                        print(f"📩 Non-transaction message: {message}")

                except json.JSONDecodeError:
                    print(f"❌ Failed to parse JSON: {message}")

            except asyncio.TimeoutError:
                print("Timeout error, closing connection")
                break
            except websockets.ConnectionClosed:
                print("Connection closed")
                break


# Run the connect function until it completes
asyncio.run(connect())
