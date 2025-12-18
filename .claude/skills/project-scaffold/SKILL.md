---
name: project-scaffold
description: |
  Create new project, start new app, initialize project, scaffold, boilerplate,
  project setup, new repository, clone template, import repo, project structure,
  directory structure, folder layout, starter template, kickstart, bootstrap.

  Trigger phrases: create new project, start new application, initialize codebase,
  set up new repo, import existing repository, scaffold project, new app,
  bootstrap project, starter template, project boilerplate, create folder structure,
  set up directory, new workspace, init project, npm init, create-react-app,
  next.js new, vite create, project generator, cookiecutter, yeoman,
  clone and setup, fork and configure, template project, example project,
  getting started, quick start, new development, fresh start, clean slate,
  project layout, recommended structure, best practice structure, organize code.
---

# Project Scaffolding

Tools for creating and initializing new projects.

## Primary Tools

### setup_claude.sh - Project Creation
```bash
# Interactive menu
~/.claude/config/setup_claude.sh

# Create with structure
~/.claude/config/setup_claude.sh --project <name>

# Venv only
~/.claude/config/setup_claude.sh --venv-only
```

### setup_project.sh - Import/Clone
```bash
# Clone repo
~/.claude/config/setup_project.sh https://github.com/user/repo.git

# Empty project
~/.claude/config/setup_project.sh <name>
```

## Project Structure Created
```
~/projects/<name>/
├── .claude/commands/
├── src/
├── tests/
├── CLAUDE.md
└── package.json
```

## Locations
- `~/projects/` - General projects
- `~/ai/` - AI projects and services
