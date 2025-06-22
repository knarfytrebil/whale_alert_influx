import os
import asyncio
import websockets
import json

WHALE_ALERT_KEY = os.environ["WHALE_ALERT_KEY"]


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
                message = await asyncio.wait_for(
                    ws.recv(), timeout=None
                )  # 20 seconds timeout
                print(f"Received: {message}")
            except asyncio.TimeoutError:
                print("Timeout error, closing connection")
                break
            except websockets.ConnectionClosed:
                print("Connection closed")
                break


# Run the connect function until it completes
asyncio.run(connect())
