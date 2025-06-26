import os
import asyncio
import websockets
import json
import signal
from datetime import datetime
from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Global shutdown flag
shutdown_event = asyncio.Event()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    print(f"\n🛑 Received signal {signum}, initiating graceful shutdown...")
    # Get the current event loop and set the shutdown event
    try:
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(shutdown_event.set)
    except RuntimeError:
        # Fallback if no event loop is running
        shutdown_event.set()

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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
        async with InfluxDBClientAsync(
            url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
        ) as client:
            write_api = client.write_api()

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
            await write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=points)
            points_written = len(points)

        total_value = sum(
            float(amt["value_usd"]) for amt in transaction_data["amounts"]
        )
        print(
            f"✓ Flow recorded: {flow_direction} | ${total_value:,.2f} | {points_written} points"
        )

    except Exception as e:
        print(f"✗ Error sending to InfluxDB: {e}")


async def connect():
    """WebSocket connection with proper lifecycle management"""
    print("🚀 Starting Whale Alert Monitor")
    print(f"📊 Tracking: {SYMBOLS} on {BLOCKCHAINS}")
    print(f"💰 Min Value: ${MIN_VALUE_USD:,}")
    
    # The WebSocket API URL with the API key included
    url = f"wss://leviathan.whale-alert.io/ws?api_key={WHALE_ALERT_KEY}"

    # The subscription message
    subscription_msg = {
        "type": "subscribe_alerts",
        "blockchains": BLOCKCHAINS,
        "symbols": SYMBOLS,
        "min_value_usd": MIN_VALUE_USD,
    }

    retry_count = 0
    max_retries = 5
    
    while retry_count < max_retries and not shutdown_event.is_set():
        try:
            print(f"🔌 Connecting to Whale Alert WebSocket... (attempt {retry_count + 1})")
            
            # Connect with ping settings for keepalive
            async with websockets.connect(
                url, 
                ping_interval=30,  # Send ping every 30 seconds
                ping_timeout=10,   # Wait 10 seconds for pong
                close_timeout=10   # Wait 10 seconds when closing
            ) as ws:
                print("✅ WebSocket connected successfully")
                
                # Send the subscription message
                await ws.send(json.dumps(subscription_msg))
                print("📡 Subscription message sent")

                # Wait for a response with timeout
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    print(f"📨 Subscription confirmed: {response}")
                except asyncio.TimeoutError:
                    print("⚠️ Subscription confirmation timeout")
                    continue
                
                # Reset retry count on successful connection
                retry_count = 0

                # Main message loop
                while not shutdown_event.is_set():
                    try:
                        # Wait for a new message with shorter timeout for faster shutdown
                        message = await asyncio.wait_for(ws.recv(), timeout=5.0)

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
                                print(f"📩 Non-transaction message received")

                        except json.JSONDecodeError:
                            print(f"❌ Failed to parse JSON: {message}")

                    except asyncio.TimeoutError:
                        # Check shutdown before sending ping
                        if shutdown_event.is_set():
                            print("🛑 Shutdown requested during timeout")
                            break
                        
                        # Send ping to keep connection alive
                        print("⏰ Message timeout - sending ping to keep connection alive")
                        try:
                            await ws.ping()
                            print("🏓 Ping sent successfully")
                        except websockets.ConnectionClosed:
                            print("❌ Connection closed during ping")
                            break
                        except Exception as e:
                            print(f"❌ Error sending ping: {e}")
                            break
                    
                    except websockets.ConnectionClosed:
                        print("🔌 WebSocket connection closed by server")
                        break
                    
                    except Exception as e:
                        print(f"❌ Unexpected error in message loop: {e}")
                        break

                # Clean connection close
                if not ws.closed:
                    print("🔄 Closing WebSocket connection gracefully...")
                    await ws.close()

        except websockets.InvalidStatusCode as e:
            retry_count += 1
            wait_time = min(30, 5 * retry_count)  # Exponential backoff, max 30s
            print(f"❌ WebSocket connection failed with status {e.status_code}")
            if retry_count < max_retries and not shutdown_event.is_set():
                print(f"⏳ Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            retry_count += 1
            wait_time = min(30, 5 * retry_count)  # Exponential backoff, max 30s
            print(f"❌ Connection failed: {e}")
            if retry_count < max_retries and not shutdown_event.is_set():
                print(f"⏳ Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                
        except Exception as e:
            retry_count += 1
            print(f"💥 Unexpected error: {e}")
            if retry_count < max_retries and not shutdown_event.is_set():
                await asyncio.sleep(10)

    if shutdown_event.is_set():
        print("🛑 Shutdown requested - exiting gracefully")
    else:
        print("🚨 Max retries exceeded - giving up")


async def main():
    """Main function with proper async lifecycle"""
    try:
        # Create a task that can be cancelled
        connect_task = asyncio.create_task(connect())
        
        # Wait for either the task to complete or shutdown event
        while not shutdown_event.is_set() and not connect_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(connect_task), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"💥 Connection error: {e}")
                break
        
        # Cancel the task if shutdown was requested
        if not connect_task.done():
            connect_task.cancel()
            try:
                await connect_task
            except asyncio.CancelledError:
                pass
                
    except KeyboardInterrupt:
        print("🛑 KeyboardInterrupt received in main")
        shutdown_event.set()
    except Exception as e:
        print(f"💥 Application crashed: {e}")
        shutdown_event.set()
    finally:
        print("🏁 Application shutdown complete")

if __name__ == "__main__":
    try:
        # Run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        raise
