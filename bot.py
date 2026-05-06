# ============================================================
# bot.py — SoDEX Testnet Auto Trading Bot
# Jalankan: python bot.py
# ============================================================
import random
import time
import logging
from datetime import datetime

from config import (
    PRIVATE_KEY, WALLET_ADDRESS, TRADING_PAIRS,
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
    get_balances, get_open_orders,
    place_batch_orders, cancel_batch_orders,
)

# ── Logger ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("sodex_bot.log"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def make_order_id(prefix: str) -> str:
    """ID unik max 36 karakter."""
    ts   = str(int(time.time() * 1000))[-10:]
    rand = str(random.randint(1000, 9999))
    return f"{prefix}-{ts}-{rand}"[:36]


def get_symbol_info(symbol: str, all_symbols: list) -> dict:
    for s in all_symbols:
        if s.get("symbol") == symbol:
            return s
    return None


def get_last_price(symbol: str) -> float:
    """Ambil harga terakhir dari ticker."""
    try:
        tickers = get_tickers(symbol)
        if tickers:
            return float(tickers[0].get("lastPrice", 0))
    except Exception:
        pass
    return 0.0


def round_to_precision(value: float, precision: int) -> str:
    """Round float ke N desimal dan return sebagai string."""
    return str(round(value, precision))


def calc_limit_price(orderbook: dict, side: str, symbol_info: dict) -> str:
    """
    Hitung harga limit order di luar spread supaya tidak langsung terisi.
    BUY  → best_bid - (tick * offset)
    SELL → best_ask + (tick * offset)
    """
    tick   = float(symbol_info.get("tickSize", "0.01"))
    prec   = int(symbol_info.get("pricePrecision", 2))
    offset = tick * PRICE_OFFSET_TICKS
    try:
        if side == "BUY":
            bids = orderbook.get("bids", [])
            if not bids:
                return None
            price = float(bids[0][0]) - offset
        else:
            asks = orderbook.get("asks", [])
            if not asks:
                return None
            price = float(asks[0][0]) + offset
        return round_to_precision(max(price, tick), prec)
    except Exception as e:
        log.error(f"calc_limit_price: {e}")
        return None


def calc_min_quantity(symbol_info: dict) -> str:
    """Ambil quantity minimum yang valid."""
    try:
        min_qty   = float(symbol_info.get("minQuantity",  "0"))
        step_size = float(symbol_info.get("stepSize",     "0.001"))
        qty_prec  = int(symbol_info.get("quantityPrecision", 3))
        qty = max(min_qty, step_size) if min_qty > 0 else step_size
        return round_to_precision(qty, qty_prec)
    except Exception as e:
        log.error(f"calc_min_quantity: {e}")
        return None


