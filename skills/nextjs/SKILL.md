---
name: nextjs
description: |
  Next.js framework, App Router, Pages Router, server actions, ISR, SSR, SSG,
  middleware, API routes, dynamic routes, layouts, loading states, error handling,
  image optimization, fonts, metadata, caching, revalidation.

  Trigger phrases: nextjs, next.js, app router, pages router, server action,
  ISR, SSR, SSG, getServerSideProps, getStaticProps, middleware, api route,
  dynamic route, layout, loading state, next/image, next/font, metadata,
  revalidate, generateStaticParams, route handler.
---

# Next.js

Next.js App Router and framework patterns.

## App Router Structure

```
app/
├── layout.tsx          # Root layout
├── page.tsx            # Home route (/)
├── loading.tsx         # Loading UI
├── error.tsx           # Error boundary
├── not-found.tsx       # 404 page
├── users/
│   ├── page.tsx        # /users
│   └── [id]/
│       └── page.tsx    # /users/:id
└── api/
    └── route.ts        # API route
```

## Server Components (Default)

```tsx
// app/users/page.tsx - Server Component
async function UsersPage() {
  const users = await db.users.findMany();
  return <UserList users={users} />;
}

export default UsersPage;
```

## Client Components

```tsx
'use client';

import { useState } from 'react';

export function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}
```

## Server Actions

```tsx
// app/actions.ts
'use server';

export async function createUser(formData: FormData) {
  const name = formData.get('name');
  await db.users.create({ data: { name } });
  revalidatePath('/users');
}

// Usage in component
<form action={createUser}>
  <input name="name" />
  <button type="submit">Create</button>
</form>
```

## Data Fetching

```tsx
// Automatic deduplication & caching
const data = await fetch('https://api.example.com/data');

// Revalidate every 60 seconds
const data = await fetch(url, { next: { revalidate: 60 } });

// No cache
const data = await fetch(url, { cache: 'no-store' });
```

## Dynamic Routes

```tsx
// app/posts/[slug]/page.tsx
interface Props {
  params: { slug: string };
}

export default function Post({ params }: Props) {
  return <article>{params.slug}</article>;
}

// Generate static params
export async function generateStaticParams() {
  const posts = await getPosts();
  return posts.map(post => ({ slug: post.slug }));
}
```

## Route Handlers (API)

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

## Middleware

```tsx
// middleware.ts (root)
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const token = request.cookies.get('token');
  if (!token && request.nextUrl.pathname.startsWith('/dashboard')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }
}

export const config = {
  matcher: '/dashboard/:path*',
};
```

## Metadata

```tsx
// Static
export const metadata = {
  title: 'My App',
  description: 'Description',
};

// Dynamic
export async function generateMetadata({ params }) {
  const post = await getPost(params.slug);
  return { title: post.title };
}
```

## Image & Font

```tsx
import Image from 'next/image';
import { Inter } from 'next/font/google';

const inter = Inter({ subsets: ['latin'] });

<Image src="/hero.jpg" alt="Hero" width={800} height={400} priority />
<main className={inter.className}>...</main>
```

## Caching Strategy

| Fetch Option | Behavior |
|--------------|----------|
| Default | Cached indefinitely |
| `revalidate: N` | Revalidate after N seconds |
| `cache: 'no-store'` | Always fresh |
| `revalidatePath()` | On-demand revalidation |
| `revalidateTag()` | Tag-based revalidation |
