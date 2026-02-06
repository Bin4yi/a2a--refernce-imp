"""
Log broadcaster for visualizer.
Sends log messages to the WebSocket server for the frontend.
"""

import httpx
import asyncio
from typing import Optional

VISUALIZER_URL = "http://localhost:8200/log"

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=2.0)
    return _client


async def broadcast_log(message: str):
    """Send a log message to the visualizer server."""
    try:
        client = get_client()
        await client.post(VISUALIZER_URL, json={"message": message})
    except Exception:
        # Silently ignore if visualizer is not running
        pass


def broadcast_log_sync(message: str):
    """Synchronous wrapper for broadcasting logs."""
    try:
        with httpx.Client(timeout=1.0) as client:
            client.post(VISUALIZER_URL, json={"message": message})
    except Exception:
        pass


# Simple print wrapper that also broadcasts
def log_and_broadcast(message: str):
    """Print message and also send to visualizer."""
    print(message)
    broadcast_log_sync(message)
