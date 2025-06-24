import os
import asyncio
import websockets
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, deque
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('whale_alerts.log')
    ]
)
logger = logging.getLogger(__name__)

# InfluxDB Configuration
WHALE_ALERT_KEY = os.environ["WHALE_ALERT_KEY"]
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUXDB_ORG = os.environ["INFLUXDB_ORG"]
INFLUXDB_BUCKET = os.environ["INFLUXDB_BUCKET"]

# Signal Detection Configuration
ROLLING_WINDOW_MINUTES = int(os.environ.get("ROLLING_WINDOW_MINUTES", "60"))
NET_FLOW_THRESHOLD_USD = int(os.environ.get("NET_FLOW_THRESHOLD_USD", "10000000"))
MM_TRANSFER_THRESHOLD_USD = int(os.environ.get("MM_TRANSFER_THRESHOLD_USD", "5000000"))
SIGNAL_CONFIDENCE_MAX_USD = int(os.environ.get("SIGNAL_CONFIDENCE_MAX_USD", "20000000"))

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


class TransactionCache:
    """In-memory cache for tracking recent transactions for signal detection"""
    
    def __init__(self, window_minutes: int = 60):
        self.window_minutes = window_minutes
        self.transactions = deque()
        self.net_flows: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        
    def add_transaction(self, transaction_data: dict):
        """Add a transaction to the cache"""
        timestamp = datetime.fromtimestamp(transaction_data["timestamp"])
        
        for amount_data in transaction_data["amounts"]:
            tx_record = {
                "timestamp": timestamp,
                "from_type": get_entity_type(transaction_data["from"]),
                "to_type": get_entity_type(transaction_data["to"]),
                "symbol": amount_data["symbol"],
                "value_usd": float(amount_data["value_usd"]),
                "blockchain": transaction_data["blockchain"],
                "from_entity": transaction_data["from"],
                "to_entity": transaction_data["to"]
            }
            self.transactions.append(tx_record)
        
        self._cleanup_old_transactions()
        self._update_net_flows()
    
    def _cleanup_old_transactions(self):
        """Remove transactions older than the rolling window"""
        cutoff_time = datetime.now() - timedelta(minutes=self.window_minutes)
        while self.transactions and self.transactions[0]["timestamp"] < cutoff_time:
            self.transactions.popleft()
    
    def _update_net_flows(self):
        """Update net flow calculations for all entity types and symbols"""
        self.net_flows.clear()
        
        for tx in self.transactions:
            from_type = tx["from_type"]
            to_type = tx["to_type"]
            symbol = tx["symbol"]
            value = tx["value_usd"]
            
            # Track outflows (negative) and inflows (positive) for each entity type
            if from_type in ["fiat_exchange", "usdt_exchange", "market_maker"]:
                key = f"{from_type}_{symbol}"
                self.net_flows[key]["outflow"] -= value
                
            if to_type in ["fiat_exchange", "usdt_exchange", "market_maker"]:
                key = f"{to_type}_{symbol}"
                self.net_flows[key]["inflow"] += value
    
    def get_net_flow(self, entity_type: str, symbol: str) -> float:
        """Get net flow (inflow - outflow) for entity type and symbol"""
        key = f"{entity_type}_{symbol}"
        flows = self.net_flows.get(key, {"inflow": 0, "outflow": 0})
        return flows["inflow"] + flows["outflow"]  # outflow is already negative
    
    def get_recent_mm_transfers(self, threshold_usd: float) -> List[dict]:
        """Get recent large transfers from market makers to exchanges"""
        mm_transfers = []
        
        for tx in self.transactions:
            if (tx["from_type"] == "market_maker" and 
                tx["to_type"] in ["fiat_exchange", "usdt_exchange"] and
                tx["value_usd"] >= threshold_usd):
                mm_transfers.append(tx)
        
        return mm_transfers


