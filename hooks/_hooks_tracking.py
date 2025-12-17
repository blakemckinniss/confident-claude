"""
Tracking-related PostToolUse hooks.

Monitors patterns, detects repetitive work, tracks learning opportunities.
Priority range: 55-72
"""

import _lib_path  # noqa: F401
import re
import time
import shutil
import subprocess
from pathlib import Path
from collections import Counter

from _hook_registry import register_hook
from _hook_result import HookResult
from _config import get_magic_number
from _cooldown import beads_sync_cooldown
from session_state import SessionState, get_adaptive_threshold, record_threshold_trigger


# =============================================================================
# SCRATCH ENFORCER (priority 55)
# =============================================================================

SCRATCH_STATE_FILE = (
    Path(__file__).parent.parent / "memory" / "scratch_enforcer_state.json"
)
REPETITION_WINDOW = get_magic_number("repetition_window_seconds", 300)

REPETITIVE_PATTERNS = {
    "multi_file_edit": {
        "tools": ["Edit", "Write"],
        "threshold": 4,
        "suggestion": "Consider writing a .claude/tmp/ script to batch these edits",
    },
    "multi_file_read": {
        "tools": ["Read"],
        "threshold": 5,
        "suggestion": "Use Glob/Grep or write a .claude/tmp/ analysis script",
    },
    "multi_bash": {
        "tools": ["Bash"],
        "threshold": 4,
        "suggestion": "Chain commands with && or write a .claude/tmp/ script",
    },
    "multi_grep": {
        "tools": ["Grep"],
        "threshold": 4,
        "suggestion": "Write a .claude/tmp/ script for complex multi-pattern search",
    },
}


