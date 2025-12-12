---
paths: "**/*.css, **/tailwind.config.*, **/*.tsx, **/*.jsx"
---

# Tailwind CSS v4 Rules (2025)

**CRITICAL:** Tailwind v4 released January 2025. Many patterns from v3 are DEPRECATED.

## v4 vs v3 - Key Differences

| v3 (OLD) | v4 (NEW) |
|----------|----------|
| `tailwind.config.js` | CSS-first with `@theme` |
| `@tailwind base/components/utilities` | `@import "tailwindcss"` |
| `content: [...]` array | Automatic source detection |
| `h-[100px]` brackets required | `h-100` works (dynamic values) |
| Separate container-queries plugin | Built into core |
| RGB/HSL colors | OKLCH color palette |

## Installation (v4)

```bash
npm install tailwindcss @tailwindcss/postcss
```

```css
/* app/globals.css - THIS IS THE NEW WAY */
@import "tailwindcss";
```

**NO** `tailwind.config.js` needed for most projects.

## CSS-First Configuration with @theme

```css
@import "tailwindcss";

@theme {
  /* Colors - creates bg-primary, text-primary, etc. */
  --color-primary: oklch(0.7 0.15 250);
  --color-secondary: oklch(0.6 0.12 180);
  --color-danger: oklch(0.6 0.2 25);

  /* Fonts - creates font-display, font-body */
  --font-display: "Inter", sans-serif;
  --font-body: "Open Sans", sans-serif;

  /* Spacing - creates p-18, m-18, etc. */
  --spacing-18: 4.5rem;
  --spacing-128: 32rem;

  /* Custom breakpoints - creates 3xl:* variant */
  --breakpoint-3xl: 120rem;

  /* Animations */
  --ease-smooth: cubic-bezier(0.4, 0, 0.2, 1);
  --animate-fade-in: fade-in 0.3s var(--ease-smooth);
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
```

## Reset Default Theme Values

```css
@theme {
  /* Reset all fonts, keep only custom */
  --font-*: initial;
  --font-sans: "Inter", sans-serif;

  /* Reset all colors, define custom palette */
  --color-*: initial;
  --color-brand: oklch(0.7 0.15 250);
}
```

## Dynamic Values (NEW in v4)

```html
<!-- v3 required brackets -->
<div class="h-[100px] w-[200px] grid-cols-[1fr_2fr]">

<!-- v4 allows direct values for common patterns -->
<div class="h-100 w-200 grid-cols-15">

<!-- Brackets still work and needed for complex values -->
<div class="bg-[url('/image.png')] grid-cols-[1fr_auto_1fr]">
```

## Multi-Theme with @theme inline

```css
@import "tailwindcss";

/* Use inline to reference CSS variables */
@theme inline {
  --color-primary: var(--primary);
  --color-background: var(--bg);
  --color-foreground: var(--fg);
}

/* Define themes outside @layer base */
:root {
  --primary: oklch(0.7 0.15 250);
  --bg: oklch(0.99 0 0);
  --fg: oklch(0.1 0 0);
}

.dark {
  --primary: oklch(0.8 0.15 250);
  --bg: oklch(0.1 0 0);
  --fg: oklch(0.95 0 0);
}
```

## Container Queries (Built-in)

```html
<!-- No plugin needed in v4 -->
<div class="@container">
  <div class="@md:flex @lg:grid">
    <!-- Responsive to container, not viewport -->
  </div>
</div>
```

## 3D Transforms (NEW)

```html
<div class="rotate-x-45 rotate-y-30 translate-z-10 perspective-500">
  <!-- 3D transformed element -->
</div>
```

## Breaking Changes to Handle

### 1. Import Syntax
```css
/* v3 - DEPRECATED */
@tailwind base;
@tailwind components;
@tailwind utilities;

/* v4 - USE THIS */
@import "tailwindcss";
```

### 2. Border Color Default
```html
<!-- v3: border was gray-200 -->
<!-- v4: border is currentColor -->

<!-- If you want old behavior, be explicit -->
<div class="border border-gray-200">
```

### 3. @apply in Components
```css
/* When using @apply in component CSS files, import main stylesheet */
@import "./globals.css";  /* or wherever your @theme is */

.btn {
  @apply px-4 py-2 rounded-lg;
}
```

### 4. Gradient Preservation
```html
<!-- v3: hover would reset entire gradient -->
<!-- v4: gradient values preserved, use via-none to reset -->
<div class="bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500
            hover:via-none hover:to-red-500">
```

### 5. Prefix Syntax
```css
/* v3 */
tw-bg-blue-500

/* v4 - uses variant syntax */
tw:bg-blue-500
```

## Color Opacity (color-mix)

```html
<!-- v4 uses color-mix() for opacity -->
<div class="bg-blue-500/50">  <!-- 50% opacity -->
<div class="text-primary/75"> <!-- 75% opacity on custom color -->
```

## Browser Support

**Minimum browsers for v4:**
- Safari 16.4+
- Chrome 111+
- Firefox 128+

If you need older browser support, stay on v3.4.

## Migration Tool

```bash
# Run in project root - handles most changes automatically
npx @tailwindcss/upgrade
```

**Always review the diff** - complex projects may need manual tweaks.

## When You Still Need tailwind.config.js

```js
// Only for advanced cases:
// - Custom plugins
// - Complex content detection overrides
// - Compatibility with tools that expect JS config

/** @type {import('tailwindcss').Config} */
export default {
  // v4 still supports JS config as escape hatch
}
```

## Anti-Patterns (v4)

```css
/* BAD: Using @tailwind directives */
@tailwind base;  /* DEPRECATED */

/* GOOD: Single import */
@import "tailwindcss";

/* BAD: Large tailwind.config.js for theme */
module.exports = {
  theme: { extend: { colors: { ... } } }
}

/* GOOD: CSS-first @theme */
@theme {
  --color-brand: oklch(0.7 0.15 250);
}

/* BAD: Using v3 arbitrary value syntax when not needed */
<div class="h-[64px]">

/* GOOD: v4 supports direct values */
<div class="h-64">  /* or h-16 for 4rem */
```
