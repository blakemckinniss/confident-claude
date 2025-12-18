---
name: windows-interop
description: |
  Windows integration, WSL2 interop, Windows paths, winget, Windows apps,
  /mnt/c/ access, cross-platform, Windows host, PowerShell, cmd.exe,
  Windows file system, Windows programs, install Windows software.

  Trigger phrases: Windows path, access Windows files, /mnt/c/, winget,
  install Windows program, Windows app, PowerShell, cmd, cross-platform,
  WSL2 Windows, Windows host, C drive, Windows filesystem, exe file,
  Windows registry, Windows service, Windows shortcut, open in Windows,
  Windows explorer, notepad, VS Code Windows, browser Windows side.
---

# Windows Interop

WSL2 integration with Windows host.

## File System Access

### Windows → WSL
```
/mnt/c/Users/<WindowsUser>/  → C:\Users\<WindowsUser>\
/mnt/c/                      → C:\
/mnt/d/                      → D:\
```

### WSL → Windows
```
\\wsl$\Ubuntu\home\blake\     → /home/blake/
```

## Windows Package Management

### /win - Winget Wrapper
```bash
/win install <app>     # Install via winget
/win uninstall <app>   # Remove
/win search <query>    # Find packages
/win list              # Installed apps
```

### Direct Winget
```bash
winget.exe install <package>
winget.exe search <query>
```

## Running Windows Programs

```bash
# Open file in Windows default app
cmd.exe /c start "" "/mnt/c/path/to/file"

# Run Windows executable
/mnt/c/Program\ Files/App/app.exe

# PowerShell
powershell.exe -Command "Get-Process"

# Open URL in Windows browser
cmd.exe /c start "" "https://example.com"
```

## Path Conversion

```bash
# WSL path to Windows path
wslpath -w /home/blake/file.txt
# Output: \\wsl$\Ubuntu\home\jinx\file.txt

# Windows path to WSL path
wslpath -u 'C:\Users\Blake\file.txt'
# Output: /mnt/c/Users/Blake/file.txt
```

## Common Patterns

### Open in VS Code (Windows)
```bash
code.exe /path/to/file
```

### Copy to Windows Clipboard
```bash
cat file.txt | clip.exe
```

### Open Explorer Here
```bash
explorer.exe .
```

## Environment

| Property | Value |
|----------|-------|
| WSL Distro | Ubuntu 24.04 |
| Windows User | Blake |
| Host OS | Windows 11 |
