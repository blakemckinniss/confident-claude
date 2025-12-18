"""
Intuition System (v4.17) - Soft reflection prompts for code/logic smells.

Unlike reducers which penalize, intuition prompts encourage self-reflection
without confidence impact. These are "spidey sense" moments that warrant
a pause without definitive evidence of wrongdoing.

Philosophy: Reducers = pain signals. Intuition = unease signals.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING
import re

if TYPE_CHECKING:
    from ._session_state_class import SessionState


@dataclass
class IntuitionSmell:
    """A soft signal that warrants reflection, not penalty."""

    name: str
    description: str
    reflection_prompts: list[str]  # Random selection from these
    cooldown_turns: int = 5  # Don't nag

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        """Check if this smell is detected. Override in subclasses."""
        if state.turn_count - last_trigger_turn < self.cooldown_turns:
            return False
        return False

    def get_prompt(self) -> str:
        """Get a reflection prompt (random from list)."""
        import random

        return random.choice(self.reflection_prompts)


class QuickFixSmell(IntuitionSmell):
    """Small edit after failure without research - might be a band-aid."""

    def __init__(self):
        super().__init__(
            name="quick_fix",
            description="Small edit after failure without research",
            reflection_prompts=[
                "Band-aid or real fix?",
                "Am I treating the symptom or the cause?",
                "Will this fix the root issue?",
            ],
            cooldown_turns=5,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        # Check: recent failure + small edit + no research
        if state.consecutive_failures == 0:
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write", "mcp__serena__replace_symbol_body"):
            return False

        # Check if there was research since the failure
        research_tools = {
            "WebSearch",
            "WebFetch",
            "mcp__crawl4ai__crawl",
            "mcp__crawl4ai__ddg_search",
            "mcp__pal__debug",
            "mcp__pal__chat",
            "mcp__pal__apilookup",
        }

        recent_tools = [
            t.get("tool_name") for t in state.last_5_tools if isinstance(t, dict)
        ]
        if any(t in research_tools for t in recent_tools):
            return False

        return True


class ComplexityCreepSmell(IntuitionSmell):
    """Adding nested conditionals or complex logic."""

    def __init__(self):
        super().__init__(
            name="complexity_creep",
            description="Adding nested conditionals or complex logic",
            reflection_prompts=[
                "Is this complexity necessary?",
                "Could this be simplified?",
                "Am I overcomplicating this?",
            ],
            cooldown_turns=8,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return False

        # Check for deeply nested structures in new content
        new_string = context.get("tool_input", {}).get("new_string", "")
        content = context.get("tool_input", {}).get("content", "")
        code = new_string or content

        if not code:
            return False

        # Count nesting indicators
        nesting_patterns = [
            r"if\s+.*:",
            r"for\s+.*:",
            r"while\s+.*:",
            r"try:",
            r"with\s+.*:",
        ]

        nesting_count = sum(len(re.findall(p, code)) for p in nesting_patterns)
        return nesting_count >= 4  # Threshold for "complex"


class MagicValuesSmell(IntuitionSmell):
    """Hardcoded numbers or strings in logic."""

    def __init__(self):
        super().__init__(
            name="magic_values",
            description="Hardcoded numbers or strings in logic",
            reflection_prompts=[
                "Should this be a named constant?",
                "Is this magic number documented?",
                "Will future-me understand what this value means?",
            ],
            cooldown_turns=6,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return False

        new_string = context.get("tool_input", {}).get("new_string", "")
        content = context.get("tool_input", {}).get("content", "")
        code = new_string or content

        if not code:
            return False

        # Look for suspicious magic numbers (not 0, 1, common values)
        magic_pattern = r"(?<![a-zA-Z_])\b(?:[2-9]|[1-9]\d{1,})\b(?!\s*[=:])"
        magic_numbers = re.findall(magic_pattern, code)

        # Filter out common acceptable values
        acceptable = {"2", "3", "4", "5", "10", "100", "1000", "60", "24", "365"}
        suspicious = [n for n in magic_numbers if n not in acceptable]

        return len(suspicious) >= 2


class UntestedAssumptionSmell(IntuitionSmell):
    """Using API without prior research this session."""

    def __init__(self):
        super().__init__(
            name="untested_assumption",
            description="Using API/library without prior research",
            reflection_prompts=[
                "Am I sure this API works this way?",
                "Did I verify this in the docs?",
                "Is this based on assumption or evidence?",
            ],
            cooldown_turns=10,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return False

        new_string = context.get("tool_input", {}).get("new_string", "")
        content = context.get("tool_input", {}).get("content", "")
        code = new_string or content

        if not code:
            return False

        # Check for imports of unresearched libraries
        import_pattern = r"(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
        imports = re.findall(import_pattern, code)

        stdlib = {
            "os",
            "sys",
            "json",
            "re",
            "time",
            "datetime",
            "pathlib",
            "typing",
            "dataclasses",
            "collections",
            "itertools",
            "functools",
            "subprocess",
            "shutil",
            "tempfile",
            "logging",
            "hashlib",
            "random",
            "math",
            "io",
            "contextlib",
            "abc",
            "enum",
        }

        external = [lib for lib in imports if lib not in stdlib]
        researched = set(state.libraries_researched)

        unresearched = [lib for lib in external if lib not in researched]
        return len(unresearched) > 0


class BuildVsBuySmell(IntuitionSmell):
    """Creating new utility/helper that might already exist."""

    def __init__(self):
        super().__init__(
            name="build_vs_buy",
            description="Creating new util/helper",
            reflection_prompts=[
                "Does this already exist somewhere?",
                "Is there a library for this?",
                "Am I reinventing the wheel?",
            ],
            cooldown_turns=10,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name != "Write":
            return False

        file_path = context.get("tool_input", {}).get("file_path", "")
        content = context.get("tool_input", {}).get("content", "")

        # Check if creating a utility file
        util_patterns = ["util", "helper", "common", "shared", "lib/", "libs/"]
        is_util_file = any(p in file_path.lower() for p in util_patterns)

        if not is_util_file:
            return False

        # Check for common utility patterns
        utility_patterns = [
            r"def\s+(?:format|parse|convert|validate|sanitize|clean|normalize)",
            r"def\s+(?:get|set|has|is|check|find|search)",
            r"def\s+(?:read|write|load|save|dump)",
        ]

        for pattern in utility_patterns:
            if re.search(pattern, content):
                return True

        return False


class ContextGapSmell(IntuitionSmell):
    """Editing file not read this session."""

    def __init__(self):
        super().__init__(
            name="context_gap",
            description="Editing file not read this session",
            reflection_prompts=[
                "Do I fully understand this code?",
                "Should I read this file first?",
                "Am I missing context here?",
            ],
            cooldown_turns=3,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "mcp__serena__replace_symbol_body"):
            return False

        file_path = context.get("tool_input", {}).get("file_path", "")
        if not file_path:
            file_path = context.get("tool_input", {}).get("relative_path", "")

        if not file_path:
            return False

        # Check if file was read this session
        files_read = state.files_read or []

        # Normalize paths for comparison
        def normalize(p):
            return p.rstrip("/").split("/")[-1] if "/" in p else p

        read_basenames = {normalize(f) for f in files_read}
        edit_basename = normalize(file_path)

        return edit_basename not in read_basenames


class ScopeDriftSmell(IntuitionSmell):
    """Touching files unrelated to original goal."""

    def __init__(self):
        super().__init__(
            name="scope_drift",
            description="Touching files unrelated to goal",
            reflection_prompts=[
                "Am I still on task?",
                "Is this related to the original goal?",
                "Should I focus on the main objective first?",
            ],
            cooldown_turns=8,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return False

        # Need original goal to check drift
        if not state.original_goal or not state.goal_keywords:
            return False

        file_path = context.get("tool_input", {}).get("file_path", "")
        if not file_path:
            return False

        # Check if file path relates to goal keywords
        file_lower = file_path.lower()
        keywords = [k.lower() for k in state.goal_keywords]

        # If any keyword in path, it's related
        if any(kw in file_lower for kw in keywords):
            return False

        # Check current feature files
        if file_path in (state.current_feature_files or []):
            return False

        return True


class EdgeCaseBlindSmell(IntuitionSmell):
    """No null/error handling in new code."""

    def __init__(self):
        super().__init__(
            name="edge_case_blind",
            description="No error handling in new code",
            reflection_prompts=[
                "What could go wrong here?",
                "Am I handling edge cases?",
                "What if the input is invalid?",
            ],
            cooldown_turns=8,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return False

        new_string = context.get("tool_input", {}).get("new_string", "")
        content = context.get("tool_input", {}).get("content", "")
        code = new_string or content

        if not code or len(code) < 100:  # Skip small edits
            return False

        # Check for function definitions without error handling
        has_function = bool(re.search(r"def\s+\w+", code))
        has_error_handling = any(
            [
                "try:" in code,
                "if not " in code,
                "if .* is None" in code,
                "raise " in code,
                "assert " in code,
            ]
        )

        return has_function and not has_error_handling


class RepetitionSmell(IntuitionSmell):
    """Similar code patterns repeated."""

    def __init__(self):
        super().__init__(
            name="repetition",
            description="Similar code patterns repeated",
            reflection_prompts=[
                "Should this be abstracted?",
                "Am I repeating myself?",
                "Could a helper function clean this up?",
            ],
            cooldown_turns=10,
        )

    def should_trigger(
        self, context: dict, state: "SessionState", last_trigger_turn: int
    ) -> bool:
        if not super().should_trigger(context, state, last_trigger_turn):
            return False

        tool_name = context.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return False

        new_string = context.get("tool_input", {}).get("new_string", "")
        content = context.get("tool_input", {}).get("content", "")
        code = new_string or content

        if not code or len(code) < 200:
            return False

        # Find repeated line patterns (3+ similar lines)
        lines = [
            ln.strip()
            for ln in code.split("\n")
            if ln.strip() and not ln.strip().startswith("#")
        ]

        # Look for structural similarity
        patterns = {}
        for line in lines:
            # Normalize: replace specific values with placeholders
            normalized = re.sub(r'"[^"]*"', '""', line)
            normalized = re.sub(r"'[^']*'", "''", normalized)
            normalized = re.sub(r"\d+", "N", normalized)

            patterns[normalized] = patterns.get(normalized, 0) + 1

        # If any pattern repeats 3+ times, it's suspicious
        return any(count >= 3 for count in patterns.values())


# Registry of all intuition smells
INTUITION_SMELLS: list[IntuitionSmell] = [
    QuickFixSmell(),
    ComplexityCreepSmell(),
    MagicValuesSmell(),
    UntestedAssumptionSmell(),
    BuildVsBuySmell(),
    ContextGapSmell(),
    ScopeDriftSmell(),
    EdgeCaseBlindSmell(),
    RepetitionSmell(),
]


def check_smells(context: dict, state: "SessionState") -> list[dict]:
    """
    Check all intuition smells and return triggered reflection prompts.

    Returns list of dicts: [{"smell": name, "prompt": reflection_prompt}, ...]
    """
    triggered = []

    # Get intuition cooldowns from nudge_history
    cooldowns = {}
    for key, value in (state.nudge_history or {}).items():
        if key.startswith("intuition_"):
            smell_name = key[len("intuition_") :]
            if isinstance(value, dict):
                cooldowns[smell_name] = value.get("last_turn", 0)
            else:
                cooldowns[smell_name] = value

    for smell in INTUITION_SMELLS:
        last_turn = cooldowns.get(smell.name, 0)

        try:
            if smell.should_trigger(context, state, last_turn):
                triggered.append(
                    {
                        "smell": smell.name,
                        "description": smell.description,
                        "prompt": smell.get_prompt(),
                    }
                )
                # Update cooldown
                state.nudge_history[f"intuition_{smell.name}"] = {
                    "last_turn": state.turn_count
                }
        except Exception:
            # Don't let smell detection break the system
            pass

    return triggered


def format_intuition_prompt(smells: list[dict]) -> str:
    """Format triggered smells into a single reflection prompt."""
    if not smells:
        return ""

    lines = ["🤔 **Reflection moment...**"]
    for s in smells:
        lines.append(f"  • {s['prompt']} ({s['smell']})")

    return "\n".join(lines)
