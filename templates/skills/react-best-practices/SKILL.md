---
name: react-best-practices
description: React and Next.js performance optimization patterns. Use BEFORE implementing any React code to ensure best practices are followed.
advertise: true
---

# React Best Practices

**Version 1.0.0**
Source: Vercel Engineering (vercel-labs/agent-skills)

> **Note:**
> This document is for agents and LLMs to follow when maintaining,
> generating, or refactoring React and Next.js codebases. Contains 40+ rules across 8 categories, prioritized by impact.

---

## How to Use This Skill

**Before implementing ANY React/Next.js code:**

1. Review the relevant sections based on what you're building
2. Apply the patterns as you write code
3. Use the "Incorrect" vs "Correct" examples as templates

**Priority order:** Eliminating Waterfalls > Bundle Size > Server-Side > Client-Side > Re-renders > Rendering > JS Perf > Advanced

---

## Quick Reference: Critical Rules

### Top 5 Rules (Always Apply)

1. **Promise.all() for independent operations** - Never sequential awaits for independent data
2. **Avoid barrel file imports** - Import directly from source files
3. **Dynamic imports for heavy components** - Lazy-load Monaco, charts, etc.
4. **Parallel data fetching with component composition** - Structure RSC for parallelism
5. **Minimize serialization at RSC boundaries** - Only pass needed fields to client

---

## 1. Eliminating Waterfalls

**Impact: CRITICAL** - Waterfalls are the #1 performance killer.

### 1.1 Defer Await Until Needed

Move `await` into branches where actually used.

```typescript
// BAD: blocks both branches
async function handleRequest(userId: string, skipProcessing: boolean) {
  const userData = await fetchUserData(userId)
  if (skipProcessing) return { skipped: true }
  return processUserData(userData)
}

// GOOD: only blocks when needed
async function handleRequest(userId: string, skipProcessing: boolean) {
  if (skipProcessing) return { skipped: true }
  const userData = await fetchUserData(userId)
  return processUserData(userData)
}
```

### 1.2 Promise.all() for Independent Operations

```typescript
// BAD: 3 round trips
const user = await fetchUser()
const posts = await fetchPosts()
const comments = await fetchComments()

// GOOD: 1 round trip
const [user, posts, comments] = await Promise.all([
  fetchUser(),
  fetchPosts(),
  fetchComments()
])
```

### 1.3 Strategic Suspense Boundaries

```tsx
// BAD: wrapper blocked by data
async function Page() {
  const data = await fetchData()
  return (
    <div>
      <Sidebar />
      <DataDisplay data={data} />
      <Footer />
    </div>
  )
}

// GOOD: wrapper shows immediately
function Page() {
  return (
    <div>
      <Sidebar />
      <Suspense fallback={<Skeleton />}>
        <DataDisplay />
      </Suspense>
      <Footer />
    </div>
  )
}
```

---

## 2. Bundle Size Optimization

**Impact: CRITICAL** - Reduces TTI and LCP.

### 2.1 Avoid Barrel File Imports

```tsx
// BAD: loads 1,583 modules
import { Check, X, Menu } from 'lucide-react'

// GOOD: loads only 3 modules
import Check from 'lucide-react/dist/esm/icons/check'
import X from 'lucide-react/dist/esm/icons/x'
import Menu from 'lucide-react/dist/esm/icons/menu'

// ALTERNATIVE: Next.js 13.5+ config
// next.config.js
module.exports = {
  experimental: {
    optimizePackageImports: ['lucide-react', '@mui/material']
  }
}
```

### 2.2 Dynamic Imports for Heavy Components

```tsx
// BAD: Monaco bundles with main chunk (~300KB)
import { MonacoEditor } from './monaco-editor'

// GOOD: Monaco loads on demand
import dynamic from 'next/dynamic'
const MonacoEditor = dynamic(
  () => import('./monaco-editor').then(m => m.MonacoEditor),
  { ssr: false }
)
```

