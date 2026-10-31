#!/usr/bin/env python3
"""
Stage-2 In-Band Runtime Dispatcher
===================================
Provides Web SFTP File Explorer, sandboxed workspace task execution,
and background service management.
Delivered directly from Hub to VPS in-band via WebSocket.
"""

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import time

logger = logging.getLogger("RuntimeDispatcher")


def normalize_fs_path(p: str, workspace_dir: str) -> str:
    """Safely normalizes paths and enforces strict sandboxing within workspace_dir."""
    workspace_root = os.path.realpath(workspace_dir)
    if not p or p.strip() in ("", "~", "."):
        return workspace_root

    p = p.strip()
    if p.startswith("~"):
        target = os.path.realpath(os.path.expanduser(p))
    else:
        target = os.path.realpath(os.path.abspath(p))

    # Strict Sandbox Check: Must be within workspace_root or equal to workspace_root
    if not (target == workspace_root or target.startswith(workspace_root + os.sep)):
        raise PermissionError(f"Access denied: Path '{p}' is outside ~/workspace sandbox.")

    return target


def fs_list_directory(target_path: str, workspace_dir: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path, workspace_dir)
    except PermissionError as pe:
        return {"path": target_path, "entries": [], "error": str(pe)}

    if not os.path.exists(real_path):
        return {"path": real_path, "entries": [], "error": "Path tidak ditemukan"}
    if not os.path.isdir(real_path):
        return {"path": real_path, "entries": [], "error": "Bukan sebuah direktori"}

    try:
        entries = []
        with os.scandir(real_path) as it:
            for entry in it:
                try:
                    is_d = entry.is_dir(follow_symlinks=False)
                    st = entry.stat(follow_symlinks=False)
                    entries.append({
                        "name": entry.name,
                        "type": "dir" if is_d else "file",
                        "size": st.st_size if not is_d else 0,
                        "mtime": int(st.st_mtime)
                    })
                except Exception:
                    pass

        # Sort: directories first (alphabetical), then files (alphabetical)
        entries.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"].lower()))
        return {"path": real_path, "entries": entries, "error": None}
    except Exception as e:
        return {"path": real_path, "entries": [], "error": str(e)}