class SignalDetector:
    """Detects potential market movement signals based on fund flows"""
    
    def __init__(self, cache: TransactionCache):
        self.cache = cache
        self.last_signals: Dict[str, datetime] = {}
        self.signal_cooldown_minutes = 30  # Prevent duplicate signals
    
    def calculate_confidence(self, amount_usd: float, max_amount: float = SIGNAL_CONFIDENCE_MAX_USD) -> float:
        """Calculate confidence score from 0.0 to 1.0 based on amount"""
        return min(amount_usd / max_amount, 1.0)
    
    def detect_signals(self) -> List[dict]:
        """Detect all types of market signals"""
        signals = []
        
        # Detect bullish signals
        signals.extend(self._detect_bullish_signals())
        
        # Detect bearish signals  
        signals.extend(self._detect_bearish_signals())
        
        # Detect MM hedging signals
        signals.extend(self._detect_mm_hedging_signals())
        
        # Filter out signals that are too recent (cooldown)
        signals = self._apply_signal_cooldown(signals)
        
        return signals
    
    def _detect_bullish_signals(self) -> List[dict]:
        """Detect bullish market signals"""
        signals = []
        
        # Bullish Signal 1: Large BTC/USDT inflows to fiat exchanges
        for symbol in ["BTC", "USDT"]:
            net_flow = self.cache.get_net_flow("fiat_exchange", symbol)
            if abs(net_flow) >= NET_FLOW_THRESHOLD_USD and net_flow > 0:
                signals.append({
                    "type": "bullish",
                    "subtype": "fiat_inflow",
                    "entity_type": "fiat_exchange",
                    "symbol": symbol,
                    "amount_usd": net_flow,
                    "confidence": self.calculate_confidence(net_flow),
                    "timestamp": datetime.now(),
                    "description": f"Large {symbol} inflow to fiat exchanges indicating potential buying pressure"
                })
        
        # Bullish Signal 2: Large USDT inflows to USDT-based exchanges
        usdt_net_flow = self.cache.get_net_flow("usdt_exchange", "USDT")
        if abs(usdt_net_flow) >= NET_FLOW_THRESHOLD_USD and usdt_net_flow > 0:
            signals.append({
                "type": "bullish",
                "subtype": "usdt_exchange_inflow",
                "entity_type": "usdt_exchange",
                "symbol": "USDT",
                "amount_usd": usdt_net_flow,
                "confidence": self.calculate_confidence(usdt_net_flow),
                "timestamp": datetime.now(),
                "description": "Large USDT inflow to USDT exchanges preparing for trading activity"
            })
        
        return signals
    
    def _detect_bearish_signals(self) -> List[dict]:
        """Detect bearish market signals"""
        signals = []
        
        # Bearish Signal 1: Large BTC/USDT outflows from fiat exchanges
        for symbol in ["BTC", "USDT"]:
            net_flow = self.cache.get_net_flow("fiat_exchange", symbol)
            if abs(net_flow) >= NET_FLOW_THRESHOLD_USD and net_flow < 0:
                signals.append({
                    "type": "bearish",
                    "subtype": "fiat_outflow",
                    "entity_type": "fiat_exchange", 
                    "symbol": symbol,
                    "amount_usd": abs(net_flow),
                    "confidence": self.calculate_confidence(abs(net_flow)),
                    "timestamp": datetime.now(),
                    "description": f"Large {symbol} outflow from fiat exchanges indicating potential selling pressure"
                })
        
        # Bearish Signal 2: Large BTC inflows to USDT-based exchanges
        btc_net_flow = self.cache.get_net_flow("usdt_exchange", "BTC")
        if abs(btc_net_flow) >= NET_FLOW_THRESHOLD_USD and btc_net_flow > 0:
            signals.append({
                "type": "bearish",
                "subtype": "btc_exchange_inflow",
                "entity_type": "usdt_exchange",
                "symbol": "BTC",
                "amount_usd": btc_net_flow,
                "confidence": self.calculate_confidence(btc_net_flow),  
                "timestamp": datetime.now(),
                "description": "Large BTC inflow to USDT exchanges indicating potential selling pressure"
            })
        
        return signals
    
    def _detect_mm_hedging_signals(self) -> List[dict]:
        """Detect market maker hedging signals"""
        signals = []
        
        mm_transfers = self.cache.get_recent_mm_transfers(MM_TRANSFER_THRESHOLD_USD)
        
        # Group transfers by time window to detect coordinated moves
        recent_transfers = [tx for tx in mm_transfers 
                          if (datetime.now() - tx["timestamp"]).total_seconds() < 3600]  # Last hour
        
        if recent_transfers:
            total_value = sum(tx["value_usd"] for tx in recent_transfers)
            avg_confidence = self.calculate_confidence(total_value / len(recent_transfers))
            
            signals.append({
                "type": "mm_hedging",
                "subtype": "mm_to_exchange",
                "entity_type": "market_maker",
                "symbol": "mixed",
                "amount_usd": total_value,
                "confidence": avg_confidence,
                "timestamp": datetime.now(),
                "description": f"Large MM transfers to exchanges ({len(recent_transfers)} transfers) indicating hedging or liquidity provisioning"
            })
        
        return signals
    
    def _apply_signal_cooldown(self, signals: List[dict]) -> List[dict]:
        """Filter out signals that were recently detected to avoid spam"""
        filtered_signals = []
        current_time = datetime.now()
        
        for signal in signals:
            signal_key = f"{signal['type']}_{signal['entity_type']}_{signal['symbol']}"
            
            last_signal_time = self.last_signals.get(signal_key)
            if (not last_signal_time or 
                (current_time - last_signal_time).total_seconds() > self.signal_cooldown_minutes * 60):
                
                filtered_signals.append(signal)
                self.last_signals[signal_key] = current_time
        
        return filtered_signals


