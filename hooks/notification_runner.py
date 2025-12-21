#!/usr/bin/env python3
"""
Notification Hook Runner

Fires when Claude Code sends notifications.
Types: permission_prompt, idle_prompt, auth_success, elicitation_dialog

Opportunities:
1. Desktop notifications (WSL → Windows)
2. Logging for audit trail
3. Idle timeout handling
4. Custom notification routing
"""

import json
import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime


MAX_NOTIFICATION_LENGTH = 200
NOTIFICATION_TIMEOUT = 5


def _send_wsl_notification(title: str, message: str) -> bool:
    """Send notification via PowerShell on WSL2."""
    ps_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $template = @"
    <toast>
        <visual>
            <binding template="ToastText02">
                <text id="1">{title}</text>
                <text id="2">{message}</text>
            </binding>
        </visual>
    </toast>
"@
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($template)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Claude Code").Show($toast)
    """
    result = subprocess.run(
        ["powershell.exe", "-Command", ps_script],
        capture_output=True,
        timeout=NOTIFICATION_TIMEOUT,
    )
    return result.returncode == 0


def _send_linux_notification(title: str, message: str, urgency: str) -> bool:
    """Send notification via notify-send on Linux."""
    result = subprocess.run(
        ["notify-send", "-u", urgency, title, message],
        capture_output=True,
        timeout=NOTIFICATION_TIMEOUT,
    )
    return result.returncode == 0


def send_desktop_notification(title: str, message: str, urgency: str = "normal"):
    """
    Send desktop notification.
    On WSL2, uses powershell to show Windows toast notification.
    On Linux, uses notify-send.
    Non-critical: failures are silently ignored.
    """
    if len(message) > MAX_NOTIFICATION_LENGTH:
        message = message[:MAX_NOTIFICATION_LENGTH] + "..."

    is_wsl = "microsoft" in os.uname().release.lower()

    try:
        if is_wsl:
            _send_wsl_notification(title, message)
        else:
            _send_linux_notification(title, message, urgency)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # Non-critical: notification failures don't break the hook


def log_notification(data: dict):
    """Log notification to audit file."""
    log_dir = Path.home() / ".claude" / "tmp" / "audit"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "notifications.jsonl"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": data.get("session_id", "unknown"),
        "notification_type": data.get("notification_type", "unknown"),
        "message": data.get("message", "")[:500],  # Truncate
    }

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def handle_notification(data: dict):
    """
    Handle different notification types.
    """
    notification_type = data.get("notification_type", "")
    message = data.get("message", "")

    # Always log
    log_notification(data)

    # Type-specific handling
    if notification_type == "permission_prompt":
        # Permission needed - send desktop notification
        send_desktop_notification(
            "🔐 Claude Code Permission", message, urgency="critical"
        )

    elif notification_type == "idle_prompt":
        # Claude is waiting - gentle notification
        send_desktop_notification(
            "⏳ Claude Code Waiting", "Claude is waiting for input", urgency="low"
        )

    elif notification_type == "auth_success":
        # Auth completed - log it
        # Could also send notification but usually not needed
        pass

    elif notification_type == "elicitation_dialog":
        # MCP server requesting info
        send_desktop_notification("💬 MCP Server Request", message, urgency="normal")

    else:
        # Unknown type - log only
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    handle_notification(data)

    # Notification hook doesn't return decision, just exit 0
    sys.exit(0)


if __name__ == "__main__":
    main()
