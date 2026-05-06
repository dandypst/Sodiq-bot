# ============================================================
# bot.py — SoDEX Testnet Auto Trading Bot
# Jalankan: python bot.py
# ============================================================
import random
import time
import logging
from datetime import datetime

from config import (
    PRIVATE_KEY, WALLET_ADDRESS,
    TARGET_ASSETS, QUOTE_ASSET, MIN_PAIRS_REQUIRED,
    ORDER_HOLD_MIN, ORDER_HOLD_MAX,
    CYCLE_DELAY_MIN, CYCLE_DELAY_MAX,
    SYMBOL_REFRESH_EVERY, STATUS_PRINT_EVERY,
    PRICE_OFFSET_TICKS, TIME_IN_FORCE,
    BOT_MODE, HYBRID_MARKET_EVERY,
    MARKET_ORDER_USDC, MARKET_SLIPPAGE_RATIO,
    BASE_URL,
)
from api import (
    get_symbols, get_orderbook, get_tickers,
    get_balances, get_account_id,
    place_batch_orders, cancel_batch_orders,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("sodex_bot.log"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

ACCOUNT_ID = None


# ══════════════════════════════════════════════════════════════
# ACCOUNT ID
# ══════════════════════════════════════════════════════════════

def fetch_account_id() -> int:
    import requests
    log.info("    Fetching accountID dari API...")
    acc_id = get_account_id()
    if acc_id is not None:
        log.info(f"    accountID: {acc_id}")
        return acc_id

    # Log raw response untuk debugging
    try:
        r = requests.get(
            f"{BASE_URL}/accounts/{WALLET_ADDRESS}/state",
            headers={"Accept": "application/json"}, timeout=10
        )
        log.warning(f"    Raw account state: {r.text[:500]}")
    except Exception as e:
        log.error(f"    Fetch account state gagal: {e}")
    return None


# ══════════════════════════════════════════════════════════════
# SYMBOL AUTO-DETECTION
# ══════════════════════════════════════════════════════════════

def detect_trading_pairs(all_symbols: list) -> list:
    if not all_symbols:
        return []

    available = {s["name"]: s for s in all_symbols if s.get("name")}
    matched   = []
    used      = set()

    for asset in TARGET_ASSETS:
        found = None
        for sym_name, sym_data in available.items():
            if (sym_data.get("baseCoin", "").upper() == asset.upper()
                    and sym_data.get("quoteCoin", "").upper() == QUOTE_ASSET.upper()
                    and sym_name not in used):
                found = sym_name
                break
        if not found:
            for sym_name in available:
                if (asset.upper() in sym_name.upper()
                        and QUOTE_ASSET.upper() in sym_name.upper()
                        and sym_name not in used):
                    found = sym_name
                    break
        if found:
            matched.append(found)
            used.add(found)

    if len(matched) < MIN_PAIRS_REQUIRED:
        log.warning(f"  Auto-detect dapat {len(matched)} pairs, fallback...")
        for sym_name, sym_data in available.items():
            if (sym_data.get("quoteCoin", "").upper() == QUOTE_ASSET.upper()
                    and sym_name not in used
                    and sym_data.get("status") == "TRADING"):
                matched.append(sym_name)
                used.add(sym_name)
                if len(matched) >= 20:
                    break

    return matched


def log_symbol_mapping(detected_pairs: list):
    log.info(f"  Auto-detected {len(detected_pairs)} trading pairs:")
    for sym in detected_pairs:
        log.info(f"    ✓ {sym}")


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def make_order_id(prefix: str) -> str:
    ts   = str(int(time.time() * 1000))[-10:]
    rand = str(random.randint(1000, 9999))
    return f"{prefix}-{ts}-{rand}"[:36]


def get_symbol_info(symbol: str, all_symbols: list) -> dict:
    for s in all_symbols:
        if s.get("name") == symbol:
            return s
    return None


def get_symbol_id(sym_info: dict) -> int:
    return sym_info.get("id", 0)


def get_last_price(symbol: str) -> float:
    try:
        tickers = get_tickers(symbol)
        if tickers:
            return float(tickers[0].get("lastPrice", 0))
    except Exception:
        pass
    return 0.0


def format_price(raw_price: str) -> str:
    """
    Format harga sesuai yang diterima API SoDEX.
    Orderbook mengembalikan integer string ("81444") — kirim balik sebagai integer string.
    Kalau harga dari kalkulasi float, bulatkan ke integer.
    """
    try:
        f = float(raw_price)
        # Kalau angka >= 1 dan tidak punya desimal signifikan = integer
        if f >= 1 and f == int(f):
            return str(int(f))
        # Kalau punya desimal, return as-is tapi strip trailing zeros
        return str(f).rstrip("0").rstrip(".")
    except Exception:
        return str(raw_price)


def calc_limit_price(orderbook: dict, side: str, symbol_info: dict) -> str:
    """
    Hitung harga limit order di luar spread.
    Harga dari API adalah integer string — offset pakai 1 tick = 1 unit integer.
    """
    try:
        if side == "BUY":
            bids = orderbook.get("bids", [])
            if not bids:
                return None
            best = int(float(bids[0][0]))
            # Pasang di bawah best bid sebanyak PRICE_OFFSET_TICKS
            price = best - PRICE_OFFSET_TICKS
        else:
            asks = orderbook.get("asks", [])
            if not asks:
                return None
            best = int(float(asks[0][0]))
            # Pasang di atas best ask sebanyak PRICE_OFFSET_TICKS
            price = best + PRICE_OFFSET_TICKS

        if price <= 0:
            return None
        return str(price)

    except Exception as e:
        log.error(f"calc_limit_price: {e}")
        return None


def calc_min_quantity(symbol_info: dict) -> str:
    try:
        min_qty   = float(symbol_info.get("minQuantity",  "0"))
        step_size = float(symbol_info.get("stepSize",     "0.001"))
        qty_prec  = int(symbol_info.get("quantityPrecision", 3))
        qty       = max(min_qty, step_size) if min_qty > 0 else step_size
        return str(round(qty, qty_prec))
    except Exception as e:
        log.error(f"calc_min_quantity: {e}")
        return None


def calc_market_quantity(symbol_info: dict, last_price: float) -> str:
    try:
        usdc_amount = float(MARKET_ORDER_USDC)
        step_size   = float(symbol_info.get("stepSize", "0.001"))
        qty_prec    = int(symbol_info.get("quantityPrecision", 3))
        min_qty     = float(symbol_info.get("minQuantity", "0"))
        if last_price <= 0:
            return None
        qty = (usdc_amount / last_price // step_size) * step_size
        qty = round(qty, qty_prec)
        if min_qty > 0 and qty < min_qty:
            qty = min_qty
        return str(qty)
    except Exception as e:
        log.error(f"calc_market_quantity: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# LIMIT MODE
# ══════════════════════════════════════════════════════════════

def trade_limit(symbol: str, all_symbols: list, cycle: int) -> bool:
    sym_info = get_symbol_info(symbol, all_symbols)
    if not sym_info:
        log.warning(f"    Symbol info tidak ditemukan: {symbol}")
        return False

    ob = get_orderbook(symbol)
    if not ob:
        log.warning(f"    Orderbook kosong: {symbol}")
        return False

    buy_price  = calc_limit_price(ob, "BUY",  sym_info)
    sell_price = calc_limit_price(ob, "SELL", sym_info)
    qty        = calc_min_quantity(sym_info)

    if not all([buy_price, sell_price, qty]):
        log.warning(f"    Tidak bisa hitung harga/qty: {symbol}")
        return False

    log.info(f"    📋 buy={buy_price} sell={sell_price} qty={qty}")

    buy_id  = make_order_id("LB")
    sell_id = make_order_id("LS")

    results = place_batch_orders({
        "accountID": ACCOUNT_ID,
        "symbolID":  get_symbol_id(sym_info),
        "orders": [
            {"clOrdID": buy_id,  "modifier": 1, "side": 1, "type": 1,
             "timeInForce": TIME_IN_FORCE, "price": buy_price,  "quantity": qty},
            {"clOrdID": sell_id, "modifier": 1, "side": 2, "type": 1,
             "timeInForce": TIME_IN_FORCE, "price": sell_price, "quantity": qty},
        ],
    })

    placed = []
    for r in results:
        if r.get("code") == 0:
            placed.append(r["clOrdID"])
            log.info(f"    ✓ [LIMIT] {r['clOrdID']}  orderID={r.get('orderID')}")
        else:
            log.warning(f"    ✗ [LIMIT] {r.get('clOrdID')}: {r.get('error')}")

    if not placed:
        return False

    hold = random.uniform(ORDER_HOLD_MIN, ORDER_HOLD_MAX)
    log.info(f"    ⏳ Hold {hold:.1f}s lalu cancel...")
    time.sleep(hold)

    cancel_results = cancel_batch_orders({
        "accountID": ACCOUNT_ID,
        "symbolID":  get_symbol_id(sym_info),
        "orders":    [{"clOrdID": oid} for oid in placed],
    })
    for r in cancel_results:
        if r.get("code") == 0:
            log.info(f"    ✓ Cancelled {r.get('origClOrdID')}")
        else:
            log.info(f"    ℹ Sudah terisi: {r.get('clOrdID')}")

    return True


# ══════════════════════════════════════════════════════════════
# MARKET MODE
# ══════════════════════════════════════════════════════════════

def trade_market(symbol: str, all_symbols: list, cycle: int) -> bool:
    sym_info = get_symbol_info(symbol, all_symbols)
    if not sym_info:
        log.warning(f"    Symbol info tidak ditemukan: {symbol}")
        return False

    last_price = get_last_price(symbol)
    if last_price <= 0:
        ob = get_orderbook(symbol, limit=1)
        if ob:
            asks = ob.get("asks", [])
            if asks:
                last_price = float(asks[0][0])

    if last_price <= 0:
        log.warning(f"    Tidak bisa ambil harga: {symbol}")
        return False

    qty = calc_market_quantity(sym_info, last_price)
    if not qty or float(qty) <= 0:
        log.warning(f"    Qty tidak valid: {symbol} (price={last_price})")
        return False

    sym_id = get_symbol_id(sym_info)

    # Harga slippage untuk market order (tetap integer)
    buy_price_limit = str(int(last_price * (1 + MARKET_SLIPPAGE_RATIO))) if MARKET_SLIPPAGE_RATIO else None
    sel_price_limit = str(int(last_price * (1 - MARKET_SLIPPAGE_RATIO))) if MARKET_SLIPPAGE_RATIO else None

    log.info(f"    💸 [MARKET] BUY {qty} {symbol}  ~{MARKET_ORDER_USDC} USDC")

    buy_order = {"clOrdID": make_order_id("MB"), "modifier": 1,
                 "side": 1, "type": 2, "timeInForce": 2, "quantity": qty}
    if buy_price_limit:
        buy_order["price"] = buy_price_limit

    buy_results = place_batch_orders({
        "accountID": ACCOUNT_ID, "symbolID": sym_id, "orders": [buy_order],
    })

    buy_ok = False
    for r in buy_results:
        if r.get("code") == 0:
            log.info(f"    ✓ BUY filled  orderID={r.get('orderID')}")
            buy_ok = True
        else:
            log.warning(f"    ✗ BUY gagal: {r.get('error')}")

    if not buy_ok:
        return False

    pause = random.uniform(2, 8)
    log.info(f"    ⏳ Jeda {pause:.1f}s sebelum SELL...")
    time.sleep(pause)

    log.info(f"    💸 [MARKET] SELL {qty} {symbol}")

    sell_order = {"clOrdID": make_order_id("MS"), "modifier": 1,
                  "side": 2, "type": 2, "timeInForce": 2, "quantity": qty}
    if sel_price_limit:
        sell_order["price"] = sel_price_limit

    sell_results = place_batch_orders({
        "accountID": ACCOUNT_ID, "symbolID": sym_id, "orders": [sell_order],
    })
    for r in sell_results:
        if r.get("code") == 0:
            log.info(f"    ✓ SELL filled  orderID={r.get('orderID')}")
        else:
            log.warning(f"    ✗ SELL gagal: {r.get('error')}")

    log.info(f"    📊 Volume ~{float(qty) * last_price * 2:.2f} USDC")
    return True


# ══════════════════════════════════════════════════════════════
# DISPATCHER
# ══════════════════════════════════════════════════════════════

def trade_pair(symbol: str, all_symbols: list, cycle: int) -> bool:
    log.info(f"  → {symbol}  (siklus #{cycle})")
    if BOT_MODE == "market":
        return trade_market(symbol, all_symbols, cycle)
    elif BOT_MODE == "limit":
        return trade_limit(symbol, all_symbols, cycle)
    elif BOT_MODE == "hybrid":
        if cycle % HYBRID_MARKET_EVERY == 0:
            log.info("    🔀 [HYBRID] Siklus market order")
            return trade_market(symbol, all_symbols, cycle)
        else:
            log.info("    🔀 [HYBRID] Siklus limit order")
            return trade_limit(symbol, all_symbols, cycle)
    else:
        log.error(f"BOT_MODE tidak dikenal: '{BOT_MODE}'")
        return False


# ══════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════

def print_status():
    log.info("─" * 55)
    log.info("📊 STATUS AKUN")
    bal = get_balances()
    if bal:
        for b in (bal.get("balances") or []):
            coin  = b.get("coin",  "?")
            free  = b.get("free",  "0")
            total = b.get("total", "0")
            try:
                if float(total) > 0:
                    log.info(f"   {coin:<12} free={free:<20} total={total}")
            except ValueError:
                pass
    else:
        log.info("   (tidak bisa ambil balance)")
    log.info("─" * 55)


# ══════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════

def main():
    global ACCOUNT_ID

    log.info("=" * 55)
    log.info("🤖  SoDEX Testnet Bot  —  START")
    log.info(f"    Wallet   : {WALLET_ADDRESS}")
    log.info(f"    Mode     : {BOT_MODE.upper()}")
    log.info(f"    Endpoint : {BASE_URL}")
    if BOT_MODE in ("market", "hybrid"):
        log.info(f"    USDC/siklus market: {MARKET_ORDER_USDC}")
    if BOT_MODE == "hybrid":
        log.info(f"    Market setiap: {HYBRID_MARKET_EVERY} siklus")
    log.info("=" * 55)

    if not PRIVATE_KEY:
        log.error("❌  PRIVATE_KEY tidak ada di .env — berhenti.")
        return
    if not WALLET_ADDRESS:
        log.error("❌  WALLET_ADDRESS tidak ada di .env — berhenti.")
        return

    # Fetch accountID
    ACCOUNT_ID = fetch_account_id()
    if ACCOUNT_ID is None:
        log.error("❌  Tidak bisa dapat accountID — berhenti.")
        return

    # Ambil symbol list
    all_symbols = get_symbols()
    if not all_symbols:
        log.error("❌  Tidak bisa ambil symbol list.")
        return

    log.info(f"    Symbol list dari API : {len(all_symbols)} symbols")

    # Auto-detect trading pairs
    trading_pairs = detect_trading_pairs(all_symbols)
    if not trading_pairs:
        log.error("❌  Tidak ada pair yang cocok. Cek TARGET_ASSETS di config.py.")
        return

    log_symbol_mapping(trading_pairs)
    log.info(f"    Pairs aktif: {len(trading_pairs)}")

    print_status()

    cycle      = 0
    pair_index = 0

    while True:
        cycle += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n{'='*55}")
        log.info(f"🔄  SIKLUS #{cycle}   —   {now}")

        # Refresh berkala
        if cycle % SYMBOL_REFRESH_EVERY == 1 and cycle > 1:
            fresh = get_symbols()
            if fresh:
                all_symbols   = fresh
                trading_pairs = detect_trading_pairs(all_symbols)
                log.info(f"    Refreshed: {len(all_symbols)} symbols, "
                         f"{len(trading_pairs)} pairs aktif")

        symbol = trading_pairs[pair_index % len(trading_pairs)]
        pair_index += 1

        ok = trade_pair(symbol, all_symbols, cycle)
        log.info(f"  {'✅' if ok else '⏭️ '}  {symbol}  {'selesai' if ok else 'diskip'}")

        if cycle % STATUS_PRINT_EVERY == 0:
            print_status()

        delay = random.uniform(CYCLE_DELAY_MIN, CYCLE_DELAY_MAX)
        log.info(f"  💤  Jeda {delay:.1f}s...")
        time.sleep(delay)


if __name__ == "__main__":
    main()
