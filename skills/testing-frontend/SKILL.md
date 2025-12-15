---
name: testing-frontend
description: |
  Frontend testing, React Testing Library, Vitest, Jest, Playwright, Cypress,
  component testing, integration testing, E2E testing, mocking, user events,
  accessibility testing, snapshot testing, test coverage.

  Trigger phrases: react testing library, vitest, jest, playwright, cypress,
  component test, integration test, e2e test, mock, user event, accessibility test,
  snapshot test, test coverage, render test, screen query, waitFor, act,
  test utils, testing library.
---

# Frontend Testing

Testing patterns for React and web applications.

## React Testing Library

### Basic Test
```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Counter } from './Counter';

test('increments counter on click', async () => {
  const user = userEvent.setup();
  render(<Counter />);

  expect(screen.getByText('Count: 0')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: /increment/i }));

  expect(screen.getByText('Count: 1')).toBeInTheDocument();
});
```

### Queries (Priority Order)
```tsx
// 1. Accessible queries (preferred)
screen.getByRole('button', { name: /submit/i })
screen.getByLabelText('Email')
screen.getByPlaceholderText('Enter email')
screen.getByText('Welcome')

// 2. Semantic queries
screen.getByAltText('Profile picture')
screen.getByTitle('Close')

// 3. Test IDs (last resort)
screen.getByTestId('custom-element')
```

### Query Variants
```tsx
// getBy - throws if not found
screen.getByText('Hello')

// queryBy - returns null if not found
screen.queryByText('Hello')

// findBy - async, waits for element
await screen.findByText('Loaded')

// getAllBy - multiple elements
screen.getAllByRole('listitem')
```

### Async Testing
```tsx
test('loads data', async () => {
  render(<DataLoader />);

  // Wait for element to appear
  await screen.findByText('Data loaded');

  // Or use waitFor for assertions
  await waitFor(() => {
    expect(screen.getByText('Data loaded')).toBeInTheDocument();
  });
});
```

### User Events
```tsx
const user = userEvent.setup();

// Click
await user.click(element);
await user.dblClick(element);

// Type
await user.type(input, 'hello');
await user.clear(input);

// Select
await user.selectOptions(select, 'option1');

// Keyboard
await user.keyboard('{Enter}');
await user.tab();
```

## Mocking

### Mock Functions
```tsx
const mockFn = vi.fn();
mockFn.mockReturnValue('value');
mockFn.mockResolvedValue('async value');
mockFn.mockImplementation((x) => x * 2);

expect(mockFn).toHaveBeenCalled();
expect(mockFn).toHaveBeenCalledWith('arg');
expect(mockFn).toHaveBeenCalledTimes(2);
```

### Mock Modules
```tsx
// Vitest
vi.mock('./api', () => ({
  fetchUsers: vi.fn(() => Promise.resolve([{ id: 1, name: 'John' }])),
}));

// Jest
jest.mock('./api');
```

### Mock Fetch
```tsx
beforeEach(() => {
  vi.spyOn(global, 'fetch').mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: 'test' }),
  } as Response);
});

afterEach(() => {
  vi.restoreAllMocks();
});
```

## Vitest Setup

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
});

// setup.ts
import '@testing-library/jest-dom';
```

## Playwright (E2E)

```typescript
import { test, expect } from '@playwright/test';

test('user can login', async ({ page }) => {
  await page.goto('/login');

  await page.getByLabel('Email').fill('user@example.com');
  await page.getByLabel('Password').fill('password');
  await page.getByRole('button', { name: 'Login' }).click();

  await expect(page).toHaveURL('/dashboard');
  await expect(page.getByText('Welcome')).toBeVisible();
});
```

## Test Patterns

### Component Testing
```tsx
describe('Button', () => {
  it('renders children', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole('button')).toHaveTextContent('Click me');
  });

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={onClick}>Click</Button>);

    await user.click(screen.getByRole('button'));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('is disabled when disabled prop is true', () => {
    render(<Button disabled>Click</Button>);
    expect(screen.getByRole('button')).toBeDisabled();
  });
});
```

### Integration Testing
```tsx
test('user can add item to cart', async () => {
  const user = userEvent.setup();
  render(<App />);

  // Navigate to product
  await user.click(screen.getByText('Products'));
  await user.click(screen.getByText('Widget'));

  // Add to cart
  await user.click(screen.getByRole('button', { name: /add to cart/i }));

  // Verify cart updated
  expect(screen.getByText('Cart (1)')).toBeInTheDocument();
});
```

## Commands

```bash
# Vitest
npm run test
npm run test:watch
npm run test:coverage

# Playwright
npx playwright test
npx playwright test --ui
npx playwright codegen  # Record tests
```
