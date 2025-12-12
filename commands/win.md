---
description: 🪟 Windows Manager - Install/uninstall Windows programs via winget
argument-hint: <action> [app]
allowed-tools: Bash
---

# Windows Program Manager

Manage Windows 11 programs from WSL2 using winget.

**Argument:** $ARGUMENTS

## Commands

| Action | Description | Example |
|--------|-------------|---------|
| `install <app>` | Install a program | `/win install Firefox` |
| `uninstall <app>` | Remove a program | `/win uninstall Spotify` |
| `search <term>` | Find available packages | `/win search discord` |
| `list` | Show installed programs | `/win list` |
| `list <filter>` | Filter installed programs | `/win list Adobe` |
| `upgrade` | Upgrade all programs | `/win upgrade` |
| `upgrade <app>` | Upgrade specific program | `/win upgrade Firefox` |
| `show <app>` | Show package details | `/win show Mozilla.Firefox` |

## Protocol

1. Parse the action from `$ARGUMENTS`
2. Run the appropriate winget command via Windows CMD
3. Report results clearly

## Execution

Run winget via CMD with full path (required from WSL2):

```bash
/mnt/c/Windows/System32/cmd.exe /c "C:\Users\Blake\AppData\Local\Microsoft\WindowsApps\winget.exe <args>"
```

Ignore the UNC path warning - it's harmless.

## Common Package IDs

| App | Package ID |
|-----|------------|
| Firefox | `Mozilla.Firefox` |
| Chrome | `Google.Chrome` |
| VS Code | `Microsoft.VisualStudioCode` |
| Discord | `Discord.Discord` |
| Spotify | `Spotify.Spotify` |
| Steam | `Valve.Steam` |
| 7-Zip | `7zip.7zip` |
| VLC | `VideoLAN.VLC` |

## Notes

- Use `search` first if unsure of exact package ID
- Some installs may prompt for UAC elevation on Windows side
- `--silent` flag available for non-interactive installs: `/win install Firefox --silent`
