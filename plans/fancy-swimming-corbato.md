# Command Center - Architecture Plan

**Location:** `/home/jinx/projects/command-center`
**Stack:** FastAPI + htmx + Tailwind (CDN) + SQLite
**Philosophy:** No Node build step, hybrid Python backend, localhost-only

---

## Core Modules

| Module | Purpose |
|--------|---------|
| **Notes** | Markdown notes with tags, FTS search, quick capture |
| **Links** | Categorized bookmarks, auto-fetch titles, quick open |
| **Files** | Dual-pane browser (WSL2 + Windows), Explorer integration |
| **Scripts** | Python/Node/Bash/PowerShell runner, save library, scheduling |
| **Launcher** | Configurable app shortcuts for Windows + WSL2 |

---

## Project Structure

```
command-center/
├── pyproject.toml              # uv/pip project config
├── run.py                      # Entry point (uvicorn)
├── src/
│   └── command_center/
│       ├── __init__.py
│       ├── main.py             # FastAPI app factory
│       ├── config.py           # Settings (Pydantic)
│       ├── database.py         # SQLite + migrations
│       ├── models/             # SQLAlchemy/dataclass models
│       │   ├── note.py
│       │   ├── link.py
│       │   ├── script.py
│       │   ├── shortcut.py
│       │   └── schedule.py
│       ├── routers/            # API endpoints
│       │   ├── notes.py
│       │   ├── links.py
│       │   ├── files.py
│       │   ├── scripts.py
│       │   ├── launcher.py
│       │   └── system.py       # Windows bridge, clipboard
│       ├── services/           # Business logic
│       │   ├── note_service.py
│       │   ├── script_runner.py
│       │   ├── windows_bridge.py
│       │   └── scheduler.py
│       ├── templates/          # Jinja2 + htmx partials
│       │   ├── base.html
│       │   ├── index.html
│       │   ├── partials/
│       │   │   ├── note_list.html
│       │   │   ├── note_editor.html
│       │   │   ├── link_list.html
│       │   │   ├── file_browser.html
│       │   │   ├── script_editor.html
│       │   │   └── launcher_grid.html
│       │   └── components/
│       │       ├── modal.html
│       │       ├── toast.html
│       │       └── command_palette.html
│       └── static/
│           ├── app.js          # Minimal vanilla JS
│           └── style.css       # Custom overrides
├── data/
│   └── command_center.db       # SQLite database
├── scripts/                    # User's saved scripts
└── tests/
```

---

## Database Schema

```sql
-- Notes with full-text search
CREATE TABLE notes (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    tags TEXT,  -- JSON array
    pinned BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE VIRTUAL TABLE notes_fts USING fts5(title, content, tags, content=notes);

-- Links/Bookmarks
CREATE TABLE links (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    category TEXT,
    tags TEXT,  -- JSON array
    favicon TEXT,
    click_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Saved Scripts
CREATE TABLE scripts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    language TEXT NOT NULL,  -- python, node, bash, powershell
    code TEXT NOT NULL,
    description TEXT,
    category TEXT,
    tags TEXT,
    run_count INTEGER DEFAULT 0,
    last_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- App/Command Shortcuts
CREATE TABLE shortcuts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    command TEXT NOT NULL,
    category TEXT,
    icon TEXT,
    environment TEXT,  -- wsl, windows
    working_dir TEXT,
    env_vars TEXT,  -- JSON object
    hotkey TEXT,
    sort_order INTEGER DEFAULT 0
);

-- Scheduled Tasks
CREATE TABLE schedules (
    id INTEGER PRIMARY KEY,
    script_id INTEGER REFERENCES scripts(id),
    cron_expr TEXT,  -- or simple interval
    enabled BOOLEAN DEFAULT 1,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP
);

-- Quick access paths
CREATE TABLE quick_paths (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    environment TEXT,  -- wsl, windows
    sort_order INTEGER DEFAULT 0
);
```

---

## API Endpoints

### Notes
```
GET    /api/notes              # List (with search query param)
POST   /api/notes              # Create
GET    /api/notes/{id}         # Get one
PUT    /api/notes/{id}         # Update
DELETE /api/notes/{id}         # Delete
GET    /api/notes/search?q=    # FTS search
```

