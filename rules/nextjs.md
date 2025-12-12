---
paths: "**/app/**/*.tsx, **/app/**/*.ts, **/next.config.*, **/middleware.ts"
---

# Next.js Development Rules (Next.js 15+)

Modern Next.js patterns for 2025. App Router, Server Actions, Turbopack.

## App Router Structure

```
app/
├── layout.tsx          # Root layout (required)
├── page.tsx            # Home route (/)
├── loading.tsx         # Loading UI (Suspense boundary)
├── error.tsx           # Error boundary
├── not-found.tsx       # 404 page
├── globals.css         # Global styles
├── (auth)/             # Route group (no URL segment)
│   ├── login/page.tsx
│   └── signup/page.tsx
├── dashboard/
│   ├── layout.tsx      # Nested layout
│   ├── page.tsx
│   └── settings/
│       └── page.tsx
└── api/                # API routes (when needed)
    └── webhook/route.ts
```

## Server vs Client Components

```tsx
// SERVER COMPONENT (default) - no directive needed
// Can: async/await, direct DB access, fetch without useEffect
// Cannot: useState, useEffect, onClick, browser APIs
async function UserList() {
  const users = await db.users.findMany();
  return <ul>{users.map(u => <li key={u.id}>{u.name}</li>)}</ul>;
}

// CLIENT COMPONENT - must have directive
'use client';
// Can: hooks, interactivity, browser APIs
// Cannot: async component, direct DB access
function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c + 1)}>{count}</button>;
}
```

**Rule:** Start with Server Components. Add 'use client' only for interactivity.

## Server Actions

```tsx
// In a Server Component or separate file
async function createUser(formData: FormData) {
  'use server';

  // Always validate input
  const name = formData.get('name');
  if (!name || typeof name !== 'string') {
    return { error: 'Name required' };
  }

  // Mutation logic
  await db.users.create({ data: { name } });
  revalidatePath('/users');
  return { success: true };
}

// Usage in form
<form action={createUser}>
  <input name="name" required />
  <button type="submit">Create</button>
</form>
```

### Server Actions Rules

| Do | Don't |
|----|-------|
| Use for mutations (create, update, delete) | Use for data fetching |
| Validate all input | Trust form data blindly |
| Return simple serializable data | Return complex objects/classes |
| Use `revalidatePath`/`revalidateTag` after mutations | Forget to revalidate cache |

## Metadata API

```tsx
// Static metadata
export const metadata: Metadata = {
  title: 'Dashboard',
  description: 'User dashboard',
};

// Dynamic metadata
export async function generateMetadata({ params }): Promise<Metadata> {
  const user = await getUser(params.id);
  return {
    title: user.name,
    openGraph: { images: [user.avatar] },
  };
}
```

**Place metadata in route folders**, close to the pages they describe.

## Data Fetching Patterns

```tsx
// SERVER COMPONENT - fetch directly
async function ProductPage({ params }: { params: { id: string } }) {
  const product = await fetch(`/api/products/${params.id}`, {
    next: { revalidate: 3600 }  // ISR: revalidate every hour
  });
  return <ProductDetail product={product} />;
}

// Caching options
fetch(url, { cache: 'force-cache' });     // Static (default)
fetch(url, { cache: 'no-store' });        // Dynamic
fetch(url, { next: { revalidate: 60 } }); // ISR
fetch(url, { next: { tags: ['products'] } }); // Tag-based revalidation
```

## Route Segment Config

```tsx
// Force static generation
export const dynamic = 'force-static';

// Force dynamic rendering
export const dynamic = 'force-dynamic';

// Revalidate every N seconds
export const revalidate = 3600;

// Runtime
export const runtime = 'edge';  // or 'nodejs'
```

## Loading & Error States

```tsx
// app/dashboard/loading.tsx - automatic Suspense
export default function Loading() {
  return <Skeleton />;
}

// app/dashboard/error.tsx - error boundary
'use client';
export default function Error({ error, reset }: {
  error: Error;
  reset: () => void;
}) {
  return (
    <div>
      <p>Something went wrong</p>
      <button onClick={reset}>Try again</button>
    </div>
  );
}
```

## Middleware

```tsx
// middleware.ts (root level)
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  // Auth check, redirects, headers
  if (!request.cookies.get('session')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/api/:path*'],
};
```

**Rule:** Keep middleware minimal. Move complex logic to Server Components.

## API Routes (Route Handlers)

```tsx
// app/api/users/route.ts
import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const users = await db.users.findMany();
  return NextResponse.json(users);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const user = await db.users.create({ data: body });
  return NextResponse.json(user, { status: 201 });
}
```

**When to use:**
- Public APIs / webhooks
- External integrations
- When you need full HTTP control

**Prefer Server Actions** for internal app mutations.

## Image Optimization

```tsx
import Image from 'next/image';

// Remote images - configure in next.config.js
<Image
  src="https://example.com/photo.jpg"
  alt="Description"
  width={800}
  height={600}
  priority  // For LCP images
/>

// Fill container
<div className="relative h-64">
  <Image src={url} alt="" fill className="object-cover" />
</div>
```

## Performance Tips

1. **Turbopack** - Default in Next.js 15, no config needed
2. **Parallel data fetching** - Multiple awaits in Server Components run in parallel
3. **Streaming** - Use `loading.tsx` for automatic streaming
4. **Dynamic imports** - `next/dynamic` for heavy client components
5. **Edge runtime** - Use for latency-sensitive routes

```tsx
// Dynamic import for heavy components
const HeavyChart = dynamic(() => import('./Chart'), {
  loading: () => <Skeleton />,
  ssr: false,  // Client-only
});
```

## Anti-Patterns

```tsx
// BAD: Fetching in client component
'use client';
useEffect(() => { fetch('/api/users')... }, []);

// GOOD: Fetch in Server Component, pass as props
async function Page() {
  const users = await getUsers();
  return <ClientComponent users={users} />;
}

// BAD: Server Action for fetching
async function getUsers() {
  'use server';
  return db.users.findMany();  // Wrong use case
}

// BAD: Giant middleware
// Move logic to Server Components or Route Handlers
```
