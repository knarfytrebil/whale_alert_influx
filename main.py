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

# Whale Alert subscription configuration
BLOCKCHAINS = os.environ.get("WHALE_ALERT_BLOCKCHAINS", "bitcoin,ethereum,tron").split(
    ","
)
SYMBOLS = os.environ.get("WHALE_ALERT_SYMBOLS", "BTC,USDT").split(",")
MIN_VALUE_USD = int(os.environ.get("WHALE_ALERT_MIN_VALUE_USD", "1000000"))

# Known exchanges to filter for
KNOWN_USDT_EXCHANGES = [
    "Binance",
    "OKEX",
    "HTX",
    "Bitfinex",
    "OKX",
    "BitGet",
    "Bybit",
    "KuCoin",
    "Huobi",
    "Gate.io",
    "Upbit",
    "CryptoCom",
    "EezyCash",
    "GateIO",
    "Coinone",
    "HitBTC",
    "ChangeNow",
]

KNOWN_FIAT_EXCHANGES = ["Kraken", "Coinbase", "Bitvavo"]

KNOWN_MMS = [
    "MatrixPort",
    "Aave",
    "Ceffu",
    "Galaxy Digital",
    "Copper",
    "FalconX",
    "Coinbase Institutional",
    "B2C2",
]


def get_entity_type(wallet):
    """Determine the entity type of a wallet"""
    wallet_lower = wallet.lower()

    for exchange in KNOWN_USDT_EXCHANGES:
        if exchange.lower() in wallet_lower:
            return "usdt_exchange"

    for exchange in KNOWN_FIAT_EXCHANGES:
        if exchange.lower() in wallet_lower:
            return "fiat_exchange"

    for mm in KNOWN_MMS:
        if mm.lower() in wallet_lower:
            return "market_maker"

    if wallet_lower == "unknown wallet":
        return "unknown"

    return "other"


def is_relevant_transaction(from_wallet, to_wallet):
    """Check if transaction involves known entities"""
    from_type = get_entity_type(from_wallet)
    to_type = get_entity_type(to_wallet)

    # Only process transactions involving our tracked entity types
    return from_type in [
        "usdt_exchange",
        "fiat_exchange",
        "market_maker",
    ] or to_type in ["usdt_exchange", "fiat_exchange", "market_maker"]


def get_flow_direction(from_wallet, to_wallet):
    """Determine the money flow direction between entity types"""
    from_type = get_entity_type(from_wallet)
    to_type = get_entity_type(to_wallet)

    # Create flow direction string
    if from_type == "unknown" and to_type != "unknown":
        return f"inflow_to_{to_type}"
    elif from_type != "unknown" and to_type == "unknown":
        return f"outflow_from_{from_type}"
    elif from_type != "unknown" and to_type != "unknown":
        return f"{from_type}_to_{to_type}"
    else:
        return "unknown_flow"


async def send_to_influxdb(transaction_data):
    """Send meaningful flow data to InfluxDB2"""
    try:
        # Run the synchronous InfluxDB operation in a thread pool
        import asyncio

        def _write_sync():
            with InfluxDBClient(
                url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
            ) as client:
                write_api = client.write_api(write_options=SYNCHRONOUS)

                from_wallet = transaction_data["from"]
                to_wallet = transaction_data["to"]
                from_type = get_entity_type(from_wallet)
                to_type = get_entity_type(to_wallet)
                flow_direction = get_flow_direction(from_wallet, to_wallet)

                points = []

                # Create flow analysis points for each amount
                for amount_data in transaction_data["amounts"]:
                    # Main transaction record
                    point = (
                        Point("whale_flows")
                        .tag("blockchain", transaction_data["blockchain"])
                        .tag("symbol", amount_data["symbol"])
                        .tag("from_entity", from_wallet)
                        .tag("to_entity", to_wallet)
                        .tag("from_type", from_type)
                        .tag("to_type", to_type)
                        .tag("flow_direction", flow_direction)
                        .tag("transaction_type", transaction_data["transaction_type"])
                        .field("amount", float(amount_data["amount"]))
                        .field("value_usd", float(amount_data["value_usd"]))
                        .field(
                            "transaction_hash", transaction_data["transaction"]["hash"]
                        )
                        .time(datetime.fromtimestamp(transaction_data["timestamp"]))
                    )
                    points.append(point)

                    # Aggregated flow metrics by direction
                    flow_metric = (
                        Point("flow_metrics")
                        .tag("flow_direction", flow_direction)
                        .tag("blockchain", transaction_data["blockchain"])
                        .tag("symbol", amount_data["symbol"])
                        .field("volume_usd", float(amount_data["value_usd"]))
                        .field("transaction_count", 1)
                        .time(datetime.fromtimestamp(transaction_data["timestamp"]))
                    )
                    points.append(flow_metric)

                # Write all points at once
                write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=points)
                return len(points)

        # Execute the synchronous operation in a thread pool
        loop = asyncio.get_event_loop()
        points_written = await loop.run_in_executor(None, _write_sync)

        from_type = get_entity_type(transaction_data["from"])
        to_type = get_entity_type(transaction_data["to"])
        flow_direction = get_flow_direction(
            transaction_data["from"], transaction_data["to"]
        )

        total_value = sum(
            float(amt["value_usd"]) for amt in transaction_data["amounts"]
        )
        print(
            f"✓ Flow recorded: {flow_direction} | ${total_value:,.2f} | {points_written} points"
        )

    except Exception as e:
        print(f"✗ Error sending to InfluxDB: {e}")


async def connect():
    # The WebSocket API URL with the API key included
    url = f"wss://leviathan.whale-alert.io/ws?api_key={WHALE_ALERT_KEY}"

    # The subscription message
    subscription_msg = {
        "type": "subscribe_alerts",
        "blockchains": BLOCKCHAINS,
        "symbols": SYMBOLS,
        "min_value_usd": MIN_VALUE_USD,
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

                        # Filter for relevant transactions involving tracked entities
                        if is_relevant_transaction(from_wallet, to_wallet):
                            from_type = get_entity_type(from_wallet)
                            to_type = get_entity_type(to_wallet)
                            flow_direction = get_flow_direction(from_wallet, to_wallet)

                            print(f"💰 Flow detected: {flow_direction}")
                            print(f"   From: {from_wallet} ({from_type})")
                            print(f"   To: {to_wallet} ({to_type})")
                            print(f"   Blockchain: {data['blockchain']}")

                            # Send to InfluxDB
                            await send_to_influxdb(data)
                        else:
                            # Check if 'to' wallet is a potential new entity to track
                            all_known = (
                                KNOWN_USDT_EXCHANGES + KNOWN_FIAT_EXCHANGES + KNOWN_MMS
                            )
                            if to_wallet.lower() != "unknown wallet" and not any(
                                entity.lower() in to_wallet.lower()
                                for entity in all_known
                            ):
                                print(f"🔍 Potential new entity detected:")
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
