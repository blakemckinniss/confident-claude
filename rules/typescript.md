---
paths: "**/*.ts, **/*.tsx, **/*.js, **/*.jsx"
---

# TypeScript/JavaScript Development Rules

## Type Safety

- Prefer TypeScript over JavaScript for new files
- Use strict mode (`"strict": true` in tsconfig)
- Avoid `any` - use `unknown` and narrow with type guards
- Define interfaces for object shapes, types for unions

## React Patterns (when applicable)

- Functional components only - no class components
- Use hooks for state and effects
- Prefer named exports over default exports
- Colocate component + styles + tests

## Imports

- Use ES modules (`import/export`), not CommonJS
- Prefer named imports over namespace imports
- Sort: react, external libs, internal modules, relative

## Error Handling

- Use try/catch for async operations
- Don't swallow errors silently
- Type error responses from APIs

## File Organization

```
src/
  components/     # React components
  hooks/          # Custom hooks
  utils/          # Pure utility functions
  types/          # Shared type definitions
  services/       # API clients, external services
```

## Naming Conventions

- Components: PascalCase (`UserProfile.tsx`)
- Hooks: camelCase with `use` prefix (`useAuth.ts`)
- Utils: camelCase (`formatDate.ts`)
- Types/Interfaces: PascalCase (`UserProfile`, `ApiResponse`)
- Constants: SCREAMING_SNAKE_CASE

## Build & Test

- Run `npm run build` or equivalent before claiming done
- Run `npm run typecheck` to verify types
- Run `npm test` for test coverage
