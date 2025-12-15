#!/usr/bin/env python3
"""
The System Probe - WSL2 system information and health monitoring

Displays system state for the WSL2 assistant context:
- Hardware: CPU, memory, disk usage
- WSL2: Distro, kernel, Windows host info
- Services: Docker, systemd status
- Network: Interfaces and connectivity

Usage:
    sysinfo.py              # Full system overview
    sysinfo.py --quick      # Just CPU/mem/disk
    sysinfo.py --json       # JSON output for scripts
"""

import argparse
import json
import os
import subprocess
from pathlib import Path


def get_cpu_info() -> dict:
    """Get CPU information."""
    info = {"model": "Unknown", "cores": 0, "load": "N/A"}

    # CPU model
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["model"] = line.split(":")[1].strip()
                    break
    except Exception:
        pass

    # Core count
    info["cores"] = os.cpu_count() or 0

    # Load average
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            info["load"] = f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        pass

    return info


def get_memory_info() -> dict:
    """Get memory information."""
    info = {"total_gb": 0, "used_gb": 0, "available_gb": 0, "percent": 0}

    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = int(parts[1].strip().split()[0])  # Value in kB
                    meminfo[key] = val

        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", 0)
        used = total - available

        info["total_gb"] = round(total / 1024 / 1024, 1)
        info["used_gb"] = round(used / 1024 / 1024, 1)
        info["available_gb"] = round(available / 1024 / 1024, 1)
        info["percent"] = round(used / total * 100, 1) if total else 0
    except Exception:
        pass

    return info


def get_disk_info() -> list:
    """Get disk usage for key paths."""
    paths = ["/", "/home", "/mnt/c"]
    disks = []

    for path in paths:
        if os.path.exists(path):
            try:
                stat = os.statvfs(path)
                total = stat.f_blocks * stat.f_frsize
                free = stat.f_bfree * stat.f_frsize
                used = total - free

                disks.append({
                    "path": path,
                    "total_gb": round(total / 1024**3, 1),
                    "used_gb": round(used / 1024**3, 1),
                    "free_gb": round(free / 1024**3, 1),
                    "percent": round(used / total * 100, 1) if total else 0,
                })
            except Exception:
                pass

    return disks


def get_wsl_info() -> dict:
    """Get WSL2-specific information."""
    info = {
        "distro": "Unknown",
        "kernel": "Unknown",
        "wsl_version": "Unknown",
        "windows_user": "Unknown",
    }

    # Distro name
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    info["distro"] = line.split("=")[1].strip().strip('"')
                    break
    except Exception:
        pass

    # Kernel version
    try:
        result = subprocess.run("uname -r", shell=True, capture_output=True, text=True, timeout=5)
        info["kernel"] = result.stdout.strip() or "Unknown"
    except Exception:
        pass

    # Check if WSL2
    kernel = info["kernel"].lower()
    if "microsoft" in kernel or "wsl" in kernel:
        info["wsl_version"] = "WSL2" if "wsl2" in kernel else "WSL"

    # Windows username
    win_user_path = Path("/mnt/c/Users")
    if win_user_path.exists():
        try:
            users = [d.name for d in win_user_path.iterdir()
                     if d.is_dir() and d.name not in ("Public", "Default", "Default User", "All Users")]
            if users:
                info["windows_user"] = users[0]
        except Exception:
            pass

    return info


def get_services_status() -> dict:
    """Get status of key services."""
    services = {"docker": "not installed", "systemd": "not available"}

    # Docker
    try:
        result = subprocess.run("docker info 2>/dev/null | head -1", shell=True, capture_output=True, text=True, timeout=5)
        if result.stdout.strip():
            services["docker"] = "running"
        elif os.path.exists("/usr/bin/docker"):
            services["docker"] = "installed but not running"
    except Exception:
        if os.path.exists("/usr/bin/docker"):
            services["docker"] = "installed but not running"

    # Systemd
    if os.path.exists("/run/systemd/system"):
        services["systemd"] = "running"
    elif os.path.exists("/lib/systemd/systemd"):
        services["systemd"] = "installed but not running"

    return services


