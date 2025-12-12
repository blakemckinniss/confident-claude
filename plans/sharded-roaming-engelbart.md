# Pandora UI/UX Redesign Plan

## Vision
Dark fantasy TCG aesthetic with VSCode-dark backgrounds, muted RPG colors, and image-first card design with proper TCG overlays.

---

## Phase 1: Foundation (Tailwind 4 + Design System)

### 1.1 Install Tailwind 4
```bash
npm install tailwindcss @tailwindcss/postcss
```

### 1.2 Create Design System (`src/styles/theme.css`)
```css
@import "tailwindcss";

@theme {
  /* Dark Fantasy Palette - VSCode-inspired darks */
  --color-bg-primary: oklch(0.13 0.01 250);      /* #1e1e1e - VSCode dark */
  --color-bg-secondary: oklch(0.16 0.01 250);    /* #252526 - sidebar */
  --color-bg-tertiary: oklch(0.19 0.01 250);     /* #2d2d2d - hover */
  --color-bg-card: oklch(0.12 0.02 250);         /* Card background */

  /* Muted RPG Accents */
  --color-gold: oklch(0.75 0.12 85);             /* Muted gold - energy/highlight */
  --color-health: oklch(0.55 0.15 25);           /* Muted red - health */
  --color-block: oklch(0.55 0.10 250);           /* Steel blue - block */
  --color-poison: oklch(0.50 0.15 145);          /* Muted green - poison/heal */
  --color-mana: oklch(0.50 0.12 280);            /* Muted purple - energy */

  /* Text */
  --color-text-primary: oklch(0.90 0.01 250);    /* Off-white */
  --color-text-secondary: oklch(0.70 0.01 250);  /* Muted */
  --color-text-accent: oklch(0.80 0.10 85);      /* Gold accent */

  /* Card Type Colors */
  --color-attack: oklch(0.45 0.12 25);           /* Muted crimson */
  --color-skill: oklch(0.45 0.10 250);           /* Steel */
  --color-power: oklch(0.45 0.12 280);           /* Purple */

  /* Spacing */
  --spacing-card-gap: 0.5rem;
  --radius-card: 0.75rem;
  --radius-button: 0.5rem;
}
```

### 1.3 Files to Modify
- `src/styles/index.css` - Replace with Tailwind import + theme
- `src/styles/variables.css` - DELETE (merged into theme)
- `postcss.config.js` - Add Tailwind plugin
- `next.config.js` - Ensure CSS processing

---

## Phase 2: TCG Card Redesign

### 2.1 New Card Structure (Image-First TCG Style)
```
┌─────────────────────────┐
│ [Energy]      [Type]    │  ← Header bar (semi-transparent overlay)
├─────────────────────────┤
│                         │
│     CARD IMAGE          │  ← 60% of card height, full bleed
│     (artwork)           │
│                         │
├─────────────────────────┤
│   Card Name             │  ← Name bar (gold accent on attack cards)
├─────────────────────────┤
│ ┌─────────────────────┐ │
│ │ Description text    │ │  ← Text box with subtle frame
│ │ Deal 6 damage.      │ │
│ └─────────────────────┘ │
├─────────────────────────┤
│ [Rarity] ─── [Stats]    │  ← Footer (damage/block icons)
└─────────────────────────┘
```

### 2.2 Card CSS Strategy
- Keep as custom CSS (not Tailwind utilities)
- Use CSS custom properties from Tailwind theme
- Preserve GSAP animation targets
- New file: `src/styles/card-tcg.css`

### 2.3 Files to Modify
- `src/components/Cards.tsx` - New JSX structure
- `src/styles/card.css` - Rewrite completely
- Card images - May need new aspect ratio guidance

---

## Phase 3: Combat Screen Layout

