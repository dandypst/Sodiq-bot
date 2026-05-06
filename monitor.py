# ============================================================
# monitor.py — SoDEX Points & Trading Monitor
# Jalankan terpisah: python monitor.py
# Bisa jalan bersamaan dengan bot.py di terminal lain
# ============================================================
import time
import logging
from datetime import datetime, timezone

from config import WALLET_ADDRESS, BASE_URL, MONITOR_INTERVAL
from api import get_balances, get_open_orders, get_tickers

import requests

log            = logging.getLogger(__name__)
PUBLIC_HEADERS = {"Accept": "application/json"}

# ── Points API (endpoint SoDEX untuk leaderboard & points) ───

POINTS_URL = "https://testnet.sodex.com/api/v1/points"


def get_points(address: str) -> dict:
    """Ambil data points dari SoDEX points API."""
    try:
        r = requests.get(
            f"{POINTS_URL}/user",
            params={"address": address},
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.debug(f"get_points: {e}")
    return {}


def get_leaderboard(limit: int = 10) -> list:
    """Ambil leaderboard teratas."""
    try:
        r = requests.get(
            f"{POINTS_URL}/leaderboard",
            params={"limit": limit},
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            d = r.json()
            return d.get("data", d) if isinstance(d, dict) else d
    except Exception as e:
        log.debug(f"get_leaderboard: {e}")
    return []


def get_trade_history(address: str, limit: int = 50) -> list:
    """Ambil riwayat trade untuk hitung volume."""
    try:
        r = requests.get(
            f"{BASE_URL}/accounts/{address}/trades",
            params={"limit": limit},
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
    except Exception as e:
        log.debug(f"get_trade_history: {e}")
    return []


def get_order_history(address: str, limit: int = 100) -> list:
    """Ambil riwayat order (filled, cancelled, expired)."""
    try:
        r = requests.get(
            f"{BASE_URL}/accounts/{address}/orders/history",
            params={"limit": limit},
            headers=PUBLIC_HEADERS,
            timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("data", [])
    except Exception as e:
        log.debug(f"get_order_history: {e}")
    return []


# ── Display Helpers ───────────────────────────────────────────

SEP  = "─" * 55
SEP2 = "═" * 55


def format_num(n) -> str:
    """Format angka dengan pemisah ribuan."""
    try:
        return f"{float(n):,.4f}"
    except Exception:
        return str(n)


def print_header():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{SEP2}")
    print(f"  📊  SoDEX Monitor  —  {now}")
    print(SEP2)


def print_points(address: str):
    print(f"\n🏆  POINTS & RANK")
    print(SEP)
    data = get_points(address)
    if not data:
        # Coba endpoint alternatif (SoDEX mungkin pakai path berbeda)
        print("  Points data tidak tersedia via API.")
        print(f"  Cek manual: https://testnet.sodex.com/points")
        print(f"  Wallet    : {address}")
        return

    # Sesuaikan field dengan response API aktual
    points = data.get("points") or data.get("totalPoints") or data.get("soPoints") or "N/A"
    rank   = data.get("rank")   or data.get("leaderboardRank") or "N/A"
    season = data.get("season") or "1"

    print(f"  Season    : {season}")
    print(f"  Points    : {points}")
    print(f"  Rank      : #{rank}")


def print_balance():
    print(f"\n💰  SALDO AKUN")
    print(SEP)
    bal = get_balances()
    if not bal:
        print("  Tidak bisa ambil balance.")
        return

    balances = bal.get("balances") or []
    if not balances:
        # Coba format alternatif
        balances = bal if isinstance(bal, list) else []

    if not balances:
        print("  Saldo kosong atau format tidak dikenal.")
        return

    total_usdc = 0.0
    for b in balances:
        coin  = b.get("coin",  b.get("asset", "?"))
        free  = float(b.get("free",  b.get("available", 0)))
        locked= float(b.get("locked", b.get("frozen", 0)))
        total = float(b.get("total", free + locked))

        if total > 0:
            print(f"  {coin:<12} free={free:<18.4f} locked={locked:<14.4f} total={total:.4f}")
            if "USDC" in coin.upper():
                total_usdc += total

    if total_usdc > 0:
        print(f"  {'─'*45}")
        print(f"  Total USDC equivalent: {total_usdc:,.4f}")


def print_open_orders():
    print(f"\n📋  OPEN ORDERS")
    print(SEP)
    orders = get_open_orders()
    if not orders:
        print("  Tidak ada open order saat ini.")
        return
    print(f"  {'Symbol':<18} {'Side':<6} {'Type':<8} {'Price':<14} {'Qty':<10}")
    print(f"  {'─'*55}")
    for o in orders[:10]:  # tampilkan max 10
        symbol = o.get("symbol", "?")
        side   = "BUY"  if o.get("side") == 1 else "SELL"
        typ    = "LIMIT" if o.get("type") == 1 else "MARKET"
        price  = o.get("price",    "?")
        qty    = o.get("quantity", "?")
        print(f"  {symbol:<18} {side:<6} {typ:<8} {price:<14} {qty}")
    if len(orders) > 10:
        print(f"  ... dan {len(orders)-10} order lainnya")


def print_volume_stats(address: str):
    print(f"\n📈  VOLUME & TRADE STATS (50 trade terakhir)")
    print(SEP)

    trades = get_trade_history(address, limit=50)
    if not trades:
        print("  Belum ada riwayat trade.")
        return

    total_vol  = 0.0
    pairs_seen = set()
    buy_count  = sell_count = 0

    for t in trades:
        symbol = t.get("symbol", "?")
        price  = float(t.get("price",    0))
        qty    = float(t.get("quantity", 0))
        side   = t.get("side", 0)

        pairs_seen.add(symbol)
        total_vol += price * qty

        if side == 1:
            buy_count += 1
        else:
            sell_count += 1

    print(f"  Total volume   : {total_vol:>18,.4f} USDC")
    print(f"  Jumlah trade   : {len(trades):>18}")
    print(f"    BUY          : {buy_count:>18}")
    print(f"    SELL         : {sell_count:>18}")
    print(f"  Pairs unik     : {len(pairs_seen):>18}")
    print(f"  Pairs          : {', '.join(sorted(pairs_seen)[:5])}{'...' if len(pairs_seen) > 5 else ''}")

    # Progress menuju 100k USDC volume target
    target = 100_000.0
    pct    = min(total_vol / target * 100, 100)
    bar_len = 30
    filled  = int(bar_len * pct / 100)
    bar     = "█" * filled + "░" * (bar_len - filled)
    print(f"\n  Volume target  : {total_vol:>12,.0f} / {target:>10,.0f} USDC")
    print(f"  Progress       : [{bar}] {pct:.1f}%")


def print_leaderboard():
    print(f"\n🥇  LEADERBOARD TOP 10")
    print(SEP)
    board = get_leaderboard(10)
    if not board:
        print("  Leaderboard tidak tersedia via API.")
        print(f"  Cek: https://testnet.sodex.com/points")
        return

    print(f"  {'#':<5} {'Address':<20} {'Points'}")
    print(f"  {'─'*45}")
    for i, entry in enumerate(board[:10], 1):
        addr   = entry.get("address", entry.get("userAddress", "?"))
        pts    = entry.get("points", entry.get("totalPoints", "?"))
        # Highlight kalau wallet kita ada di leaderboard
        tag = " ← kamu!" if addr.lower() == WALLET_ADDRESS.lower() else ""
        short_addr = addr[:6] + "..." + addr[-4:] if len(addr) > 12 else addr
        print(f"  {i:<5} {short_addr:<20} {pts}{tag}")


# ── Main Monitor Loop ─────────────────────────────────────────

def run_monitor():
    logging.basicConfig(
        level=logging.WARNING,   # suppress INFO dari api.py
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    print(f"\n{'='*55}")
    print(f"  🔭  SoDEX Monitor START")
    print(f"  Wallet   : {WALLET_ADDRESS}")
    print(f"  Refresh  : setiap {MONITOR_INTERVAL}s")
    print(f"{'='*55}")

    if not WALLET_ADDRESS:
        print("❌  WALLET_ADDRESS tidak ada di .env — berhenti.")
        return

    while True:
        try:
            print_header()
            print_points(WALLET_ADDRESS)
            print_balance()
            print_open_orders()
            print_volume_stats(WALLET_ADDRESS)
            print_leaderboard()
            print(f"\n  ⏳  Refresh berikutnya dalam {MONITOR_INTERVAL}s... (Ctrl+C untuk keluar)")

        except KeyboardInterrupt:
            print("\n\n  Monitor dihentikan. Sampai jumpa!")
            break
        except Exception as e:
            print(f"\n  ⚠️  Error: {e}")

        time.sleep(MONITOR_INTERVAL)


if __name__ == "__main__":
    run_monitor()