def get_entity_type(wallet):
    """Determine the entity type of a wallet"""
    wallet_lower = wallet.lower()

    # Use exact matching to avoid conflicts (e.g., "Coinbase" vs "Coinbase Institutional")
    for mm in KNOWN_MMS:
        if mm.lower() == wallet_lower:
            return "market_maker"

    for exchange in KNOWN_USDT_EXCHANGES:
        if exchange.lower() == wallet_lower:
            return "usdt_exchange"

    for exchange in KNOWN_FIAT_EXCHANGES:
        if exchange.lower() == wallet_lower:
            return "fiat_exchange"

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


async def send_to_influxdb(transaction_data, signals=None, net_flows=None):
    """Send meaningful flow data, market signals, and net flows to InfluxDB2"""
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

                    # Enhanced flow metrics with net flow tracking
                    flow_metric = (
                        Point("flow_metrics")
                        .tag("flow_direction", flow_direction)
                        .tag("blockchain", transaction_data["blockchain"])
                        .tag("symbol", amount_data["symbol"])
                        .tag("from_type", from_type)
                        .tag("to_type", to_type)
                        .field("volume_usd", float(amount_data["value_usd"]))
                        .field("transaction_count", 1)
                        .time(datetime.fromtimestamp(transaction_data["timestamp"]))
                    )
                    points.append(flow_metric)

                # Add real-time net flow data
                if net_flows:
                    timestamp = datetime.now()
                    for entity_symbol, flows in net_flows.items():
                        if '_' in entity_symbol:
                            entity_type, symbol = entity_symbol.split('_', 1)
                        else:
                            continue  # Skip malformed keys
                        net_flow_value = flows.get("inflow", 0) + flows.get("outflow", 0)  # outflow is negative
                        
                        # Only write net flows with significant activity
                        if abs(net_flow_value) > 100000:  # $100k threshold for net flow recording
                            net_flow_point = (
                                Point("net_flows")
                                .tag("entity_type", entity_type)
                                .tag("symbol", symbol)
                                .field("net_flow_usd", float(net_flow_value))
                                .field("inflow_usd", float(flows.get("inflow", 0)))
                                .field("outflow_usd", float(flows.get("outflow", 0)))
                                .field("window_minutes", ROLLING_WINDOW_MINUTES)
                                .time(timestamp)
                            )
                            points.append(net_flow_point)

                # Add market signal points if any
                if signals:
                    for signal in signals:
                        signal_point = (
                            Point("market_signals")
                            .tag("signal_type", signal["type"])
                            .tag("entity_type", signal["entity_type"])
                            .tag("symbol", signal["symbol"])
                            .tag("subtype", signal["subtype"])
                            .field("amount_usd", float(signal["amount_usd"]))
                            .field("confidence_score", float(signal["confidence"]))
                            .field("description", signal["description"])
                            .time(signal["timestamp"])
                        )
                        points.append(signal_point)

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
        logger.info(
            f"✓ Flow recorded: {flow_direction} | ${total_value:,.2f} | {points_written} points"
        )

    except Exception as e:
        logger.error(f"✗ Error sending to InfluxDB: {e}")


