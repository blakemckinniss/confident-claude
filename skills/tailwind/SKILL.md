---
name: tailwind
description: |
  Tailwind CSS, utility classes, responsive design, dark mode, custom theme,
  arbitrary values, component patterns, @apply, plugins, JIT, container queries,
  animations, transitions, flexbox, grid, spacing, colors.

  Trigger phrases: tailwind, utility class, responsive design, dark mode,
  tailwind theme, arbitrary value, @apply, tailwind plugin, tailwind config,
  flex, grid, spacing, tailwind color, tailwind animation, tailwind transition,
  container query, tailwind pattern.
---

# Tailwind CSS

Tailwind utility patterns and best practices.

## Common Patterns

### Flexbox
```html
<!-- Center horizontally and vertically -->
<div class="flex items-center justify-center">

<!-- Space between -->
<div class="flex justify-between">

<!-- Column with gap -->
<div class="flex flex-col gap-4">

<!-- Wrap -->
<div class="flex flex-wrap gap-2">
```

### Grid
```html
<!-- 3 columns -->
<div class="grid grid-cols-3 gap-4">

<!-- Responsive columns -->
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">

<!-- Auto-fit -->
<div class="grid grid-cols-[repeat(auto-fit,minmax(250px,1fr))] gap-4">
```

### Spacing
```html
<!-- Padding -->
<div class="p-4">        <!-- All sides -->
<div class="px-4 py-2">  <!-- Horizontal, Vertical -->
<div class="pt-8">       <!-- Top only -->

<!-- Margin -->
<div class="m-auto">     <!-- Center -->
<div class="mt-4 mb-8">  <!-- Top, Bottom -->
<div class="-mt-4">      <!-- Negative -->
```

## Responsive Design

```html
<!-- Mobile-first breakpoints -->
<div class="text-sm md:text-base lg:text-lg">
<div class="hidden md:block">
<div class="grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">

<!-- Breakpoints: sm(640) md(768) lg(1024) xl(1280) 2xl(1536) -->
```

## Dark Mode

```html
<!-- Class-based (recommended) -->
<div class="bg-white dark:bg-gray-900">
<p class="text-gray-900 dark:text-gray-100">

<!-- In tailwind.config.js -->
module.exports = {
  darkMode: 'class', // or 'media'
}
```

## Arbitrary Values

```html
<!-- Custom values -->
<div class="top-[117px]">
<div class="w-[calc(100%-2rem)]">
<div class="bg-[#1da1f2]">
<div class="grid-cols-[1fr_2fr_1fr]">
<div class="text-[length:var(--font-size)]">
```

## Component Patterns

### Card
```html
<div class="rounded-lg border bg-card p-6 shadow-sm">
  <h3 class="text-lg font-semibold">Title</h3>
  <p class="mt-2 text-muted-foreground">Description</p>
</div>
```

### Button
```html
<button class="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50">
  Click me
</button>
```

### Input
```html
<input class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50" />
```

## Animations

```html
<!-- Built-in -->
<div class="animate-spin">
<div class="animate-pulse">
<div class="animate-bounce">

<!-- Transitions -->
<button class="transition-colors duration-200 hover:bg-blue-600">
<div class="transition-all duration-300 ease-in-out">

<!-- Transform -->
<div class="hover:scale-105 hover:-translate-y-1 transition-transform">
```

## Custom Theme

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#3b82f6',
          foreground: '#ffffff',
        },
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-in-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
}
```

## @apply (Use Sparingly)

```css
/* Only for truly repeated patterns */
@layer components {
  .btn-primary {
    @apply inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90;
  }
}
```

## Tips

- Mobile-first: Start with base styles, add responsive variants
- Composition over extraction: Prefer utility classes
- Group hover: `group` + `group-hover:*`
- Peer modifiers: `peer` + `peer-checked:*`
- Container queries: `@container` + `@lg:*`
