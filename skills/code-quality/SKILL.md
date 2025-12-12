---
name: code-quality
description: |
  Code review, security audit, completeness check, gap detection, style drift,
  anti-patterns, vulnerabilities, missing functionality, CRUD asymmetry, error handling gaps,
  code smell, technical debt, refactoring candidates, dead code, unused imports.

  Trigger phrases: review this code, check for bugs, security issues, what's missing,
  find gaps, completeness, anti-patterns, code smell, style drift, before I commit,
  audit this, quality check, is this secure, vulnerability scan, SQL injection,
  XSS, hardcoded secrets, unsafe code, best practices, lint, static analysis,
  code coverage, test coverage, untested code, risky code, complex code,
  cyclomatic complexity, maintainability, readability, clean code, refactor,
  technical debt, TODO comments, FIXME, unfinished code, stub, placeholder,
  error handling, edge cases, null checks, validation, input sanitization,
  OWASP, penetration test, pentest, security review, code audit, peer review,
  pull request review, PR review, merge request, before deploy, production ready.
---

# Code Quality

Tools for code review, security, and completeness verification.

## Primary Tools

### audit.py - Security & Anti-Pattern Detection
```bash
audit.py <file_or_dir>
```
Detects: SQL injection, XSS, hardcoded secrets, command injection, unsafe deserialization.

### void.py / gaps.py - Completeness Check
```bash
void.py <file_or_dir>
gaps.py <file_or_dir>
```
Detects: TODO/FIXME, missing CRUD, error handling gaps, unimplemented methods.

### drift.py - Style Consistency
```bash
drift.py <file>
```

### upkeep.py - Pre-Commit Health
```bash
upkeep.py
```

## Slash Commands
- `/audit <file>` - Security audit
- `/void <file>` - Completeness check
- `/gaps <file>` - Find missing functionality
- `/drift` - Style consistency
- `/cr` - CodeRabbit AI review

## Before Commit Workflow
```bash
void <files>      # Check completeness
audit <files>     # Security scan
upkeep            # Health check
git commit
```