### 2.3 Defer Non-Critical Libraries

```tsx
// BAD: blocks initial bundle
import { Analytics } from '@vercel/analytics/react'

// GOOD: loads after hydration
import dynamic from 'next/dynamic'
const Analytics = dynamic(
  () => import('@vercel/analytics/react').then(m => m.Analytics),
  { ssr: false }
)
```

### 2.4 Preload on User Intent

```tsx
function EditorButton({ onClick }: { onClick: () => void }) {
  const preload = () => {
    if (typeof window !== 'undefined') {
      void import('./monaco-editor')
    }
  }
  return (
    <button onMouseEnter={preload} onFocus={preload} onClick={onClick}>
      Open Editor
    </button>
  )
}
```

---

## 3. Server-Side Performance

**Impact: HIGH**

### 3.1 Minimize Serialization at RSC Boundaries

```tsx
// BAD: serializes all 50 fields
async function Page() {
  const user = await fetchUser()  // 50 fields
  return <Profile user={user} />
}

// GOOD: serializes only needed fields
async function Page() {
  const user = await fetchUser()
  return <Profile name={user.name} avatar={user.avatar} />
}
```

### 3.2 Parallel Data Fetching with Component Composition

```tsx
// BAD: Sidebar waits for Header's fetch
export default async function Page() {
  const header = await fetchHeader()
  return (
    <div>
      <div>{header}</div>
      <Sidebar />
    </div>
  )
}

// GOOD: both fetch simultaneously
async function Header() {
  const data = await fetchHeader()
  return <div>{data}</div>
}

async function Sidebar() {
  const items = await fetchSidebarItems()
  return <nav>{items.map(renderItem)}</nav>
}

export default function Page() {
  return (
    <div>
      <Header />
      <Sidebar />
    </div>
  )
}
```

### 3.3 Per-Request Deduplication with React.cache()

```typescript
import { cache } from 'react'

export const getCurrentUser = cache(async () => {
  const session = await auth()
  if (!session?.user?.id) return null
  return await db.user.findUnique({ where: { id: session.user.id } })
})
```

### 3.4 Use after() for Non-Blocking Operations

```tsx
import { after } from 'next/server'

export async function POST(request: Request) {
  await updateDatabase(request)

  // Log after response is sent
  after(async () => {
    const userAgent = (await headers()).get('user-agent')
    logUserAction({ userAgent })
  })

  return Response.json({ status: 'success' })
}
```

---

## 4. Client-Side Data Fetching

**Impact: MEDIUM-HIGH**

### 4.1 Use SWR for Automatic Deduplication

```tsx
// BAD: no deduplication
function UserList() {
  const [users, setUsers] = useState([])
  useEffect(() => {
    fetch('/api/users').then(r => r.json()).then(setUsers)
  }, [])
}

// GOOD: multiple instances share one request
import useSWR from 'swr'
function UserList() {
  const { data: users } = useSWR('/api/users', fetcher)
}
```

---

## 5. Re-render Optimization

**Impact: MEDIUM**

### 5.1 Use Functional setState Updates

```tsx
// BAD: requires state as dependency, risk of stale closure
const addItems = useCallback((newItems: Item[]) => {
  setItems([...items, ...newItems])
}, [items])

// GOOD: stable callback, no stale closures
const addItems = useCallback((newItems: Item[]) => {
  setItems(curr => [...curr, ...newItems])
}, [])
```

### 5.2 Use Lazy State Initialization

```tsx
// BAD: runs on every render
const [settings] = useState(JSON.parse(localStorage.getItem('settings') || '{}'))

// GOOD: runs only once
const [settings] = useState(() => {
  const stored = localStorage.getItem('settings')
  return stored ? JSON.parse(stored) : {}
})
```

### 5.3 Use Transitions for Non-Urgent Updates

