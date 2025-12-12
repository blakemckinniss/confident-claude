Search past session transcripts for relevant context.

**Query:** $ARGUMENTS

**Protocol:**

1. Run the session RAG search:
   ```bash
   /home/jinx/.claude/.venv/bin/python /home/jinx/.claude/lib/session_rag.py "$ARGUMENTS"
   ```

2. If results found, summarize:
   - Show top 3-5 relevant excerpts
   - Note the session date and context
   - Highlight key insights applicable to current work

3. If no arguments provided, show stats:
   ```bash
   /home/jinx/.claude/.venv/bin/python /home/jinx/.claude/lib/session_rag.py --stats
   ```

**Examples:**
- `/recall hook performance` - Find past discussions about hook performance
- `/recall beads workflow` - Find beads-related conversations
- `/recall` - Show index statistics
