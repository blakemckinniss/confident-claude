#!/usr/bin/env python3
"""
compress_session.py - Preservation-focused session compression with token-efficient format

PHILOSOPHY: Preserve ALL meaningful content, remove only JSON overhead + redundancy
TARGET: 40-60% compression by eliminating structure overhead while keeping full conversations

Ported from claude-starter's compress-session-v3.py.

What gets KEPT (valuable):
- ALL user messages (full text, whitespace compressed)
- ALL assistant responses (full text, whitespace compressed)
- ALL thinking blocks (full text, whitespace compressed)
- ALL tool calls and results (summarized, not full content)
- ALL file modifications
- ALL structured sections (DOCS/DEBT/NEXT)

What gets REMOVED (worthless):
- JSON structure overhead (42% of file size)
- Duplicate system reminders (same text 50+ times)
- Excessive whitespace
- Redundant metadata fields

OUTPUT FORMAT: Token-efficient delimiters
[CTX:session_preservation]
[U1] First user message...
[R1] First assistant response...
[T1] Thinking block...
[TOOL1] Tool result...
[FILES] file1.py:modified|file2.ts:created
[DONE] Completed todo 1|Completed todo 2
[TODO] Pending todo 1|Pending todo 2
[DOCS] 20 Update ADR.md|45 Document new pattern
[DEBT] 60 Tech debt item 1
[NEXT] 85 Next step 1|70 Next step 2

Usage:
  compress_session.py <input.jsonl> [output.txt]
  compress_session.py --latest [output.txt]  # Compress most recent session
"""

import json
import sys
import re
from typing import Dict, Any, Set
from pathlib import Path
from hashlib import md5


