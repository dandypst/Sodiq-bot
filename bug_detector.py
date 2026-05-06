# ============================================================
# bug_detector.py — SoDEX Testnet Bug Detector
#
# Mendeteksi anomali & inkonsistensi di platform SoDEX secara
# otomatis. Semua check bersifat READ-ONLY — tidak ada order
# yang dikirim, tidak ada dana yang bergerak.
#
# Jalankan: python bug_detector.py
# Output  : bug_reports/bug_YYYYMMDD_HHMMSS_foundN.txt
#
# Kirim isi file laporan ke SoDEX untuk bug bounty points
# (hingga 50.000 points per bug yang diterima).
# ============================================================
import os
import time
import json
import logging
import threading
import requests
from datetime import datetime
from dataclasses import dataclass, field

from config import BASE_URL, WALLET_ADDRESS, MONITOR_INTERVAL
from api import get_symbols, get_orderbook, get_tickers, get_balances, get_open_orders

log            = logging.getLogger(__name__)
PUBLIC_HEADERS = {"Accept": "application/json"}
REPORT_DIR     = "bug_reports"


# ══════════════════════════════════════════════════════════════
# DATA STRUCTURE
# ══════════════════════════════════════════════════════════════

@dataclass
class BugReport:
    title:       str
    severity:    str          # CRITICAL | HIGH | MEDIUM | LOW
    category:    str          # PRICING | ORDER | API | BALANCE | LOGIC
    description: str
    expected:    str
    actual:      str
    evidence:    dict = field(default_factory=dict)
    timestamp:   str  = field(default_factory=lambda: datetime.now().isoformat())


# ══════════════════════════════════════════════════════════════
# CHECK 1: ORDERBOOK INTEGRITY
# ══════════════════════════════════════════════════════════════

