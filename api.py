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

def get_account_state() -> dict:
    """Ambil state akun lengkap — termasuk accountID yang benar."""
    try:
        r = requests.get(
            f"{BASE_URL}/accounts/{WALLET_ADDRESS}/state",
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data")
    except Exception as e:
        log.error(f"get_account_state: {e}")
    return None


def get_account_id() -> int:
    """
    Fetch accountID yang benar dari API.
    API SoDEX tidak menerima accountID=0 — harus pakai ID asli dari akun.
    """
    state = get_account_state()
    if not state:
        return None

    # Coba beberapa kemungkinan field name
    for field in ["accountID", "account_id", "id", "accountId"]:
        if field in state:
            return int(state[field])

    # Kalau state adalah list (multiple accounts), ambil yang pertama
    if isinstance(state, list) and state:
        first = state[0]
        for field in ["accountID", "account_id", "id", "accountId"]:
            if field in first:
                return int(first[field])

    log.warning(f"accountID tidak ditemukan di state. Keys: {list(state.keys()) if isinstance(state, dict) else type(state)}")
    return None


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
    """Ambil semua open order."""
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
    """Place batch orders."""
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
    """Cancel batch orders."""
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
