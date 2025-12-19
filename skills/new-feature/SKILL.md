---
name: new-feature
description: "Scaffold a new feature with branch, bead, and structure. Use when starting new work."
---

# /new-feature - Feature Scaffolding

**Purpose:** Start new feature work with proper tracking and structure.

## Usage

```
/new-feature <feature-name> [--description "what it does"]
```

## Execution Sequence

### Step 1: Create Tracking
```bash
bd create "<feature-name>" --type=feature --description="<description>"
bd update <id> --status=in_progress
```

### Step 2: Create Branch
```bash
git checkout -b feature/<feature-name>
```

### Step 3: Scaffold Structure (if applicable)

For React component:
```bash
mkdir -p src/components/<FeatureName>
touch src/components/<FeatureName>/index.tsx
touch src/components/<FeatureName>/<FeatureName>.tsx
touch src/components/<FeatureName>/<FeatureName>.test.tsx
```

For API endpoint:
```bash
touch src/api/<feature-name>.ts
touch src/api/<feature-name>.test.ts
```

For Python module:
```bash
mkdir -p src/<feature_name>
touch src/<feature_name>/__init__.py
touch src/<feature_name>/<feature_name>.py
touch tests/test_<feature_name>.py
```

### Step 4: Create Minimal Skeleton

Write stub implementations that:
- Have correct exports/signatures
- Return placeholder values
- Have TODO comments for implementation

### Step 5: Verify Setup
```bash
# Ensure imports work
npm run build 2>&1 | head -20  # or equivalent

# Run empty test
npm test -- <test_file>
```

## Output

After scaffolding, report:
```
Feature: <name>
Branch: feature/<name>
Bead: <id>
Files created:
  - <file1>
  - <file2>
Next: Implement <first function/component>
```

## Behavior Rules

- Always create bead FIRST (tracking)
- Always create branch (isolation)
- Scaffold matches project conventions (check existing structure)
- Skeleton code must compile/import successfully
- Don't implement yet - just scaffold
