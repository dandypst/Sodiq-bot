# ============================================================
# signer.py — EIP-712 signing untuk SoDEX
# ============================================================
import time
import json
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from config import PRIVATE_KEY, WALLET_ADDRESS, TESTNET_CHAIN_ID


def compute_payload_hash(payload: dict) -> str:
    """
    payloadHash = Keccak256(json.Marshal(payload))
    Compact JSON tanpa whitespace, key order sesuai Go struct (wajib).
    """
    payload_json  = json.dumps(payload, separators=(",", ":"))
    payload_bytes = payload_json.encode("utf-8")
    keccak        = Web3.keccak(payload_bytes)
    return "0x" + keccak.hex()


def sign_action(payload: dict) -> tuple:
    """
    Sign action payload dengan EIP-712.
    Return: (typed_signature, nonce)
    Typed signature format SoDEX = 0x01 + sig_bytes
    """
    nonce              = int(time.time() * 1000)
    payload_hash       = compute_payload_hash(payload)
    payload_hash_bytes = bytes.fromhex(payload_hash[2:])

    # Domain separator
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

    # Message hash
    action_type_hash = Web3.keccak(
        text="ExchangeAction(bytes32 payloadHash,uint64 nonce)"
    )
    encoded_message = Web3.solidity_keccak(
        ["bytes32", "bytes32", "uint64"],
        [action_type_hash, payload_hash_bytes, nonce]
    )

    # Final EIP-191 hash: \x19\x01 + domainSeparator + messageHash
    final_hash = Web3.keccak(b"\x19\x01" + encoded_domain + encoded_message)

    # Sign — kompatibel dengan eth-account versi lama dan baru
    account = Account.from_key(PRIVATE_KEY)
    try:
        # eth-account >= 0.9
        sig = account.signHash(final_hash)
    except AttributeError:
        # eth-account >= 0.11 — signHash dihapus, pakai unsafe_sign_hash
        try:
            sig = account.unsafe_sign_hash(final_hash)
        except AttributeError:
            # Fallback: sign raw bytes lewat sign_message
            from eth_account._utils.signing import sign_message_hash
            sig = sign_message_hash(account.key, final_hash)

    typed_sig = "0x01" + sig.signature.hex()
    return typed_sig, nonce


def signed_headers(payload: dict) -> dict:
    """Buat HTTP headers untuk signed write endpoint."""
    typed_sig, nonce = sign_action(payload)
    return {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-API-Key":    WALLET_ADDRESS,
        "X-API-Sign":   typed_sig,
        "X-API-Nonce":  str(nonce),
    }