def check_orderbook_integrity(symbol: str) -> list:
    """
    Cek konsistensi orderbook:
    - Best bid harus < best ask (crossed book)
    - Spread tidak lebih dari 5% mid price
    - Bid harus urut descending, ask ascending
    - Harga dan qty harus positif
    """
    bugs = []
    ob   = get_orderbook(symbol, limit=20)
    if not ob:
        return bugs

    bids = ob.get("bids", [])
    asks = ob.get("asks", [])
    if not bids or not asks:
        return bugs

    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        # ── Crossed orderbook ─────────────────────────────────
        if best_bid >= best_ask:
            bugs.append(BugReport(
                title    = f"Crossed Orderbook — {symbol}",
                severity = "CRITICAL",
                category = "PRICING",
                description = (
                    f"Best bid ({best_bid}) >= best ask ({best_ask}) pada {symbol}. "
                    "Kondisi ini tidak seharusnya terjadi — matching engine "
                    "seharusnya langsung mencocokkan order ini."
                ),
                expected = f"best_bid < best_ask",
                actual   = f"best_bid={best_bid} >= best_ask={best_ask}",
                evidence = {"symbol": symbol, "best_bid": best_bid, "best_ask": best_ask,
                            "bids": bids[:3], "asks": asks[:3]},
            ))

        # ── Spread > 5% ───────────────────────────────────────
        mid_price  = (best_bid + best_ask) / 2
        spread_pct = ((best_ask - best_bid) / mid_price * 100) if mid_price > 0 else 0
        if spread_pct > 5.0:
            bugs.append(BugReport(
                title    = f"Spread Tidak Wajar — {symbol}",
                severity = "MEDIUM",
                category = "PRICING",
                description = (
                    f"Spread {symbol} sebesar {spread_pct:.2f}% dari mid price. "
                    "Spread > 5% mengindikasikan masalah pada liquidity seeding."
                ),
                expected = "Spread < 5%",
                actual   = f"Spread = {spread_pct:.2f}% (bid={best_bid}, ask={best_ask})",
                evidence = {"symbol": symbol, "spread_pct": spread_pct,
                            "best_bid": best_bid, "best_ask": best_ask},
            ))

        # ── Urutan bid harus descending ───────────────────────
        bid_prices = [float(b[0]) for b in bids]
        if bid_prices != sorted(bid_prices, reverse=True):
            bugs.append(BugReport(
                title    = f"Urutan Bid Tidak Valid — {symbol}",
                severity = "HIGH",
                category = "PRICING",
                description = f"Bid pada {symbol} tidak urut descending.",
                expected = "Bid prices descending (tertinggi di atas)",
                actual   = f"Urutan: {bid_prices[:5]}",
                evidence = {"symbol": symbol, "bid_prices": bid_prices[:10]},
            ))

        # ── Urutan ask harus ascending ────────────────────────
        ask_prices = [float(a[0]) for a in asks]
        if ask_prices != sorted(ask_prices):
            bugs.append(BugReport(
                title    = f"Urutan Ask Tidak Valid — {symbol}",
                severity = "HIGH",
                category = "PRICING",
                description = f"Ask pada {symbol} tidak urut ascending.",
                expected = "Ask prices ascending (terendah di atas)",
                actual   = f"Urutan: {ask_prices[:5]}",
                evidence = {"symbol": symbol, "ask_prices": ask_prices[:10]},
            ))

        # ── Harga/qty nol atau negatif ────────────────────────
        for i, entry in enumerate(bids[:5]):
            p, q = float(entry[0]), float(entry[1])
            if p <= 0 or q <= 0:
                bugs.append(BugReport(
                    title    = f"Harga/Qty Tidak Valid di Bid — {symbol}",
                    severity = "HIGH", category = "PRICING",
                    description = f"Bid index {i}: price={p}, qty={q}",
                    expected = "price > 0 dan qty > 0",
                    actual   = f"price={p}, qty={q}",
                    evidence = {"symbol": symbol, "index": i, "entry": entry},
                ))

        for i, entry in enumerate(asks[:5]):
            p, q = float(entry[0]), float(entry[1])
            if p <= 0 or q <= 0:
                bugs.append(BugReport(
                    title    = f"Harga/Qty Tidak Valid di Ask — {symbol}",
                    severity = "HIGH", category = "PRICING",
                    description = f"Ask index {i}: price={p}, qty={q}",
                    expected = "price > 0 dan qty > 0",
                    actual   = f"price={p}, qty={q}",
                    evidence = {"symbol": symbol, "index": i, "entry": entry},
                ))

    except (ValueError, IndexError) as e:
        log.debug(f"check_orderbook_integrity {symbol}: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 2: TICKER vs ORDERBOOK CONSISTENCY
# ══════════════════════════════════════════════════════════════

def check_ticker_vs_orderbook(symbol: str) -> list:
    """
    Cek konsistensi antara data ticker dan orderbook:
    - Last price harus berada dalam rentang bid-ask
    - 24h high harus >= 24h low
    - Last price harus dalam rentang 24h high-low
    """
    bugs   = []
    tickers = get_tickers(symbol)
    ob      = get_orderbook(symbol, limit=1)
    if not tickers or not ob:
        return bugs

    ticker = tickers[0]
    bids   = ob.get("bids", [])
    asks   = ob.get("asks", [])
    if not bids or not asks:
        return bugs

    try:
        last_price = float(ticker.get("lastPrice", 0))
        high_24h   = float(ticker.get("high",      0))
        low_24h    = float(ticker.get("low",        0))
        best_bid   = float(bids[0][0])
        best_ask   = float(asks[0][0])

        # ── Last price di luar spread (toleransi 1%) ──────────
        tol = best_ask * 0.01
        if last_price > best_ask + tol or last_price < best_bid - tol:
            bugs.append(BugReport(
                title    = f"Last Price di Luar Spread — {symbol}",
                severity = "MEDIUM", category = "PRICING",
                description = (
                    f"Last trade price ({last_price}) di luar rentang "
                    f"bid-ask ({best_bid}–{best_ask}). Bisa indikasi lag atau bug price feed."
                ),
                expected = f"last_price dalam {best_bid}–{best_ask}",
                actual   = f"last_price = {last_price}",
                evidence = {"symbol": symbol, "last_price": last_price,
                            "best_bid": best_bid, "best_ask": best_ask},
            ))

        # ── 24h high < 24h low ────────────────────────────────
        if high_24h > 0 and low_24h > 0 and high_24h < low_24h:
            bugs.append(BugReport(
                title    = f"24h High < 24h Low — {symbol}",
                severity = "HIGH", category = "PRICING",
                description = f"24h high ({high_24h}) < 24h low ({low_24h}) pada {symbol}.",
                expected = "high_24h >= low_24h",
                actual   = f"high={high_24h}, low={low_24h}",
                evidence = {"symbol": symbol, "high_24h": high_24h, "low_24h": low_24h},
            ))

        # ── Last price di luar range 24h ──────────────────────
        if high_24h > 0 and low_24h > 0:
            if last_price > high_24h * 1.01 or last_price < low_24h * 0.99:
                bugs.append(BugReport(
                    title    = f"Last Price di Luar 24h Range — {symbol}",
                    severity = "MEDIUM", category = "PRICING",
                    description = (
                        f"Last price ({last_price}) di luar range 24h "
                        f"(low={low_24h}, high={high_24h})."
                    ),
                    expected = f"{low_24h} <= last_price <= {high_24h}",
                    actual   = f"last_price = {last_price}",
                    evidence = {"symbol": symbol, "last_price": last_price,
                                "high_24h": high_24h, "low_24h": low_24h},
                ))

    except (ValueError, KeyError) as e:
        log.debug(f"check_ticker_vs_orderbook {symbol}: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 3: API RESPONSE CONSISTENCY
# ══════════════════════════════════════════════════════════════

def check_api_response_consistency() -> list:
    """
    Cek field wajib ada di semua response envelope dan object data.
    """
    bugs = []

    # ── Symbols endpoint ──────────────────────────────────────
    try:
        r    = requests.get(f"{BASE_URL}/markets/symbols", headers=PUBLIC_HEADERS, timeout=10)
        data = r.json()

        for f in ["code", "timestamp", "data"]:
            if f not in data:
                bugs.append(BugReport(
                    title    = f"Field '{f}' Hilang dari Response Envelope",
                    severity = "HIGH", category = "API",
                    description = f"Field '{f}' tidak ada di GET /markets/symbols.",
                    expected = f"Response memiliki field '{f}'",
                    actual   = f"Keys: {list(data.keys())}",
                    evidence = {"endpoint": "/markets/symbols", "keys": list(data.keys())},
                ))

        symbols = data.get("data", [])
        if symbols:
            required = ["symbol", "symbolID", "tickSize", "stepSize",
                        "pricePrecision", "quantityPrecision", "minQuantity"]
            sample = symbols[0]
            for f in required:
                if f not in sample:
                    bugs.append(BugReport(
                        title    = f"Field '{f}' Hilang dari SpotSymbol Object",
                        severity = "MEDIUM", category = "API",
                        description = f"Field '{f}' tidak ada di SpotSymbol object.",
                        expected = f"SpotSymbol memiliki field '{f}'",
                        actual   = f"Keys: {list(sample.keys())}",
                        evidence = {"sample_keys": list(sample.keys())},
                    ))
    except Exception as e:
        log.debug(f"check_api_response_consistency: {e}")

    # ── Tickers endpoint ──────────────────────────────────────
    try:
        r    = requests.get(f"{BASE_URL}/markets/tickers", headers=PUBLIC_HEADERS, timeout=10)
        data = r.json()
        if data.get("code") == 0:
            tickers = data.get("data", [])
            if tickers:
                required = ["symbol", "lastPrice", "high", "low", "volume"]
                sample   = tickers[0]
                for f in required:
                    if f not in sample:
                        bugs.append(BugReport(
                            title    = f"Field '{f}' Hilang dari SpotTicker Object",
                            severity = "LOW", category = "API",
                            description = f"Field '{f}' tidak ada di SpotTicker.",
                            expected = f"SpotTicker memiliki field '{f}'",
                            actual   = f"Keys: {list(sample.keys())}",
                            evidence = {"sample_keys": list(sample.keys())},
                        ))
    except Exception as e:
        log.debug(f"check_api_response_consistency tickers: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 4: API ERROR HANDLING
# ══════════════════════════════════════════════════════════════

def check_api_error_handling() -> list:
    """
    Cek apakah API menangani request tidak valid dengan benar.
    Semua request di sini bersifat GET ke public endpoint.
    """
    bugs = []

    # ── Endpoint tidak ada → harusnya 404, bukan 500 ─────────
    try:
        r = requests.get(
            f"{BASE_URL}/markets/nonexistent_endpoint_xyz",
            headers=PUBLIC_HEADERS, timeout=10
        )
        if r.status_code == 500:
            bugs.append(BugReport(
                title    = "HTTP 500 untuk Endpoint yang Tidak Ada",
                severity = "MEDIUM", category = "API",
                description = "Request ke endpoint tidak valid mengembalikan 500 bukan 404.",
                expected = "HTTP 404 Not Found",
                actual   = f"HTTP {r.status_code}",
                evidence = {"endpoint": "/markets/nonexistent_endpoint_xyz",
                            "status_code": r.status_code},
            ))
    except Exception as e:
        log.debug(f"check_api_error_handling 404: {e}")

    # ── Symbol tidak valid → harusnya error ───────────────────
    try:
        r = requests.get(
            f"{BASE_URL}/markets/INVALID_PAIR_XYZ123/orderbook",
            headers=PUBLIC_HEADERS, timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            bugs.append(BugReport(
                title    = "Symbol Tidak Valid Mengembalikan Success (code=0)",
                severity = "HIGH", category = "API",
                description = "Request orderbook 'INVALID_PAIR_XYZ123' mengembalikan code=0.",
                expected = "code != 0 dengan pesan error",
                actual   = f"code=0, data={str(d.get('data'))[:100]}",
                evidence = {"endpoint": "/markets/INVALID_PAIR_XYZ123/orderbook", "response": d},
            ))
    except Exception as e:
        log.debug(f"check_api_error_handling invalid symbol: {e}")

    # ── Limit parameter melebihi batas (max=1000 per docs) ────
    try:
        r = requests.get(
            f"{BASE_URL}/markets/vBTC_vUSDC/orderbook",
            params={"limit": 99999},
            headers=PUBLIC_HEADERS, timeout=10
        )
        d = r.json()
        if d.get("code") == 0:
            data   = d.get("data", {})
            total  = len(data.get("bids", [])) + len(data.get("asks", []))
            if total > 2000:
                bugs.append(BugReport(
                    title    = "Parameter 'limit' Melewati Batas Tidak Divalidasi",
                    severity = "LOW", category = "API",
                    description = (
                        f"limit=99999 (max=1000 per docs) mengembalikan {total} entries "
                        "tanpa error validasi."
                    ),
                    expected = "Dibatasi ke max 1000, atau error validasi",
                    actual   = f"Mengembalikan {total} entries",
                    evidence = {"requested_limit": 99999, "actual_entries": total},
                ))
    except Exception as e:
        log.debug(f"check_api_error_handling limit: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 5: SYMBOL CONSTRAINTS VALIDITY
# ══════════════════════════════════════════════════════════════

def check_symbol_constraints(all_symbols: list) -> list:
    """
    Cek validitas constraint yang dideklarasikan setiap symbol.
    """
    bugs = []

    for sym in all_symbols:
        name = sym.get("symbol", "?")
        try:
            tick_size  = float(sym.get("tickSize",  0))
            step_size  = float(sym.get("stepSize",  0))
            min_price  = float(sym.get("minPrice",  0))
            max_price  = float(sym.get("maxPrice",  0))
            min_qty    = float(sym.get("minQuantity", 0))
            max_qty    = float(sym.get("maxQuantity", 0))
            price_prec = int(sym.get("pricePrecision", 0))
            qty_prec   = int(sym.get("quantityPrecision", 0))

            if tick_size <= 0:
                bugs.append(BugReport(
                    title=f"tickSize Tidak Valid — {name}", severity="HIGH", category="LOGIC",
                    description=f"tickSize={tick_size} harus > 0.",
                    expected="tickSize > 0", actual=f"tickSize={tick_size}",
                    evidence={"symbol": name, "tickSize": tick_size},
                ))
            if step_size <= 0:
                bugs.append(BugReport(
                    title=f"stepSize Tidak Valid — {name}", severity="HIGH", category="LOGIC",
                    description=f"stepSize={step_size} harus > 0.",
                    expected="stepSize > 0", actual=f"stepSize={step_size}",
                    evidence={"symbol": name, "stepSize": step_size},
                ))
            if min_price > 0 and max_price > 0 and min_price > max_price:
                bugs.append(BugReport(
                    title=f"minPrice > maxPrice — {name}", severity="HIGH", category="LOGIC",
                    description=f"minPrice ({min_price}) > maxPrice ({max_price}).",
                    expected="minPrice <= maxPrice",
                    actual=f"minPrice={min_price}, maxPrice={max_price}",
                    evidence={"symbol": name, "minPrice": min_price, "maxPrice": max_price},
                ))
            if min_qty > 0 and max_qty > 0 and min_qty > max_qty:
                bugs.append(BugReport(
                    title=f"minQuantity > maxQuantity — {name}", severity="HIGH", category="LOGIC",
                    description=f"minQuantity ({min_qty}) > maxQuantity ({max_qty}).",
                    expected="minQuantity <= maxQuantity",
                    actual=f"minQuantity={min_qty}, maxQuantity={max_qty}",
                    evidence={"symbol": name, "minQty": min_qty, "maxQty": max_qty},
                ))
            if price_prec < 0:
                bugs.append(BugReport(
                    title=f"pricePrecision Negatif — {name}", severity="MEDIUM", category="LOGIC",
                    description=f"pricePrecision={price_prec} harus >= 0.",
                    expected="pricePrecision >= 0", actual=f"pricePrecision={price_prec}",
                    evidence={"symbol": name, "pricePrecision": price_prec},
                ))
            if qty_prec < 0:
                bugs.append(BugReport(
                    title=f"quantityPrecision Negatif — {name}", severity="MEDIUM", category="LOGIC",
                    description=f"quantityPrecision={qty_prec} harus >= 0.",
                    expected="quantityPrecision >= 0", actual=f"quantityPrecision={qty_prec}",
                    evidence={"symbol": name, "quantityPrecision": qty_prec},
                ))
        except (ValueError, TypeError) as e:
            log.debug(f"check_symbol_constraints {name}: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 6: CROSS-PAIR PRICE CONSISTENCY
# ══════════════════════════════════════════════════════════════

def check_price_deviation_across_pairs() -> list:
    """
    Cek apakah harga implied antar pair konsisten.
    Contoh: BTC/USDC dan ETH/USDC → implied BTC/ETH.
    Deviasi > 2% dari harga aktual BTC/ETH menunjukkan inkonsistensi.
    """
    bugs   = []
    try:
        tickers = get_tickers()
        if not tickers:
            return bugs

        usdc_prices = {}
        for t in tickers:
            sym   = t.get("symbol", "")
            price = float(t.get("lastPrice", 0))
            if price > 0 and sym.endswith("_vUSDC"):
                base = sym.replace("_vUSDC", "")
                usdc_prices[base] = price

        for t in tickers:
            sym   = t.get("symbol", "")
            price = float(t.get("lastPrice", 0))
            if price <= 0 or "_vUSDC" in sym:
                continue

            parts = sym.split("_")
            if len(parts) != 2:
                continue

            base, quote = parts
            if base in usdc_prices and quote in usdc_prices:
                implied   = usdc_prices[base] / usdc_prices[quote]
                deviation = abs(price - implied) / implied * 100

                if deviation > 2.0:
                    bugs.append(BugReport(
                        title    = f"Harga Implied Tidak Konsisten — {sym}",
                        severity = "MEDIUM", category = "PRICING",
                        description = (
                            f"Harga {sym} ({price}) menyimpang {deviation:.2f}% dari "
                            f"implied price ({implied:.6f}) berdasarkan pair USDC."
                        ),
                        expected = f"Harga {sym} ≈ {implied:.6f} (±2%)",
                        actual   = f"Harga = {price} (deviasi {deviation:.2f}%)",
                        evidence = {
                            "symbol": sym, "market_price": price,
                            "implied_price": implied, "deviation_pct": deviation,
                            f"{base}_usdc": usdc_prices[base],
                            f"{quote}_usdc": usdc_prices[quote],
                        },
                    ))
    except Exception as e:
        log.debug(f"check_price_deviation_across_pairs: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 7: BALANCE CONSISTENCY
# ══════════════════════════════════════════════════════════════

def check_balance_consistency() -> list:
    """
    Cek: total = free + locked, tidak ada nilai negatif.
    """
    bugs = []
    bal  = get_balances()
    if not bal:
        return bugs

    for b in (bal.get("balances") or []):
        coin = b.get("coin", "?")
        try:
            free   = float(b.get("free",   0))
            locked = float(b.get("locked", 0))
            total  = float(b.get("total",  0))

            if free < 0:
                bugs.append(BugReport(
                    title=f"Saldo 'free' Negatif — {coin}", severity="CRITICAL", category="BALANCE",
                    description=f"free balance negatif: {free}",
                    expected="free >= 0", actual=f"free={free}",
                    evidence={"coin": coin, "free": free, "locked": locked, "total": total},
                ))
            if locked < 0:
                bugs.append(BugReport(
                    title=f"Saldo 'locked' Negatif — {coin}", severity="CRITICAL", category="BALANCE",
                    description=f"locked balance negatif: {locked}",
                    expected="locked >= 0", actual=f"locked={locked}",
                    evidence={"coin": coin, "free": free, "locked": locked, "total": total},
                ))
            expected_total = round(free + locked, 8)
            if abs(total - expected_total) > 0.00001:
                bugs.append(BugReport(
                    title=f"Total Balance Tidak Konsisten — {coin}", severity="HIGH", category="BALANCE",
                    description=f"total ({total}) != free ({free}) + locked ({locked}) = {expected_total}",
                    expected=f"total = {expected_total}",
                    actual=f"total = {total}",
                    evidence={"coin": coin, "free": free, "locked": locked,
                              "total": total, "expected": expected_total},
                ))
        except (ValueError, TypeError) as e:
            log.debug(f"check_balance_consistency {coin}: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 8: PRECISION & ROUNDING VALIDATION (READ-ONLY)
# ══════════════════════════════════════════════════════════════

def check_precision_validation(all_symbols: list) -> list:
    """
    Bandingkan data aktual orderbook dengan constraint pricePrecision,
    quantityPrecision, tickSize, stepSize yang dideklarasikan symbol.
    Kalau ada data live yang melanggar constraint-nya sendiri = bug.
    Murni read-only: hanya GET orderbook.
    """
    bugs = []

    for sym in all_symbols[:10]:
        name = sym.get("symbol", "?")
        try:
            price_prec = int(sym.get("pricePrecision", 8))
            qty_prec   = int(sym.get("quantityPrecision", 8))
            tick_size  = float(sym.get("tickSize", 0))
            step_size  = float(sym.get("stepSize", 0))

            ob = get_orderbook(name, limit=10)
            if not ob:
                continue

            violations = []

            for side_key, label in [("bids", "bid"), ("asks", "ask")]:
                for entry in ob.get(side_key, []):
                    try:
                        price = float(entry[0])
                        qty   = float(entry[1])

                        # Cek decimal places harga
                        price_str  = f"{price:.10f}".rstrip("0")
                        dec_part   = price_str.split(".")[-1] if "." in price_str else ""
                        if len(dec_part) > price_prec:
                            violations.append({
                                "type": "price_precision", "side": label,
                                "price": price, "declared": price_prec, "actual": len(dec_part),
                            })

                        # Cek decimal places qty
                        qty_str  = f"{qty:.10f}".rstrip("0")
                        dec_part = qty_str.split(".")[-1] if "." in qty_str else ""
                        if len(dec_part) > qty_prec:
                            violations.append({
                                "type": "qty_precision", "side": label,
                                "qty": qty, "declared": qty_prec, "actual": len(dec_part),
                            })

                        # Cek tick size
                        if tick_size > 0:
                            remainder = round(price % tick_size, 10)
                            if remainder > 1e-9 and abs(remainder - tick_size) > 1e-9:
                                violations.append({
                                    "type": "tick_size", "side": label,
                                    "price": price, "tick_size": tick_size, "remainder": remainder,
                                })

                        # Cek step size
                        if step_size > 0:
                            remainder = round(qty % step_size, 10)
                            if remainder > 1e-9 and abs(remainder - step_size) > 1e-9:
                                violations.append({
                                    "type": "step_size", "side": label,
                                    "qty": qty, "step_size": step_size, "remainder": remainder,
                                })

                    except (ValueError, IndexError):
                        continue

            if violations:
                bugs.append(BugReport(
                    title    = f"Data Orderbook Melanggar Constraint Symbol — {name}",
                    severity = "HIGH", category = "LOGIC",
                    description = (
                        f"{len(violations)} entri orderbook {name} melanggar "
                        "constraint pricePrecision/quantityPrecision/tickSize/stepSize "
                        "yang dideklarasikan di /markets/symbols."
                    ),
                    expected = (
                        f"Semua harga kelipatan tickSize={tick_size} & max {price_prec} desimal. "
                        f"Semua qty kelipatan stepSize={step_size} & max {qty_prec} desimal."
                    ),
                    actual   = f"{len(violations)} pelanggaran",
                    evidence = {"symbol": name, "price_precision": price_prec,
                                "qty_precision": qty_prec, "tick_size": tick_size,
                                "step_size": step_size, "violations": violations[:5]},
                ))

            time.sleep(0.2)

        except Exception as e:
            log.debug(f"check_precision_validation {name}: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 9: RATE LIMIT HEADER CONSISTENCY (READ-ONLY)
# ══════════════════════════════════════════════════════════════

def check_rate_limit_headers() -> list:
    """
    Dokumentasi SoDEX menyebut rate limit 1200 weight/menit.
    Cek apakah response header rate limit ada dan konsisten antar endpoint.
    Murni read-only: hanya GET ke public endpoint.
    """
    bugs = []

    endpoints = [
        "/markets/symbols",
        "/markets/tickers",
        "/markets/vBTC_vUSDC/orderbook",
    ]

    known_rl_headers = [
        "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
        "X-MBX-USED-WEIGHT", "X-RateLimit-Used-Weight",
        "RateLimit-Limit",   "RateLimit-Remaining",
    ]

    results = []
    for path in endpoints:
        try:
            r = requests.get(f"{BASE_URL}{path}", headers=PUBLIC_HEADERS, timeout=10)
            found = {h: r.headers.get(h) for h in known_rl_headers if r.headers.get(h)}
            results.append({"endpoint": path, "rl_headers": found,
                            "all_header_keys": list(r.headers.keys())})
            time.sleep(0.2)
        except Exception as e:
            log.debug(f"check_rate_limit_headers {path}: {e}")

    if not results:
        return bugs

    without_rl = [r["endpoint"] for r in results if not r["rl_headers"]]

    # Tidak ada header rate limit sama sekali
    if len(without_rl) == len(results):
        bugs.append(BugReport(
            title    = "Tidak Ada Header Rate Limit di Response",
            severity = "LOW", category = "API",
            description = (
                "Dokumentasi menyebut rate limit 1200 weight/menit, tapi "
                "tidak ada header rate limit di response manapun. "
                "Client tidak bisa memantau penggunaan rate limit secara proaktif."
            ),
            expected = "Header seperti X-RateLimit-Remaining tersedia",
            actual   = "Tidak ada header rate limit ditemukan",
            evidence = {"endpoints_checked": [r["endpoint"] for r in results],
                        "sample_headers": results[0]["all_header_keys"][:20]},
        ))

    # Ada di sebagian endpoint tapi tidak semua
    elif len(without_rl) > 0:
        bugs.append(BugReport(
            title    = "Header Rate Limit Tidak Konsisten Antar Endpoint",
            severity = "LOW", category = "API",
            description = "Beberapa endpoint punya header rate limit, sebagian tidak.",
            expected = "Semua endpoint mengembalikan header rate limit",
            actual   = f"Endpoint tanpa header: {without_rl}",
            evidence = {"with_headers":    [r["endpoint"] for r in results if r["rl_headers"]],
                        "without_headers": without_rl},
        ))

    return bugs


# ══════════════════════════════════════════════════════════════
# CHECK 10: WEBSOCKET vs REST CONSISTENCY (READ-ONLY)
# ══════════════════════════════════════════════════════════════

def check_websocket_vs_rest(symbol: str = "vBTC_vUSDC") -> list:
    """
    Snapshot harga dari REST, lalu connect WebSocket sebentar
    dan bandingkan data pertama yang datang.
    Deviasi > 0.5% = indikasi kedua feed tidak sinkron.
    Murni read-only: tidak mengirim order, hanya subscribe data.
    """
    bugs   = []
    WS_URL = "wss://testnet-gw.sodex.dev/ws/spot"

    # ── Step 1: REST snapshot ─────────────────────────────────
    try:
        rest_ob     = get_orderbook(symbol, limit=1)
        rest_ticker = get_tickers(symbol)
        if not rest_ob or not rest_ticker:
            return bugs
        rest_best_bid = float(rest_ob.get("bids", [[0]])[0][0])
        rest_best_ask = float(rest_ob.get("asks", [[0]])[0][0])
        rest_ts       = time.time()
    except Exception as e:
        log.debug(f"check_websocket_vs_rest REST: {e}")
        return bugs

    # ── Step 2: Coba import websocket-client ──────────────────
    try:
        import websocket as ws_lib
    except ImportError:
        bugs.append(BugReport(
            title    = "Library websocket-client Tidak Terinstall",
            severity = "LOW", category = "API",
            description = "Check WebSocket vs REST tidak bisa jalan karena library tidak ada.",
            expected = "websocket-client tersedia",
            actual   = "ModuleNotFoundError: websocket-client",
            evidence = {"fix": "pip install websocket-client --break-system-packages"},
        ))
        return bugs

    # ── Step 3: Connect WS dan tangkap 1 pesan ───────────────
    ws_data  = {}
    ws_error = {}
    received = threading.Event()

    def on_message(wsapp, message):
        try:
            ws_data["msg"] = json.loads(message)
            ws_data["ts"]  = time.time()
        except Exception:
            pass
        received.set()
        wsapp.close()

    def on_error(wsapp, error):
        ws_error["err"] = str(error)
        received.set()

    def on_open(wsapp):
        wsapp.send(json.dumps({
            "op":     "subscribe",
            "topics": [f"orderbook.1.{symbol}"],
        }))

    try:
        wsapp = ws_lib.WebSocketApp(
            WS_URL, on_open=on_open, on_message=on_message, on_error=on_error,
        )
        t = threading.Thread(target=wsapp.run_forever, daemon=True)
        t.start()
        received.wait(timeout=8)
    except Exception as e:
        log.debug(f"check_websocket_vs_rest connect: {e}")
        return bugs

    # ── Cek error koneksi ─────────────────────────────────────
    if ws_error.get("err"):
        bugs.append(BugReport(
            title    = "WebSocket Testnet Tidak Bisa Dikoneksi",
            severity = "MEDIUM", category = "API",
            description = f"Koneksi ke {WS_URL} gagal.",
            expected = f"Koneksi sukses ke {WS_URL}",
            actual   = f"Error: {ws_error['err']}",
            evidence = {"ws_url": WS_URL, "symbol": symbol, "error": ws_error["err"]},
        ))
        return bugs

    if not ws_data.get("msg"):
        bugs.append(BugReport(
            title    = "WebSocket Tidak Kirim Data dalam 8 Detik",
            severity = "MEDIUM", category = "API",
            description = f"Subscribe ke 'orderbook.1.{symbol}' tapi tidak ada data masuk.",
            expected = "Data diterima dalam < 5 detik",
            actual   = "Tidak ada data dalam 8 detik",
            evidence = {"ws_url": WS_URL, "symbol": symbol},
        ))
        return bugs

    # ── Step 4: Bandingkan WS vs REST ────────────────────────
    try:
        msg  = ws_data["msg"]
        lag  = ws_data["ts"] - rest_ts
        data = msg.get("data", msg)

        ws_bid = ws_ask = None
        if isinstance(data, dict):
            bids = data.get("bids") or data.get("b", [])
            asks = data.get("asks") or data.get("a", [])
            if bids:
                ws_bid = float(bids[0][0])
            if asks:
                ws_ask = float(asks[0][0])

        if ws_bid and ws_ask:
            tol      = rest_best_bid * 0.005
            bid_diff = abs(ws_bid - rest_best_bid)
            ask_diff = abs(ws_ask - rest_best_ask)

            if bid_diff > tol or ask_diff > tol:
                bugs.append(BugReport(
                    title    = f"WebSocket dan REST Tidak Sinkron — {symbol}",
                    severity = "MEDIUM", category = "API",
                    description = (
                        f"Data orderbook WS berbeda signifikan dari REST pada {symbol}. "
                        f"Bid diff: {bid_diff:.6f}, Ask diff: {ask_diff:.6f} (lag: {lag:.2f}s)."
                    ),
                    expected = "WS dan REST konsisten (toleransi 0.5%)",
                    actual   = (f"REST: bid={rest_best_bid} ask={rest_best_ask} | "
                                f"WS: bid={ws_bid} ask={ws_ask}"),
                    evidence = {"symbol": symbol, "rest_bid": rest_best_bid, "rest_ask": rest_best_ask,
                                "ws_bid": ws_bid, "ws_ask": ws_ask,
                                "bid_diff": bid_diff, "ask_diff": ask_diff, "lag_s": lag},
                ))
    except Exception as e:
        log.debug(f"check_websocket_vs_rest compare: {e}")

    return bugs


# ══════════════════════════════════════════════════════════════
# REPORT WRITER
# ══════════════════════════════════════════════════════════════

def format_report_text(bugs: list, scan_duration: float) -> str:
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep  = "=" * 60
    sep2 = "-" * 60

    lines = [
        sep,
        "  SoDEX TESTNET — BUG REPORT",
        f"  Tanggal      : {now}",
        f"  Wallet       : {WALLET_ADDRESS}",
        f"  Durasi scan  : {scan_duration:.1f} detik",
        f"  Bug ditemukan: {len(bugs)}",
        sep, "",
    ]

    if not bugs:
        lines.append("✅  Tidak ada anomali ditemukan pada scan ini.")
        return "\n".join(lines)

    order   = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    grouped = {s: [b for b in bugs if b.severity == s] for s in order}
    emoji_map = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}

    lines.append("📊  RINGKASAN")
    lines.append(sep2)
    for sev in order:
        count = len(grouped[sev])
        if count:
            lines.append(f"  {emoji_map[sev]}  {sev:<10}: {count} bug")
    lines.append("")

    bug_num = 0
    for sev in order:
        for bug in grouped[sev]:
            bug_num += 1
            lines += [
                sep2,
                f"  Bug #{bug_num}  {emoji_map[sev]} [{bug.severity}] [{bug.category}]",
                f"  Judul     : {bug.title}",
                f"  Waktu     : {bug.timestamp}",
                "",
                f"  DESKRIPSI",
                f"  {bug.description}",
                "",
                f"  EXPECTED  : {bug.expected}",
                f"  ACTUAL    : {bug.actual}",
                "",
                "  EVIDENCE (JSON):",
                f"  {json.dumps(bug.evidence, indent=4)}",
                "",
            ]

    lines += [sep,
              "  Laporan ini di-generate otomatis oleh SoDEX Bug Detector.",
              "  Kirim ke tim SoDEX untuk diklaim sebagai bug bounty points.",
              sep]
    return "\n".join(lines)


def save_report(text: str, bug_count: int) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORT_DIR, f"bug_{ts}_found{bug_count}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ══════════════════════════════════════════════════════════════
# MAIN SCAN LOOP
# ══════════════════════════════════════════════════════════════

SEVERITY_COLOR = {
    "CRITICAL": "\033[91m", "HIGH": "\033[93m",
    "MEDIUM":   "\033[94m", "LOW":  "\033[96m",
    "RESET":    "\033[0m",
}

def cprint(text, color="RESET"):
    print(f"{SEVERITY_COLOR.get(color, '')}{text}{SEVERITY_COLOR['RESET']}")


def run_scan(all_symbols: list, sample_size: int = 5) -> list:
    """Jalankan semua 10 check dan kumpulkan bug."""
    all_bugs        = []
    symbols_to_check = [s.get("symbol") for s in all_symbols[:sample_size] if s.get("symbol")]
    first_symbol     = symbols_to_check[0] if symbols_to_check else "vBTC_vUSDC"

    print(f"\n  🔍 Scanning {len(symbols_to_check)} pairs, 10 check categories...")

    checks = [
        ("API response consistency",       lambda: check_api_response_consistency()),
        ("API error handling",             lambda: check_api_error_handling()),
        ("Symbol constraints",             lambda: check_symbol_constraints(all_symbols)),
        ("Balance consistency",            lambda: check_balance_consistency()),
        ("Cross-pair price deviation",     lambda: check_price_deviation_across_pairs()),
        ("Precision & rounding validation",lambda: check_precision_validation(all_symbols)),
        ("Rate limit headers",             lambda: check_rate_limit_headers()),
        (f"WebSocket vs REST ({first_symbol})", lambda: check_websocket_vs_rest(first_symbol)),
    ]

    for label, fn in checks:
        print(f"     ├─ {label}...")
        try:
            all_bugs += fn()
        except Exception as e:
            log.debug(f"check error [{label}]: {e}")

    # Per-pair checks
    for sym in symbols_to_check:
        print(f"     ├─ Orderbook + ticker: {sym}...")
        try:
            all_bugs += check_orderbook_integrity(sym)
            all_bugs += check_ticker_vs_orderbook(sym)
        except Exception as e:
            log.debug(f"per-pair check error {sym}: {e}")
        time.sleep(0.3)

    print(f"     └─ Selesai.")
    return all_bugs


def run_detector():
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    cprint("\n" + "=" * 55)
    cprint("  🐛  SoDEX Bug Detector  —  START")
    cprint(f"  Wallet   : {WALLET_ADDRESS}")
    cprint(f"  Interval : setiap {MONITOR_INTERVAL}s")
    cprint(f"  Output   : ./{REPORT_DIR}/")
    cprint("=" * 55)

    if not WALLET_ADDRESS:
        cprint("❌  WALLET_ADDRESS tidak ada di .env — berhenti.", "CRITICAL")
        return

    scan_count = 0

    while True:
        scan_count += 1
        cprint(f"\n🔄  SCAN #{scan_count}  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        start      = time.time()
        all_symbols = get_symbols()

        if not all_symbols:
            cprint("  ⚠️  Tidak bisa ambil symbol list, skip scan ini.", "HIGH")
            time.sleep(MONITOR_INTERVAL)
            continue

        bugs     = run_scan(all_symbols, sample_size=5)
        duration = time.time() - start

        if not bugs:
            cprint(f"\n  ✅  Tidak ada anomali ({duration:.1f}s)")
        else:
            cprint(f"\n  ⚠️  {len(bugs)} anomali ditemukan ({duration:.1f}s)!")
            emoji_map = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}
            for b in bugs:
                cprint(f"     {emoji_map.get(b.severity,'⚪')} [{b.severity}] {b.title}", b.severity)

            report_text = format_report_text(bugs, duration)
            path        = save_report(report_text, len(bugs))
            cprint(f"\n  📄  Laporan: {path}")
            cprint(f"      Kirim isi file ini ke SoDEX untuk bug bounty points!")

        cprint(f"\n  ⏳  Scan berikutnya dalam {MONITOR_INTERVAL}s... (Ctrl+C untuk keluar)")

        try:
            time.sleep(MONITOR_INTERVAL)
        except KeyboardInterrupt:
            cprint("\n\n  Bug Detector dihentikan. Sampai jumpa!")
            break


if __name__ == "__main__":
    run_detector()
