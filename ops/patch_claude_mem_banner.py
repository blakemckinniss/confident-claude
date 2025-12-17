#!/usr/bin/env python3
"""Patch claude-mem plugin to remove startup banner noise.

Removes the verbose banner (header, tips, Discord link, localhost link) while
keeping the actual context injection functional.

Usage:
    python patch_claude_mem_banner.py [--check] [--all]

Options:
    --check  Only check if patch is needed, don't apply
    --all    Patch all cached versions, not just latest
"""

import re
import sys
from pathlib import Path

PLUGIN_CACHE = Path.home() / ".claude" / "plugins" / "cache" / "thedotmack" / "claude-mem"

# The banner pattern to find (the verbose output)
BANNER_PATTERN = re.compile(
    r'console\.error\(`\s*'
    r'[^`]*Claude-Mem Context Loaded[^`]*'
    r'`\s*\+\s*r\s*\+\s*`[^`]*'
    r'(?:Community|Discord|localhost)[^`]*`\)',
    re.DOTALL
)

# What to replace it with (just output the context)
REPLACEMENT = 'console.error(r)'

# Simpler detection: check if the clean version exists
CLEAN_PATTERN = re.compile(r'console\.error\(r\)\}catch')


def get_versions() -> list[Path]:
    """Get all cached plugin versions, sorted newest first."""
    if not PLUGIN_CACHE.exists():
        return []
    versions = [d for d in PLUGIN_CACHE.iterdir() if d.is_dir() and re.match(r'\d+\.\d+\.\d+', d.name)]
    return sorted(versions, key=lambda p: [int(x) for x in p.name.split('.')], reverse=True)


def is_patched(hook_file: Path) -> bool:
    """Check if the hook file is already patched."""
    content = hook_file.read_text()
    # If we find the clean pattern and NOT the banner pattern, it's patched
    return bool(CLEAN_PATTERN.search(content)) and not bool(BANNER_PATTERN.search(content))


def needs_patch(hook_file: Path) -> bool:
    """Check if the hook file needs patching."""
    content = hook_file.read_text()
    return bool(BANNER_PATTERN.search(content))


def patch_file(hook_file: Path, dry_run: bool = False) -> bool:
    """Patch the hook file to remove the banner. Returns True if patched."""
    content = hook_file.read_text()

    if not BANNER_PATTERN.search(content):
        return False

    new_content = BANNER_PATTERN.sub(REPLACEMENT, content)

    if new_content == content:
        return False

    if not dry_run:
        hook_file.write_text(new_content)

    return True


def main():
    check_only = '--check' in sys.argv
    patch_all = '--all' in sys.argv

    versions = get_versions()

    if not versions:
        print("No claude-mem versions found in plugin cache")
        return 1

    targets = versions if patch_all else versions[:1]

    results = []
    for version_dir in targets:
        hook_file = version_dir / "scripts" / "user-message-hook.js"

        if not hook_file.exists():
            results.append((version_dir.name, "missing", None))
            continue

        if is_patched(hook_file):
            results.append((version_dir.name, "patched", hook_file))
        elif needs_patch(hook_file):
            if check_only:
                results.append((version_dir.name, "needs_patch", hook_file))
            else:
                if patch_file(hook_file):
                    results.append((version_dir.name, "patched_now", hook_file))
                else:
                    results.append((version_dir.name, "failed", hook_file))
        else:
            results.append((version_dir.name, "unknown", hook_file))

    # Print results
    for version, status, path in results:
        if status == "patched":
            print(f"  {version}: Already patched")
        elif status == "needs_patch":
            print(f"  {version}: Needs patching")
        elif status == "patched_now":
            print(f"  {version}: Patched successfully")
        elif status == "missing":
            print(f"  {version}: Hook file missing")
        elif status == "failed":
            print(f"  {version}: Patch failed (pattern not found)")
        else:
            print(f"  {version}: Unknown state")

    # Summary
    needs = [r for r in results if r[1] == "needs_patch"]
    patched = [r for r in results if r[1] in ("patched", "patched_now")]

    if check_only and needs:
        print(f"\n{len(needs)} version(s) need patching. Run without --check to apply.")
        return 1
    elif patched:
        print(f"\n{len(patched)} version(s) patched.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