def calc_market_quantity(symbol_info: dict, last_price: float) -> str:
    """
    Hitung quantity untuk market order berdasarkan MARKET_ORDER_USDC.
    qty = USDC_amount / last_price, dibulatkan ke step_size.
    """
    try:
        usdc_amount = float(MARKET_ORDER_USDC)
        step_size   = float(symbol_info.get("stepSize", "0.001"))
        qty_prec    = int(symbol_info.get("quantityPrecision", 3))
        min_qty     = float(symbol_info.get("minQuantity", "0"))

        if last_price <= 0:
            return None

        qty = usdc_amount / last_price
        # Bulatkan ke step_size terdekat (ke bawah, supaya tidak exceed budget)
        qty = (qty // step_size) * step_size
        qty = round(qty, qty_prec)

        # Pastikan di atas minimum
        if min_qty > 0 and qty < min_qty:
            qty = min_qty

        return str(qty)
    except Exception as e:
        log.error(f"calc_market_quantity: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# LIMIT MODE — place & cancel limit orders
# ══════════════════════════════════════════════════════════════

def trade_limit(symbol: str, all_symbols: list, cycle: int) -> bool:
    """
    Satu siklus limit order:
    1. Place BUY + SELL limit (GTX post-only) di luar spread
    2. Tahan beberapa detik
    3. Cancel semua
    """
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

    if float(buy_price) <= 0 or float(sell_price) <= 0:
        log.warning(f"    Harga tidak valid: buy={buy_price} sell={sell_price}")
        return False

    buy_id  = make_order_id("LB")
    sell_id = make_order_id("LS")

    # modifier: 1=normal | side: 1=BUY 2=SELL | type: 1=LIMIT | timeInForce: lihat config
    orders_payload = {
        "accountID": 0,
        "symbolID":  sym_info.get("symbolID", 0),
        "orders": [
            {
                "clOrdID":     buy_id,
                "modifier":    1,
                "side":        1,
                "type":        1,
                "timeInForce": TIME_IN_FORCE,
                "price":       buy_price,
                "quantity":    qty,
            },
            {
                "clOrdID":     sell_id,
                "modifier":    1,
                "side":        2,
                "type":        1,
                "timeInForce": TIME_IN_FORCE,
                "price":       sell_price,
                "quantity":    qty,
            },
        ],
    }

    results = place_batch_orders(orders_payload)
    placed  = []
    for r in results:
        if r.get("code") == 0:
            placed.append(r["clOrdID"])
            log.info(f"    ✓ [LIMIT] Placed {r['clOrdID']}  orderID={r.get('orderID')}")
        else:
            log.warning(f"    ✗ [LIMIT] Gagal {r.get('clOrdID')}: {r.get('error')}")

    if not placed:
        return False

    # Tahan order
    hold = random.uniform(ORDER_HOLD_MIN, ORDER_HOLD_MAX)
    log.info(f"    ⏳ Hold {hold:.1f}s lalu cancel...")
    time.sleep(hold)

    # Cancel
    cancel_results = cancel_batch_orders({
        "accountID": 0,
        "symbolID":  sym_info.get("symbolID", 0),
        "orders":    [{"clOrdID": oid} for oid in placed],
    })
    for r in cancel_results:
        if r.get("code") == 0:
            log.info(f"    ✓ Cancelled {r.get('origClOrdID')}")
        else:
            log.info(f"    ℹ Sudah terisi / tidak ada: {r.get('clOrdID')}")

    return True


# ══════════════════════════════════════════════════════════════
# MARKET MODE — place market orders untuk volume cepat
# ══════════════════════════════════════════════════════════════

def trade_market(symbol: str, all_symbols: list, cycle: int) -> bool:
    """
    Satu siklus market order (volume agresif):
    1. BUY market order kecil → langsung terisi
    2. Tunggu sebentar
    3. SELL market order dengan qty yang sama → balik ke USDC

    Volume = 2x MARKET_ORDER_USDC per siklus (BUY + SELL).
    Biaya = taker fee * 2 (biasanya sangat kecil di testnet).
    """
    sym_info = get_symbol_info(symbol, all_symbols)
    if not sym_info:
        log.warning(f"    Symbol info tidak ditemukan: {symbol}")
        return False

    # Ambil harga terakhir
    last_price = get_last_price(symbol)
    if last_price <= 0:
        # Coba dari orderbook
        ob = get_orderbook(symbol, limit=1)
        if ob:
            asks = ob.get("asks", [])
            if asks:
                last_price = float(asks[0][0])

    if last_price <= 0:
        log.warning(f"    Tidak bisa ambil harga {symbol}")
        return False

    qty = calc_market_quantity(sym_info, last_price)
    if not qty or float(qty) <= 0:
        log.warning(f"    Qty tidak valid untuk {symbol} (price={last_price})")
        return False

    price_prec = int(sym_info.get("pricePrecision", 2))

    # Harga slippage protection untuk BUY
    buy_price_limit = None
    if MARKET_SLIPPAGE_RATIO:
        bp = last_price * (1 + MARKET_SLIPPAGE_RATIO)
        buy_price_limit = round_to_precision(bp, price_prec)

    log.info(f"    💸 [MARKET] BUY  {qty} {symbol}  ~{MARKET_ORDER_USDC} USDC  (price≈{last_price})")

    # ── Step 1: BUY market order ──────────────────────────────
    buy_id = make_order_id("MB")
    buy_order = {
        "clOrdID":     buy_id,
        "modifier":    1,
        "side":        1,       # BUY
        "type":        2,       # MARKET
        "timeInForce": 2,       # IOC (wajib untuk market order)
        "quantity":    qty,
    }
    if buy_price_limit:
        buy_order["price"] = buy_price_limit

    buy_payload = {
        "accountID": 0,
        "symbolID":  sym_info.get("symbolID", 0),
        "orders":    [buy_order],
    }

    buy_results = place_batch_orders(buy_payload)
    buy_ok = False
    for r in buy_results:
        if r.get("code") == 0:
            log.info(f"    ✓ BUY filled  orderID={r.get('orderID')}")
            buy_ok = True
        else:
            log.warning(f"    ✗ BUY gagal: {r.get('error')}")

    if not buy_ok:
        return False

    # Tunggu sebentar antar BUY dan SELL
    pause = random.uniform(2, 8)
    log.info(f"    ⏳ Jeda {pause:.1f}s sebelum SELL...")
    time.sleep(pause)

    # ── Step 2: SELL market order (balik ke USDC) ─────────────
    log.info(f"    💸 [MARKET] SELL {qty} {symbol}")

    sell_id = make_order_id("MS")

    # Harga slippage protection untuk SELL
    sell_price_limit = None
    if MARKET_SLIPPAGE_RATIO:
        sp = last_price * (1 - MARKET_SLIPPAGE_RATIO)
        sell_price_limit = round_to_precision(sp, price_prec)

    sell_order = {
        "clOrdID":     sell_id,
        "modifier":    1,
        "side":        2,       # SELL
        "type":        2,       # MARKET
        "timeInForce": 2,       # IOC
        "quantity":    qty,
    }
    if sell_price_limit:
        sell_order["price"] = sell_price_limit

    sell_payload = {
        "accountID": 0,
        "symbolID":  sym_info.get("symbolID", 0),
        "orders":    [sell_order],
    }

    sell_results = place_batch_orders(sell_payload)
    for r in sell_results:
        if r.get("code") == 0:
            log.info(f"    ✓ SELL filled  orderID={r.get('orderID')}")
        else:
            log.warning(f"    ✗ SELL gagal: {r.get('error')}")

    vol = float(qty) * last_price * 2
    log.info(f"    📊 Volume siklus ini: ~{vol:.2f} USDC")
    return True


# ══════════════════════════════════════════════════════════════
# DISPATCHER — pilih mode berdasarkan config
# ══════════════════════════════════════════════════════════════

def trade_pair(symbol: str, all_symbols: list, cycle: int) -> bool:
    """Pilih strategi berdasarkan BOT_MODE dan jalankan."""
    log.info(f"  → {symbol}  (siklus #{cycle})")

    if BOT_MODE == "market":
        return trade_market(symbol, all_symbols, cycle)

    elif BOT_MODE == "limit":
        return trade_limit(symbol, all_symbols, cycle)

    elif BOT_MODE == "hybrid":
        # Setiap HYBRID_MARKET_EVERY siklus, pakai market order
        if cycle % HYBRID_MARKET_EVERY == 0:
            log.info(f"    🔀 [HYBRID] Siklus market order")
            return trade_market(symbol, all_symbols, cycle)
        else:
            log.info(f"    🔀 [HYBRID] Siklus limit order")
            return trade_limit(symbol, all_symbols, cycle)

    else:
        log.error(f"BOT_MODE tidak dikenal: '{BOT_MODE}'. Gunakan: limit | market | hybrid")
        return False


# ══════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════

def print_status():
    """Print saldo akun ke log."""
    log.info("─" * 55)
    log.info("📊 STATUS AKUN")
    bal = get_balances()
    if bal:
        for b in (bal.get("balances") or []):
            coin  = b.get("coin",  "?")
            free  = b.get("free",  "0")
            total = b.get("total", "0")
            if float(total) > 0:
                log.info(f"   {coin:<12} free={free:<20} total={total}")
    else:
        log.info("   (tidak bisa ambil balance)")
    log.info("─" * 55)


# ══════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════

def main():
    log.info("=" * 55)
    log.info("🤖  SoDEX Testnet Bot  —  START")
    log.info(f"    Wallet   : {WALLET_ADDRESS}")
    log.info(f"    Mode     : {BOT_MODE.upper()}")
    log.info(f"    Pairs    : {len(TRADING_PAIRS)}")
    log.info(f"    Endpoint : {BASE_URL}")
    if BOT_MODE == "market":
        log.info(f"    USDC/siklus: {MARKET_ORDER_USDC}")
    if BOT_MODE == "hybrid":
        log.info(f"    Market setiap: {HYBRID_MARKET_EVERY} siklus")
    log.info("=" * 55)

    if not PRIVATE_KEY:
        log.error("❌  PRIVATE_KEY tidak ada di .env — berhenti.")
        return
    if not WALLET_ADDRESS:
        log.error("❌  WALLET_ADDRESS tidak ada di .env — berhenti.")
        return

    all_symbols = get_symbols()
    if all_symbols:
        log.info(f"    Symbol list : {len(all_symbols)} symbols")
    else:
        log.warning("    ⚠️  Tidak bisa ambil symbol list. Cek koneksi ke testnet-gw.sodex.dev")

    print_status()

    cycle      = 0
    pair_index = 0

    while True:
        cycle += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n{'='*55}")
        log.info(f"🔄  SIKLUS #{cycle}   —   {now}")

        # Refresh symbol list berkala
        if cycle % SYMBOL_REFRESH_EVERY == 1 and cycle > 1:
            fresh = get_symbols()
            if fresh:
                all_symbols = fresh
                log.info(f"    Symbol list refreshed: {len(all_symbols)}")

        # Pilih pair round-robin
        symbol = TRADING_PAIRS[pair_index % len(TRADING_PAIRS)]
        pair_index += 1

        ok = trade_pair(symbol, all_symbols, cycle)
        log.info(f"  {'✅' if ok else '⏭️ '}  {symbol}  {'selesai' if ok else 'diskip'}")

        # Print status berkala
        if cycle % STATUS_PRINT_EVERY == 0:
            print_status()

        # Jeda acak antar siklus
        delay = random.uniform(CYCLE_DELAY_MIN, CYCLE_DELAY_MAX)
        log.info(f"  💤  Jeda {delay:.1f}s...")
        time.sleep(delay)


if __name__ == "__main__":
    main()