### 3.1 New Layout
```
┌────────────────────────────────────────────┐
│  [Menu]                    [Deck] [Discard]│  ← Top bar
├────────────────────────────────────────────┤
│                                            │
│           MONSTERS (centered)              │  ← Targets area
│        ┌────┐  ┌────┐  ┌────┐             │
│        │ M1 │  │ M2 │  │ M3 │             │
│        └────┘  └────┘  └────┘             │
│                                            │
├────────────────────────────────────────────┤
│     [Player HP]  [Energy]  [End Turn]      │  ← Player bar
├────────────────────────────────────────────┤
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐       │
│  │ C1 │ │ C2 │ │ C3 │ │ C4 │ │ C5 │       │  ← Hand (fan layout)
│  └────┘ └────┘ └────┘ └────┘ └────┘       │
└────────────────────────────────────────────┘
```

### 3.2 Files to Modify
- `src/components/GameScreen.tsx` - Layout structure
- `src/styles/app.css` - Rewrite layout
- `src/styles/targets.css` - Monster/player positioning
- `src/styles/overlay.css` - Modal styling

---

## Phase 4: Health Bars & Powers

### 4.1 Health Bar Redesign
- Beveled/metallic frame effect
- Gradient health fill (darker at edges)
- Block shown as secondary overlay with pattern
- Damage flash animation

### 4.2 Powers Display
- Icon-based with subtle glow
- Tooltip on hover
- Stack count as badge

### 4.3 Files to Modify
- `src/components/Player.tsx` - Structure updates
- `src/styles/healthbar.css` - Complete rewrite
- `src/styles/fct.css` - Combat text styling

---

## Phase 5: Navigation & Menus

### 5.1 Splash Screen
- Full-screen dark background with subtle particle effect
- Large title with metallic text effect
- Glowing button hover states

### 5.2 Overlays/Modals
- Frosted glass effect (backdrop-blur)
- Subtle border glow
- Smooth transitions

### 5.3 Map (if keeping legacy mode)
- Node styling update
- Path visualization

### 5.4 Files to Modify
- `src/components/SplashScreen.tsx`
- `src/components/Menu.tsx`
- `src/components/Overlays.tsx`
- `src/styles/map.css`
- `src/styles/overlay.css`

---

## Implementation Order

1. **Week 1: Foundation**
   - [ ] Install Tailwind 4
   - [ ] Create theme.css with design tokens
   - [ ] Update build config
   - [ ] Create base utility classes

2. **Week 2: Cards (Hero Component)**
   - [ ] New Card JSX structure
   - [ ] TCG-style card CSS
   - [ ] Card hover/drag states
   - [ ] Test with existing card images

3. **Week 3: Combat Screen**
   - [ ] Layout restructure
   - [ ] Health bar redesign
   - [ ] Power icons
   - [ ] FCT updates

4. **Week 4: Shell & Polish**
   - [ ] Splash screen
   - [ ] Menus/overlays
   - [ ] Transitions & animations
   - [ ] Responsive adjustments

---

## Files Summary

### Delete
- `src/styles/variables.css` (merged into theme)

### Rewrite Completely
- `src/styles/card.css` → `src/styles/card-tcg.css`
- `src/styles/healthbar.css`
- `src/styles/app.css`

### Modify Significantly
- `src/styles/index.css`
- `src/styles/targets.css`
- `src/styles/overlay.css`
- `src/styles/typography.css`
- `src/styles/forms.css`

### Component Updates
- `src/components/Cards.tsx`
- `src/components/Player.tsx`
- `src/components/GameScreen.tsx`
- `src/components/SplashScreen.tsx`
- `src/components/Overlays.tsx`

### New Files
- `postcss.config.js` (Tailwind config)
- `src/styles/theme.css` (@theme block)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Card images wrong aspect ratio | Create fallback/placeholder system |
| GSAP animations break | Keep same class names as targets |
| Drag-drop affected | Test thoroughly, keep data attributes |
| Browser support | Tailwind 4 needs Safari 16.4+ |

---

## Success Criteria

- [ ] All 21 cards render correctly with new design
- [ ] Combat feels responsive and satisfying
- [ ] Health/damage feedback is clear
- [ ] Dark theme is consistent throughout
- [ ] No visual regressions on mobile
- [ ] Tests still pass
