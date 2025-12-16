#!/usr/bin/env python3
"""
Integration Install - One-shot setup for Integration Synergy components.

Sets up:
- Verifies all required files exist
- Creates shell aliases for common operations
- Sets up systemd user service (if available)
- Validates claude-mem connection
- Reports installation status

Usage:
    integration_install.py [--check | --install | --uninstall]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
VENV_PYTHON = CLAUDE_DIR / ".venv" / "bin" / "python"

# Required files for integration
REQUIRED_FILES = {
    "lib/project_context.py": "Project detection",
    "lib/agent_registry.py": "Agent assignment tracking",
    "ops/bd_bridge.py": "Beads-memory bridge",
    "ops/bead_claim.py": "Agent claim wrapper",
    "ops/bead_release.py": "Agent release wrapper",
    "ops/bead_lifecycle_daemon.py": "Lifecycle daemon",
    "ops/bead_orphan_check.py": "Orphan diagnostic",
    "ops/serena.py": "Serena integration",
    "ops/unified_context.py": "Context aggregator",
    "commands/serena.md": "/serena command",
    "commands/si.md": "/si command",
    "commands/sv.md": "/sv command",
    "commands/sm.md": "/sm command",
}

# Shell aliases to add
ALIASES = {
    "bead-claim": f"{VENV_PYTHON} {CLAUDE_DIR}/ops/bead_claim.py",
    "bead-release": f"{VENV_PYTHON} {CLAUDE_DIR}/ops/bead_release.py",
    "bead-orphans": f"{VENV_PYTHON} {CLAUDE_DIR}/ops/bead_orphan_check.py",
    "bead-daemon": f"{VENV_PYTHON} {CLAUDE_DIR}/ops/bead_lifecycle_daemon.py",
    "unified-context": f"{VENV_PYTHON} {CLAUDE_DIR}/ops/unified_context.py",
    "serena-util": f"{VENV_PYTHON} {CLAUDE_DIR}/ops/serena.py",
}


def check_file(rel_path: str) -> tuple[bool, str]:
    """Check if a required file exists."""
    full_path = CLAUDE_DIR / rel_path
    if full_path.exists():
        return True, f"✅ {rel_path}"
    return False, f"❌ {rel_path} - MISSING"


def check_claudemem() -> tuple[bool, str]:
    """Check if claude-mem API is reachable."""
    try:
        import urllib.request

        req = urllib.request.Request("http://127.0.0.1:37777/api/status", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return True, "✅ claude-mem API reachable"
    except Exception as e:
        return False, f"⚠️  claude-mem API not reachable: {e}"
    return False, "⚠️  claude-mem API returned non-200"


def check_bd_cli() -> tuple[bool, str]:
    """Check if bd CLI is available."""
    if shutil.which("bd"):
        return True, "✅ bd CLI found"
    return False, "❌ bd CLI not found in PATH"


def check_systemd() -> tuple[bool, str]:
    """Check if systemd user services are available."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 or "running" in result.stdout:
            return True, "✅ systemd user services available"
        return False, f"⚠️  systemd: {result.stdout.strip()}"
    except FileNotFoundError:
        return False, "⚠️  systemd not available (WSL2?)"
    except Exception as e:
        return False, f"⚠️  systemd check failed: {e}"


def run_check() -> int:
    """Run installation check."""
    print("=" * 50)
    print("Integration Synergy - Installation Check")
    print("=" * 50)
    print()

    all_ok = True

    # Check required files
    print("Required Files:")
    for rel_path, desc in REQUIRED_FILES.items():
        ok, msg = check_file(rel_path)
        print(f"  {msg}")
        if not ok:
            all_ok = False
    print()

    # Check dependencies
    print("Dependencies:")
    ok, msg = check_bd_cli()
    print(f"  {msg}")
    if not ok:
        all_ok = False

    ok, msg = check_claudemem()
    print(f"  {msg}")
    # claude-mem is optional, don't fail

    ok, msg = check_systemd()
    print(f"  {msg}")
    # systemd is optional for WSL2
    print()

    # Check Python venv
    print("Python Environment:")
    if VENV_PYTHON.exists():
        print(f"  ✅ venv: {VENV_PYTHON}")
    else:
        print(f"  ❌ venv not found: {VENV_PYTHON}")
        all_ok = False
    print()

    # Summary
    print("=" * 50)
    if all_ok:
        print("✅ All required components present")
        return 0
    else:
        print("❌ Some components missing - run with --install")
        return 1


