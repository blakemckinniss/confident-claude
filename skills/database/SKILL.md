---
name: database
description: |
  Database operations, SQL queries, schema design, migrations, ORM,
  Prisma, SQLAlchemy, query optimization, indexes, transactions,
  PostgreSQL, MySQL, SQLite, MongoDB, Redis, data modeling.

  Trigger phrases: database, SQL query, schema design, migration,
  Prisma, SQLAlchemy, ORM, query optimization, add index, transaction,
  PostgreSQL, MySQL, SQLite, MongoDB, Redis, foreign key, join,
  select, insert, update, delete, create table, alter table.
---

# Database

Tools for database operations and design.

## Primary Tools

### schema-validator Agent
```bash
Task(subagent_type="schema-validator", prompt="Validate schema in <path>")
```
Validates schemas, finds migration issues, detects type mismatches.

### PAL Debug - Query Issues
```bash
mcp__pal__debug  # Complex query debugging
```

## SQL Basics

```sql
-- Select with joins
SELECT u.name, o.total
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.status = 'completed';

-- Insert
INSERT INTO users (name, email) VALUES ('John', 'john@example.com');

-- Update
UPDATE users SET name = 'Jane' WHERE id = 1;

-- Delete
DELETE FROM users WHERE id = 1;
```

## Query Optimization

### Explain Plans
```sql
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'test@example.com';
```

### Indexes
```sql
-- Create index
CREATE INDEX idx_users_email ON users(email);

-- Composite index
CREATE INDEX idx_orders_user_status ON orders(user_id, status);
```

### N+1 Prevention
```sql
-- Instead of N queries, use JOIN or IN
SELECT * FROM posts WHERE user_id IN (1, 2, 3);
```

## Prisma (Node.js)

```typescript
// Schema
model User {
  id    Int     @id @default(autoincrement())
  email String  @unique
  posts Post[]
}

// Query
const users = await prisma.user.findMany({
  include: { posts: true }
});
```

### Migrations
```bash
npx prisma migrate dev --name add_users
npx prisma migrate deploy
```

## SQLAlchemy (Python)

```python
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)

# Query
users = session.query(User).filter(User.email.like('%@example.com')).all()
```

## Transactions

```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;
-- or ROLLBACK on error
```

## Common Patterns

### Soft Deletes
```sql
ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP;
-- Query only active
SELECT * FROM users WHERE deleted_at IS NULL;
```

### Audit Columns
```sql
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
```

### Connection Pooling
```python
engine = create_engine(url, pool_size=5, max_overflow=10)
```
