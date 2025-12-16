#!/usr/bin/env python3
"""
System Assistant Statusline v2.0 - Full WSL2 system status at a glance

Line 1: Model | Context% | CPU | RAM | Disk | GPU | Services | Ports | Network
Line 2: Session | Project | Confidence+Streak | Beads | Serena | Git

Improvements in v2.0:
- Project-aware (shows detected project name, not just folder)
- Confidence streak indicator
- Beads task count
- Serena activation status
- Session age
- Context exhaustion warning (🚨 at 75%+)
- Extracted color thresholds
- Type hints throughout
- Fixed misleading log messages
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Add lib path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent))  # For _config

from _config import get_magic_number
from _logging import log_debug

# =============================================================================
# CONSTANTS - Extracted thresholds for easy tuning
# =============================================================================

# Color thresholds (percentage)
class Thresholds:
    # CPU load (as % of cores)
    CPU_RED = 80
    CPU_YELLOW = 50
    # RAM usage
    RAM_RED = 85
    RAM_YELLOW = 70
    # Disk usage
    DISK_RED = 90
    DISK_YELLOW = 75
    # GPU VRAM
    GPU_RED = 90
    GPU_YELLOW = 70
    # Context window
    CTX_RED = 80
    CTX_YELLOW = 60
    CTX_WARN = 75  # Show 🚨 warning


# =============================================================================
# CACHE LAYER - subprocess results don't change rapidly
# =============================================================================

CACHE_FILE = Path("/tmp/.claude_statusline_cache.json")

# TTL per metric (seconds) - tuned for typical change frequency
CACHE_TTL: dict[str, int] = {
    "gpu": 2,      # VRAM can change during inference
    "services": 5,  # Docker/node/python processes stable
    "comfyui": 10,  # Service status very stable
    "net": 10,      # Connectivity rarely changes
    "git": 3,       # Changes with edits but not rapidly
    "ports": 3,     # Dev servers start/stop occasionally
    "beads": 5,     # Task status relatively stable
}

# Dev ports worth monitoring (port -> short label)
DEV_PORTS: dict[int, str] = {
    3000: "3k",    # React, Next.js, Create React App
    3001: "3k1",   # Next.js alt
    4200: "ng",    # Angular
    5000: "5k",    # Flask, various
    5173: "vite",  # Vite dev server
    5174: "vite",  # Vite alt
    8000: "8k",    # Django, FastAPI, uvicorn
    8080: "8080",  # Generic, Tomcat, etc
    8888: "jup",   # Jupyter
    9000: "9k",    # PHP-FPM, SonarQube
}


def load_cache() -> dict[str, Any]:
    """Load cache from file, return empty dict if missing/invalid."""
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception as e:
        log_debug("statusline", f"cache load failed: {e}")
    return {}


def save_cache(cache: dict[str, Any]) -> None:
    """Save cache to file (best effort)."""
    try:
        CACHE_FILE.write_text(json.dumps(cache))
    except Exception as e:
        log_debug("statusline", f"cache save failed: {e}")


def get_cached(cache: dict[str, Any], key: str) -> tuple[bool, str]:
    """Return (hit, value) - hit is True if cache is fresh."""
    entry = cache.get(key)
    if not entry:
        return False, ""
    ttl = CACHE_TTL.get(key, 5)
    if time.time() - entry.get("ts", 0) < ttl:
        return True, entry.get("val", "")
    return False, ""


def set_cached(cache: dict[str, Any], key: str, value: str) -> None:
    """Store value in cache with current timestamp."""
    cache[key] = {"ts": time.time(), "val": value}


# =============================================================================
# ANSI COLORS
# =============================================================================

class C:
    RESET = "\033[0m"
    DIM = "\033[90m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"


def colorize(value: str, pct: float, red: float, yellow: float) -> str:
    """Apply color based on threshold (higher = worse)."""
    color = C.RED if pct > red else C.YELLOW if pct > yellow else C.GREEN
    return f"{color}{value}{C.RESET}"


# =============================================================================
# SYSTEM METRICS (Fast - /proc reads, no subprocess)
# =============================================================================

def get_cpu_load() -> str:
    """Get CPU load average (1 min)."""
    try:
        with open("/proc/loadavg") as f:
            load = float(f.read().split()[0])
        cores = os.cpu_count() or 1
        pct = (load / cores) * 100
        return colorize(f"{load:.1f}", pct, Thresholds.CPU_RED, Thresholds.CPU_YELLOW)
    except Exception:
        return f"{C.DIM}--{C.RESET}"


def get_ram_usage() -> str:
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
        return colorize(f"{pct:.0f}%", pct, Thresholds.RAM_RED, Thresholds.RAM_YELLOW)
    except Exception:
        return f"{C.DIM}--{C.RESET}"


def get_disk_usage() -> str:
    """Get disk free space for /home."""
    try:
        stat = os.statvfs("/home")
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bfree * stat.f_frsize
        pct = ((total - free) / total) * 100
        free_gb = free / (1024**3)
        return colorize(f"{free_gb:.0f}G", pct, Thresholds.DISK_RED, Thresholds.DISK_YELLOW)
    except Exception:
        return f"{C.DIM}--{C.RESET}"


# =============================================================================
# SUBPROCESS METRICS (Slow - cached + parallel)
# =============================================================================

def get_services_status() -> str:
    """Get status of key services (Docker, Node, Python)."""
    services = []

    # Docker containers
    try:
        result = subprocess.run(
            ["docker", "ps", "-q"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
            if count > 0:
                services.append(f"{C.CYAN}D:{count}{C.RESET}")
    except Exception as e:
        log_debug("statusline", f"docker check failed: {e}")

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
        log_debug("statusline", f"node check failed: {e}")

    # Python processes (excluding self)
    try:
        result = subprocess.run(
            ["pgrep", "-c", "python"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            if count > 1:
                services.append(f"{C.YELLOW}P:{count - 1}{C.RESET}")
    except Exception as e:
        log_debug("statusline", f"python check failed: {e}")

    return " ".join(services) if services else ""


def get_network_status() -> str:
    """Check internet connectivity via DNS."""
    try:
        result = subprocess.run(
            ["getent", "hosts", "google.com"], capture_output=True, timeout=1
        )
        return f"{C.GREEN}NET{C.RESET}" if result.returncode == 0 else f"{C.RED}NET{C.RESET}"
    except Exception:
        return f"{C.RED}NET{C.RESET}"


def get_gpu_vram() -> str:
    """Get GPU VRAM usage via nvidia-smi (WSL2)."""
    nvidia_smi = "/usr/lib/wsl/lib/nvidia-smi"
    try:
        if not Path(nvidia_smi).exists():
            return ""
        result = subprocess.run(
            [nvidia_smi, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        used, total = map(int, result.stdout.strip().split(", "))
        pct = (used / total) * 100
        used_gb, total_gb = used / 1024, total / 1024
        return colorize(f"{used_gb:.1f}/{total_gb:.0f}G", pct, Thresholds.GPU_RED, Thresholds.GPU_YELLOW)
    except Exception:
        return ""


def get_dev_ports() -> str:
    """Check which dev ports are listening."""
    try:
        result = subprocess.run(["ss", "-tlnH"], capture_output=True, text=True, timeout=1)
        if result.returncode != 0:
            return ""

        listening = set()
        for line in result.stdout.split("\n"):
            parts = line.split()
            if len(parts) >= 4:
                addr = parts[3]
                if ":" in addr:
                    port_str = addr.rsplit(":", 1)[-1]
                    if port_str.isdigit():
                        port = int(port_str)
                        if port in DEV_PORTS:
                            listening.add(port)

        if not listening:
            return ""
        labels = [DEV_PORTS[p] for p in sorted(listening)]
        return f"{C.MAGENTA}{' '.join(labels)}{C.RESET}"
    except Exception:
        return ""


def get_comfyui_status() -> str:
    """Check if ComfyUI is running."""
    try:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=1)
        if result.returncode == 0 and ":8188" in result.stdout:
            return f"{C.GREEN}ComfyUI{C.RESET}"

        result = subprocess.run(["pgrep", "-af", "python"], capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                lower = line.lower()
                if ("comfyui" in lower or "comfy" in lower) and "main.py" in lower:
                    return f"{C.GREEN}ComfyUI{C.RESET}"
        return ""
    except Exception:
        return ""


def get_git_info() -> str:
    """Get git branch and status."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, timeout=1
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


