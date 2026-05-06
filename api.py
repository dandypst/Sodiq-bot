# ============================================================
# api.py — SoDEX REST API wrapper
# ============================================================
import logging
import requests
from config import BASE_URL, WALLET_ADDRESS
from signer import sign_new_order, sign_cancel_order

log            = logging.getLogger(__name__)
PUBLIC_HEADERS = {"Accept": "application/json"}


# ── Market Data ───────────────────────────────────────────────

def get_symbols() -> list:
    try:
        r = requests.get(f"{BASE_URL}/markets/symbols",
                         headers=PUBLIC_HEADERS, timeout=10)
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
    except Exception as e:
        log.error(f"get_symbols: {e}")
    return []


def get_orderbook(symbol: str, limit: int = 5) -> dict:
    try:
        r = requests.get(f"{BASE_URL}/markets/{symbol}/orderbook",
                         params={"limit": limit},
                         headers=PUBLIC_HEADERS, timeout=10)
        d = r.json()
        if d.get("code") == 0:
            return d.get("data")
    except Exception as e:
        log.error(f"get_orderbook {symbol}: {e}")
    return None


def get_tickers(symbol: str = None) -> list:
    try:
        params = {"symbol": symbol} if symbol else {}
        r = requests.get(f"{BASE_URL}/markets/tickers",
                         params=params, headers=PUBLIC_HEADERS, timeout=10)
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
    except Exception as e:
        log.error(f"get_tickers: {e}")
    return []


# ── Account ───────────────────────────────────────────────────

def get_account_state() -> dict:
    try:
        r = requests.get(f"{BASE_URL}/accounts/{WALLET_ADDRESS}/state",
                         headers=PUBLIC_HEADERS, timeout=10)
        d = r.json()
        if d.get("code") == 0:
            return d.get("data")
    except Exception as e:
        log.error(f"get_account_state: {e}")
    return None


def get_account_id() -> int:
    state = get_account_state()
    if not state:
        return None
    if isinstance(state, dict):
        for field in ["aid", "accountID", "account_id", "id", "accountId", "uid"]:
            if field in state and state[field] and int(state[field]) > 0:
                return int(state[field])
    if isinstance(state, list) and state:
        first = state[0]
        for field in ["aid", "accountID", "account_id", "id", "accountId", "uid"]:
            if field in first and first[field] and int(first[field]) > 0:
                return int(first[field])
    log.warning(f"accountID tidak ditemukan. State: {state}")
    return None


def get_balances() -> dict:
    try:
        r = requests.get(f"{BASE_URL}/accounts/{WALLET_ADDRESS}/balances",
                         headers=PUBLIC_HEADERS, timeout=10)
        d = r.json()
        if d.get("code") == 0:
            return d.get("data")
    except Exception as e:
        log.error(f"get_balances: {e}")
    return None


def get_open_orders(symbol: str = None) -> list:
    try:
        params = {"symbol": symbol} if symbol else {}
        r = requests.get(f"{BASE_URL}/accounts/{WALLET_ADDRESS}/orders",
                         params=params, headers=PUBLIC_HEADERS, timeout=10)
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", {}).get("orders", [])
    except Exception as e:
        log.error(f"get_open_orders: {e}")
    return []


# ── Trading ───────────────────────────────────────────────────

def place_batch_orders(account_id: int, symbol_id: int,
                       orders: list) -> list:
    """
    Place batch orders.
    Sesuai docs:
    - symbolID ada di level batch (bukan di tiap order item)
    - HTTP body = params saja (tanpa wrapper type/params)
    - Signing tetap pakai payload penuh {"type": "newOrder", "params": ...}

    orders: list of dict dengan keys (sesuai Go struct order):
      clOrdID, modifier, side, type, timeInForce, price, quantity
    """
    body, headers = sign_new_order(account_id, symbol_id, orders)
    try:
        r = requests.post(
            f"{BASE_URL}/trade/orders/batch",
            headers=headers,
            json=body,
            timeout=15
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
        log.warning(f"place_batch_orders gagal: {d.get('error')} | raw: {r.text[:200]}")
    except Exception as e:
        log.error(f"place_batch_orders: {e}")
    return []


def cancel_batch_orders(account_id: int, symbol_id: int,
                        clord_ids: list) -> list:
    """
    Cancel batch orders.
    clord_ids: list of clOrdID string yang mau di-cancel
    """
    orders = [{"clOrdID": oid} for oid in clord_ids]
    body, headers = sign_cancel_order(account_id, symbol_id, orders)
    try:
        r = requests.delete(
            f"{BASE_URL}/trade/orders/batch",
            headers=headers,
            json=body,
            timeout=15
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
        log.warning(f"cancel_batch_orders gagal: {d.get('error')}")
    except Exception as e:
        log.error(f"cancel_batch_orders: {e}")
    return []