def get_network_info() -> dict:
    """Get network information."""
    info = {"hostname": "Unknown", "interfaces": [], "internet": False}

    # Hostname
    try:
        result = subprocess.run("hostname", shell=True, capture_output=True, text=True, timeout=5)
        info["hostname"] = result.stdout.strip() or "Unknown"
    except Exception:
        pass

    # Get interfaces with IPs
    try:
        result = subprocess.run("ip -4 addr show | grep -E 'inet |^[0-9]+:'", shell=True, capture_output=True, text=True, timeout=5)
        ip_output = result.stdout.strip()
        current_iface = None
        for line in ip_output.split("\n"):
            if line and line[0].isdigit():
                parts = line.split(":")
                if len(parts) >= 2:
                    current_iface = parts[1].strip()
            elif "inet " in line and current_iface:
                ip = line.split()[1].split("/")[0]
                if current_iface != "lo":
                    info["interfaces"].append({"name": current_iface, "ip": ip})
                current_iface = None
    except Exception:
        pass

    # Internet connectivity
    try:
        result = subprocess.run("ping -c 1 -W 2 8.8.8.8 2>/dev/null | grep -c '1 received'", shell=True, capture_output=True, text=True, timeout=5)
        info["internet"] = result.stdout.strip() == "1"
    except Exception:
        pass

    return info


def format_output(data: dict) -> str:
    """Format data as human-readable text."""
    lines = ["=== System Information ===\n"]

    # CPU
    cpu = data["cpu"]
    lines.append(f"CPU: {cpu['model']}")
    lines.append(f"     {cpu['cores']} cores, load: {cpu['load']}\n")

    # Memory
    mem = data["memory"]
    bar_len = 20
    filled = int(bar_len * mem["percent"] / 100)
    bar = "[" + "#" * filled + "-" * (bar_len - filled) + "]"
    lines.append(f"Memory: {mem['used_gb']:.1f} / {mem['total_gb']:.1f} GB ({mem['percent']:.0f}%)")
    lines.append(f"        {bar}\n")

    # Disk
    lines.append("Disk:")
    for disk in data["disks"]:
        lines.append(f"  {disk['path']:10} {disk['used_gb']:>6.1f} / {disk['total_gb']:.1f} GB ({disk['percent']:.0f}%)")
    lines.append("")

    # WSL
    wsl = data["wsl"]
    lines.append(f"WSL2: {wsl['distro']}")
    lines.append(f"      Kernel: {wsl['kernel']}")
    lines.append(f"      Windows user: {wsl['windows_user']}\n")

    # Services
    lines.append("Services:")
    for svc, status in data["services"].items():
        icon = "ok" if "running" in status else "--"
        lines.append(f"  [{icon}] {svc}: {status}")
    lines.append("")

    # Network
    net = data["network"]
    internet_icon = "ok" if net["internet"] else "--"
    lines.append(f"Network: {net['hostname']}")
    for iface in net["interfaces"]:
        lines.append(f"  {iface['name']}: {iface['ip']}")
    lines.append(f"  [{internet_icon}] Internet: {'connected' if net['internet'] else 'disconnected'}")

    return "\n".join(lines)


def format_quick(data: dict) -> str:
    """Format quick summary."""
    mem = data["memory"]
    disk = data["disks"][0] if data["disks"] else {"percent": 0}
    cpu = data["cpu"]

    return f"CPU: {cpu['load']} | Mem: {mem['percent']:.0f}% | Disk: {disk['percent']:.0f}%"


def main():
    parser = argparse.ArgumentParser(description="WSL2 system information")
    parser.add_argument("--quick", action="store_true", help="Quick CPU/mem/disk summary")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    data = {
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disks": get_disk_info(),
        "wsl": get_wsl_info(),
        "services": get_services_status(),
        "network": get_network_info(),
    }

    if args.json:
        print(json.dumps(data, indent=2))
    elif args.quick:
        print(format_quick(data))
    else:
        print(format_output(data))


if __name__ == "__main__":
    main()
