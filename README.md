# 🚀 Muse VPS Fleet Manager

Sistem kontrol terpusat untuk mengontrol **30 instans VPS Muse.ai Linux** dari satu **Dashboard Web** di PC Windows Anda.

---

## ⚡ Fitur Utama

| Fitur | Deskripsi |
|-------|-----------|
| **Fleet Dashboard** | Pantau 30 VPS secara real-time: status online/offline, RAM, CPU, uptime, tugas aktif |
| **YouTube Automation** | Cari video → tonton 5-10 menit → auto-like → kirim komentar acak (Playwright Chromium) |
| **Mining Manager** | Start/stop/update mining di semua VPS sekaligus, konfigurasi proxy & wallet dari dashboard |
| **Shell Runner** | Kirim perintah bash arbitrary ke satu atau semua VPS dari dashboard |
| **Buka URL Massal** | Perintahkan 30 VPS buka URL yang sama sekaligus |
| **Auto-Reconnect** | Agent VPS reconnect otomatis setiap 30 detik jika koneksi terputus |
| **Auto-Recovery Mining** | Mining otomatis dimulai ulang setelah VPS restart |

---

## 📁 Struktur File

```
muse-fleet-manager/
├── hub_server.py          # Server pusat + Dashboard Web (dijalankan di PC Windows)
├── agent.py               # Daemon agent (dijalankan di VPS ~/workspace/)
├── youtube_worker.py      # Otomasi browser YouTube via Playwright (VPS)
├── install_agent.sh       # Script instalasi 1-perintah untuk VPS Muse
├── requirements.txt       # Dependensi Python untuk PC (websockets, aiohttp)
├── requirements-vps.txt   # Dependensi Python untuk VPS (websockets, playwright)
├── cloudflared_setup.md   # Panduan lengkap Cloudflare Tunnel
└── README.md              # Dokumentasi ini
```

---

## 🏗️ Arsitektur Sistem

```
PC Windows Anda
┌──────────────────────────────────────────┐
│ hub_server.py                            │
│ ├── WebSocket Server (:9000) ← Agent VPS │
│ └── Dashboard Web    (:9001) ← Browser   │
└──────────────┬───────────────────────────┘
               │ Cloudflare Tunnel (gratis)
               │ https://xxxx.trycloudflare.com
               │
    ┌──────────┼──────────┐
    │          │          │
  VPS-01    VPS-02  ... VPS-30
  agent.py  agent.py    agent.py
    │
    ├── youtube_worker.py (Playwright)
    └── gaszep/ (graftcp + miner)
```

VPS Muse **tidak punya IP publik**, jadi setiap VPS menghubungi PC Anda melalui Cloudflare Tunnel.

---

## 🚀 Cara Penggunaan

### Langkah 1: Setup Hub Server di PC Windows

```cmd
cd C:\Users\Admin\Desktop\EXTENTION PROJECT MUSSE\muse-fleet-manager

:: Install dependensi
pip install -r requirements.txt

:: Jalankan Hub Server
python hub_server.py
```

Output yang diharapkan:
```
🚀 MEMULAI MUSE VPS FLEET MANAGER HUB SERVER
📡 Agent WebSocket Server : ws://0.0.0.0:9000
💻 Browser Dashboard Web UI : http://localhost:9001
```

### Langkah 2: Aktifkan Cloudflare Tunnel

Buka terminal **baru** (jangan tutup Hub Server!):

```cmd
cloudflared.exe tunnel --url http://localhost:9000
```

Salin URL publik yang muncul (contoh: `https://abc123xyz.trycloudflare.com`)

> 📖 Panduan lengkap: lihat `cloudflared_setup.md`

### Langkah 3: Buka Dashboard

Buka browser di PC Anda:
```
http://localhost:9001
```

### Langkah 4: Install Agent di Setiap VPS Muse

Copy-paste perintah berikut ke **chat Muse AI** atau terminal VPS:

```bash
bash install_agent.sh --hub wss://abc123xyz.trycloudflare.com --name Muse-01
```

> **Catatan:** Ganti `abc123xyz` dengan URL tunnel Anda yang sebenarnya.
> Ganti `Muse-01` menjadi `Muse-02`, `Muse-03`, dst.

Dalam beberapa detik, VPS akan muncul di Dashboard sebagai **Online** ✅.

Ulangi langkah ini untuk semua 30 VPS.

---

## 📺 YouTube Campaign

