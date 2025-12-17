#!/usr/bin/env python3
"""
Capability Inventory Generator

Generates capabilities_index.json from:
1. ~/.claude/ops/*.py - Parse module docstrings
2. ~/.claude/commands/*.md - Parse YAML frontmatter
3. ~/.claude/capabilities/registry.yaml - Agents + MCPs

Usage:
    capability_inventory.py [--refresh] [--validate] [--output PATH]

Options:
    --refresh    Force regeneration even if sources unchanged
    --validate   Validate output against schema (no write)
    --output     Output path (default: ~/.claude/capabilities/capabilities_index.json)
"""

import ast
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

try:
    import yaml
except ImportError:
    yaml = None  # Will error if registry.yaml needed


# =============================================================================
# CONFIGURATION
# =============================================================================

CLAUDE_DIR = Path.home() / ".claude"
OPS_DIR = CLAUDE_DIR / "ops"
COMMANDS_DIR = CLAUDE_DIR / "commands"
CAPABILITIES_DIR = CLAUDE_DIR / "capabilities"
REGISTRY_PATH = CAPABILITIES_DIR / "registry.yaml"
TAG_VOCAB_PATH = CAPABILITIES_DIR / "tag_vocab.json"
OUTPUT_PATH = CAPABILITIES_DIR / "capabilities_index.json"

# Stage inference keywords
STAGE_KEYWORDS = {
    "triage": ["triage", "classify", "categorize", "assess"],
    "locate": ["find", "search", "locate", "grep", "discover", "lookup"],
    "analyze": ["analyze", "debug", "trace", "audit", "review", "check", "diagnose"],
    "modify": ["fix", "apply", "patch", "format", "refactor", "edit", "write", "create"],
    "validate": ["test", "verify", "lint", "check", "validate", "audit"],
    "report": ["report", "summarize", "document", "explain"],
}

# Risk inference patterns
WRITE_PATTERNS = [
    r"\.write_text\(",
    r"open\([^)]*['\"]w['\"]",
    r"shutil\.(copy|move|rmtree)",
    r"os\.(remove|unlink|rename)",
    r"Path\([^)]*\)\.write",
    r"git\s+(apply|commit|push)",
    r"sed\s+-i",
]

NETWORK_PATTERNS = [
    r"import\s+requests",
    r"import\s+httpx",
    r"import\s+aiohttp",
    r"from\s+urllib",
    r"curl\s+",
    r"wget\s+",
]

DESTRUCTIVE_PATTERNS = [
    r"rm\s+-rf",
    r"shutil\.rmtree",
    r"--force",
    r"--hard",
]


# =============================================================================
# HELPERS
# =============================================================================

def load_tag_vocab() -> set[str]:
    """Load valid tags from vocabulary file."""
    if TAG_VOCAB_PATH.exists():
        with open(TAG_VOCAB_PATH) as f:
            return set(json.load(f))
    return set()


