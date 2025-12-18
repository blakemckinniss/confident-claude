---
name: security-audit
description: |
  Security analysis, vulnerability scanning, OWASP top 10, injection attacks,
  XSS, CSRF, authentication flaws, authorization issues, secrets detection,
  dependency vulnerabilities, code security review, penetration testing prep.

  Trigger phrases: security audit, find vulnerabilities, check for XSS,
  SQL injection, OWASP, security review, secrets in code, hardcoded passwords,
  authentication bypass, authorization flaw, CSRF protection, input validation,
  sanitization, escape output, secure coding, CVE, dependency audit,
  npm audit, security scan, penetration test, threat model, attack surface.
---

# Security Audit

Tools for security analysis and vulnerability detection.

## Primary Tools

### deep-security Agent
```bash
Task(subagent_type="deep-security", prompt="Audit <path> for security issues")
```
Full-capability security audit: auth flows, injection vectors, OWASP top 10.

### audit.py - Quick Security Scan
```bash
~/.claude/ops/audit.py <path>
```
Fast security and quality check for a file.

## Dependency Security

```bash
# NPM
npm audit
npm audit fix

# Python
pip-audit
safety check

# Check for known CVEs
gh api /repos/{owner}/{repo}/dependabot/alerts
```

## Common Vulnerabilities

### Injection (SQL, Command, etc.)
- Never interpolate user input into queries/commands
- Use parameterized queries
- Validate and sanitize all inputs

### XSS (Cross-Site Scripting)
- Escape all output in HTML contexts
- Use Content-Security-Policy headers
- Sanitize HTML if allowing rich text

### Authentication Issues
- Check for hardcoded credentials
- Verify password hashing (bcrypt, argon2)
- Session management security

### Secrets Detection
```bash
# Find potential secrets
grep -rn "password\|secret\|api_key\|token" --include="*.py" --include="*.js"

# Check git history for secrets
git log -p | grep -i "password\|secret\|key"
```

## OWASP Top 10 Checklist

1. Broken Access Control
2. Cryptographic Failures
3. Injection
4. Insecure Design
5. Security Misconfiguration
6. Vulnerable Components
7. Authentication Failures
8. Data Integrity Failures
9. Logging Failures
10. SSRF