@register_hook("scratch_enforcer", None, priority=55)
def check_scratch_enforcer(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Detect repetitive manual work, suggest scripts."""
    tool_name = data.get("tool_name", "")
    if not tool_name:
        return HookResult.none()

    scratch_state = runner_state.get("scratch_state", {})
    scratch_state.setdefault("tool_counts", {})
    scratch_state.setdefault("last_reset", time.time())
    scratch_state.setdefault("suggestions_given", [])

    if time.time() - scratch_state.get("last_reset", 0) > REPETITION_WINDOW:
        scratch_state = {
            "tool_counts": {},
            "last_reset": time.time(),
            "suggestions_given": [],
        }

    scratch_state["tool_counts"][tool_name] = (
        scratch_state["tool_counts"].get(tool_name, 0) + 1
    )

    suggestion = None
    for pattern_name, config in REPETITIVE_PATTERNS.items():
        if pattern_name in scratch_state.get("suggestions_given", []):
            continue
        total = sum(scratch_state["tool_counts"].get(t, 0) for t in config["tools"])
        if total >= config["threshold"]:
            scratch_state["suggestions_given"].append(pattern_name)
            suggestion = config["suggestion"]
            break

    runner_state["scratch_state"] = scratch_state

    if suggestion:
        return HookResult.with_context(
            f"🔄 REPETITIVE PATTERN DETECTED:\n"
            f"   {suggestion}\n"
            f"   (.claude/tmp/ scripts are faster than manual iteration)"
        )

    return HookResult.none()


# =============================================================================
# AUTO LEARN (priority 60)
# =============================================================================

MEMORY_DIR = Path(__file__).parent.parent / "memory"

LEARNABLE_PATTERNS = [
    (r"ModuleNotFoundError: No module named '([^']+)'", "Missing module: {0}"),
    (r"ImportError: cannot import name '([^']+)'", "Import error: {0}"),
    (r"AttributeError: '(\w+)' object has no attribute '(\w+)'", "{0}.{1} missing"),
    (
        r"TypeError: ([^(]+)\(\) got an unexpected keyword argument '(\w+)'",
        "{0} rejects '{1}'",
    ),
    (r"FileNotFoundError: \[Errno 2\].*'([^']+)'", "File not found: {0}"),
    (r"🛑 GAP: (.+)", "Gap detected: {0}"),
    (r"BLOCKED: (.+)", "Blocked: {0}"),
    (r"command not found: (\w+)", "Command not found: {0}"),
    (r"Permission denied", "Permission denied"),
    (r"fatal: (.+)", "Git error: {0}"),
]

IGNORE_PATTERNS = [
    r"^\s*$",
    r"warning:",
    r"^\d+ passed",
    r"ModuleNotFoundError.*No module named 'test_'",
]


def _learn_from_bash_error(tool_output: str) -> str | None:
    """Extract lesson from bash error output."""
    if not tool_output or not any(
        k in tool_output.lower() for k in ("error", "failed")
    ):
        return None
    if any(re.search(p, tool_output, re.IGNORECASE) for p in IGNORE_PATTERNS):
        return None
    for pattern, template in LEARNABLE_PATTERNS:
        if match := re.search(pattern, tool_output):
            try:
                return template.format(*match.groups())[:60]
            except (IndexError, KeyError):
                pass
    return None


def _get_quality_hint(
    tool_name: str, tool_input: dict, runner_state: dict
) -> str | None:
    """Get quality hint for tool usage."""
    hints_shown = runner_state.setdefault("hints_shown", [])
    if tool_name in ("Write", "Edit") and tool_input.get("file_path", "").endswith(
        ".py"
    ):
        if "py_ruff" not in hints_shown:
            hints_shown.append("py_ruff")
            return "💡 Run `ruff check --fix && ruff format` after editing Python"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if (
            re.search(r"\bgrep\s+-r", cmd)
            and "rg " not in cmd
            and "use_rg" not in hints_shown
        ):
            hints_shown.append("use_rg")
            return "💡 Use `rg` (ripgrep) instead of `grep -r` for 10-100x speed"
    return None


@register_hook("auto_learn", None, priority=60)
def check_auto_learn(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Capture lessons from errors and provide quality hints."""
    messages = []

    if data.get("tool_name") == "Bash":
        if lesson := _learn_from_bash_error(data.get("tool_output", "")):
            messages.append(f"🐘 Auto-learned: {lesson}...")

    if hint := _get_quality_hint(
        data.get("tool_name", ""), data.get("tool_input", {}), runner_state
    ):
        messages.append(hint)

    return (
        HookResult.with_context("\n".join(messages[:2]))
        if messages
        else HookResult.none()
    )


# =============================================================================
# VELOCITY TRACKER (priority 65)
# =============================================================================


def _check_self_check_pattern(
    tool_name: str, tool_input: dict, state: SessionState
) -> str | None:
    """Detect Edit-then-Read self-distrust pattern."""
    if tool_name != "Read" or len(state.last_5_tools) < 2:
        return None
    current_file = tool_input.get("file_path", "")
    if not current_file or state.last_5_tools[-1] not in ("Edit", "Write"):
        return None
    recent_edits = state.files_edited[-3:] if state.files_edited else []
    if current_file in recent_edits:
        name = current_file.split("/")[-1] if "/" in current_file else current_file
        return (
            f"🔄 SELF-CHECK: Edited then re-read `{name}`.\n"
            f"💡 Trust your edit or verify with a test, not re-reading."
        )
    return None


def _check_oscillation_pattern(last_5: list, state: SessionState) -> str | None:
    """Detect Read→Edit→Read→Edit oscillation."""
    pattern = "".join(
        "R" if t == "Read" else "E" for t in last_5 if t in ("Read", "Edit", "Write")
    )
    if "RERE" in pattern or "ERER" in pattern:
        record_threshold_trigger(state, "velocity_oscillation", 1)
        return (
            "🔄 OSCILLATION: Read→Edit→Read→Edit pattern.\n"
            "💡 Step back: progress or checking repeatedly?"
        )
    return None


def _check_search_loop(last_5: list, state: SessionState) -> str | None:
    """Detect low diversity search loops."""
    threshold = get_adaptive_threshold(state, "iteration_same_tool")
    if threshold == float("inf") or len(last_5) != 5:
        return None
    unique = len(set(last_5))
    if unique <= 2 and all(t in ("Read", "Glob", "Grep") for t in last_5):
        record_threshold_trigger(state, "iteration_same_tool", 5 - unique)
        return "🔄 SEARCH LOOP: 5+ searches without action.\n💡 Enough info to act?"
    return None


def _check_reread_pattern(state: SessionState) -> str | None:
    """Detect excessive re-reading of same file."""
    threshold = get_adaptive_threshold(state, "batch_sequential_reads")
    if threshold == float("inf"):
        return None
    recent = state.files_read[-10:] if len(state.files_read) >= 10 else state.files_read
    counts = Counter(recent)
    repeated = [(f, c) for f, c in counts.items() if c >= int(threshold)]
    if repeated:
        file, count = repeated[0]
        name = file.split("/")[-1] if "/" in file else file
        record_threshold_trigger(state, "batch_sequential_reads", count)
        return f"🔄 RE-READ: `{name}` read {count}x.\n💡 What are you looking for?"
    return None


@register_hook("velocity_tracker", "Read|Edit|Write|Bash|Glob|Grep", priority=65)
def check_velocity(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Detect spinning vs actual progress with adaptive thresholds."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    last_5 = state.last_5_tools

    if len(last_5) < 3:
        return HookResult.none()
    if get_adaptive_threshold(state, "velocity_oscillation") == float("inf"):
        return HookResult.none()

    if msg := _check_self_check_pattern(tool_name, tool_input, state):
        return HookResult.with_context(msg)

    if len(last_5) < 4:
        return HookResult.none()

    if msg := _check_oscillation_pattern(last_5, state):
        return HookResult.with_context(msg)
    if msg := _check_search_loop(last_5, state):
        return HookResult.with_context(msg)
    if msg := _check_reread_pattern(state):
        return HookResult.with_context(msg)

    return HookResult.none()


# =============================================================================
# INFO GAIN TRACKER (priority 70)
# =============================================================================

INFO_GAIN_STATE_FILE = MEMORY_DIR / "info_gain_state.json"
READS_BEFORE_WARN = get_magic_number("reads_before_warn", 5)
READS_BEFORE_CRYSTALLIZE = get_magic_number("reads_before_crystallize", 8)

READ_TOOLS = {"Read", "Grep", "Glob"}
PROGRESS_TOOLS = {"Edit", "Write"}
PROGRESS_BASH_PATTERNS = [
    "pytest",
    "npm test",
    "npm run",
    "cargo test",
    "cargo build",
    "python3 .claude/ops/verify",
    "python3 .claude/ops/audit",
    "git commit",
    "git add",
    "pip install",
    "npm install",
]


@register_hook("info_gain_tracker", None, priority=70)
def check_info_gain(data: dict, state: SessionState, runner_state: dict) -> HookResult:
    """Detect reads without progress."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    ig_state = runner_state.get("info_gain_state", {})
    ig_state.setdefault("reads_since_progress", 0)
    ig_state.setdefault("files_read_this_burst", [])
    ig_state.setdefault("last_stall_warn", 0)

    if tool_name in READ_TOOLS:
        ig_state["reads_since_progress"] = ig_state.get("reads_since_progress", 0) + 1
        filepath = tool_input.get("file_path", "") or tool_input.get("pattern", "")
        if filepath:
            ig_state.setdefault("files_read_this_burst", []).append(filepath)
            ig_state["files_read_this_burst"] = ig_state["files_read_this_burst"][-10:]

        reads = ig_state["reads_since_progress"]
        time_since_warn = time.time() - ig_state.get("last_stall_warn", 0)

        if reads >= READS_BEFORE_WARN and time_since_warn > 60:
            ig_state["last_stall_warn"] = time.time()
            files = ig_state.get("files_read_this_burst", [])[-5:]
            file_names = [Path(f).name if f else "?" for f in files]
            file_list = ", ".join(file_names) if file_names else "multiple files"
            runner_state["info_gain_state"] = ig_state

            severity = "⚠️" if reads < READS_BEFORE_CRYSTALLIZE else "🛑"
            hint = (
                " → crystallize to .claude/tmp/"
                if reads >= READS_BEFORE_CRYSTALLIZE
                else ""
            )
            return HookResult.with_context(
                f"{severity} INFO GAIN: {reads} reads ({file_list}) - act or need more?{hint}"
            )

    elif tool_name in PROGRESS_TOOLS:
        ig_state["reads_since_progress"] = 0
        ig_state["files_read_this_burst"] = []

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if any(p in command.lower() for p in PROGRESS_BASH_PATTERNS):
            ig_state["reads_since_progress"] = 0
            ig_state["files_read_this_burst"] = []

    runner_state["info_gain_state"] = ig_state
    return HookResult.none()


# =============================================================================
# BEADS AUTO-SYNC (priority 72)
# =============================================================================


@register_hook("beads_auto_sync", "Bash", priority=72)
def check_beads_auto_sync(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Automatically sync beads after git commit/push operations."""
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})
    command = tool_input.get("command", "")

    if not re.search(r"\bgit\s+(commit|push)\b", command, re.IGNORECASE):
        return HookResult.none()

    success = True
    if isinstance(tool_result, dict):
        stderr = tool_result.get("stderr", "")
        exit_code = tool_result.get("exit_code", 0)
        success = exit_code == 0 and "error" not in stderr.lower()

    if not success:
        return HookResult.none()

    if beads_sync_cooldown.is_active():
        return HookResult.none()

    bd_path = shutil.which("bd")
    if not bd_path:
        return HookResult.none()

    beads_dir = Path.cwd() / ".beads"
    if not beads_dir.exists():
        beads_dir = Path.home() / ".claude" / ".beads"
        if not beads_dir.exists():
            return HookResult.none()

    try:
        subprocess.Popen(
            [bd_path, "sync"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        beads_sync_cooldown.reset()
        return HookResult.with_context("🔄 Beads auto-synced in background")
    except (OSError, IOError):
        return HookResult.none()


# =============================================================================
# TOOLCHAIN BEAD CREATOR (priority 73)
# =============================================================================

TOOLCHAIN_MARKER = '"toolchain":'
TOOLCHAIN_STAGES = {"triage", "locate", "analyze", "modify", "validate", "report"}


def _extract_toolchain_from_response(response_text: str) -> list[dict] | None:
    """Extract toolchain steps from GPT-5.2 routing response."""
    import json

    if not response_text or TOOLCHAIN_MARKER not in response_text:
        return None

    # Find JSON in response (may be wrapped in markdown code block)
    text = response_text.strip()
    if "```" in text:
        # Extract from code block
        lines = text.split("\n")
        in_block = False
        json_lines = []
        for line in lines:
            if line.strip().startswith("```"):
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)

    # Try to parse JSON
    try:
        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        data = json.loads(text[start:end])
        toolchain = data.get("toolchain", [])
        if not toolchain or not isinstance(toolchain, list):
            return None
        return toolchain
    except (json.JSONDecodeError, KeyError):
        return None


def _create_beads_from_toolchain(toolchain: list[dict], session_id: str) -> list[str]:
    """Create beads from toolchain steps. Returns list of created bead IDs."""
    import json

    bd_path = shutil.which("bd")
    if not bd_path:
        return []

    bead_ids = []
    for step in toolchain[:5]:  # Max 5 steps
        stage = step.get("stage", "analyze")
        if stage not in TOOLCHAIN_STAGES:
            continue

        primary = step.get("primary", {})
        rationale = step.get("rationale", "") or primary.get(
            "capability_id", "Task step"
        )
        rationale = rationale[:50]

        title = f"[{stage}] {rationale}"

        try:
            result = subprocess.run(
                [bd_path, "create", f"--title={title}", "--type=task", "--json"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    bead_id = data.get("id") or data.get("bead_id")
                    if bead_id:
                        bead_ids.append(bead_id)
                except json.JSONDecodeError:
                    pass
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Add dependencies: each step depends on previous
    for i in range(1, len(bead_ids)):
        try:
            subprocess.run(
                [bd_path, "dep", "add", bead_ids[i], bead_ids[i - 1]],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    return bead_ids


@register_hook("toolchain_bead_creator", "mcp__pal__chat", priority=73)
def check_toolchain_bead_creator(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Create beads from GPT-5.2 toolchain recommendations.

    When mcp__pal__chat returns a routing response with a toolchain,
    parse the JSON and create beads for each stage.
    """
    tool_result = data.get("tool_result", {})
    if not isinstance(tool_result, dict):
        return HookResult.none()

    # Get response content
    content = tool_result.get("content", "") or tool_result.get("response", "")
    if not content:
        return HookResult.none()

    # Check if this looks like a routing response
    if TOOLCHAIN_MARKER not in content:
        return HookResult.none()

    # Cooldown: only create beads once per session
    tc_state = runner_state.get("toolchain_bead_state", {})
    if tc_state.get("beads_created_this_session"):
        return HookResult.none()

    # Extract and create beads
    toolchain = _extract_toolchain_from_response(content)
    if not toolchain or len(toolchain) < 2:
        return HookResult.none()

    session_id = getattr(state, "session_id", "unknown")
    bead_ids = _create_beads_from_toolchain(toolchain, session_id)

    if bead_ids:
        tc_state["beads_created_this_session"] = True
        tc_state["bead_ids"] = bead_ids
        runner_state["toolchain_bead_state"] = tc_state

        stages = [s.get("stage", "?") for s in toolchain[: len(bead_ids)]]
        return HookResult.with_context(
            f"📋 **Beads created from toolchain** ({len(bead_ids)} stages: {', '.join(stages)})\n"
            f"Run `bd list` to see tasks. First bead: `{bead_ids[0]}`"
        )

    return HookResult.none()


# =============================================================================
# PATTERN RECOGNITION CURIOSITY (priority 75)
# =============================================================================

PATTERN_PROMPTS = [
    "🔍 What patterns are emerging across these files?",
    "🧩 How do these pieces fit together architecturally?",
    "🔗 What dependencies or relationships am I seeing?",
    "💡 Is there a common abstraction hiding here?",
]


@register_hook("pattern_curiosity", "Read", priority=75)
def inject_pattern_curiosity(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Inject pattern recognition prompts after reading multiple files.

    After 5+ file reads, prompt expanded thinking about patterns,
    relationships, and emergent structure across the files read.

    This is the PostToolUse companion to PreToolUse curiosity_injection -
    it fires AFTER gathering information to prompt synthesis.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return HookResult.none()

    # Skip non-code files
    code_ext = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java"}
    ext = Path(file_path).suffix.lower()
    if ext not in code_ext:
        return HookResult.none()

    # Track reads in runner_state
    pc_state = runner_state.get("pattern_curiosity", {})
    pc_state.setdefault("code_reads", 0)
    pc_state.setdefault("last_prompt_at", 0)
    pc_state["code_reads"] = pc_state.get("code_reads", 0) + 1

    reads = pc_state["code_reads"]
    last_prompt = pc_state.get("last_prompt_at", 0)

    # Fire every 5 code reads, with cooldown
    if reads >= 5 and reads - last_prompt >= 5:
        pc_state["last_prompt_at"] = reads
        prompt = PATTERN_PROMPTS[reads % len(PATTERN_PROMPTS)]
        runner_state["pattern_curiosity"] = pc_state
        return HookResult.with_context(f"💡 CURIOSITY: {prompt}")

    runner_state["pattern_curiosity"] = pc_state
    return HookResult.none()


# =============================================================================
# FAILURE CURIOSITY (priority 76)
# =============================================================================

FAILURE_PROMPTS = [
    "🔀 What related approaches could solve this differently?",
    "🤔 What assumption led to this failure?",
    "🔍 Is there an existing solution I'm not seeing?",
    "💡 Would breaking this into smaller steps help?",
]


@register_hook("failure_curiosity", "Bash", priority=76)
def inject_failure_curiosity(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Inject alternative thinking prompts after tool failures.

    When a command fails, prompt expanded thinking about alternative
    approaches rather than just retrying the same thing.
    """
    tool_result = data.get("tool_result", {})

    # Check for failure
    exit_code = None
    if isinstance(tool_result, dict):
        exit_code = tool_result.get("exit_code")
    if exit_code is None or exit_code == 0:
        return HookResult.none()

    # Track consecutive failures
    fc_state = runner_state.get("failure_curiosity", {})
    fc_state["consecutive_failures"] = fc_state.get("consecutive_failures", 0) + 1
    failures = fc_state["consecutive_failures"]

    # Fire on first failure and every 2nd failure after
    if failures == 1 or failures % 2 == 0:
        prompt = FAILURE_PROMPTS[failures % len(FAILURE_PROMPTS)]
        runner_state["failure_curiosity"] = fc_state
        return HookResult.with_context(f"💡 CURIOSITY: {prompt}")

    runner_state["failure_curiosity"] = fc_state
    return HookResult.none()


# =============================================================================
# LOW CONFIDENCE CURIOSITY (priority 77)
# =============================================================================

UNCERTAINTY_PROMPTS = [
    "❓ What specifically am I uncertain about?",
    "🎯 What would increase my confidence here?",
    "📚 What context am I missing?",
    "🔬 What could I verify to reduce uncertainty?",
]


@register_hook("low_confidence_curiosity", None, priority=77)
def inject_low_confidence_curiosity(
    data: dict, state: SessionState, runner_state: dict
) -> HookResult:
    """Inject uncertainty exploration prompts when confidence drops below 70%.

    When confidence is low, prompt explicit thinking about what's causing
    the uncertainty rather than proceeding blindly.
    """
    # Check confidence level
    if state.confidence >= 70:
        return HookResult.none()

    # Cooldown: only fire every 5 turns when in low confidence
    lc_state = runner_state.get("low_confidence_curiosity", {})
    last_prompt_turn = lc_state.get("last_prompt_turn", 0)

    if state.turn_count - last_prompt_turn < 5:
        return HookResult.none()

    lc_state["last_prompt_turn"] = state.turn_count
    prompt = UNCERTAINTY_PROMPTS[state.turn_count % len(UNCERTAINTY_PROMPTS)]
    runner_state["low_confidence_curiosity"] = lc_state

    return HookResult.with_context(
        f"⚠️ LOW CONFIDENCE ({state.confidence}%)\n💡 CURIOSITY: {prompt}"
    )
