---
paths: "**/*.tsx, **/*.jsx"
---

# React Development Rules (React 19+)

Modern React patterns for 2025. Updated for React 19.x with compiler, new hooks, and Server Components.

## React Compiler (Auto-Memoization)

React 19's compiler handles memoization automatically. **Stop using these for performance:**

```tsx
// DEPRECATED for performance optimization:
useMemo()      // Compiler handles this
useCallback()  // Compiler handles this
React.memo()   // Compiler handles this
```

**When to still use them:**
- `useMemo` for expensive computations with specific deps you want to control
- `useCallback` when passing to non-React APIs (event listeners, third-party libs)
- `React.memo` when you need explicit control over re-render boundaries

## New Hooks (React 19)

### useActionState (replaces useFormState)
```tsx
const [state, submitAction, isPending] = useActionState(
  async (prevState, formData) => {
    const result = await saveData(formData);
    return result;
  },
  initialState
);
```

### useOptimistic
```tsx
const [optimisticItems, addOptimistic] = useOptimistic(
  items,
  (state, newItem) => [...state, { ...newItem, pending: true }]
);
```

### useFormStatus
```tsx
function SubmitButton() {
  const { pending } = useFormStatus();
  return <button disabled={pending}>{pending ? 'Saving...' : 'Save'}</button>;
}
```

### use() API
```tsx
// Read promises directly in render (with Suspense)
function UserProfile({ userPromise }) {
  const user = use(userPromise);  // Suspends until resolved
  return <div>{user.name}</div>;
}
```

### useDeferredValue
```tsx
// Defer non-urgent updates
const deferredQuery = useDeferredValue(searchQuery);
// UI stays responsive while deferred value catches up
```

## Component Patterns

### Functional Components Only
```tsx
// GOOD
function UserCard({ user }: { user: User }) {
  return <div>{user.name}</div>;
}

// BAD - no class components
class UserCard extends React.Component { ... }
```

### Named Exports Over Default
```tsx
// GOOD
export function UserCard() { ... }
export function UserList() { ... }

// AVOID
export default function UserCard() { ... }
```

### Colocate Related Code
```
components/
  UserCard/
    UserCard.tsx       # Component
    UserCard.test.tsx  # Tests
    useUserCard.ts     # Component-specific hook
    types.ts           # Component types
```

## Server Components (React 19)

```tsx
// Server Component (default in App Router)
// - No 'use client' directive
// - Can use async/await directly
// - No hooks, no browser APIs
async function UserList() {
  const users = await db.users.findMany();
  return <ul>{users.map(u => <li key={u.id}>{u.name}</li>)}</ul>;
}

// Client Component
'use client';
function InteractiveButton() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}
```

**Rule:** Start with Server Components, add 'use client' only when needed (interactivity, hooks, browser APIs).

## State Management

### Local State First
```tsx
// Prefer useState for component-local state
const [isOpen, setIsOpen] = useState(false);

// Lift state only when siblings need it
// Context for truly global state (theme, auth, i18n)
```

### Avoid Prop Drilling > 2 Levels
```tsx
// If passing props through 3+ components, use:
// 1. Context
// 2. Composition (children pattern)
// 3. State management library
```

## Event Handlers

```tsx
// Inline for simple handlers
<button onClick={() => setCount(c => c + 1)}>

// Named for complex logic or reuse
function handleSubmit(e: FormEvent) {
  e.preventDefault();
  // complex logic
}
<form onSubmit={handleSubmit}>
```

## TypeScript Integration

```tsx
// Props interface
interface UserCardProps {
  user: User;
  onSelect?: (user: User) => void;
}

// Component with props
function UserCard({ user, onSelect }: UserCardProps) { ... }

// Generic components
function List<T>({ items, renderItem }: ListProps<T>) { ... }

// Event types
function handleChange(e: ChangeEvent<HTMLInputElement>) { ... }
```

## Performance

1. **Trust the compiler** - Don't pre-optimize with memo/useCallback
2. **Measure first** - Use React Profiler before optimizing
3. **Virtualize long lists** - react-window or @tanstack/virtual
4. **Lazy load routes** - React.lazy() + Suspense
5. **Defer non-critical** - useDeferredValue for search/filter

## Anti-Patterns to Avoid

```tsx
// BAD: Derived state in useState
const [fullName, setFullName] = useState(first + ' ' + last);

// GOOD: Compute during render
const fullName = `${first} ${last}`;

// BAD: Object/array in dependency array without memo
useEffect(() => { ... }, [{ id: 1 }]);  // New object every render!

// BAD: Fetching in useEffect (use Server Components or React Query)
useEffect(() => {
  fetch('/api/users').then(...)
}, []);

// GOOD: Server Component or data library
const users = await fetchUsers();  // Server Component
const { data } = useQuery(['users'], fetchUsers);  // React Query
```

## Testing

- Use React Testing Library (not Enzyme)
- Test behavior, not implementation
- Prefer `getByRole`, `getByLabelText` over `getByTestId`
- Mock at network boundary (MSW), not internal functions