Dari Dashboard, buka tab **📺 YouTube Automation**:

1. Isi **Kata Kunci Pencarian** (contoh: "Tutorial Python Pemula")
2. Isi **Target Channel** (opsional, contoh: "@ProgrammerZamanNow")
3. Atur **Durasi Tonton** (default: 300-600 detik = 5-10 menit)
4. Centang **Auto-Like** dan **Auto-Comment**
5. Isi **Pool Komentar Acak** (1 per baris):
   ```
   Keren banget penjelasannya!
   Sangat bermanfaat
   Terima kasih tutornya kak
   ```
6. Klik **🚀 Jalankan Kampanye di SEMUA VPS**

Setiap VPS akan:
- Membuka YouTube dan mencari video
- Menonton video selama durasi acak
- Meng-klik Like (jika diaktifkan)
- Mengetik dan mengirim komentar acak

> ⚠️ **Syarat:** Browser di VPS harus sudah login ke akun Google/YouTube.
> Login perlu dilakukan **satu kali** secara manual, setelah itu cookies tersimpan permanen di `~/workspace/browser_profile/`.

---

## ⛏️ Mining Manager

Dari Dashboard, buka tab **⛏️ Mining Manager (graftcp)**:

1. Isi konfigurasi:
   - **SOCKS5 Proxy** (Dante server): `43.135.134.20:443`
   - **Username / Password**: sesuai server Anda
   - **Pool Address** (xmrig-proxy): `43.135.134.20:10080`
   - **Algoritma**: `rx/0` (Monero/Zephyr)
   - **Wallet Address**: alamat wallet Anda

2. Klik **▶️ Start Mining di SEMUA VPS**

**Fitur Auto-Recovery:**
Jika VPS restart, agent.py akan otomatis:
1. Membaca konfigurasi mining terakhir dari `~/.mining_config.json`
2. Menjalankan `graftcp-local` dan miner secara otomatis
3. Reconnect ke Hub Server

> ⚠️ **Syarat:** Folder `~/workspace/gaszep/` harus sudah berisi binary graftcp dan miner.
> Anda perlu meng-clone repositori mining ke `~/workspace/gaszep/` sebelum menggunakan fitur ini.

---

## 🐚 Shell Runner

Dari Dashboard, buka tab **🐚 Shell Runner**:

1. Ketik perintah bash (contoh: `uptime; free -m; df -h`)
2. Klik **⚡ Kirim ke SEMUA VPS**

Output dari setiap VPS akan muncul di panel **Live Logs** di bawah.

---

## 🔧 Troubleshooting

| Masalah | Solusi |
|---------|--------|
| VPS tidak muncul di Dashboard | Pastikan Hub Server dan Cloudflare Tunnel berjalan. Cek URL tunnel sudah benar di file `~/workspace/.hub_url` di VPS |
| VPS muncul tapi langsung Offline | Periksa log agent: `tail -f ~/workspace/agent.log` |
| YouTube Like/Comment gagal | Pastikan browser di VPS sudah login ke Google. Jalankan Playwright dalam mode headed sekali untuk login manual |
| Mining tidak jalan | Pastikan folder `~/workspace/gaszep/` ada dan berisi binary graftcp + gasdag |
| URL Cloudflare berubah setelah PC restart | Jalankan ulang `cloudflared.exe tunnel`. Untuk URL permanen, gunakan Cloudflare Named Tunnel |
| Dashboard tidak bisa diakses | Pastikan port 9001 tidak diblokir firewall. Buka `http://localhost:9001` |

---

## 📋 FAQ

**Q: Berapa banyak VPS yang bisa ditangani?**
A: Hub Server dirancang untuk menangani 30 koneksi WebSocket simultan. Secara teknis bisa menangani lebih banyak.

**Q: Apakah butuh akun Cloudflare?**
A: Tidak, Quick Tunnel (tanpa login) sudah cukup. Tapi URL akan berubah setiap kali cloudflared di-restart.

**Q: Bagaimana kalau PC saya mati?**
A: Agent VPS akan terus mencoba reconnect setiap 30 detik. Begitu PC Anda hidup lagi dan Hub Server + Cloudflare Tunnel berjalan, semua VPS otomatis terhubung kembali.

**Q: Apakah aman?**
A: URL Cloudflare Tunnel bersifat random dan sulit ditebak. Namun siapa pun yang mengetahui URL tersebut bisa mengirim perintah ke VPS. Jangan bagikan URL tunnel ke orang lain.
