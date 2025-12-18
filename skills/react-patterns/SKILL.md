---
name: react-patterns
description: |
  React patterns, hooks, context, suspense, server components, RSC, use client,
  use server, useState, useEffect, useCallback, useMemo, useRef, custom hooks,
  render props, compound components, HOC, error boundaries, portals.

  Trigger phrases: react hook, custom hook, useEffect, useState, useContext,
  useMemo, useCallback, useRef, server component, client component, suspense,
  error boundary, portal, render prop, compound component, HOC, higher order,
  react pattern, react best practice, hydration, concurrent rendering.
---

# React Patterns

Modern React patterns and best practices.

## Hooks

### State & Effects
```tsx
// State with type inference
const [items, setItems] = useState<Item[]>([]);

// Effect with cleanup
useEffect(() => {
  const controller = new AbortController();
  fetchData(controller.signal);
  return () => controller.abort();
}, [dependency]);

// Memoized callback (stable reference)
const handleClick = useCallback((id: string) => {
  setItems(prev => prev.filter(item => item.id !== id));
}, []);

// Memoized computation
const total = useMemo(() => items.reduce((sum, i) => sum + i.price, 0), [items]);
```

### Refs
```tsx
// DOM ref
const inputRef = useRef<HTMLInputElement>(null);
inputRef.current?.focus();

// Mutable value (no re-render)
const renderCount = useRef(0);
renderCount.current++;
```

### Custom Hooks
```tsx
function useLocalStorage<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    const stored = localStorage.getItem(key);
    return stored ? JSON.parse(stored) : initial;
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);

  return [value, setValue] as const;
}
```

## Component Patterns

### Compound Components
```tsx
const Tabs = ({ children }) => {
  const [active, setActive] = useState(0);
  return (
    <TabsContext.Provider value={{ active, setActive }}>
      {children}
    </TabsContext.Provider>
  );
};
Tabs.List = TabList;
Tabs.Panel = TabPanel;
```

### Render Props
```tsx
<MouseTracker>
  {({ x, y }) => <Cursor x={x} y={y} />}
</MouseTracker>
```

### Error Boundaries
```tsx
class ErrorBoundary extends Component {
  state = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  render() {
    return this.state.hasError ? <Fallback /> : this.props.children;
  }
}
```

## Server Components (RSC)

```tsx
// Server Component (default in app/)
async function UserList() {
  const users = await db.users.findMany(); // Direct DB access
  return <ul>{users.map(u => <li key={u.id}>{u.name}</li>)}</ul>;
}

// Client Component
'use client';
function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}
```

## Performance

### Avoid Re-renders
```tsx
// Split state (only affected components re-render)
const [name, setName] = useState('');
const [email, setEmail] = useState('');

// Memoize expensive children
const MemoChild = memo(ExpensiveChild);

// Move state down (co-locate with usage)
```

### Suspense
```tsx
<Suspense fallback={<Skeleton />}>
  <AsyncComponent />
</Suspense>
```

## Anti-patterns to Avoid

- ❌ useEffect for derived state (use useMemo)
- ❌ Object/array literals in deps (unstable references)
- ❌ Missing cleanup in effects
- ❌ State for values that can be computed
- ❌ Prop drilling > 3 levels (use context)
