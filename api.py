# ============================================================
# api.py — SoDEX REST API wrapper
# ============================================================
import logging
import requests
from config import BASE_URL, WALLET_ADDRESS, TESTNET_CHAIN_ID
from signer import make_headers

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

def place_order(account_id: int, symbol_id: int,
                clord_id: str, side: int, order_type: int,
                time_in_force: int, price: str = None,
                quantity: str = None) -> dict:
    """
    Place single spot order.
    Sesuai docs: POST /trade/orders
    Field order: accountID, symbolID, clOrdID, side, type, timeInForce, price, quantity
    timeInForce tidak diperlukan untuk market order (type=2).
    """
    params = {
        "accountID": account_id,
        "symbolID":  symbol_id,
        "clOrdID":   clord_id,
        "side":      side,
        "type":      order_type,
    }
    if time_in_force is not None:  # selalu ada
        params["timeInForce"] = time_in_force
    if price is not None:
        params["price"] = price
    if quantity is not None:
        params["quantity"] = quantity

    headers, _ = make_headers("newOrder", params)
    try:
        r = requests.post(
            f"{BASE_URL}/trade/orders",
            headers=headers,
            json=params,
            timeout=15
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", {})
        log.warning(f"place_order gagal: {d.get('error')} | {r.text[:200]}")
    except Exception as e:
        log.error(f"place_order: {e}")
    return {}


def cancel_order(account_id: int, symbol_id: int,
                 clord_id: str, order_id: int = None) -> dict:
    """
    Cancel single spot order.
    Sesuai docs: DELETE /trade/orders
    Field order: accountID, symbolID, clOrdID, orderID
    """
    params = {
        "accountID": account_id,
        "symbolID":  symbol_id,
        "clOrdID":   clord_id,
    }
    if order_id:
        params["orderID"] = order_id

    headers, _ = make_headers("cancelOrder", params)
    try:
        r = requests.delete(
            f"{BASE_URL}/trade/orders",
            headers=headers,
            json=params,
            timeout=15
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", {})
        log.warning(f"cancel_order gagal: {d.get('error')}")
    except Exception as e:
        log.error(f"cancel_order: {e}")
    return {}
