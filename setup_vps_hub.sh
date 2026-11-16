#!/usr/bin/env bash
# ==============================================================================
# MUSE FLEET MANAGER - VPS HUB SERVER AUTOMATED INSTALLER (24/7 INDEPENDENT)
# ==============================================================================
# Skrip ini menginstal Hub Server di VPS Linux (Ubuntu/Debian) secara otomatis,
# mendaftarkan systemd daemon (auto-start saat reboot), dan menyambungkan
# Cloudflare Tunnel sehingga Hub Server online 24/7 tanpa bergantung pada laptop.
# ==============================================================================

set -e

# Warna Terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================================${NC}"
echo -e "${GREEN}   MUSE FLEET MANAGER - INSTALLER HUB SERVER LINUX VPS 24/7${NC}"
echo -e "${BLUE}======================================================================${NC}"

# 1. Pastikan dijalankan sebagai root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[ERROR] Skrip ini harus dijalankan sebagai root (atau gunakan sudo bash setup_vps_hub.sh)${NC}"
  exit 1
fi

CF_TOKEN="${1:-eyJhIjoiYmNlODRhMjBkMjgzOTdiYzAyNTEwZWE2YTY3NTlmOGQiLCJ0IjoiNWE1MmMwZmEtODU1ZS00YzA1LThhNzktYTNiMGU5NjdkOTVhIiwicyI6Ik56RmtNbVV4WW1FdFptVTFOeTAwT0dVMUxUZ3lOMlF0WVdZeE9XUXdNV0V3WWpaaU5XVTROR1V5T0RZdE9EQmhPUzAwTWpVM0xUbGpORE10Wm1NMllqTXhaVGcwTnpNMiJ9}"

# 2. Update sistem dan instal dependensi OS
echo -e "\n${YELLOW}[1/6] Memperbarui paket sistem dan menginstal dependensi...${NC}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-pip git curl wget tar ufw procps net-tools

# 3. Clone atau Update Repository Hub
INSTALL_DIR="/opt/muse-fleet-hub"
echo -e "\n${YELLOW}[2/6] Menyiapkan source code di ${INSTALL_DIR}...${NC}"
if [ -d "${INSTALL_DIR}/.git" ]; then
    echo -e "${BLUE}[INFO] Repository ditemukan, menarik pembaruan terbaru (git pull)...${NC}"
    cd "${INSTALL_DIR}"
    git pull origin main
else
    echo -e "${BLUE}[INFO] Melakukan git clone repository muse-fleet-hub...${NC}"
    git clone https://github.com/makassartoraja936-max/muse-fleet-hub.git "${INSTALL_DIR}"
    cd "${INSTALL_DIR}"
fi

# 4. Instal Python Dependencies
echo -e "\n${YELLOW}[3/6] Menginstal dependensi Python (aiohttp, websockets, psutil)...${NC}"
cd "${INSTALL_DIR}"
pip3 install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt

# 5. Pasang Systemd Service (Auto-start 24/7)
echo -e "\n${YELLOW}[4/6] Mengonfigurasi systemd service (hub-server.service)...${NC}"
cp "${INSTALL_DIR}/hub-server.service" /etc/systemd/system/hub-server.service
systemctl daemon-reload
systemctl enable hub-server
systemctl restart hub-server
echo -e "${GREEN}[OK] Service hub-server berhasil diaktifkan dan dijalankan!${NC}"

# 6. Pasang Cloudflare Tunnel (cloudflared)
echo -e "\n${YELLOW}[5/6] Memeriksa dan menginstal Cloudflare Tunnel (cloudflared)...${NC}"
if ! command -v cloudflared &> /dev/null; then
    echo -e "${BLUE}[INFO] Mengunduh biner cloudflared Linux AMD64...${NC}"
    ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
    curl -L --output /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
    dpkg -i /tmp/cloudflared.deb || apt-get install -f -y
    rm -f /tmp/cloudflared.deb
    echo -e "${GREEN}[OK] cloudflared berhasil terinstal: $(cloudflared --version)${NC}"
else
    echo -e "${GREEN}[OK] cloudflared sudah terpasang: $(cloudflared --version)${NC}"
fi

# 7. Aktifkan Service Tunnel dengan Token
if [ -n "$CF_TOKEN" ]; then
    echo -e "\n${YELLOW}[6/6] Memasang Cloudflare Tunnel sebagai system service...${NC}"
    cloudflared service uninstall 2>/dev/null || true
    cloudflared service install "$CF_TOKEN"
    systemctl daemon-reload
    systemctl enable cloudflared
    systemctl restart cloudflared
    echo -e "${GREEN}[OK] Cloudflare Tunnel Service berhasil dipasang dan aktif!${NC}"
else
    echo -e "\n${YELLOW}[INFO] Token Cloudflare Tunnel tidak diberikan. Anda dapat menjalankannya nanti dengan:${NC}"
    echo "cloudflared service install <TOKEN_ANDA>"
fi

# 8. Verifikasi Status
echo -e "\n${BLUE}======================================================================${NC}"
echo -e "${GREEN}   INSTALASI HUB SERVER BERHASIL! STATUS SISTEM:${NC}"
echo -e "${BLUE}======================================================================${NC}"
systemctl status hub-server --no-pager | head -n 10
echo ""
if command -v cloudflared &> /dev/null && systemctl is-active --quiet cloudflared; then
    echo -e "${GREEN}✅ Cloudflare Tunnel : AKTIF (Menghubungkan ke hub.databaru.my.id)${NC}"
else
    echo -e "${YELLOW}⚠️ Cloudflare Tunnel : Belum berjalan${NC}"
fi
echo -e "${GREEN}✅ Hub Server Local   : AKTIF (Listening port 9000)${NC}"
echo -e "${GREEN}✅ URL Dashboard      : https://hub.databaru.my.id${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo -e "Perintah Pemeliharaan:"
echo -e " - Cek log Hub Server : journalctl -u hub-server -f (atau tail -f /var/log/hub_server.log)"
echo -e " - Restart Hub Server : systemctl restart hub-server"
echo -e " - Cek log Tunnel     : journalctl -u cloudflared -f"
echo -e "${BLUE}======================================================================${NC}"
