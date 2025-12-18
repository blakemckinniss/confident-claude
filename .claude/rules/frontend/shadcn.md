---
paths: "**/components/ui/**, **/components.json"
---

# shadcn/ui Rules (2025)

Modern shadcn/ui patterns with Tailwind v4 and React 19.

## Key 2025 Updates

| Change | Details |
|--------|---------|
| React 19 | `forwardRef` removed, adjusted types |
| Tailwind v4 | CSS-first config, OKLCH colors |
| `data-slot` | Every primitive has this for styling |
| HSL → OKLCH | Colors converted to OKLCH format |
| `tw-animate-css` | Replaces `tailwindcss-animate` |
| `new-york` style | Default (default style deprecated) |
| `sonner` | Replaces toast component |

## Project Structure

```
components/
├── ui/                 # shadcn/ui generated components (don't heavily modify)
│   ├── button.tsx
│   ├── card.tsx
│   └── dialog.tsx
├── shared/             # Composed components using ui/*
│   ├── user-avatar.tsx
│   └── nav-menu.tsx
├── forms/              # Form-specific compositions
│   └── login-form.tsx
└── overrides/          # Heavy customizations of ui/*
    └── custom-button.tsx
```

## Installation (Tailwind v4)

```bash
npx shadcn@latest init
```

Select:
- Style: `new-york` (default is deprecated)
- Tailwind CSS: v4
- CSS variables: Yes

## CSS Variables with Tailwind v4

```css
@import "tailwindcss";

/* shadcn variables in :root */
:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.141 0.005 285.823);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.141 0.005 285.823);
  --primary: oklch(0.21 0.006 285.885);
  --primary-foreground: oklch(0.985 0 0);
  --secondary: oklch(0.967 0.001 286.375);
  --secondary-foreground: oklch(0.21 0.006 285.885);
  --muted: oklch(0.967 0.001 286.375);
  --muted-foreground: oklch(0.552 0.016 285.938);
  --accent: oklch(0.967 0.001 286.375);
  --accent-foreground: oklch(0.21 0.006 285.885);
  --destructive: oklch(0.577 0.245 27.325);
  --destructive-foreground: oklch(0.577 0.245 27.325);
  --border: oklch(0.92 0.004 286.32);
  --input: oklch(0.92 0.004 286.32);
  --ring: oklch(0.705 0.015 286.067);
  --radius: 0.5rem;
}

.dark {
  --background: oklch(0.141 0.005 285.823);
  --foreground: oklch(0.985 0 0);
  /* ... dark variants */
}

/* Map to Tailwind @theme */
@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
}
```

## Component Usage Patterns

### Composition Over Modification
```tsx
// GOOD: Compose in shared/
// components/shared/submit-button.tsx
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

export function SubmitButton({ loading, children, ...props }) {
  return (
    <Button disabled={loading} {...props}>
      {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
      {children}
    </Button>
  );
}

// BAD: Modifying ui/button.tsx directly for one use case
```

### Using data-slot for Styling
```tsx
// Components expose data-slot for targeted styling
<Dialog>
  <DialogContent className="[&[data-slot=header]]:pb-0">
    {/* Override header padding */}
  </DialogContent>
</Dialog>
```

### CVA Variants (Class Variance Authority)
```tsx
import { cva, type VariantProps } from "class-variance-authority";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline: "border border-input bg-background hover:bg-accent",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);
```

## Adding Components

```bash
# Add individual components
npx shadcn@latest add button
npx shadcn@latest add card dialog

# Add multiple at once
npx shadcn@latest add button card dialog dropdown-menu
```

## Dark Mode

```tsx
// Use next-themes (recommended)
import { ThemeProvider } from "next-themes";

<ThemeProvider attribute="class" defaultTheme="system" enableSystem>
  {children}
</ThemeProvider>

// Toggle
import { useTheme } from "next-themes";
const { setTheme, theme } = useTheme();
```

## Form Integration

```tsx
// shadcn/ui + react-hook-form + zod
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Form, FormField, FormItem, FormLabel, FormControl } from "@/components/ui/form";

const form = useForm<z.infer<typeof schema>>({
  resolver: zodResolver(schema),
  defaultValues: { name: "" },
});

<Form {...form}>
  <form onSubmit={form.handleSubmit(onSubmit)}>
    <FormField
      control={form.control}
      name="name"
      render={({ field }) => (
        <FormItem>
          <FormLabel>Name</FormLabel>
          <FormControl>
            <Input {...field} />
          </FormControl>
        </FormItem>
      )}
    />
  </form>
</Form>
```

## Animation (tw-animate-css)

```bash
# New projects use tw-animate-css (not tailwindcss-animate)
npm install tw-animate-css
```

```css
@import "tailwindcss";
@import "tw-animate-css";
```

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Modifying ui/* directly | Create wrappers in shared/ or overrides/ |
| Missing dark: variants in CVA | Add dark mode variants upfront |
| Radix version mismatch | Pin to version in shadcn's package.json |
| HSL colors in v4 | Use OKLCH format |
| tailwindcss-animate in v4 | Use tw-animate-css instead |

## Recommended Radix Imports

```tsx
// shadcn uses these Radix primitives
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import * as SelectPrimitive from "@radix-ui/react-select";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

// Always check Radix docs for prop changes on updates
```

## Toast → Sonner Migration

```tsx
// OLD (deprecated)
import { useToast, toast } from "@/components/ui/toast";

// NEW
import { toast } from "sonner";

// Usage
toast.success("Saved!");
toast.error("Failed to save");
toast.promise(saveData(), {
  loading: "Saving...",
  success: "Saved!",
  error: "Failed",
});
```