def install_aliases() -> None:
    """Add aliases to shell config."""
    # Find shell config file
    shell = os.environ.get("SHELL", "/bin/bash")
    if "zsh" in shell:
        rc_file = Path.home() / ".zshrc"
    else:
        rc_file = Path.home() / ".bashrc"

    if not rc_file.exists():
        print(f"  ⚠️  Shell config not found: {rc_file}")
        return

    # Read current content
    content = rc_file.read_text()

    # Check if already installed
    if "# Integration Synergy aliases" in content:
        print("  ✅ Aliases already installed")
        return

    # Add aliases
    alias_block = ["\n# Integration Synergy aliases"]
    for name, cmd in ALIASES.items():
        alias_block.append(f'alias {name}="{cmd}"')
    alias_block.append("# End Integration Synergy aliases\n")

    with open(rc_file, "a") as f:
        f.write("\n".join(alias_block))

    print(f"  ✅ Aliases added to {rc_file}")
    print("     Run: source ~/.bashrc (or ~/.zshrc) to activate")


def install_systemd_service() -> bool:
    """Install systemd user service for lifecycle daemon."""
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    service_file = systemd_dir / "bead-lifecycle.service"

    # Check if systemd is available
    ok, _ = check_systemd()
    if not ok:
        print("  ⚠️  Skipping systemd (not available)")
        return False

    # Create service file
    systemd_dir.mkdir(parents=True, exist_ok=True)

    service_content = f"""[Unit]
Description=Bead Lifecycle Daemon - Auto-recovery for orphaned beads
After=default.target

[Service]
Type=simple
ExecStart={VENV_PYTHON} {CLAUDE_DIR}/ops/bead_lifecycle_daemon.py --daemon
Restart=on-failure
RestartSec=60
StandardOutput=append:{CLAUDE_DIR}/.beads/daemon.log
StandardError=append:{CLAUDE_DIR}/.beads/daemon.log

[Install]
WantedBy=default.target
"""

    service_file.write_text(service_content)
    print(f"  ✅ Service file created: {service_file}")

    # Reload systemd
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print("  ✅ systemd reloaded")

    # Enable but don't start
    subprocess.run(
        ["systemctl", "--user", "enable", "bead-lifecycle.service"],
        capture_output=True,
    )
    print("  ✅ Service enabled (run 'systemctl --user start bead-lifecycle' to start)")

    return True


def run_install() -> int:
    """Run installation."""
    print("=" * 50)
    print("Integration Synergy - Installation")
    print("=" * 50)
    print()

    # First check what's missing
    missing = []
    for rel_path in REQUIRED_FILES:
        ok, _ = check_file(rel_path)
        if not ok:
            missing.append(rel_path)

    if missing:
        print("Missing required files:")
        for f in missing:
            print(f"  - {f}")
        print("\nThese files must be created first. Cannot proceed.")
        return 1

    print("Installing components...")
    print()

    # Install aliases
    print("Shell Aliases:")
    install_aliases()
    print()

    # Install systemd service
    print("Systemd Service:")
    install_systemd_service()
    print()

    # Make scripts executable
    print("File Permissions:")
    for rel_path in REQUIRED_FILES:
        if rel_path.endswith(".py"):
            full_path = CLAUDE_DIR / rel_path
            if full_path.exists():
                full_path.chmod(0o755)
    print("  ✅ Python scripts made executable")
    print()

    print("=" * 50)
    print("✅ Installation complete")
    print()
    print("Next steps:")
    print("  1. source ~/.bashrc  (or ~/.zshrc)")
    print("  2. systemctl --user start bead-lifecycle  (optional)")
    print("  3. unified-context  (test context aggregation)")
    return 0


def run_uninstall() -> int:
    """Remove installed components."""
    print("=" * 50)
    print("Integration Synergy - Uninstall")
    print("=" * 50)
    print()

    # Remove systemd service
    print("Removing systemd service...")
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "bead-lifecycle.service"],
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "disable", "bead-lifecycle.service"],
            capture_output=True,
        )
        service_file = (
            Path.home() / ".config" / "systemd" / "user" / "bead-lifecycle.service"
        )
        if service_file.exists():
            service_file.unlink()
            print("  ✅ Service removed")
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    except Exception as e:
        print(f"  ⚠️  Could not remove service: {e}")
    print()

    # Note about aliases
    print("Shell Aliases:")
    print("  ⚠️  Manual removal required")
    print(
        "  Edit ~/.bashrc or ~/.zshrc and remove the 'Integration Synergy aliases' block"
    )
    print()

    print("=" * 50)
    print("✅ Uninstall complete (aliases require manual removal)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Integration Synergy installer")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Check installation status")
    group.add_argument("--install", action="store_true", help="Install components")
    group.add_argument("--uninstall", action="store_true", help="Uninstall components")

    args = parser.parse_args()

    if args.install:
        return run_install()
    elif args.uninstall:
        return run_uninstall()
    else:
        # Default to check
        return run_check()


if __name__ == "__main__":
    sys.exit(main())
