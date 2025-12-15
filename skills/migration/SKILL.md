---
name: migration
description: |
  Data migrations, schema changes, database migrations, codebase migrations,
  framework upgrades, API versioning, breaking changes, rollback plans,
  zero-downtime migrations, data transformation, ETL, version upgrades.

  Trigger phrases: migrate database, schema change, upgrade framework,
  breaking change, rollback plan, data migration, ETL, transform data,
  upgrade version, migrate to v2, deprecate API, backward compatible,
  zero downtime, blue-green deployment, feature flags for migration,
  migrate from X to Y, convert data, schema evolution.
---

# Migration

Tools for safe migrations and upgrades.

## Primary Tools

### migration-planner Agent
```bash
Task(subagent_type="migration-planner", prompt="Plan migration for <description>")
```
Creates rollback plans and validates data integrity.

### upgrade-scout Agent
```bash
Task(subagent_type="upgrade-scout", prompt="Plan upgrade from <old> to <new>")
```
Reads changelogs, finds breaking changes, creates migration plan.

## Database Migrations

### Schema Changes
```bash
# Prisma
npx prisma migrate dev --name <name>
npx prisma migrate deploy

# Django
python manage.py makemigrations
python manage.py migrate

# Alembic (SQLAlchemy)
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### Safe Migration Pattern
1. Add new column (nullable)
2. Deploy code that writes to both
3. Backfill existing data
4. Deploy code that reads from new
5. Remove old column

## Framework Upgrades

### Pre-Upgrade Checklist
- [ ] Read CHANGELOG/migration guide
- [ ] Check deprecation warnings
- [ ] Review breaking changes
- [ ] Test in staging first
- [ ] Prepare rollback plan

### Dependency Updates
```bash
# Check outdated
npm outdated
pip list --outdated

# Update with care
npm update --save
pip install --upgrade <package>
```

## Rollback Strategies

### Database
```bash
# Keep rollback migration ready
alembic downgrade -1

# Point-in-time recovery
pg_restore --target-time="2024-01-01 12:00:00"
```

### Code
```bash
# Git rollback
git revert <commit>

# Feature flags
if (featureFlags.newSystem) { ... } else { ... }
```

## Zero-Downtime Patterns

- Blue-green deployments
- Canary releases
- Feature flags
- Expand-contract pattern
- Strangler fig pattern
