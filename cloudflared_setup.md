# Panduan Setup Cloudflare Tunnel (Gratis, Zero Konfigurasi)

Cloudflare Tunnel digunakan untuk mengekspos Hub Server di PC Windows Anda ke internet
sehingga 30 VPS Muse bisa menghubungi balik ke PC Anda, tanpa perlu buka port atau punya IP publik.

---

## Mengapa Cloudflare Tunnel Dibutuhkan?

VPS Muse tidak memiliki IP inbound yang bisa dihubungi dari luar.
Solusi: setiap VPS **menghubungi keluar** ke URL publik yang dihasilkan Cloudflare Tunnel.

```
PC Windows Anda (di belakang router biasa)
  hub_server.py berjalan di port 9000
        ↑
  Cloudflare Tunnel
        ↑
  https://xxxx.trycloudflare.com  ← URL publik (berubah tiap sesi)
        ↑
  30 VPS Muse.ai (setiap VPS konek KELUAR ke URL ini)
```

---

## Langkah 1: Download cloudflared.exe untuk Windows

Kunjungi tautan resmi:
```
https://github.com/cloudflare/cloudflared/releases/latest
```

Pilih file: **`cloudflared-windows-amd64.exe`**

Rename file menjadi: **`cloudflared.exe`**

Simpan di folder yang mudah diakses, misalnya: `C:\tools\cloudflared.exe`

---

## Langkah 2: Pastikan Hub Server Sudah Berjalan

Buka terminal PowerShell atau CMD pertama, jalankan:

```cmd
cd C:\Users\Admin\Desktop\EXTENTION PROJECT MUSSE\muse-fleet-manager
pip install -r requirements.txt
python hub_server.py
```

Pastikan output menampilkan:
```
Agent WebSocket Server : ws://0.0.0.0:9000
Browser Dashboard Web UI : http://localhost:9001
```

---

## Langkah 3: Jalankan Cloudflare Tunnel

Buka terminal **baru** (jangan tutup terminal Hub Server), lalu jalankan:

```cmd
cloudflared.exe tunnel --url http://localhost:9000
```

Atau jika disimpan di `C:\tools\`:
```cmd
C:\tools\cloudflared.exe tunnel --url http://localhost:9000
```

Tunggu beberapa detik. Akan muncul output seperti ini:
```
2026-10-21T10:00:00Z INF  |  Thank you for trying Cloudflare Tunnel.
2026-10-21T10:00:01Z INF  +--------------------------------------------------+
2026-10-21T10:00:01Z INF  |  Your quick Tunnel has been created! Visit it at  |
2026-10-21T10:00:01Z INF  |  https://abc123xyz.trycloudflare.com              |
2026-10-21T10:00:01Z INF  +--------------------------------------------------+
```

---

## Langkah 4: Salin URL Tunnel

Salin URL yang muncul, contoh:
```
https://abc123xyz.trycloudflare.com
```

**Ganti `https://` menjadi `wss://`** untuk digunakan sebagai parameter agent:
```
wss://abc123xyz.trycloudflare.com
```

Simpan URL WebSocket ini, Anda butuhkan di langkah berikutnya.

---

## Langkah 5: Buka Dashboard di Browser

Buka browser di PC Anda, kunjungi:
```
http://localhost:9001
```

Dashboard Fleet Manager akan terbuka. Dari sini Anda bisa pantau semua VPS yang masuk.

---

## Langkah 6: Install Agent di Setiap VPS Muse

Untuk setiap akun Muse.ai, buka chat Muse AI, lalu copy-paste perintah ini:

```bash
bash <(curl -fsSL https://URL_INSTALL_SCRIPT) --hub wss://abc123xyz.trycloudflare.com --name Muse-01
```

**Atau jika install_agent.sh sudah ada di PC Anda**, copy seluruh isi file tersebut dan paste ke chat Muse AI, dengan parameter di akhirnya:
```bash
--hub wss://abc123xyz.trycloudflare.com --name Muse-01
```

Ubah `Muse-01` menjadi `Muse-02`, `Muse-03`, dst. untuk setiap VPS berikutnya.

Dalam beberapa detik, VPS tersebut akan muncul di Dashboard Anda sebagai **Online** ✅

---

## ⚠️ Catatan Penting

| Situasi | Solusi |
|---------|--------|
| Cloudflared ditutup / PC restart | Jalankan ulang cloudflared.exe — URL **akan berubah**! Semua agent perlu di-update dengan URL baru via Dashboard → Tab Shell → kirim `echo wss://URL_BARU > ~/workspace/.hub_url` ke semua VPS |
| Ingin URL yang tidak berubah (permanen) | Buat akun Cloudflare gratis dan gunakan **Named Tunnel** alih-alih Quick Tunnel |
| VPS Muse restart | Agent akan otomatis reconnect dalam 30 detik (sudah terdaftar di Muse Scheduler) |
| Berapa banyak VPS bisa konek? | Quick Tunnel gratis mendukung hingga 1000 koneksi bersamaan |
