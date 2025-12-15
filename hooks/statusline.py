#!/usr/bin/env python3
"""
System Assistant Statusline - Full WSL2 system status at a glance

Shows: Model | Context% | CPU | RAM | Disk | Services | Network
Line 2: Session | Folder | Confidence | Git
Designed for personalized WSL2 system assistant use.
"""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add lib path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent))  # For _config

from _config import get_magic_number
from _logging import log_debug

# =============================================================================
# CACHE LAYER - subprocess results don't change rapidly
# =============================================================================

CACHE_FILE = Path("/tmp/.claude_statusline_cache.json")

# TTL per metric (seconds) - tuned for typical change frequency
CACHE_TTL = {
    "gpu": 2,  # VRAM can change during inference
    "services": 5,  # Docker/node/python processes stable
    "comfyui": 10,  # Service status very stable
    "net": 10,  # Connectivity rarely changes
    "git": 3,  # Changes with edits but not rapidly
    "ports": 3,  # Dev servers start/stop occasionally
}

# Dev ports worth monitoring (port -> short label)
DEV_PORTS = {
    3000: "3k",  # React, Next.js, Create React App
    3001: "3k1",  # Next.js alt
    4200: "ng",  # Angular
    5000: "5k",  # Flask, various
    5173: "vite",  # Vite dev server
    5174: "vite",  # Vite alt
    8000: "8k",  # Django, FastAPI, uvicorn
    8080: "8080",  # Generic, Tomcat, etc
    8888: "jup",  # Jupyter
    9000: "9k",  # PHP-FPM, SonarQube
}


def load_cache() -> dict:
    """Load cache from file, return empty dict if missing/invalid."""
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception as e:
        log_debug("statusline", f"confidence state read failed: {e}")
    return {}


def save_cache(cache: dict):
    """Save cache to file (best effort)."""
    try:
        CACHE_FILE.write_text(json.dumps(cache))
    except Exception as e:
        log_debug("statusline", f"git data read failed: {e}")


def get_cached(cache: dict, key: str) -> tuple[bool, str]:
    """Return (hit, value) - hit is True if cache is fresh."""
    entry = cache.get(key)
    if not entry:
        return False, ""
    ttl = CACHE_TTL.get(key, 5)
    if time.time() - entry.get("ts", 0) < ttl:
        return True, entry.get("val", "")
    return False, ""


def set_cached(cache: dict, key: str, value: str):
    """Store value in cache with current timestamp."""
    cache[key] = {"ts": time.time(), "val": value}


# ANSI colors
class C:
    RESET = "\033[0m"
    DIM = "\033[90m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def run_cmd(cmd_list, timeout=2):
    """Run command with list args, return stdout."""
    try:
        result = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def get_cpu_load():
    """Get CPU load average (1 min)."""
    try:
        with open("/proc/loadavg") as f:
            load = float(f.read().split()[0])
        cores = os.cpu_count() or 1
        pct = (load / cores) * 100
        color = C.RED if pct > 80 else C.YELLOW if pct > 50 else C.GREEN
        return f"{color}{load:.1f}{C.RESET}"
    except Exception:
        return f"{C.DIM}--{C.RESET}"


