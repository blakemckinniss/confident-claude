# .claude Framework

**Full constitution:** See `~/CLAUDE.md`

This file exists as a visibility reminder when working within `.claude/`.

---

## .claude-specific Notes

When modifying framework internals:

1. **Confidence gates apply** - `ops/`, `hooks/`, `lib/` require audit + void before commit
2. **Self-surgery = +10** - Fixing reducers/hooks/confidence earns `framework_self_heal`
3. **FP → Fix DNA** - False positives are bugs, not dismissals
4. **Update ~/CLAUDE.md** - If framework behavior changes, constitution should reflect it

## Quick Refs

| Area | Key Files |
|------|-----------|
| Confidence | `lib/confidence.py`, `rules/confidence.md` |
| Hooks | `hooks/*_runner.py`, `rules/hooks.md` |
| Mastermind | `lib/mastermind/`, `config/mastermind.json` |
| Capabilities | `capabilities/registry.yaml` |
| Tools | `ops/*.py`, `rules/tools.md` |