class PreservationCompressor:
    """Preserve meaning with token-efficient delimiter format"""

    def __init__(self):
        # Full preservation (no truncation)
        self.user_messages: list[str] = []
        self.assistant_responses: list[str] = []
        self.thinking_blocks: list[str] = []
        self.tool_results: list[str] = []
        self.tool_calls: list[str] = []
        self.file_states: dict[str, str] = {}
        self.todos: dict[str, list] = {"completed": [], "pending": []}
        self.tech_stack: set[str] = set()
        self.decisions: list[dict] = []

        # Structured sections with priority/severity markers
        self.doc_updates: list[str] = []
        self.tech_debt: list[str] = []
        self.next_steps: list[str] = []

        # Deduplication tracking
        self.seen_system_reminders: Set[str] = set()
        self.seen_tool_results: Dict[str, int] = {}
        self.deduplicated_tool_results: int = 0

    def compress_whitespace(self, text: str) -> str:
        """Remove excessive whitespace while preserving readability"""
        if not text:
            return ""
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = text.replace('\t', ' ')
        text = '\n'.join(line.rstrip() for line in text.split('\n'))
        return text.strip()

    def hash_content(self, content: str) -> str:
        """Create hash of content for deduplication"""
        normalized = re.sub(r'\s+', ' ', content).strip().lower()
        return md5(normalized.encode()).hexdigest()[:16]

    def extract_structured_sections(self, text: str) -> None:
        """Extract structured sections with priority/severity markers"""
        if not text:
            return

        item_pattern = r'^\s*\d+\.\s*([🟢🟡🟠🔴⚪🔵🟣⭐])\s*(\d+)\s+(.+?)$'
        lines = text.split('\n')
        current_section = None

        for line in lines:
            if '📚' in line and 'Documentation' in line:
                current_section = 'doc_updates'
            elif '⚠️' in line and ('Technical Debt' in line or 'Risks' in line):
                current_section = 'tech_debt'
            elif 'Next Steps' in line and 'Considerations' in line:
                current_section = 'next_steps'
            elif line.strip().startswith('##') and current_section:
                current_section = None

            if current_section:
                match = re.match(item_pattern, line, re.MULTILINE)
                if match:
                    emoji, priority, description = match.groups()
                    item = f"{emoji}{priority} {description.strip()}"
                    if current_section == 'doc_updates' and item not in self.doc_updates:
                        self.doc_updates.append(item)
                    elif current_section == 'tech_debt' and item not in self.tech_debt:
                        self.tech_debt.append(item)
                    elif current_section == 'next_steps' and item not in self.next_steps:
                        self.next_steps.append(item)

    def remove_system_reminders(self, text: str) -> str:
        """Remove duplicate system-reminder blocks"""
        reminder_pattern = r'<system-reminder>.*?</system-reminder>'
        reminders = re.findall(reminder_pattern, text, re.DOTALL)

        for reminder in reminders:
            reminder_hash = self.hash_content(reminder)
            if reminder_hash in self.seen_system_reminders:
                text = text.replace(reminder, '', 1)
            else:
                self.seen_system_reminders.add(reminder_hash)

        return text

    def parse_message(self, msg: Dict[str, Any]) -> None:
        """Extract and compress information from transcript messages"""
        msg_type = msg.get("type", "")

        if msg_type == "user":
            content = msg.get("message", {}).get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_content = block.get("content", "")
                        if tool_content and len(tool_content) > 10:
                            compressed = self.compress_whitespace(tool_content)
                            compressed = self.remove_system_reminders(compressed)
                            if compressed:
                                result_hash = self.hash_content(compressed)
                                if result_hash in self.seen_tool_results:
                                    count = self.seen_tool_results[result_hash]
                                    if count < 2:
                                        self.tool_results.append(compressed)
                                        self.seen_tool_results[result_hash] += 1
                                    else:
                                        self.deduplicated_tool_results += 1
                                else:
                                    self.tool_results.append(compressed)
                                    self.seen_tool_results[result_hash] = 1
            elif isinstance(content, str) and content and len(content) > 10:
                compressed = self.compress_whitespace(content)
                compressed = self.remove_system_reminders(compressed)
                if compressed:
                    self.user_messages.append(compressed)

        elif msg_type == "assistant":
            content_blocks = msg.get("message", {}).get("content", [])
            for block in content_blocks:
                self._process_content_block(block)

    def _process_content_block(self, block: Dict[str, Any]) -> None:
        """Process assistant content blocks with preservation"""
        block_type = block.get("type", "")

        if block_type == "tool_use":
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            self._process_tool_call(tool_name, tool_input)

        elif block_type == "thinking":
            thinking_text = block.get("thinking", "")
            if thinking_text and len(thinking_text) > 30:
                compressed = self.compress_whitespace(thinking_text)
                self.thinking_blocks.append(compressed)

        elif block_type == "text":
            text_content = block.get("text", "")
            if text_content and len(text_content) > 10:
                self.extract_structured_sections(text_content)
                compressed = self.compress_whitespace(text_content)
                compressed = self.remove_system_reminders(compressed)
                if compressed:
                    self.assistant_responses.append(compressed)

    def _process_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> None:
        """Extract file state, todos, and tool info"""
        if tool_name not in ["Read", "Glob", "Grep"]:
            self.tool_calls.append(tool_name)

        if tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            if file_path:
                self.file_states[file_path] = "created"

        elif tool_name == "Edit":
            file_path = tool_input.get("file_path", "")
            if file_path:
                self.file_states[file_path] = "modified"

        elif tool_name == "TodoWrite":
            todos = tool_input.get("todos", [])
            for todo in todos:
                status = todo.get("status", "")
                content = todo.get("content", "")
                compressed = self.compress_whitespace(content)
                if status == "completed" and compressed not in self.todos["completed"]:
                    self.todos["completed"].append(compressed)
                elif status in ["pending", "in_progress"] and compressed not in self.todos["pending"]:
                    self.todos["pending"].append(compressed)

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            for pm in ["npm", "pnpm", "yarn", "pip", "cargo", "go", "mvn", "gradle"]:
                if pm in cmd.lower():
                    self.tech_stack.add(pm)

        elif tool_name.startswith("mcp__pal__"):
            prompt = tool_input.get("prompt", "")
            if prompt:
                compressed = self.compress_whitespace(prompt)[:200]
                self.decisions.append({
                    "type": tool_name.replace("mcp__pal__", ""),
                    "context": compressed
                })

    def compress(self, input_path: str, output_path: str) -> Dict[str, Any]:
        """Compress session with token-efficient delimiter format + full preservation"""
        messages = []
        try:
            with open(input_path, 'r') as f:
                for line in f:
                    if line.strip():
                        messages.append(json.loads(line))
        except Exception as e:
            return {"error": f"Failed to read input: {e}"}

        for msg in messages:
            self.parse_message(msg)

        output_lines = ["[CTX:session_preservation]"]

        for i, msg in enumerate(self.user_messages, 1):
            output_lines.append(f"[U{i}] {msg}")

        for i, resp in enumerate(self.assistant_responses, 1):
            output_lines.append(f"[R{i}] {resp}")

        for i, think in enumerate(self.thinking_blocks, 1):
            output_lines.append(f"[T{i}] {think}")

        for i, result in enumerate(self.tool_results, 1):
            output_lines.append(f"[TOOL{i}] {result}")

        if self.file_states:
            files_str = "|".join([f"{p}:{s}" for p, s in self.file_states.items()])
            output_lines.append(f"[FILES] {files_str}")

        if self.todos["completed"]:
            output_lines.append(f"[DONE] {'|'.join(self.todos['completed'])}")
        if self.todos["pending"]:
            output_lines.append(f"[TODO] {'|'.join(self.todos['pending'])}")

        if self.tech_stack:
            output_lines.append(f"[TECH] {','.join(sorted(self.tech_stack))}")

        for dec in self.decisions:
            output_lines.append(f"[DEC:{dec['type']}] {dec['context']}")

        if self.doc_updates:
            output_lines.append(f"[DOCS] {'|'.join(self.doc_updates)}")
        if self.tech_debt:
            output_lines.append(f"[DEBT] {'|'.join(self.tech_debt)}")
        if self.next_steps:
            output_lines.append(f"[NEXT] {'|'.join(self.next_steps)}")

        original_size = Path(input_path).stat().st_size

        try:
            with open(output_path, 'w') as f:
                f.write('\n'.join(output_lines))
        except Exception as e:
            return {"error": f"Failed to write output: {e}"}

        compressed_size = Path(output_path).stat().st_size
        ratio = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0

        return {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "compression_ratio": f"{ratio:.1f}%",
            "saved_bytes": original_size - compressed_size,
            "original_messages": len(messages),
            "user_messages": len(self.user_messages),
            "responses": len(self.assistant_responses),
            "thinking": len(self.thinking_blocks),
            "tool_results": len(self.tool_results),
            "files": len(self.file_states),
            "todos": len(self.todos["completed"]) + len(self.todos["pending"]),
            "doc_updates": len(self.doc_updates),
            "tech_debt": len(self.tech_debt),
            "next_steps": len(self.next_steps),
            "deduplicated_reminders": len(self.seen_system_reminders),
            "deduplicated_tool_results": self.deduplicated_tool_results
        }


