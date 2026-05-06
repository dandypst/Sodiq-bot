# ============================================================
# signer.py — EIP-712 signing untuk SoDEX
# Sesuai dokumentasi resmi: https://sodex.com/documentation/api/api
#
# Wire format signature (66 bytes):
#   [0x01][r (32 bytes)][s (32 bytes)][v (1 byte)]
#
# payloadHash = Keccak256(JSON dengan key order sesuai Go struct)
# ============================================================
import json
import time
from web3 import Web3
from eth_account import Account
from config import PRIVATE_KEY, WALLET_ADDRESS, TESTNET_CHAIN_ID, API_KEY_NAME


def build_payload_json(action_type: str, params: dict) -> str:
    """
    Bangun JSON payload dengan key order yang BENAR sesuai Go struct.
    PENTING: key order harus match Go struct — server re-marshal pakai Go
    json.Marshal yang serializes fields in struct definition order.

    Go struct BatchNewOrderRequest field order:
      accountID → orders[]
    Go struct BatchNewOrderItem field order:
      symbolID → clOrdID → modifier → side → type → timeInForce → price → quantity

    Docs: "Key order must match the Go struct field order"
    """
    # Susun ulang params dengan key order yang benar
    if action_type == "newOrder":
        ordered_params = _order_new_order_params(params)
    elif action_type == "cancelOrder":
        ordered_params = _order_cancel_params(params)
    else:
        ordered_params = params

    payload = {"type": action_type, "params": ordered_params}
    # Compact JSON tanpa whitespace — sesuai docs "no whitespace or newlines"
    return json.dumps(payload, separators=(",", ":"))


def _order_new_order_params(params: dict) -> dict:
    """Susun key BatchNewOrderRequest sesuai Go struct order."""
    ordered_orders = []
    for order in params.get("orders", []):
        # Go struct BatchNewOrderItem field order:
        # symbolID, clOrdID, modifier, side, type, timeInForce, price, quantity
        item = {}
        for key in ["symbolID", "clOrdID", "modifier", "side", "type",
                    "timeInForce", "price", "quantity"]:
            if key in order:
                item[key] = order[key]
        ordered_orders.append(item)

    # Go struct BatchNewOrderRequest field order: accountID, orders
    return {"accountID": params["accountID"], "orders": ordered_orders}


def _order_cancel_params(params: dict) -> dict:
    """Susun key BatchCancelOrderRequest sesuai Go struct order."""
    ordered_orders = []
    for order in params.get("orders", []):
        # Go struct BatchCancelOrderItem: symbolID, clOrdID
        item = {}
        for key in ["symbolID", "clOrdID"]:
            if key in order:
                item[key] = order[key]
        ordered_orders.append(item)

    return {"accountID": params["accountID"], "orders": ordered_orders}


def sign_payload(action_type: str, params: dict, nonce: int) -> str:
    """
    Sign payload dan return typed signature (66 bytes):
    [0x01][r(32)][s(32)][v(1)]

    Steps:
    1. JSON encode payload (key order sesuai Go struct)
    2. payloadHash = Keccak256(JSON bytes)
    3. EIP-712 hash dengan domain "spot"
    4. Sign dengan private key
    5. Return 0x01 + r + s + v
    """
    # Step 1 & 2: payload hash
    payload_json  = build_payload_json(action_type, params)
    payload_hash  = Web3.keccak(payload_json.encode("utf-8"))

    # Step 3: EIP-712 domain separator
    domain_type_hash = Web3.keccak(
        text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    encoded_domain = Web3.solidity_keccak(
        ["bytes32", "bytes32", "bytes32", "uint256", "address"],
        [
            domain_type_hash,
            Web3.keccak(text="spot"),
            Web3.keccak(text="1"),
            TESTNET_CHAIN_ID,
            "0x0000000000000000000000000000000000000000",
        ]
    )

    # Step 3: EIP-712 message hash
    action_type_hash = Web3.keccak(
        text="ExchangeAction(bytes32 payloadHash,uint64 nonce)"
    )
    encoded_message = Web3.solidity_keccak(
        ["bytes32", "bytes32", "uint64"],
        [action_type_hash, payload_hash, nonce]
    )

    # Step 3: Final digest
    digest = Web3.keccak(b"\x19\x01" + encoded_domain + encoded_message)

    # Step 4: Sign
    account = Account.from_key(PRIVATE_KEY)
    sig = account.sign_typed_data(
        domain_data={
            "name":              "spot",
            "version":           "1",
            "chainId":           TESTNET_CHAIN_ID,
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        message_types={
            "ExchangeAction": [
                {"name": "payloadHash", "type": "bytes32"},
                {"name": "nonce",       "type": "uint64"},
            ]
        },
        message_data={
            "payloadHash": "0x" + payload_hash.hex(),
            "nonce":       nonce,
        },
    )

    # Step 5: Wire format = 0x01 + r(32) + s(32) + v(1)
    # v dari sign_typed_data adalah 27 atau 28 → normalize ke 0 atau 1
    v_normalized = sig.v - 27 if sig.v >= 27 else sig.v
    r_bytes = sig.r.to_bytes(32, "big")
    s_bytes = sig.s.to_bytes(32, "big")
    v_bytes = bytes([v_normalized])

    typed_sig = "0x01" + r_bytes.hex() + s_bytes.hex() + v_bytes.hex()
    return typed_sig


def make_signed_headers(action_type: str, params: dict) -> tuple:
    """
    Buat nonce dan signed headers untuk request.
    Return: (headers_dict, nonce)
    """
    nonce     = int(time.time() * 1000)
    typed_sig = sign_payload(action_type, params, nonce)
    headers   = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-API-Key":    API_KEY_NAME,
        "X-API-Sign":   typed_sig,
        "X-API-Nonce":  str(nonce),
    }
    return headers, nonce
