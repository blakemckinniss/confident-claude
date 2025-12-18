---
name: system-maintenance
description: |
  System health, disk space, cleanup, housekeeping, maintenance, system info,
  CPU usage, memory, services, WSL2 status, free space, clear cache,
  performance issues, slow computer, resource usage, process management.

  Trigger phrases: check system health, how much disk space, clean up,
  free some space, housekeeping, system slow, out of memory, CPU usage,
  what tools available, WSL2 status, system resources, performance check,
  memory leak, high CPU, disk full, no space left, storage cleanup,
  cache clear, temp files, garbage collection, prune old files,
  system info, hardware info, specs, available RAM, free memory,
  running processes, background tasks, zombie processes, hung process,
  service status, daemon running, systemd, process list, top, htop,
  network status, connectivity, ports in use, listening ports,
  environment check, dependencies installed, missing tools, setup verify.
---

# System Maintenance

Tools for system health and cleanup.

## Primary Tools

### sysinfo.py - System Health
```bash
sysinfo.py           # Full report
sysinfo.py --quick   # Summary
sysinfo.py --json    # For scripts
```
Reports: CPU, memory, disk, services, network, WSL2.

### housekeeping.py - Disk Cleanup
```bash
housekeeping.py --status   # Check usage
housekeeping.py --execute  # Clean up
```
Cleans: debug/, file-history/, session-env/, todos/

### inventory.py - Available Tools
```bash
inventory.py           # Full scan
inventory.py --compact # Brief
```

## Slash Commands
- `/sysinfo` - Health check
- `/housekeeping` - Disk cleanup
- `/inventory` - Tool scan

## Maintenance Workflow
```bash
sysinfo --quick          # Check health
housekeeping --status    # Check disk
housekeeping --execute   # Clean if needed
```