### Links
```
GET    /api/links              # List by category
POST   /api/links              # Create (auto-fetch title)
PUT    /api/links/{id}         # Update
DELETE /api/links/{id}         # Delete
POST   /api/links/{id}/click   # Track click, return URL
```

### Files
```
GET    /api/files/browse?path= # List directory
POST   /api/files/open         # Open in default app
POST   /api/files/explorer     # Open folder in Explorer
GET    /api/files/quick-paths  # Saved shortcuts
POST   /api/files/quick-paths  # Add shortcut
```

### Scripts
```
GET    /api/scripts            # List
POST   /api/scripts            # Save new
PUT    /api/scripts/{id}       # Update
DELETE /api/scripts/{id}       # Delete
POST   /api/scripts/run        # Run ephemeral (WebSocket upgrade)
POST   /api/scripts/{id}/run   # Run saved script
WS     /ws/script-output       # Real-time output stream
```

### Launcher
```
GET    /api/shortcuts          # List by category
POST   /api/shortcuts          # Create
PUT    /api/shortcuts/{id}     # Update
DELETE /api/shortcuts/{id}     # Delete
POST   /api/shortcuts/{id}/run # Execute shortcut
```

### System
```
POST   /api/system/clipboard   # Copy to clipboard
GET    /api/system/info        # WSL2/Windows info
POST   /api/system/command     # Run arbitrary command
POST   /api/system/open-url    # Open URL in Windows browser
```

---

## Windows Bridge Implementation

```python
# src/command_center/services/windows_bridge.py

import subprocess
from pathlib import Path

def wsl_to_windows_path(wsl_path: str) -> str:
    """Convert /home/user/file to \\wsl$\Ubuntu\home\user\file"""
    result = subprocess.run(
        ["wslpath", "-w", wsl_path],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def windows_to_wsl_path(win_path: str) -> str:
    """Convert C:\Users\... to /mnt/c/Users/..."""
    result = subprocess.run(
        ["wslpath", "-u", win_path],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def open_in_explorer(path: str):
    """Open folder in Windows Explorer"""
    win_path = wsl_to_windows_path(path)
    subprocess.run(["explorer.exe", win_path])

def open_file_default(path: str):
    """Open file with Windows default application"""
    win_path = wsl_to_windows_path(path)
    subprocess.run(["cmd.exe", "/c", "start", "", win_path])

def run_powershell(script: str) -> tuple[str, str, int]:
    """Execute PowerShell script from WSL2"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True, text=True
    )
    return result.stdout, result.stderr, result.returncode

def copy_to_clipboard(text: str):
    """Copy text to Windows clipboard"""
    subprocess.run(
        ["clip.exe"],
        input=text.encode(),
        check=True
    )

def open_url_windows(url: str):
    """Open URL in Windows default browser"""
    subprocess.run(["cmd.exe", "/c", "start", url])

def start_windows_app(exe_path: str, args: list[str] = None):
    """Launch Windows application"""
    cmd = ["cmd.exe", "/c", "start", "", exe_path]
    if args:
        cmd.extend(args)
    subprocess.Popen(cmd)
```

---

## Frontend Approach

### htmx + Jinja2 Pattern
```html
<!-- templates/partials/note_list.html -->
<div id="note-list" class="space-y-2">
  {% for note in notes %}
  <div class="p-3 bg-gray-800 rounded hover:bg-gray-700 cursor-pointer"
       hx-get="/api/notes/{{ note.id }}"
       hx-target="#note-editor"
       hx-swap="innerHTML">
    <h3 class="font-medium">{{ note.title }}</h3>
    <p class="text-sm text-gray-400 truncate">{{ note.content[:100] }}</p>
    <div class="flex gap-1 mt-1">
      {% for tag in note.tags %}
      <span class="text-xs bg-blue-900 px-1.5 py-0.5 rounded">{{ tag }}</span>
      {% endfor %}
    </div>
  </div>
  {% endfor %}
</div>
```