def find_latest_session() -> str | None:
    """Find the most recent session JSONL file."""
    home = Path.home()
    projects_dir = home / ".claude" / "projects"

    if not projects_dir.exists():
        return None

    # Find all JSONL files
    jsonl_files = list(projects_dir.glob("**/*.jsonl"))

    if not jsonl_files:
        return None

    # Sort by modification time, most recent first
    jsonl_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return str(jsonl_files[0])


def main():
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  compress_session.py <input.jsonl> [output.txt]", file=sys.stderr)
        print("  compress_session.py --latest [output.txt]", file=sys.stderr)
        sys.exit(1)

    # Handle --latest flag
    if sys.argv[1] == "--latest":
        input_path = find_latest_session()
        if not input_path:
            print("Error: No session files found in ~/.claude/projects/", file=sys.stderr)
            sys.exit(1)
        print(f"Found latest session: {input_path}", file=sys.stderr)
        output_arg_idx = 2
    else:
        input_path = sys.argv[1]
        output_arg_idx = 2

    # Determine output path
    if len(sys.argv) > output_arg_idx:
        output_path = sys.argv[output_arg_idx]
    else:
        home = Path.home()
        logs_dir = home / '.claude' / 'logs'
        logs_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(logs_dir / 'last_conversation.txt')

    if not Path(input_path).exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    compressor = PreservationCompressor()
    result = compressor.compress(input_path, output_path)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"Preservation compression: {result['original_messages']} messages")
    print(f"  Original: {result['original_size']:,} bytes")
    print(f"  Compressed: {result['compressed_size']:,} bytes")
    print(f"  Saved: {result['compression_ratio']} ({result['saved_bytes']:,} bytes)")
    print(f"  Preserved: {result['user_messages']}U {result['responses']}R {result['thinking']}T {result['tool_results']}TOOL")
    print(f"  Tracked: {result['files']} files, {result['todos']} tasks")

    dedup_items = []
    if result['deduplicated_reminders'] > 0:
        dedup_items.append(f"{result['deduplicated_reminders']} reminders")
    if result['deduplicated_tool_results'] > 0:
        dedup_items.append(f"{result['deduplicated_tool_results']} tool results")
    if dedup_items:
        print(f"  Deduplicated: {', '.join(dedup_items)}")

    sections = []
    if result['doc_updates'] > 0:
        sections.append(f"{result['doc_updates']} docs")
    if result['tech_debt'] > 0:
        sections.append(f"{result['tech_debt']} debt")
    if result['next_steps'] > 0:
        sections.append(f"{result['next_steps']} next")
    if sections:
        print(f"  Sections: {', '.join(sections)}")

    print(f"\n  Output: {output_path}")


if __name__ == "__main__":
    main()