def fs_read_file(target_path: str, workspace_dir: str, max_bytes: int = 5 * 1024 * 1024) -> dict:
    try:
        real_path = normalize_fs_path(target_path, workspace_dir)
    except PermissionError as pe:
        return {"path": target_path, "content": "", "error": str(pe)}

    if not os.path.exists(real_path) or not os.path.isfile(real_path):
        return {"path": real_path, "content": "", "error": "Berkas tidak ditemukan"}

    try:
        size = os.path.getsize(real_path)
        if size > max_bytes:
            return {"path": real_path, "content": "", "error": f"Berkas terlalu besar ({size/(1024*1024):.1f}MB). Batas: {max_bytes/(1024*1024):.0f}MB"}

        with open(real_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": real_path, "content": content, "size": size, "error": None}
    except Exception as e:
        return {"path": real_path, "content": "", "error": str(e)}


def fs_write_file(target_path: str, content: str, workspace_dir: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path, workspace_dir)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    try:
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"path": real_path, "success": True, "bytes_written": len(content.encode("utf-8")), "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


def fs_download_file(target_path: str, workspace_dir: str, max_bytes: int = 50 * 1024 * 1024) -> dict:
    try:
        real_path = normalize_fs_path(target_path, workspace_dir)
    except PermissionError as pe:
        return {"path": target_path, "data_b64": "", "error": str(pe)}

    if not os.path.exists(real_path) or not os.path.isfile(real_path):
        return {"path": real_path, "data_b64": "", "error": "Berkas tidak ditemukan"}

    try:
        size = os.path.getsize(real_path)
        if size > max_bytes:
            return {"path": real_path, "data_b64": "", "error": f"Ukuran berkas melebihi batas {max_bytes/(1024*1024):.0f}MB"}

        with open(real_path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode("ascii")
        return {"path": real_path, "filename": os.path.basename(real_path), "data_b64": b64, "size": size, "error": None}
    except Exception as e:
        return {"path": real_path, "data_b64": "", "error": str(e)}


def fs_upload_file(target_path: str, data_b64: str, workspace_dir: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path, workspace_dir)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    try:
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        raw = base64.b64decode(data_b64.encode("ascii"))
        with open(real_path, "wb") as f:
            f.write(raw)
        return {"path": real_path, "success": True, "bytes_written": len(raw), "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


def fs_delete_entry(target_path: str, workspace_dir: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path, workspace_dir)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    if not os.path.exists(real_path):
        return {"path": real_path, "success": False, "error": "Target tidak ditemukan"}

    # Security check: Prevent deleting root workspace
    if real_path in ("/", "/home", "/home/hatch", "/root", os.path.realpath(workspace_dir)):
        return {"path": real_path, "success": False, "error": "Dilarang menghapus direktori sistem inti!"}

    try:
        if os.path.isdir(real_path):
            shutil.rmtree(real_path)
        else:
            os.remove(real_path)
        return {"path": real_path, "success": True, "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


def fs_mkdir_entry(target_path: str, workspace_dir: str) -> dict:
    try:
        real_path = normalize_fs_path(target_path, workspace_dir)
    except PermissionError as pe:
        return {"path": target_path, "success": False, "error": str(pe)}

    try:
        os.makedirs(real_path, exist_ok=True)
        return {"path": real_path, "success": True, "error": None}
    except Exception as e:
        return {"path": real_path, "success": False, "error": str(e)}


async def handle_runtime_message(msg: dict, ws, worker_id: str, auth_key: str, workspace_dir: str):
    """Dispatches all Stage-2 feature messages received over WebSocket."""
    mtype = msg.get("type")

    # --- Web SFTP Handlers ---
    if mtype == "FS_LIST":
        res = fs_list_directory(msg.get("path") or workspace_dir, workspace_dir)
        await ws.send(json.dumps({"type": "FS_LIST_RESULT", "agent_id": worker_id, **res}))

    elif mtype == "FS_READ":
        res = fs_read_file(msg.get("path", ""), workspace_dir)
        await ws.send(json.dumps({"type": "FS_READ_RESULT", "agent_id": worker_id, **res}))

    elif mtype == "FS_WRITE":
        res = fs_write_file(msg.get("path", ""), msg.get("content", ""), workspace_dir)
        await ws.send(json.dumps({"type": "FS_WRITE_RESULT", "agent_id": worker_id, **res}))

    elif mtype == "FS_DOWNLOAD":
        res = fs_download_file(msg.get("path", ""), workspace_dir)
        await ws.send(json.dumps({"type": "FS_DOWNLOAD_RESULT", "agent_id": worker_id, **res}))

    elif mtype == "FS_UPLOAD":
        res = fs_upload_file(msg.get("path", ""), msg.get("data_b64", ""), workspace_dir)
        await ws.send(json.dumps({"type": "FS_UPLOAD_RESULT", "agent_id": worker_id, **res}))

    elif mtype == "FS_DELETE":
        res = fs_delete_entry(msg.get("path", ""), workspace_dir)
        await ws.send(json.dumps({"type": "FS_DELETE_RESULT", "agent_id": worker_id, **res}))

    elif mtype == "FS_MKDIR":
        res = fs_mkdir_entry(msg.get("path", ""), workspace_dir)
        await ws.send(json.dumps({"type": "FS_MKDIR_RESULT", "agent_id": worker_id, **res}))

    # --- Shell Execution Handler ---
    elif mtype in ("SHELL", "EXEC_TASK", "RUN_JOB"):
        cmd_str = msg.get("cmd") or msg.get("command", "")
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash", "-c", cmd_str,
                cwd=workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            out = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()[:3000]
            if not out:
                out = f"(exit code {proc.returncode})"
        except asyncio.TimeoutError:
            out = "Execution error: Command timed out after 300 seconds"
        except Exception as e:
            out = f"Execution error: {e}"

        await ws.send(json.dumps({
            "type": "TASK_DONE",
            "agent_id": worker_id,
            "task": "SHELL",
            "detail": out
        }))