### Command Palette (Ctrl+K)
```javascript
// static/app.js
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    document.getElementById('command-palette').classList.toggle('hidden');
    document.getElementById('palette-search').focus();
  }
});
```

### Real-time Script Output (WebSocket)
```javascript
function runScript(code, language) {
  const ws = new WebSocket(`ws://${location.host}/ws/script-output`);
  const output = document.getElementById('script-output');
  output.textContent = '';

  ws.onopen = () => {
    ws.send(JSON.stringify({ code, language }));
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'stdout') {
      output.textContent += data.text;
    } else if (data.type === 'stderr') {
      output.innerHTML += `<span class="text-red-400">${data.text}</span>`;
    } else if (data.type === 'exit') {
      output.innerHTML += `\n<span class="text-gray-500">Exit code: ${data.code}</span>`;
    }
  };
}
```

---

## Implementation Phases

### Phase 1: Foundation + Notes MVP (Day 1)
1. Project scaffolding (pyproject.toml, directory structure)
2. FastAPI app with Jinja2 templates
3. SQLite database setup with notes table + FTS
4. Basic CRUD for notes
5. Simple UI: list + editor + search
6. **Deliverable:** Working notes app, immediate value

### Phase 2: Links + Quick Capture (Day 2)
1. Links table + CRUD endpoints
2. Auto-fetch page titles (httpx)
3. Category management
4. Quick-add modal (Ctrl+L hotkey)
5. Click tracking + clipboard copy
6. **Deliverable:** Bookmark manager working

### Phase 3: File Browser + Windows Bridge (Day 3)
1. Windows bridge service (all functions)
2. File browser API (list, open, navigate)
3. Dual-pane UI (WSL2 | Windows)
4. Quick paths (bookmarked directories)
5. Context menu (open in Explorer, copy path)
6. **Deliverable:** Full file navigation

### Phase 4: Script Runner (Day 4-5)
1. Script model + CRUD
2. WebSocket endpoint for streaming output
3. Script editor with syntax highlighting (CodeMirror CDN)
4. Language selector (Python, Node, Bash, PowerShell)
5. Ephemeral + saved script modes
6. **Deliverable:** Interactive script hub

### Phase 5: Launcher + Polish (Day 6)
1. Shortcuts model + CRUD
2. Launcher grid UI
3. Category organization
4. Hotkey support
5. Command palette (Ctrl+K) searching everything
6. **Deliverable:** Full launcher

### Phase 6: Scheduling + Extensions (Day 7+)
1. Simple scheduler (APScheduler)
2. Schedule UI for scripts
3. Module/plugin architecture
4. Dashboard customization
5. Settings page
6. **Deliverable:** Complete command center

---

## Key Dependencies

```toml
[project]
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "httpx>=0.27",          # Async HTTP for fetching link titles
    "websockets>=12.0",     # Script output streaming
    "apscheduler>=3.10",    # Simple scheduling
]

[project.optional-dependencies]
dev = ["ruff", "pytest"]
```

No SQLAlchemy needed - use raw sqlite3 with simple helper functions for this scale.

---

## Quick Start Commands

```bash
# Create project
cd /home/jinx/projects/command-center
uv init
uv add fastapi uvicorn jinja2 python-multipart httpx websockets apscheduler

# Run development server
uv run uvicorn src.command_center.main:app --reload --host 127.0.0.1 --port 8080

# Access from Windows browser
# http://localhost:8080
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| No ORM | Raw sqlite3 | Simpler, this scale doesn't need it |
| htmx over React | No build step | Faster iteration, user preference |
| Tailwind CDN | No PostCSS | Zero build complexity |
| WebSocket for scripts | Real-time streaming | Better UX than polling |
| Single SQLite file | Simple backup/restore | Just copy one file |
| No auth | localhost-only | Single user, trusted network |

---

## Future Extensions

- **Claude Code integration**: Button to `cd /path && claude` in terminal
- **System tray**: Electron wrapper for Windows tray icon (later)
- **Mobile view**: Responsive design for phone access on LAN
- **Import notepad files**: Bulk import existing .txt files to notes
- **Git backup**: Auto-commit data/ to a private repo