```tsx
import { startTransition } from 'react'

function ScrollTracker() {
  const [scrollY, setScrollY] = useState(0)
  useEffect(() => {
    const handler = () => {
      startTransition(() => setScrollY(window.scrollY))
    }
    window.addEventListener('scroll', handler, { passive: true })
    return () => window.removeEventListener('scroll', handler)
  }, [])
}
```

### 5.4 Narrow Effect Dependencies

```tsx
// BAD: re-runs on any user field change
useEffect(() => {
  console.log(user.id)
}, [user])

// GOOD: re-runs only when id changes
useEffect(() => {
  console.log(user.id)
}, [user.id])
```

---

## 6. Rendering Performance

**Impact: MEDIUM**

### 6.1 CSS content-visibility for Long Lists

```css
.message-item {
  content-visibility: auto;
  contain-intrinsic-size: 0 80px;
}
```

### 6.2 Hoist Static JSX Elements

```tsx
// BAD: recreates element every render
function Container() {
  return loading && <div className="animate-pulse h-20 bg-gray-200" />
}

// GOOD: reuses same element
const loadingSkeleton = <div className="animate-pulse h-20 bg-gray-200" />
function Container() {
  return loading && loadingSkeleton
}
```

### 6.3 Animate SVG Wrapper, Not SVG Element

```tsx
// BAD: no hardware acceleration
<svg className="animate-spin">...</svg>

// GOOD: hardware accelerated
<div className="animate-spin">
  <svg>...</svg>
</div>
```

---

## 7. JavaScript Performance

**Impact: LOW-MEDIUM**

### 7.1 Build Index Maps for Repeated Lookups

```typescript
// BAD: O(n) per lookup
items.filter(item => allowedIds.includes(item.id))

// GOOD: O(1) per lookup
const allowedSet = new Set(allowedIds)
items.filter(item => allowedSet.has(item.id))
```

### 7.2 Use toSorted() Instead of sort()

```typescript
// BAD: mutates original array
const sorted = users.sort((a, b) => a.name.localeCompare(b.name))

// GOOD: creates new array
const sorted = users.toSorted((a, b) => a.name.localeCompare(b.name))
```

### 7.3 Early Return from Functions

```typescript
// BAD: processes all items after finding error
function validateUsers(users: User[]) {
  let hasError = false
  for (const user of users) {
    if (!user.email) hasError = true
  }
  return hasError ? { valid: false } : { valid: true }
}

// GOOD: returns immediately on first error
function validateUsers(users: User[]) {
  for (const user of users) {
    if (!user.email) return { valid: false, error: 'Email required' }
  }
  return { valid: true }
}
```

---

## 8. Advanced Patterns

**Impact: LOW**

### 8.1 useEffectEvent for Stable Callbacks

```tsx
import { useEffectEvent } from 'react'

function useWindowEvent(event: string, handler: () => void) {
  const onEvent = useEffectEvent(handler)
  useEffect(() => {
    window.addEventListener(event, onEvent)
    return () => window.removeEventListener(event, onEvent)
  }, [event])
}
```

---

## Checklist Before Implementation

- [ ] Independent async operations use Promise.all()
- [ ] Heavy components use dynamic imports
- [ ] RSC boundaries pass only needed fields
- [ ] Suspense boundaries isolate data fetching
- [ ] No barrel file imports for large libraries
- [ ] State updates use functional form when depending on current state
- [ ] Effects have narrow dependencies
- [ ] Repeated lookups use Set/Map

---

## References

- [React Documentation](https://react.dev)
- [Next.js Documentation](https://nextjs.org)
- [SWR Documentation](https://swr.vercel.app)
- [Vercel Blog: Package Import Optimization](https://vercel.com/blog/how-we-optimized-package-imports-in-next-js)
- [Vercel Blog: Dashboard Performance](https://vercel.com/blog/how-we-made-the-vercel-dashboard-twice-as-fast)
