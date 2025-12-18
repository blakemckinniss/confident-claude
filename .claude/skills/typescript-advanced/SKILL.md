---
name: typescript-advanced
description: |
  TypeScript advanced patterns, generics, type guards, utility types, mapped types,
  conditional types, infer, template literals, discriminated unions, branded types,
  type narrowing, strict mode, declaration files.

  Trigger phrases: typescript generic, type guard, utility type, mapped type,
  conditional type, infer keyword, template literal type, discriminated union,
  branded type, type narrowing, strict typescript, declaration file, .d.ts,
  typescript pattern, type inference, as const, satisfies.
---

# TypeScript Advanced

Advanced TypeScript patterns and type utilities.

## Generics

### Basic Generic
```typescript
function identity<T>(value: T): T {
  return value;
}

// Constrained generic
function getProperty<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}
```

### Generic Components
```tsx
interface ListProps<T> {
  items: T[];
  renderItem: (item: T) => React.ReactNode;
}

function List<T>({ items, renderItem }: ListProps<T>) {
  return <ul>{items.map(renderItem)}</ul>;
}
```

## Type Guards

```typescript
// Type predicate
function isUser(value: unknown): value is User {
  return typeof value === 'object' && value !== null && 'id' in value;
}

// in operator
if ('email' in person) {
  // person has email
}

// Discriminated union
type Result<T> = { ok: true; value: T } | { ok: false; error: Error };

function handle<T>(result: Result<T>) {
  if (result.ok) {
    return result.value; // T
  }
  throw result.error; // Error
}
```

## Utility Types

```typescript
// Built-in
Partial<T>          // All properties optional
Required<T>         // All properties required
Readonly<T>         // All properties readonly
Pick<T, K>          // Select properties
Omit<T, K>          // Exclude properties
Record<K, V>        // Object with K keys and V values
Extract<T, U>       // Types assignable to U
Exclude<T, U>       // Types not assignable to U
NonNullable<T>      // Exclude null/undefined
ReturnType<T>       // Function return type
Parameters<T>       // Function parameters tuple
Awaited<T>          // Unwrap Promise

// Custom
type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};
```

## Conditional Types

```typescript
type IsString<T> = T extends string ? true : false;

// With infer
type UnwrapPromise<T> = T extends Promise<infer U> ? U : T;

type ArrayElement<T> = T extends (infer E)[] ? E : never;

// Distributive
type ToArray<T> = T extends any ? T[] : never;
ToArray<string | number> // string[] | number[]
```

## Mapped Types

```typescript
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};

// Remove readonly
type Mutable<T> = {
  -readonly [K in keyof T]: T[K];
};
```

## Template Literal Types

```typescript
type EventName = `on${Capitalize<string>}`;
type CSSValue = `${number}${'px' | 'em' | 'rem'}`;

type PropEventSource<T> = {
  on<K extends string & keyof T>(
    eventName: `${K}Changed`,
    callback: (value: T[K]) => void
  ): void;
};
```

## Branded Types

```typescript
type UserId = string & { readonly __brand: unique symbol };
type OrderId = string & { readonly __brand: unique symbol };

function createUserId(id: string): UserId {
  return id as UserId;
}

// Can't accidentally pass OrderId where UserId expected
```

## as const & satisfies

```typescript
// as const - literal types, readonly
const config = {
  api: 'https://api.example.com',
  timeout: 5000
} as const;
// type: { readonly api: "https://..."; readonly timeout: 5000 }

// satisfies - type check while preserving inference
const routes = {
  home: '/',
  users: '/users'
} satisfies Record<string, string>;
// Still inferred as { home: "/"; users: "/users" }
```

## Strict Mode Tips

- Enable all strict flags
- Avoid `any` - use `unknown` instead
- Use `noUncheckedIndexedAccess`
- Prefer interfaces for objects, types for unions
