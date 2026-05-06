# ============================================================
# signer.py — EIP-712 signing untuk SoDEX
# Sesuai dokumentasi resmi: https://sodex.com/documentation/api/api
#
# PENTING dari docs:
# - Signing payload = {"type": "...", "params": {...}}
# - HTTP body       = hanya params saja (tanpa wrapper type/params)
# - Wire format     = 0x01 + sig_bytes (65 bytes) = total 66 bytes
# - Key order harus match Go struct field order
# ============================================================
import json
import time
from web3 import Web3
from eth_account import Account
from config import PRIVATE_KEY, TESTNET_CHAIN_ID, API_KEY_NAME


# ── Field order sesuai Go struct SoDEX ───────────────────────
# Spot NewOrderRequest: accountID, symbolID, clOrdID, modifier,
#                       side, type, timeInForce, price, quantity
# Spot BatchNewOrderRequest: accountID, symbolID, orders[]
# Spot BatchNewOrderItem: clOrdID, modifier, side, type,
#                         timeInForce, price, quantity
# Spot CancelOrderRequest: accountID, symbolID, clOrdID

NEW_ORDER_KEYS    = ["clOrdID", "modifier", "side", "type",
                     "timeInForce", "price", "quantity"]
CANCEL_ORDER_KEYS = ["clOrdID"]


def _make_new_order_params(account_id: int, symbol_id: int,
                           orders: list) -> dict:
    """
    Susun params BatchNewOrderRequest sesuai Go struct field order.
    symbolID ada di level batch (bukan di tiap order item).
    """
    ordered_orders = []
    for order in orders:
        item = {}
        for key in NEW_ORDER_KEYS:
            if key in order:
                item[key] = order[key]
        ordered_orders.append(item)

    return {
        "accountID": account_id,
        "symbolID":  symbol_id,
        "orders":    ordered_orders,
    }


def _make_cancel_params(account_id: int, symbol_id: int,
                        orders: list) -> dict:
    """Susun params BatchCancelOrderRequest sesuai Go struct."""
    ordered_orders = []
    for order in orders:
        item = {}
        for key in CANCEL_ORDER_KEYS:
            if key in order:
                item[key] = order[key]
        ordered_orders.append(item)

    return {
        "accountID": account_id,
        "symbolID":  symbol_id,
        "orders":    ordered_orders,
    }


def _compute_signature(action_type: str, params: dict, nonce: int) -> str:
    """
    Hitung EIP-712 signature sesuai docs SoDEX.

    1. signing_payload = {"type": action_type, "params": params}
    2. payloadHash = Keccak256(compact JSON of signing_payload)
    3. digest = EIP-712 hash(domain, ExchangeAction{payloadHash, nonce})
    4. sig = unsafe_sign_hash(digest)
    5. return 0x01 + sig.signature (65 bytes)
    """
    # Step 1 & 2: payloadHash
    signing_payload = {"type": action_type, "params": params}
    payload_json    = json.dumps(signing_payload, separators=(",", ":"))
    payload_hash    = Web3.keccak(payload_json.encode("utf-8"))

    # Step 3: EIP-712 domain separator
    domain_type_hash = Web3.keccak(
        text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    domain_sep = Web3.solidity_keccak(
        ["bytes32", "bytes32", "bytes32", "uint256", "address"],
        [
            domain_type_hash,
            Web3.keccak(text="spot"),
            Web3.keccak(text="1"),
            TESTNET_CHAIN_ID,
            "0x0000000000000000000000000000000000000000",
        ]
    )

    # Step 3: message hash
    action_type_hash = Web3.keccak(
        text="ExchangeAction(bytes32 payloadHash,uint64 nonce)"
    )
    msg_hash = Web3.solidity_keccak(
        ["bytes32", "bytes32", "uint64"],
        [action_type_hash, payload_hash, nonce]
    )

    # Step 3: final digest
    digest = Web3.keccak(b"\x19\x01" + domain_sep + msg_hash)

    # Step 4: sign
    account = Account.from_key(PRIVATE_KEY)
    sig     = account.unsafe_sign_hash(digest)

    # Step 5: typed signature = 0x01 + sig bytes (65 bytes)
    # sig.signature sudah berisi r+s+v dalam format standar (65 bytes)
    return "0x01" + sig.signature.hex()


def sign_new_order(account_id: int, symbol_id: int,
                   orders: list) -> tuple:
    """
    Sign new order request.
    Return: (http_body, headers)
    - http_body: params saja (tanpa wrapper type/params)
    - headers: berisi X-API-Key, X-API-Sign, X-API-Nonce
    """
    nonce  = int(time.time() * 1000)
    params = _make_new_order_params(account_id, symbol_id, orders)
    sig    = _compute_signature("newOrder", params, nonce)

    headers = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-API-Key":    API_KEY_NAME,
        "X-API-Sign":   sig,
        "X-API-Nonce":  str(nonce),
    }
    return params, headers


def sign_cancel_order(account_id: int, symbol_id: int,
                      orders: list) -> tuple:
    """
    Sign cancel order request.
    Return: (http_body, headers)
    """
    nonce  = int(time.time() * 1000)
    params = _make_cancel_params(account_id, symbol_id, orders)
    sig    = _compute_signature("cancelOrder", params, nonce)

    headers = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-API-Key":    API_KEY_NAME,
        "X-API-Sign":   sig,
        "X-API-Nonce":  str(nonce),
    }
    return params, headers
