#!/usr/bin/env python3
"""
System Assistant Statusline v2.1 - Full WSL2 system status at a glance

Line 1: Model | Context$ | CPU | RAM | Swap | Disk | GPU | Services | Ports | Network
Line 2: Session | Project | Confidence+Streak | Beads | Serena | Git

v2.1 Improvements:
- Subprocess consolidation: services now uses single `ps aux` (-2 calls)
- Git commands combined: single `git status --porcelain --branch` (-1 call)
- Direct beads DB access via SQLite (no subprocess overhead)
- Robust nvidia-smi parsing for output variations
- Swap usage indicator for WSL2 memory pressure
- ComfyUI folded into DEV_PORTS (8188:comfy)
- Extracted timeout constants (Timeouts class)
- User-specific cache file (avoids multi-instance collision)

v2.0 Improvements:
- Project-aware (shows detected project name, not just folder)
- Confidence streak indicator
- Beads task count
- Serena activation status
- Session age
- Context exhaustion warning (🚨 at 75%+)
- Extracted color thresholds
- Type hints throughout
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
    # Swap usage
    SWAP_RED = 50
    SWAP_YELLOW = 25
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


# Subprocess timeouts (seconds)
class Timeouts:
    FAST = 1  # Quick checks (pgrep, ss, git)
    MEDIUM = 2  # Heavier checks (nvidia-smi, bd)
    PARALLEL = 3  # ThreadPoolExecutor timeout
    DB = 0.5  # SQLite connection timeout


# =============================================================================
# CACHE LAYER - subprocess results don't change rapidly
# =============================================================================

# User-specific cache to avoid collision between instances
CACHE_FILE = Path.home() / ".claude" / "tmp" / "statusline_cache.json"

# TTL per metric (seconds) - tuned for typical change frequency
CACHE_TTL: dict[str, int] = {
    "gpu": 2,  # VRAM can change during inference
    "services": 5,  # Docker/node/python processes stable
    "net": 10,  # Connectivity rarely changes
    "git": 3,  # Changes with edits but not rapidly
    "ports": 3,  # Dev servers start/stop occasionally
    "beads": 5,  # Task status relatively stable
    "swap": 5,  # Swap usage relatively stable
}

# Dev ports worth monitoring (port -> short label)
DEV_PORTS: dict[int, str] = {
    3000: "3k",  # React, Next.js, Create React App
    3001: "3k1",  # Next.js alt
    4200: "ng",  # Angular
    5000: "5k",  # Flask, various
    5173: "vite",  # Vite dev server
    5174: "vite",  # Vite alt
    8000: "8k",  # Django, FastAPI, uvicorn
    8080: "8080",  # Generic, Tomcat, etc
    8188: "comfy",  # ComfyUI
    8888: "jup",  # Jupyter
    9000: "9k",  # PHP-FPM, SonarQube
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
        return colorize(
            f"{free_gb:.0f}G", pct, Thresholds.DISK_RED, Thresholds.DISK_YELLOW
        )
    except Exception:
        return f"{C.DIM}--{C.RESET}"


# =============================================================================
# SUBPROCESS METRICS (Slow - cached + parallel)
# =============================================================================


def get_services_status() -> str:
    """Get status of key services (Docker, Node, Python) in single subprocess."""
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=Timeouts.FAST
        )
        if result.returncode != 0:
            return ""

        lines = result.stdout.split("\n")
        docker_count = 0
        node_count = 0
        python_count = 0

        for line in lines:
            lower = line.lower()
            # Docker containers (exclude containerd daemon)
            if (
                "docker" in lower
                and "containerd" not in lower
                and "/docker" not in lower
            ):
                docker_count += 1
            # Node processes
            if (
                "/node " in line or "node " in lower.split()[-1]
                if lower.split()
                else False
            ):
                node_count += 1
            # Python processes
            if "python" in lower:
                python_count += 1

        # Exclude self from python count
        python_count = max(0, python_count - 1)

        services = []
        if docker_count > 0:
            services.append(f"{C.CYAN}D:{docker_count}{C.RESET}")
        if node_count > 0:
            services.append(f"{C.GREEN}N:{node_count}{C.RESET}")
        if python_count > 0:
            services.append(f"{C.YELLOW}P:{python_count}{C.RESET}")
        return " ".join(services)
    except Exception as e:
        log_debug("statusline", f"services check failed: {e}")
        return ""


def get_network_status() -> str:
    """Check internet connectivity via DNS."""
    try:
        result = subprocess.run(
            ["getent", "hosts", "google.com"],
            capture_output=True,
            timeout=Timeouts.FAST,
        )
        return (
            f"{C.GREEN}NET{C.RESET}"
            if result.returncode == 0
            else f"{C.RED}NET{C.RESET}"
        )
    except Exception:
        return f"{C.RED}NET{C.RESET}"


def get_gpu_vram() -> str:
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
            timeout=Timeouts.MEDIUM,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        # Robust parsing: handle ", " or "," or whitespace variations
        parts = result.stdout.strip().replace(",", " ").split()
        if len(parts) < 2:
            return ""
        used, total = int(parts[0]), int(parts[1])
        pct = (used / total) * 100
        used_gb, total_gb = used / 1024, total / 1024
        return colorize(
            f"{used_gb:.1f}/{total_gb:.0f}G",
            pct,
            Thresholds.GPU_RED,
            Thresholds.GPU_YELLOW,
        )
    except Exception:
        return ""


def get_dev_ports() -> str:
    """Check which dev ports are listening."""
    try:
        result = subprocess.run(
            ["ss", "-tlnH"],
            capture_output=True,
            text=True,
            timeout=Timeouts.FAST,
        )
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


def get_git_info() -> str:
    """Get git branch and status in single command."""
    try:
        # Combined: --branch shows branch info, --porcelain shows file status
        result = subprocess.run(
            ["git", "status", "--porcelain", "--branch"],
            capture_output=True,
            text=True,
            timeout=Timeouts.FAST,
        )
        if result.returncode != 0:
            return ""

        lines = result.stdout.strip().split("\n")
        if not lines:
            return ""

        # First line: ## branch...tracking or ## HEAD (detached)
        branch_line = lines[0]
        branch = ""
        if branch_line.startswith("## "):
            branch_part = branch_line[3:]  # Remove "## "
            # Handle "branch...origin/branch" format
            branch = branch_part.split("...")[0].split()[0]

        if not branch:
            return ""

        # Rest is file status
        status_lines = lines[1:] if len(lines) > 1 else []
        status_str = ""
        if status_lines:
            modified = sum(1 for ln in status_lines if len(ln) > 1 and ln[1] == "M")
            staged = sum(1 for ln in status_lines if ln and ln[0] not in (" ", "?"))
            untracked = sum(1 for ln in status_lines if ln.startswith("??"))
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
    """Get active beads count via direct DB read (faster than subprocess)."""
    try:
        import sqlite3

        db_path = Path.home() / ".claude" / ".beads" / "beads.db"
        if not db_path.exists():
            return ""
        with sqlite3.connect(str(db_path), timeout=Timeouts.DB) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE status = 'in_progress'"
            )
            count = cursor.fetchone()[0]
            if count > 0:
                return f"{C.YELLOW}📋{count}{C.RESET}"
        return ""
    except Exception:
        return ""


def get_swap_usage() -> str:
    """Get swap usage if significant (WSL2 memory pressure indicator)."""
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mem[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = mem.get("SwapTotal", 0)
        free = mem.get("SwapFree", 0)
        if total == 0:
            return ""
        used_pct = ((total - free) / total) * 100
        if used_pct < 10:
            return ""  # Don't show if minimal
        return colorize(
            f"{used_pct:.0f}%", used_pct, Thresholds.SWAP_RED, Thresholds.SWAP_YELLOW
        )
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


def get_mastermind_turn() -> str:
    """Get mastermind turn count for current session."""
    try:
        from _session_constants import get_project_state_file

        state_file = get_project_state_file()
        if not state_file.exists():
            return ""
        with open(state_file) as f:
            data = json.load(f)
        session_id = data.get("session_id", "")
        if not session_id:
            return ""

        # Load mastermind state for this session
        mm_state_file = (
            Path.home() / ".claude" / "tmp" / f"mastermind_{session_id}.json"
        )
        if not mm_state_file.exists():
            return ""
        with open(mm_state_file) as f:
            mm_data = json.load(f)

        turn = mm_data.get("turn_count", 0)
        if turn > 0:
            return f"{C.DIM}T{turn}{C.RESET}"
        return ""
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


def get_context_usage(
    transcript_path: str, context_window: int
) -> tuple[int, int, float]:
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
    context_window = model.get(
        "context_window", get_magic_number("default_context_window", 200000)
    )
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
            for future in as_completed(futures, timeout=Timeouts.PARALLEL):
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
    net = results.get("net", f"{C.DIM}NET{C.RESET}")
    git = results.get("git", "")
    beads = results.get("beads", "")
    swap = get_swap_usage()  # Fast /proc read, not cached

    # Line 1: Model | Context | System
    line1_parts = [
        model_short,
        f"CTX:{context_str}",
        f"CPU:{cpu}",
        f"RAM:{ram}",
    ]
    if swap:
        line1_parts.append(f"SW:{swap}")
    line1_parts.append(f"DSK:{disk}")
    if gpu:
        line1_parts.append(f"GPU:{gpu}")
    if services:
        line1_parts.append(services)
    if ports:
        line1_parts.append(ports)
    line1_parts.append(net)
    line1 = f" {C.DIM}|{C.RESET} ".join(line1_parts)

    # Line 2: Session | Project | Confidence | Turn | Beads | Serena | Git
    session_id = input_data.get("session_id", "")[:8]
    project_name, _ = get_project_info()
    confidence = get_confidence_status()
    mm_turn = get_mastermind_turn()
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
    if mm_turn:
        line2_parts.append(mm_turn)
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
