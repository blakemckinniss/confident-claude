---
name: verification
description: |
  Verify claims, check if something exists, validate state, confirm assumptions,
  reality check, fact verification, file exists, port open, grep text, test assertions,
  prove it works, sanity check, double check, confirm changes, validate output.

  Trigger phrases: verify this works, check if X exists, confirm the change,
  validate the state, is the port open, did the file get created, reality check,
  prove it works, does this file contain, is the server running, test if,
  assert that, make sure, ensure that, confirm that, validate that,
  check the output, verify the result, did it work, is it running,
  file exists, directory exists, path exists, port listening, service running,
  process running, command succeeds, exit code, return value, output contains,
  grep for, search for text, find in file, pattern match, regex match,
  structural search, find class, find function, find import, AST search,
  code structure, where is defined, who calls, callers, references, usages,
  double check my work, did I miss anything, sanity check the changes.
---

# Verification

Tools for validating state and confirming reality.

## Primary Tools

### verify.py - State Assertions
```bash
verify.py file_exists "<path>"
verify.py grep_text "<path>" "<text>"
verify.py port_open <port>
verify.py command_success "<command>"
```

### xray.py - Structural Code Search
```bash
xray.py --type class --name "Name" <path>
xray.py --type function --name "func" <path>
xray.py --type import <path>
```

## Slash Commands
- `/verify <check> <target>` - State check
- `/xray <path>` - Code structure
- `/cwms <condition>` - Enforce invariant

## Before Claiming Done
```bash
verify file_exists "<file>"
verify grep_text "<file>" "<expected>"
verify command_success "npm run build"
verify port_open 3000
```