def format_signal_alert(signal: dict) -> str:
    """Format a market signal for console output"""
    signal_emoji = {
        "bullish": "🚀",
        "bearish": "🔻", 
        "mm_hedging": "⚖️"
    }
    
    emoji = signal_emoji.get(signal["type"], "📊")
    signal_type = signal["type"].upper()
    amount_formatted = f"${signal['amount_usd']:,.0f}"
    confidence_pct = f"{signal['confidence']*100:.0f}%"
    
    time_window_start = (signal["timestamp"] - timedelta(minutes=ROLLING_WINDOW_MINUTES)).strftime("%H:%M")
    time_window_end = signal["timestamp"].strftime("%H:%M")
    
    alert_msg = f"{emoji} {signal_type} Signal Detected: {signal['description']}\n"
    alert_msg += f"   Amount: {amount_formatted} | Confidence: {confidence_pct} | Time Window: {time_window_start} - {time_window_end}\n"
    alert_msg += f"   Entity: {signal['entity_type']} | Symbol: {signal['symbol']}"
    
    return alert_msg


async def write_periodic_net_flows(cache: TransactionCache):
    """Periodically write net flow data to InfluxDB for continuous monitoring"""
    while True:
        try:
            await asyncio.sleep(300)  # Write net flows every 5 minutes
            
            if cache.net_flows:
                # Create a mock transaction data structure for the InfluxDB write
                mock_transaction = {
                    "from": "periodic_update",
                    "to": "periodic_update", 
                    "blockchain": "system",
                    "timestamp": datetime.now().timestamp(),
                    "amounts": [{"symbol": "SYSTEM", "amount": "0", "value_usd": "0"}],
                    "transaction": {"hash": f"periodic_{int(datetime.now().timestamp())}"},
                    "transaction_type": "periodic_update"
                }
                
                # Write only net flows (no signals)
                await send_to_influxdb(
                    mock_transaction,
                    None,  # No signals
                    dict(cache.net_flows)  # Current net flows
                )
                
                logger.info(f"📊 Periodic net flows written: {len(cache.net_flows)} entity-symbol pairs")
                
        except Exception as e:
            logger.error(f"❌ Error in periodic net flow write: {e}")


