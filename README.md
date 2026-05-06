# 🤖 SoDEX Testnet Auto Trading Bot

Bot otomatis untuk farming points di [SoDEX Testnet](https://testnet.sodex.com).  
Mendukung 3 mode trading + monitoring points secara otomatis.

---

## 📁 Struktur File

```
sodex-bot/
├── bot.py            ← Engine utama & main loop
├── monitor.py        ← Monitor points, balance, volume (jalankan terpisah)
├── config.py         ← Semua pengaturan (edit di sini)
├── api.py            ← HTTP calls ke SoDEX REST API
├── signer.py         ← EIP-712 signing untuk auth
├── .env.example      ← Template kredensial
├── .env              ← Kredensial kamu (JANGAN di-commit!)
├── requirements.txt
└── README.md
```

---

## 🚀 Setup di VPS Linux

### 1. Clone repo
```bash
git clone https://github.com/username/sodex-bot.git
cd sodex-bot
```

### 2. Install dependencies
```bash
pip install -r requirements.txt --break-system-packages
```

### 3. Buat file `.env`
```bash
cp .env.example .env
nano .env
chmod 600 .env
```
Isi:
```
PRIVATE_KEY=0x_private_key_kamu
WALLET_ADDRESS=0x_wallet_address_kamu
```

### 4. Jalankan bot
```bash
python bot.py
```

### 5. Jalankan monitor di terminal lain
```bash
python monitor.py
```

### 6. Jalankan keduanya di background (screen)
```bash
# Bot trading
screen -S bot
python bot.py
# Ctrl+A + D untuk detach

# Monitor
screen -S monitor
python monitor.py
# Ctrl+A + D untuk detach

# Lihat semua session
screen -ls

# Kembali ke session tertentu
screen -r bot
screen -r monitor
```

---

## ⚙️ Mode Bot

Edit `BOT_MODE` di `config.py`:

| Mode | Cara Kerja | Volume | Aman? |
|---|---|---|---|
| `limit` | Place & cancel limit order (GTX) | Lambat | ✅ Paling aman |
| `market` | Buy & sell market order kecil | Cepat | ⚠️ Saldo berkurang |
| `hybrid` | Campur limit & market | Sedang | ✅ Rekomendasi |

**Rekomendasi:** Gunakan `hybrid` — setiap 5 siklus sekali pakai market order untuk naikin volume, sisanya limit order yang aman.

---

## ⚙️ Konfigurasi Lengkap

Semua pengaturan ada di `config.py`:

### Mode & Strategy
| Setting | Default | Keterangan |
|---|---|---|
| `BOT_MODE` | `hybrid` | Mode bot: limit / market / hybrid |
| `HYBRID_MARKET_EVERY` | `5` | Market order setiap N siklus (mode hybrid) |

### Limit Order
| Setting | Default | Keterangan |
|---|---|---|
| `PRICE_OFFSET_TICKS` | `2` | Jarak harga dari spread |
| `TIME_IN_FORCE` | `3` (GTX) | 1=GTC, 2=IOC, 3=GTX post-only |
| `ORDER_HOLD_MIN` | `8` detik | Min tahan order sebelum cancel |
| `ORDER_HOLD_MAX` | `20` detik | Max tahan order sebelum cancel |

### Market Order
| Setting | Default | Keterangan |
|---|---|---|
| `MARKET_ORDER_USDC` | `"10"` | USDC per siklus market order |
| `MARKET_SLIPPAGE_RATIO` | `0.02` | 2% slippage tolerance |

### Timing
| Setting | Default | Keterangan |
|---|---|---|
| `CYCLE_DELAY_MIN` | `5` detik | Min jeda antar siklus |
| `CYCLE_DELAY_MAX` | `30` detik | Max jeda antar siklus |

### Monitor
| Setting | Default | Keterangan |
|---|---|---|
| `MONITOR_INTERVAL` | `60` detik | Interval refresh monitor |

---

## 📊 Fitur Monitor (`monitor.py`)

Menampilkan secara otomatis setiap N detik:
- 🏆 **Points & Rank** — total points dan posisi di leaderboard
- 💰 **Saldo akun** — semua coin dengan free & locked amount
- 📋 **Open orders** — order yang sedang aktif
- 📈 **Volume stats** — total volume, jumlah trade, pairs unik
- 📊 **Progress bar** — menuju target 100.000 USDC volume
- 🥇 **Leaderboard** — top 10 dengan highlight posisi kamu

---

## 🎯 Cara Dapat Points Maksimal

1. ✅ **Trading 10+ pairs** — bot sudah cover 12 pairs secara round-robin
2. ✅ **Volume > 100.000 USDC** — gunakan mode `hybrid` atau `market`
3. ✅ **Klaim faucet harian** — 100 USDC/hari di https://testnet.sodex.com/faucet (manual)
4. 📝 **Laporkan bug** — bisa dapat sampai 50.000 points per window
5. 🏆 **Masuk top 100 leaderboard** — dapat sampai 240.000 bonus points

---

## ⚠️ Penting

- Gunakan **wallet baru** khusus bot ini, bukan wallet utama
- **Jangan commit** file `.env` ke GitHub (sudah ada di `.gitignore`)
- Mode `market` akan **menghabiskan saldo** pelan-pelan karena ada taker fee
- Klaim faucet harian tetap **harus manual** via browser
- Sambungkan wallet ke SoDEX testnet via browser **minimal sekali** sebelum pakai bot

---

## 🔧 Troubleshooting

**Order selalu gagal:**
→ Pastikan sudah klaim faucet dan ada saldo USDC  
→ Cek wallet sudah terdaftar (login dulu via browser)

**`PRIVATE_KEY tidak ada`:**
→ Pastikan file `.env` sudah dibuat dan diisi

**Error koneksi:**
→ `curl https://testnet-gw.sodex.dev/api/v1/spot/markets/symbols`  
→ Kalau gagal, cek firewall VPS atau hubungi support SoDEX

**Monitor tidak tampil points:**
→ Points API mungkin butuh autentikasi atau endpoint berbeda  
→ Cek manual di https://testnet.sodex.com/points