def get_ram_usage():
    """Get RAM usage percentage."""
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mem[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = mem.get("MemTotal", 1)
        available = mem.get("MemAvailable", 0)
        pct = ((total - available) / total) * 100
        color = C.RED if pct > 85 else C.YELLOW if pct > 70 else C.GREEN
        return f"{color}{pct:.0f}%{C.RESET}"
    except Exception:
        return f"{C.DIM}--{C.RESET}"


def get_disk_usage():
    """Get disk free space for /home."""
    try:
        stat = os.statvfs("/home")
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bfree * stat.f_frsize
        pct = ((total - free) / total) * 100
        free_gb = free / (1024**3)
        color = C.RED if pct > 90 else C.YELLOW if pct > 75 else C.GREEN
        return f"{color}{free_gb:.0f}G{C.RESET}"
    except Exception:
        return f"{C.DIM}--{C.RESET}"


def get_services_status():
    """Get status of key services."""
    services = []

    # Docker containers
    try:
        result = subprocess.run(
            ["docker", "ps", "-q"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            count = (
                len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
            )
            if count > 0:
                services.append(f"{C.CYAN}D:{count}{C.RESET}")
    except Exception as e:
        log_debug("statusline", f"bead state read failed: {e}")

    # Node processes
    try:
        result = subprocess.run(
            ["pgrep", "-c", "node"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            if count > 0:
                services.append(f"{C.GREEN}N:{count}{C.RESET}")
    except Exception as e:
        log_debug("statusline", f"bead state read failed: {e}")

    # Python processes
    try:
        result = subprocess.run(
            ["pgrep", "-c", "python"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            if count > 1:
                services.append(f"{C.YELLOW}P:{count - 1}{C.RESET}")
    except Exception as e:
        log_debug("statusline", f"decay timer read failed: {e}")

    return " ".join(services) if services else ""


def get_network_status():
    """Check internet connectivity via DNS."""
    try:
        result = subprocess.run(
            ["getent", "hosts", "google.com"], capture_output=True, timeout=1
        )
        return (
            f"{C.GREEN}NET{C.RESET}"
            if result.returncode == 0
            else f"{C.RED}NET{C.RESET}"
        )
    except Exception:
        return f"{C.RED}NET{C.RESET}"


def get_gpu_vram():
    """Get GPU VRAM usage via nvidia-smi (WSL2)."""
    nvidia_smi = "/usr/lib/wsl/lib/nvidia-smi"
    try:
        if not Path(nvidia_smi).exists():
            return ""
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        used, total = map(int, result.stdout.strip().split(", "))
        pct = (used / total) * 100
        used_gb = used / 1024
        total_gb = total / 1024
        color = C.RED if pct > 90 else C.YELLOW if pct > 70 else C.GREEN
        return f"{color}{used_gb:.1f}/{total_gb:.0f}G{C.RESET}"
    except Exception:
        return ""


def get_dev_ports():
    """Check which dev ports are listening."""
    try:
        result = subprocess.run(
            ["ss", "-tlnH"], capture_output=True, text=True, timeout=1
        )
        if result.returncode != 0:
            return ""

        listening = set()
        for line in result.stdout.split("\n"):
            # Parse ss output: LISTEN 0 511 *:3000 *:*
            parts = line.split()
            if len(parts) >= 4:
                addr = parts[3]  # Local address like *:3000 or 127.0.0.1:8000
                if ":" in addr:
                    port_str = addr.rsplit(":", 1)[-1]
                    if port_str.isdigit():
                        port = int(port_str)
                        if port in DEV_PORTS:
                            listening.add(port)

        if not listening:
            return ""

        # Sort and format: "3k 8k vite"
        labels = [DEV_PORTS[p] for p in sorted(listening)]
        return f"{C.MAGENTA}{' '.join(labels)}{C.RESET}"
    except Exception:
        return ""


def get_comfyui_status():
    """Check if ComfyUI is running."""
    try:
        # Primary: check if port 8188 is listening (ComfyUI default)
        result = subprocess.run(
            ["ss", "-tlnp"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0 and ":8188" in result.stdout:
            return f"{C.GREEN}ComfyUI{C.RESET}"

        # Fallback: check for ComfyUI main.py being executed
        # Must match the SCRIPT, not just the venv path
        result = subprocess.run(
            ["pgrep", "-af", "python"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                # Look for actual ComfyUI execution patterns
                lower = line.lower()
                # Match: "comfyui/main.py" or "comfy/main.py" in the command args
                if ("comfyui" in lower or "comfy" in lower) and "main.py" in lower:
                    return f"{C.GREEN}ComfyUI{C.RESET}"

        return ""
    except Exception:
        return ""


def get_confidence_status():
    """Get confidence level from session state - reads directly from file."""
    try:
        # Read directly from JSON to avoid any module-level caching
        state_file = Path(__file__).parent.parent / "memory" / "session_state_v3.json"
        if not state_file.exists():
            return ""
        with open(state_file) as f:
            data = json.load(f)
        confidence = data.get("confidence", 70)

        # Import tier info (no caching issues here)
        from confidence import get_tier_info, STASIS_FLOOR

        tier_name, emoji, _ = get_tier_info(confidence)

        # Trajectory prediction (3 turns, decay only - can't predict edits/bash)
        projected = confidence - 3  # -1 decay per turn
        trajectory = ""
        if projected < STASIS_FLOOR and confidence >= STASIS_FLOOR:
            # Will drop below stasis floor - warn
            trajectory = f" 📉{projected - confidence}"
        elif projected < confidence:
            # Simple decay indicator (compact)
            trajectory = f" ⚡{projected - confidence}"

        return f"{emoji}{confidence}% {tier_name}{trajectory}"
    except Exception:
        return ""


def get_git_info():
    """Get git branch and status."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode != 0:
            return ""
        branch = result.stdout.strip()

        result = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=1
        )
        status_str = ""
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            modified = sum(1 for ln in lines if len(ln) > 1 and ln[1] == "M")
            staged = sum(1 for ln in lines if ln[0] not in (" ", "?"))
            untracked = sum(1 for ln in lines if ln.startswith("??"))
            parts = []
            if staged:
                parts.append(f"{C.GREEN}+{staged}{C.RESET}")
            if modified:
                parts.append(f"{C.YELLOW}~{modified}{C.RESET}")
            if untracked:
                parts.append(f"{C.RED}?{untracked}{C.RESET}")
            if parts:
                status_str = f"[{' '.join(parts)}]"

        return f"{C.GREEN}{branch}{C.RESET}{status_str}"
    except Exception:
        return ""


def get_context_usage(transcript_path, context_window):
    """Calculate context window usage from transcript."""
    if not transcript_path or not Path(transcript_path).exists():
        return 0, 0
    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()
        for line in reversed(lines):
            try:
                data = json.loads(line.strip())
                if data.get("message", {}).get("role") != "assistant":
                    continue
                model = str(data.get("message", {}).get("model", "")).lower()
                if "synthetic" in model:
                    continue
                usage = data.get("message", {}).get("usage")
                if usage:
                    used = (
                        usage.get("input_tokens", 0)
                        + usage.get("output_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
                    return used, context_window
            except Exception:
                continue
        return 0, 0
    except Exception:
        return 0, 0


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except Exception:
        input_data = {}

    # Model
    model = input_data.get("model", {})
    model_name = model.get("display_name", "Claude")
    if "Opus" in model_name:
        model_short = f"{C.MAGENTA}Opus{C.RESET}"
    elif "Sonnet" in model_name:
        model_short = f"{C.BLUE}Sonnet{C.RESET}"
    elif "Haiku" in model_name:
        model_short = f"{C.CYAN}Haiku{C.RESET}"
    else:
        model_short = f"{C.DIM}{model_name[:6]}{C.RESET}"

    # Context
    transcript = input_data.get("transcript_path", "")
    context_window = model.get("context_window", get_magic_number("default_context_window", 200000))
    used, total = get_context_usage(transcript, context_window)
    if used > 0 and total > 0:
        pct = (used / total) * 100
        ctx_color = C.RED if pct > 80 else C.YELLOW if pct > 60 else C.GREEN
        context_str = f"{ctx_color}{pct:.0f}%{C.RESET}"
    else:
        context_str = f"{C.DIM}0%{C.RESET}"

    # Fast system stats (no subprocess, just /proc reads)
    cpu = get_cpu_load()
    ram = get_ram_usage()
    disk = get_disk_usage()

    # Slow subprocess calls - cached + parallel
    # Cache eliminates redundant subprocess calls between rapid prompts
    slow_funcs = {
        "gpu": get_gpu_vram,
        "services": get_services_status,
        "ports": get_dev_ports,
        "comfyui": get_comfyui_status,
        "net": get_network_status,
        "git": get_git_info,
    }

    cache = load_cache()
    results = {}
    stale_funcs = {}

    # Check cache first
    for name, fn in slow_funcs.items():
        hit, val = get_cached(cache, name)
        if hit:
            results[name] = val
        else:
            stale_funcs[name] = fn

    # Only run subprocess calls for stale entries (parallel)
    if stale_funcs:
        with ThreadPoolExecutor(max_workers=len(stale_funcs)) as executor:
            futures = {executor.submit(fn): name for name, fn in stale_funcs.items()}
            for future in as_completed(futures, timeout=3):
                name = futures[future]
                try:
                    val = future.result()
                    results[name] = val
                    set_cached(cache, name, val)
                except Exception:
                    results[name] = ""
        save_cache(cache)

    gpu = results.get("gpu", "")
    services = results.get("services", "")
    ports = results.get("ports", "")
    comfyui = results.get("comfyui", "")
    net = results.get("net", f"{C.DIM}NET{C.RESET}")
    git = results.get("git", "")

    # Line 1: Model | Context | System
    line1_parts = [
        model_short,
        f"CTX:{context_str}",
        f"CPU:{cpu}",
        f"RAM:{ram}",
        f"DSK:{disk}",
    ]
    if gpu:
        line1_parts.append(f"GPU:{gpu}")
    if services:
        line1_parts.append(services)
    if ports:
        line1_parts.append(ports)
    if comfyui:
        line1_parts.append(comfyui)
    line1_parts.append(net)
    line1 = f" {C.DIM}|{C.RESET} ".join(line1_parts)

    # Line 2: Session + Folder + Confidence + Git
    session_id = input_data.get("session_id", "")[:8]
    folder = Path.cwd().name
    confidence = get_confidence_status()
    line2_parts = [f"{C.DIM}{session_id}{C.RESET}", f"{C.CYAN}{folder}{C.RESET}"]
    if confidence:
        line2_parts.append(confidence)
    if git:
        line2_parts.append(git)
    line2 = f" {C.DIM}|{C.RESET} ".join(line2_parts)

    print(f"{line1}\n{line2}")


if __name__ == "__main__":
    main()