def get_beads_status() -> str:
    """Get active beads (in_progress tasks) count."""
    try:
        result = subprocess.run(
            ["bd", "list", "--status=in_progress", "--format=json"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return ""
        try:
            data = json.loads(result.stdout)
            count = len(data) if isinstance(data, list) else 0
            if count > 0:
                return f"{C.YELLOW}📋{count}{C.RESET}"
        except json.JSONDecodeError:
            # Fallback: count lines
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            if lines:
                return f"{C.YELLOW}📋{len(lines)}{C.RESET}"
        return ""
    except Exception:
        return ""


# =============================================================================
# SESSION/PROJECT INFO (Direct file reads)
# =============================================================================

def get_project_info() -> tuple[str, str]:
    """Get project name and ID from project detector."""
    try:
        from project_detector import detect_project

        ctx = detect_project()
        project_name = ctx.project_name or Path.cwd().name
        project_id = ctx.project_id
        return project_name, project_id
    except Exception:
        return Path.cwd().name, ""


def get_confidence_status() -> str:
    """Get confidence level with streak indicator from session state."""
    try:
        from _session_constants import get_project_state_file
        state_file = get_project_state_file()
        if not state_file.exists():
            return ""
        with open(state_file) as f:
            data = json.load(f)

        confidence = data.get("confidence", 70)

        # Get streak from confidence_streaks module
        try:
            from _confidence_streaks import get_current_streak
            streak = get_current_streak(data)
        except Exception:
            streak = 0

        from confidence import get_tier_info, STASIS_FLOOR
        tier_name, emoji, _ = get_tier_info(confidence)

        # Streak indicator
        streak_str = ""
        if streak >= 5:
            streak_str = f" 🔥{streak}"
        elif streak >= 2:
            streak_str = f" ⚡{streak}"

        # Fatigue indicator (v4.9) - show when not fresh
        fatigue_str = ""
        fatigue_mult = 1.0
        turn_count = data.get("turn_count", 0)
        try:
            from _fatigue import get_fatigue_tier
            tier, fatigue_emoji, fatigue_mult = get_fatigue_tier(turn_count)
            if tier != "fresh":  # Only show if fatigued
                fatigue_str = f" {fatigue_emoji}{fatigue_mult:.1f}x"
        except ImportError:
            fatigue_mult = 1.0  # Fallback if fatigue module not available

        # Trajectory prediction (3 turns decay, adjusted for fatigue)
        projected = confidence - int(3 * fatigue_mult)
        trajectory = ""
        if projected < STASIS_FLOOR and confidence >= STASIS_FLOOR:
            trajectory = " 📉"

        return f"{emoji}{confidence}%{streak_str}{fatigue_str}{trajectory}"
    except Exception:
        return ""


def get_serena_status() -> str:
    """Check if Serena is activated for current project."""
    try:
        from _session_constants import get_project_state_file
        state_file = get_project_state_file()
        if not state_file.exists():
            return ""
        with open(state_file) as f:
            data = json.load(f)

        if data.get("serena_activated", False):
            project = data.get("serena_project", "")
            return f"{C.MAGENTA}🔮{C.RESET}"
        return ""
    except Exception:
        return ""


def get_session_age(started_at: float) -> str:
    """Get human-readable session age."""
    if not started_at:
        return ""
    try:
        elapsed = time.time() - started_at
        if elapsed < 60:
            return ""  # Too short to show
        elif elapsed < 3600:
            mins = int(elapsed / 60)
            return f"{C.DIM}{mins}m{C.RESET}"
        else:
            hours = int(elapsed / 3600)
            mins = int((elapsed % 3600) / 60)
            return f"{C.DIM}{hours}h{mins}m{C.RESET}"
    except Exception:
        return ""


def format_token_budget(used: int, total: int) -> str:
    """Format remaining tokens as money - triggers loss aversion.

    Entity Model: Framing context as $200,000 budget creates visceral
    resource awareness. Watching money drain feels worse than watching
    a percentage grow.
    """
    remaining = total - used
    # Scale to make numbers feel significant (1 token = $1)
    dollars = remaining

    if dollars > 150_000:
        emoji = "💰"  # Wealthy
        color = C.GREEN
    elif dollars > 100_000:
        emoji = "💵"  # Comfortable
        color = C.GREEN
    elif dollars > 50_000:
        emoji = "💸"  # Spending freely
        color = C.YELLOW
    elif dollars > 20_000:
        emoji = "⚠️"  # Getting tight
        color = C.YELLOW
    else:
        emoji = "🔥"  # Burning through it
        color = C.RED

    # Format with K suffix for readability
    if dollars >= 1000:
        return f"{color}{emoji}${dollars // 1000}K{C.RESET}"
    return f"{color}{emoji}${dollars}{C.RESET}"


def get_context_usage(transcript_path: str, context_window: int) -> tuple[int, int, float]:
    """Calculate context window usage from transcript. Returns (used, total, pct)."""
    if not transcript_path or not Path(transcript_path).exists():
        return 0, 0, 0.0
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
                    pct = (used / context_window) * 100 if context_window else 0
                    return used, context_window, pct
            except Exception:
                continue
        return 0, 0, 0.0
    except Exception:
        return 0, 0, 0.0


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
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

    # Context with warning + money framing (Entity Model: loss aversion)
    transcript = input_data.get("transcript_path", "")
    context_window = model.get("context_window", get_magic_number("default_context_window", 200000))
    used, total, pct = get_context_usage(transcript, context_window)
    if used > 0 and total > 0:
        warn = "🚨" if pct >= Thresholds.CTX_WARN else ""
        # Money framing: show remaining budget instead of % used
        budget_str = format_token_budget(used, total)
        context_str = f"{budget_str}{warn}"
    else:
        context_str = f"{C.GREEN}💰$200K{C.RESET}"

    # Fast system stats
    cpu = get_cpu_load()
    ram = get_ram_usage()
    disk = get_disk_usage()

    # Slow subprocess calls - cached + parallel
    slow_funcs = {
        "gpu": get_gpu_vram,
        "services": get_services_status,
        "ports": get_dev_ports,
        "comfyui": get_comfyui_status,
        "net": get_network_status,
        "git": get_git_info,
        "beads": get_beads_status,
    }

    cache = load_cache()
    results: dict[str, str] = {}
    stale_funcs: dict[str, Any] = {}

    for name, fn in slow_funcs.items():
        hit, val = get_cached(cache, name)
        if hit:
            results[name] = val
        else:
            stale_funcs[name] = fn

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
    beads = results.get("beads", "")

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

    # Line 2: Session | Project | Confidence | Beads | Serena | Git
    session_id = input_data.get("session_id", "")[:8]
    project_name, _ = get_project_info()
    confidence = get_confidence_status()
    serena = get_serena_status()

    # Session age from state
    try:
        from _session_constants import get_project_state_file
        state_file = get_project_state_file()
        if state_file.exists():
            with open(state_file) as f:
                state_data = json.load(f)
            session_age = get_session_age(state_data.get("started_at", 0))
        else:
            session_age = ""
    except Exception:
        session_age = ""

    line2_parts = [f"{C.DIM}{session_id}{C.RESET}"]
    if session_age:
        line2_parts.append(session_age)
    line2_parts.append(f"{C.CYAN}{project_name}{C.RESET}")
    if confidence:
        line2_parts.append(confidence)
    if beads:
        line2_parts.append(beads)
    if serena:
        line2_parts.append(serena)
    if git:
        line2_parts.append(git)
    line2 = f" {C.DIM}|{C.RESET} ".join(line2_parts)

    print(f"{line1}\n{line2}")


if __name__ == "__main__":
    main()
