---
name: state-management
description: |
  State management, Redux, Zustand, Context API, MobX, state mutations,
  data flow, store design, actions, reducers, selectors, state debugging,
  hydration, persistence, global state, local state.

  Trigger phrases: state management, Redux, Zustand, Context, MobX,
  store design, state mutation, reducer, action, selector, dispatch,
  global state, local state, state flow, hydration error, state persistence,
  state debugging, where is state, state update, subscribe to state.
---

# State Management

Tools for managing application state.

## Primary Tools

### state-mapper Agent
```bash
Task(subagent_type="state-mapper", prompt="Map state flow in <path>")
```
Maps state management flows, finds mutations, traces data through stores.

### PAL Debug - State Issues
```bash
mcp__pal__debug  # For complex state bugs
```

## React State Patterns

### Local State (useState)
```javascript
const [value, setValue] = useState(initialValue);
```

### Context API
```javascript
const StateContext = createContext();
const useAppState = () => useContext(StateContext);
```

### Zustand (Recommended)
```javascript
const useStore = create((set) => ({
  count: 0,
  increment: () => set((state) => ({ count: state.count + 1 })),
}));
```

### Redux Toolkit
```javascript
const slice = createSlice({
  name: 'feature',
  initialState,
  reducers: {
    action: (state, action) => { ... }
  }
});
```

## State Debugging

### Find State Location
```bash
# Search for store definitions
grep -rn "createStore\|createSlice\|create(" --include="*.ts" --include="*.tsx"

# Find state usage
grep -rn "useSelector\|useStore\|useState" --include="*.tsx"
```

### Trace Data Flow
```bash
# Find where state is modified
grep -rn "dispatch\|setState\|set(" --include="*.ts"

# Find subscribers
grep -rn "subscribe\|useEffect.*state" --include="*.tsx"
```

## Common Issues

### Hydration Mismatches
- Server and client state must match
- Use `suppressHydrationWarning` sparingly
- Initialize with same values

### Stale Closures
```javascript
// Problem: stale value in closure
useEffect(() => {
  interval = setInterval(() => console.log(count), 1000);
}, []); // count is stale

// Fix: use ref or add dependency
```

### Unnecessary Re-renders
```javascript
// Use selectors to pick specific state
const name = useStore((state) => state.user.name);
// Instead of
const { user } = useStore(); // Re-renders on any user change
```

## State Persistence

### localStorage
```javascript
const useStore = create(
  persist(
    (set) => ({ ... }),
    { name: 'app-storage' }
  )
);
```

### URL State
```javascript
// React Router
const [searchParams, setSearchParams] = useSearchParams();
```
