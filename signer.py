# ============================================================
# signer.py — EIP-712 signing untuk SoDEX
# Sesuai dokumentasi resmi dan Go SDK source code
#
# Root cause fix: nonce harus di-encode sebagai uint256 (32 bytes)
# bukan uint64, sesuai Go code: binary.BigEndian.PutUint64(nonceBytes[24:], nonce)
# ============================================================
import json
import time
from web3 import Web3
from eth_account import Account
from config import PRIVATE_KEY, TESTNET_CHAIN_ID, API_KEY_NAME


def _build_domain_sep() -> bytes:
    """Compute EIP-712 domain separator untuk SoDEX spot engine."""
    domain_type_hash = Web3.keccak(
        text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    return Web3.keccak(
        domain_type_hash +
        Web3.keccak(text="spot") +
        Web3.keccak(text="1") +
        TESTNET_CHAIN_ID.to_bytes(32, "big") +
        bytes(32)   # verifyingContract = zero address, padded 32 bytes
    )


def _build_struct_hash(payload_hash: bytes, nonce: int) -> bytes:
    """
    Compute EIP-712 struct hash untuk ExchangeAction.
    PENTING: nonce di-encode sebagai uint256 (32 bytes), bukan uint64!
    Sesuai Go: binary.BigEndian.PutUint64(nonceBytes[24:], ea.Nonce)
    """
    action_type_hash = Web3.keccak(
        text="ExchangeAction(bytes32 payloadHash,uint64 nonce)"
    )
    nonce_bytes = nonce.to_bytes(32, "big")   # uint256, bukan uint64
    return Web3.keccak(action_type_hash + payload_hash + nonce_bytes)


def _sign_digest(digest: bytes) -> str:
    """
    Sign digest dan return wire format signature (66 bytes):
    0x01 + r(32) + s(32) + v(1, normalized 0/1)
    """
    account   = Account.from_key(PRIVATE_KEY)
    sig       = account.unsafe_sign_hash(digest)
    sig_bytes = bytearray(sig.signature)
    # v dari eth-account = 27/28, normalize ke 0/1 sesuai Go crypto.Sign
    sig_bytes[-1] = sig_bytes[-1] - 27 if sig_bytes[-1] >= 27 else sig_bytes[-1]
    return "0x01" + bytes(sig_bytes).hex()


def compute_signature(action_type: str, params: dict, nonce: int) -> str:
    """
    Hitung EIP-712 signature sesuai SoDEX signing pipeline:
    1. signing_payload = {"type": action_type, "params": params}
    2. payloadHash = keccak256(compact JSON)
    3. structHash = keccak256(typeHash + payloadHash + nonce_as_uint256)
    4. digest = keccak256(0x1901 + domainSep + structHash)
    5. return 0x01 + sign(digest)
    """
    signing_payload = {"type": action_type, "params": params}
    payload_json    = json.dumps(signing_payload, separators=(",", ":"))
    payload_hash    = Web3.keccak(payload_json.encode("utf-8"))

    domain_sep  = _build_domain_sep()
    struct_hash = _build_struct_hash(payload_hash, nonce)
    digest      = Web3.keccak(b"\x19\x01" + domain_sep + struct_hash)

    return _sign_digest(digest)


def make_headers(action_type: str, params: dict) -> tuple:
    """
    Buat nonce + signed headers.
    Return: (headers_dict, nonce)
    """
    nonce   = int(time.time() * 1000)
    sig     = compute_signature(action_type, params, nonce)
    headers = {
        "Content-Type": "application/json",
        "Accept":       "application/json",
        "X-API-Key":    API_KEY_NAME,
        "X-API-Sign":   sig,
        "X-API-Nonce":  str(nonce),
        "X-API-Chain":  str(TESTNET_CHAIN_ID),
    }
    return headers, nonce
