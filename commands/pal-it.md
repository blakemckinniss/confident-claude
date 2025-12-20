---
description: 🔮 PAL Consult - Get external LLM guidance on next approach
argument-hint: [context or question]
allowed-tools: Bash, Read, Glob, Grep, mcp__pal__chat, mcp__pal__planner, mcp__pal__thinkdeep
---

Consult PAL MCP for strategic guidance on what approach to take next.

## Execution

1. **Gather Context**
   - Review recent conversation for: current task, blockers, decisions pending
   - Note any beads in progress (`bd list --status=in_progress`)
   - Identify the core question or decision point

2. **Formulate Consultation**
   - If `$ARGUMENTS` provided, use as the primary question/context
   - Otherwise, synthesize from conversation: "Given [situation], what's the best approach for [goal]?"

3. **Consult PAL**
   Use `mcp__pal__chat` with:
   - `prompt`: The synthesized question with relevant context
   - `model`: "auto" (let PAL select appropriate model)
   - `working_directory_absolute_path`: Current working directory
   - `thinking_mode`: "medium" for balanced depth

4. **Present Recommendation**
   Format the PAL response as actionable guidance:
   - **Recommended Approach:** [primary recommendation]
   - **Rationale:** [why this approach]
   - **Alternatives Considered:** [if PAL mentioned any]
   - **Next Action:** [concrete first step]

## Notes
- Use `mcp__pal__planner` for complex multi-step planning needs
- Use `mcp__pal__thinkdeep` for deep investigation/debugging
- Reuse `continuation_id` from previous PAL calls when continuing a thread
