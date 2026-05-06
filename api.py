# ============================================================
# api.py — SoDEX REST API wrapper
# ============================================================
import logging
import requests
from config import BASE_URL, WALLET_ADDRESS
from signer import signed_headers

log            = logging.getLogger(__name__)
PUBLIC_HEADERS = {"Accept": "application/json"}


# ── Market Data ───────────────────────────────────────────────

def get_symbols() -> list:
    """Ambil semua symbol trading yang tersedia."""
    try:
        r = requests.get(
            f"{BASE_URL}/markets/symbols",
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
    except Exception as e:
        log.error(f"get_symbols: {e}")
    return []


def get_orderbook(symbol: str, limit: int = 5) -> dict:
    """Ambil orderbook untuk menentukan harga limit order."""
    try:
        r = requests.get(
            f"{BASE_URL}/markets/{symbol}/orderbook",
            params={"limit": limit},
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data")
    except Exception as e:
        log.error(f"get_orderbook {symbol}: {e}")
    return None


def get_tickers(symbol: str = None) -> list:
    """Ambil data ticker 24h."""
    try:
        params = {"symbol": symbol} if symbol else {}
        r = requests.get(
            f"{BASE_URL}/markets/tickers",
            params=params,
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
    except Exception as e:
        log.error(f"get_tickers: {e}")
    return []


# ── Account ───────────────────────────────────────────────────

def get_balances() -> dict:
    """Ambil saldo spot akun."""
    try:
        r = requests.get(
            f"{BASE_URL}/accounts/{WALLET_ADDRESS}/balances",
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data")
    except Exception as e:
        log.error(f"get_balances: {e}")
    return None


def get_open_orders(symbol: str = None) -> list:
    """Ambil semua open order, opsional filter per symbol."""
    try:
        params = {"symbol": symbol} if symbol else {}
        r = requests.get(
            f"{BASE_URL}/accounts/{WALLET_ADDRESS}/orders",
            params=params,
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", {}).get("orders", [])
    except Exception as e:
        log.error(f"get_open_orders: {e}")
    return []


# ── Trading ───────────────────────────────────────────────────

def place_batch_orders(orders_payload: dict) -> list:
    """
    Place batch orders (max 100 per request).
    orders_payload: {
        "accountID": 0,
        "symbolID": X,
        "orders": [{ clOrdID, modifier, side, type, timeInForce, price, quantity }]
    }
    """
    sign_payload = {"type": "newOrder", "params": orders_payload}
    headers = signed_headers(sign_payload)
    try:
        r = requests.post(
            f"{BASE_URL}/trade/orders/batch",
            headers=headers,
            json=orders_payload,
            timeout=15
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
        log.warning(f"place_batch_orders gagal: {d.get('error')}")
    except Exception as e:
        log.error(f"place_batch_orders: {e}")
    return []


def cancel_batch_orders(cancel_payload: dict) -> list:
    """
    Cancel batch orders.
    cancel_payload: {
        "accountID": 0,
        "symbolID": X,
        "orders": [{ "clOrdID": "..." }]
    }
    """
    sign_payload = {"type": "cancelOrder", "params": cancel_payload}
    headers = signed_headers(sign_payload)
    try:
        r = requests.delete(
            f"{BASE_URL}/trade/orders/batch",
            headers=headers,
            json=cancel_payload,
            timeout=15
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
        log.warning(f"cancel_batch_orders gagal: {d.get('error')}")
    except Exception as e:
        log.error(f"cancel_batch_orders: {e}")
    return []