def compute_fingerprint(path: Path) -> str:
    """Compute fingerprint for a file or directory."""
    if path.is_file():
        stat = path.stat()
        return f"file:{stat.st_size}:{stat.st_mtime_ns}"
    elif path.is_dir():
        entries = []
        for p in sorted(path.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                stat = p.stat()
                entries.append(f"{p.relative_to(path)}:{stat.st_size}:{stat.st_mtime_ns}")
        return hashlib.sha256("|".join(entries).encode()).hexdigest()[:16]
    return "missing"


def normalize_id(name: str, prefix: str) -> str:
    """Normalize a name to a valid ID."""
    stem = Path(name).stem if "." in name else name
    normalized = re.sub(r"[^a-z0-9_]", "_", stem.lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return f"{prefix}__{normalized}"


def infer_stages(text: str, filename: str) -> list[str]:
    """Infer stages from text content and filename."""
    combined = f"{text} {filename}".lower()
    stages = []
    for stage, keywords in STAGE_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            stages.append(stage)
    return stages or ["analyze"]  # Default


def infer_tags(text: str, filename: str, valid_tags: set[str]) -> list[str]:
    """Infer tags from text content."""
    combined = f"{text} {filename}".lower()
    found = []
    
    # Map keywords to tags
    tag_keywords = {
        "debugging": ["debug", "error", "exception", "traceback"],
        "tests": ["test", "pytest", "jest", "unittest"],
        "lint": ["lint", "ruff", "eslint", "flake8"],
        "static_analysis": ["analyze", "audit", "scan"],
        "refactor": ["refactor", "rename", "extract"],
        "validation": ["verify", "validate", "check"],
        "web_research": ["web", "search", "fetch", "crawl"],
        "code_reading": ["read", "parse", "inspect"],
        "workflow": ["workflow", "pipeline", "orchestrate"],
        "security_review": ["security", "vulnerability", "owasp"],
        "performance": ["performance", "optimize", "profile"],
        "formatting": ["format", "prettier", "black"],
        "docs_lookup": ["docs", "documentation", "api"],
    }
    
    for tag, keywords in tag_keywords.items():
        if tag in valid_tags and any(kw in combined for kw in keywords):
            found.append(tag)
    
    return found[:8]  # Max 8 tags


def infer_risk(content: str) -> dict[str, bool]:
    """Infer risk profile from code content."""
    risk = {
        "read_only": True,
        "writes_repo": False,
        "network": False,
        "executes_code": True,  # Ops scripts execute
        "destructive_possible": False,
    }
    
    for pattern in WRITE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            risk["writes_repo"] = True
            risk["read_only"] = False
            break
    
    for pattern in NETWORK_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            risk["network"] = True
            break
    
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            risk["destructive_possible"] = True
            break
    
    return risk


def extract_python_docstring(content: str) -> str:
    """Extract module docstring from Python file."""
    try:
        tree = ast.parse(content)
        return ast.get_docstring(tree) or ""
    except SyntaxError:
        # Fallback: regex for triple-quoted string at top
        match = re.search(r'^["\']["\']["\'](.+?)["\']["\']["\']', content, re.DOTALL)
        return match.group(1).strip() if match else ""


def extract_yaml_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown file."""
    if not content.startswith("---"):
        return {}, content
    
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    
    try:
        if yaml:
            fm = yaml.safe_load(parts[1])
        else:
            # Minimal parsing without yaml
            fm = {}
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    fm[key.strip()] = val.strip()
        return fm or {}, parts[2]
    except Exception:
        return {}, content


def extract_summary(docstring: str, max_len: int = 140) -> str:
    """Extract summary from docstring."""
    if not docstring:
        return ""
    
    # Take first non-empty line
    for line in docstring.split("\n"):
        line = line.strip()
        if line and not line.startswith("Usage:"):
            # Remove "Title: " prefix if present
            if ":" in line and len(line.split(":")[0]) < 30:
                line = line.split(":", 1)[1].strip()
            if len(line) > max_len:
                line = line[:max_len-3] + "..."
            return line
    return ""


# =============================================================================
# PARSERS
# =============================================================================

def parse_ops_scripts(valid_tags: set[str]) -> list[dict[str, Any]]:
    """Parse ops scripts into capability cards."""
    cards = []
    
    if not OPS_DIR.exists():
        return cards
    
    for path in sorted(OPS_DIR.glob("*.py")):
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        
        try:
            content = path.read_text()
        except Exception:
            continue
        
        docstring = extract_python_docstring(content)
        summary = extract_summary(docstring)
        
        if not summary:
            summary = f"Run {path.name} script."
        
        card = {
            "id": normalize_id(path.name, "ops"),
            "type": "ops_script",
            "name": path.name,
            "summary": summary,
            "stages": infer_stages(docstring, path.name),
            "interaction_mode": "primitive",
            "tags": infer_tags(docstring, path.name, valid_tags),
            "cost": {"price_tier": "free", "latency_tier": "low"},
            "risk": infer_risk(content),
            "scope": "local_machine",
            "source": {
                "source_type": "ops",
                "path": str(path),
            },
        }
        
        cards.append(card)
    
    return cards


def parse_slash_commands(valid_tags: set[str]) -> list[dict[str, Any]]:
    """Parse slash commands into capability cards."""
    cards = []
    
    if not COMMANDS_DIR.exists():
        return cards
    
    for path in sorted(COMMANDS_DIR.glob("*.md")):
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        
        try:
            content = path.read_text()
        except Exception:
            continue
        
        fm, body = extract_yaml_frontmatter(content)
        
        # Get description from frontmatter
        description = fm.get("description", "")
        # Remove emoji prefix
        description = re.sub(r"^[^\w\s]+\s*", "", description).strip()
        
        summary = description or extract_summary(body)
        if not summary:
            summary = f"Run /{path.stem} command."
        
        # Infer allowed tools risk
        allowed_tools = fm.get("allowed-tools", "")
        risk = {
            "read_only": True,
            "writes_repo": False,
            "network": False,
            "executes_code": False,
            "destructive_possible": False,
        }
        
        if "Write" in allowed_tools or "Edit" in allowed_tools:
            risk["writes_repo"] = True
            risk["read_only"] = False
        if "Bash" in allowed_tools:
            risk["executes_code"] = True
        if "WebFetch" in allowed_tools or "WebSearch" in allowed_tools:
            risk["network"] = True
        
        card = {
            "id": f"slash__/{path.stem}",
            "type": "slash_command",
            "name": f"/{path.stem}",
            "summary": summary[:140],
            "stages": infer_stages(description + " " + body[:500], path.name),
            "interaction_mode": "orchestrator",
            "tags": infer_tags(description + " " + body[:500], path.name, valid_tags),
            "cost": {"price_tier": "low", "latency_tier": "medium"},
            "risk": risk,
            "scope": "claude_runtime",
            "source": {
                "source_type": "commands",
                "path": str(path),
            },
        }
        
        cards.append(card)
    
    return cards


def parse_registry() -> tuple[list[dict], list[dict]]:
    """Parse registry.yaml for agents and MCP tools."""
    agents = []
    mcp_tools = []
    
    if not REGISTRY_PATH.exists():
        return agents, mcp_tools
    
    if not yaml:
        print("Warning: PyYAML not installed, skipping registry.yaml", file=sys.stderr)
        return agents, mcp_tools
    
    try:
        with open(REGISTRY_PATH) as f:
            registry = yaml.safe_load(f)
    except Exception as e:
        print(f"Warning: Failed to parse registry.yaml: {e}", file=sys.stderr)
        return agents, mcp_tools
    
    defaults = registry.get("defaults", {})
    
    def apply_defaults(card: dict) -> dict:
        """Apply default values to card."""
        if "cost" not in card:
            card["cost"] = defaults.get("cost", {"price_tier": "low", "latency_tier": "medium"})
        if "risk" not in card:
            card["risk"] = defaults.get("risk", {
                "read_only": True,
                "writes_repo": False,
                "network": False,
                "executes_code": False,
                "destructive_possible": False,
            })
        card["source"] = {"source_type": "registry", "ref": "registry.yaml"}
        return card
    
    for agent in registry.get("agents", []):
        agent["type"] = "agent"
        agents.append(apply_defaults(agent))
    
    for tool in registry.get("mcp_tools", []):
        tool["type"] = "mcp_tool"
        mcp_tools.append(apply_defaults(tool))
    
    return agents, mcp_tools


# =============================================================================
# MAIN
# =============================================================================

def generate_inventory(refresh: bool = False) -> dict[str, Any]:
    """Generate the complete capabilities index."""
    valid_tags = load_tag_vocab()
    
    # Compute source fingerprints
    sources = [
        {"source_type": "ops_dir", "path": str(OPS_DIR), "fingerprint": compute_fingerprint(OPS_DIR)},
        {"source_type": "commands_dir", "path": str(COMMANDS_DIR), "fingerprint": compute_fingerprint(COMMANDS_DIR)},
        {"source_type": "registry", "path": str(REGISTRY_PATH), "fingerprint": compute_fingerprint(REGISTRY_PATH)},
    ]
    
    # Check if regeneration needed
    if not refresh and OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH) as f:
                existing = json.load(f)
            if existing.get("sources") == sources:
                print("Sources unchanged, skipping regeneration")
                return existing
        except Exception:
            pass
    
    # Parse all sources
    ops_cards = parse_ops_scripts(valid_tags)
    cmd_cards = parse_slash_commands(valid_tags)
    agents, mcp_tools = parse_registry()
    
    # Combine all capabilities
    capabilities = agents + mcp_tools + ops_cards + cmd_cards
    
    # Sort by ID for stable output
    capabilities.sort(key=lambda c: c["id"])
    
    # Build index
    index = {
        "schema_version": "1.0",
        "inventory_version": "",  # Will be computed
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "capabilities": capabilities,
    }
    
    # Compute inventory version (hash of normalized content)
    normalized = json.dumps(capabilities, sort_keys=True)
    index["inventory_version"] = f"sha256:{hashlib.sha256(normalized.encode()).hexdigest()[:16]}"
    
    return index


def validate_index(index: dict[str, Any], valid_tags: set[str]) -> list[str]:
    """Validate index against schema rules."""
    errors = []
    seen_ids = set()
    
    for cap in index.get("capabilities", []):
        cap_id = cap.get("id", "unknown")
        
        # Unique ID
        if cap_id in seen_ids:
            errors.append(f"Duplicate ID: {cap_id}")
        seen_ids.add(cap_id)
        
        # Required fields
        for field in ["id", "type", "name", "summary", "stages", "interaction_mode", "tags", "risk", "scope"]:
            if field not in cap:
                errors.append(f"{cap_id}: Missing required field '{field}'")
        
        # Tags validation
        if valid_tags:
            invalid_tags = set(cap.get("tags", [])) - valid_tags
            if invalid_tags:
                errors.append(f"{cap_id}: Invalid tags: {invalid_tags}")
        
        # Max 8 tags
        if len(cap.get("tags", [])) > 8:
            errors.append(f"{cap_id}: Too many tags (max 8)")
        
        # Stages non-empty
        if not cap.get("stages"):
            errors.append(f"{cap_id}: Stages cannot be empty")
        
        # Risk consistency
        risk = cap.get("risk", {})
        if risk.get("writes_repo") and risk.get("read_only"):
            errors.append(f"{cap_id}: Cannot be both writes_repo=true and read_only=true")
    
    return errors


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate capability inventory")
    parser.add_argument("--refresh", action="store_true", help="Force regeneration")
    parser.add_argument("--validate", action="store_true", help="Validate only, no write")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output path")
    args = parser.parse_args()
    
    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    # Generate index
    index = generate_inventory(refresh=args.refresh)
    
    # Validate
    valid_tags = load_tag_vocab()
    errors = validate_index(index, valid_tags)
    
    if errors:
        print("Validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        if args.validate:
            sys.exit(1)
    
    if args.validate:
        print(f"Validation passed: {len(index['capabilities'])} capabilities")
        return
    
    # Write output
    with open(args.output, "w") as f:
        json.dump(index, f, indent=2)
    
    print(f"Generated {args.output}")
    print(f"  - {sum(1 for c in index['capabilities'] if c['type'] == 'agent')} agents")
    print(f"  - {sum(1 for c in index['capabilities'] if c['type'] == 'mcp_tool')} MCP tools")
    print(f"  - {sum(1 for c in index['capabilities'] if c['type'] == 'ops_script')} ops scripts")
    print(f"  - {sum(1 for c in index['capabilities'] if c['type'] == 'slash_command')} slash commands")
    print(f"  - Version: {index['inventory_version']}")


if __name__ == "__main__":
    main()