async def connect():
    """Main WebSocket connection with enhanced signal detection"""
    # Initialize signal detection components
    transaction_cache = TransactionCache(window_minutes=ROLLING_WINDOW_MINUTES)
    signal_detector = SignalDetector(transaction_cache)
    
    logger.info("🚀 Starting Whale Alert with Market Signal Detection")
    logger.info(f"📊 Configuration: Window={ROLLING_WINDOW_MINUTES}min, Threshold=${NET_FLOW_THRESHOLD_USD:,}, MM Threshold=${MM_TRANSFER_THRESHOLD_USD:,}")
    
    # Start periodic net flow writing task
    periodic_task = asyncio.create_task(write_periodic_net_flows(transaction_cache))
    logger.info("📈 Started periodic net flow monitoring (5-minute intervals)")
    
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
    
    while retry_count < max_retries:
        try:
            # Connect to the WebSocket server
            async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                # Send the subscription message
                await ws.send(json.dumps(subscription_msg))

                # Wait for a response
                response = await ws.recv()
                logger.info(f"📡 Connected: {response}")
                retry_count = 0  # Reset retry count on successful connection

                # Continue to handle incoming messages
                while True:
                    try:
                        # Wait for a new message
                        message = await asyncio.wait_for(ws.recv(), timeout=60)

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

                                    logger.info(f"💰 Flow detected: {flow_direction}")
                                    logger.info(f"   From: {from_wallet} ({from_type})")
                                    logger.info(f"   To: {to_wallet} ({to_type})")
                                    logger.info(f"   Blockchain: {data['blockchain']}")

                                    # Add transaction to cache for signal detection
                                    transaction_cache.add_transaction(data)
                                    
                                    # Detect market signals
                                    signals = signal_detector.detect_signals()
                                    
                                    # Log any detected signals
                                    for signal in signals:
                                        alert_msg = format_signal_alert(signal)
                                        logger.warning(alert_msg)  # Use warning level for signal alerts
                                        print(alert_msg)  # Also print to console for immediate visibility

                                    # Send to InfluxDB (including signals and net flows)
                                    await send_to_influxdb(
                                        data, 
                                        signals if signals else None,
                                        dict(transaction_cache.net_flows) if transaction_cache.net_flows else None
                                    )
                                    
                                else:
                                    # Check if 'to' wallet is a potential new entity to track
                                    all_known = (
                                        KNOWN_USDT_EXCHANGES + KNOWN_FIAT_EXCHANGES + KNOWN_MMS
                                    )
                                    if to_wallet.lower() != "unknown wallet" and not any(
                                        entity.lower() in to_wallet.lower()
                                        for entity in all_known
                                    ):
                                        total_value = sum(float(amt['value_usd']) for amt in data['amounts'])
                                        logger.info(f"🔍 Potential new entity detected:")
                                        logger.info(f"   TO: {to_wallet}")
                                        logger.info(f"   Blockchain: {data['blockchain']}")
                                        logger.info(f"   Value: ${total_value:,.2f}")
                                    else:
                                        logger.debug(f"⏭️  Filtered out: {from_wallet} → {to_wallet}")
                            else:
                                logger.debug(f"📩 Non-transaction message: {message}")

                        except json.JSONDecodeError:
                            logger.error(f"❌ Failed to parse JSON: {message}")

                    except asyncio.TimeoutError:
                        logger.warning("⏰ WebSocket timeout - sending ping")
                        try:
                            await ws.ping()
                        except websockets.ConnectionClosed:
                            logger.error("Connection closed during ping")
                            break
                    except websockets.ConnectionClosed:
                        logger.error("🔌 Connection closed")
                        break
                        
        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            retry_count += 1
            wait_time = min(30, 5 * retry_count)  # Exponential backoff, max 30s
            logger.error(f"🔄 Connection failed (attempt {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                logger.info(f"⏳ Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("🚨 Max retries exceeded. Exiting.")
                break
        except Exception as e:
            logger.error(f"💥 Unexpected error: {e}")
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(10)
            else:
                break
    
    # Cancel the periodic task when exiting
    if not periodic_task.done():
        periodic_task.cancel()
        try:
            await periodic_task
        except asyncio.CancelledError:
            logger.info("📈 Periodic net flow monitoring stopped")


if __name__ == "__main__":
    try:
        # Run the connect function until it completes
        asyncio.run(connect())
    except KeyboardInterrupt:
        logger.info("🛑 Application stopped by user")
    except Exception as e:
        logger.error(f"💥 Application crashed: {e}")
        raise
