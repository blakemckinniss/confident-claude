---
name: ci-cd
description: |
  CI/CD pipelines, GitHub Actions, build automation, deployment workflows,
  testing automation, linting checks, artifact publishing, release management,
  environment configuration, secrets management, pipeline optimization.

  Trigger phrases: CI pipeline, GitHub Actions, build workflow, deploy,
  automated tests, CI failing, pipeline slow, add CI, release workflow,
  publish package, artifact, environment secrets, CI configuration,
  workflow file, action, job, step, matrix build, cache dependencies,
  parallel jobs, deployment automation.
---

# CI/CD

Tools for continuous integration and deployment.

## Primary Tools

### ci-optimizer Agent
```bash
Task(subagent_type="ci-optimizer", prompt="Optimize CI pipeline in <repo>")
```
Analyzes pipelines for speed, caching, parallelization opportunities.

### GitHub CLI
```bash
# Check workflow runs
gh run list
gh run view <run-id>

# Check PR checks
gh pr checks

# Trigger workflow
gh workflow run <workflow>
```

## GitHub Actions

### Basic Workflow Structure
```yaml
name: CI
on: [push, pull_request]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci
      - run: npm test
```

### Caching Dependencies
```yaml
- uses: actions/cache@v4
  with:
    path: ~/.npm
    key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
```

### Matrix Builds
```yaml
strategy:
  matrix:
    node: [18, 20, 22]
    os: [ubuntu-latest, windows-latest]
```

## Pipeline Optimization

### Speed Improvements
- Cache dependencies aggressively
- Run jobs in parallel
- Use smaller base images
- Skip unnecessary steps with conditionals

### Common Patterns
```yaml
# Only on main
if: github.ref == 'refs/heads/main'

# Skip CI
if: "!contains(github.event.head_commit.message, '[skip ci]')"

# Conditional job
needs: [build, test]
if: success()
```

## Secrets Management

```bash
# GitHub secrets
gh secret set SECRET_NAME

# Environment secrets
gh secret set SECRET_NAME --env production
```

## Deployment Patterns

### Staging → Production
```yaml
deploy-staging:
  environment: staging
deploy-production:
  needs: deploy-staging
  environment: production
```

### Release Automation
```bash
gh release create v1.0.0 --generate-notes
```
