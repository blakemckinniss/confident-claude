# PoE-Style Map System Implementation Plan

> Replace key system with Path of Exile-inspired map items that the AI DM uses to generate themed, modified dungeons.

## Design Decisions

| Decision | Choice |
|----------|--------|
| Map Acquisition | Drops + Tavern vendor + AI rewards |
| Tier System | T1-T10 (difficulty) + Rarity (modifier density) |
| Key System | Full replacement |
| Map Crafting | Currency orbs + AI enhancement |

## Key Insight

**The modifier infrastructure already exists but is dormant:**
- `DungeonCard.modifiers` field exists (never populated)
- Modifier effects defined in `entity-system.ts` (echoing, fortified, trapped, etc.)
- `calculateEffectiveStats()` already accepts `dungeonModifiers`
- Map system **activates this dormant system**

---

## Phase 1: Core Map Item Infrastructure

### 1.1 Type Definitions
**File:** `src/lib/core/game-types.ts`

```typescript
interface MapItem extends Item {
  category: "consumable"
  subtype: "map"
  mapProps: {
    tier: 1-10              // Difficulty tier
    theme: string           // "Goblin Warrens", "Shadow Maze"
    biome: string           // "underground", "void", "cursed"
    floors: number          // 3-10 based on tier
    modifiers: DungeonModifier[]
    modSlots: number        // Max modifiers (rarity determines)
    quality: number         // 0-20% bonus loot/XP
    identified: boolean
  }
  consumedOnUse: true
}

interface CraftingCurrency extends Item {
  category: "currency"
  subtype: CurrencyType
  currencyProps: {
    effect: "add_modifier" | "reroll_modifiers" | "upgrade_rarity" | "add_quality"
    targetType: "map" | "equipment" | "any"
  }
}
// Remove: DungeonKey, KeyRarity
```

**Rarity → Modifier Slots:** Common=0, Uncommon=1-2, Rare=3-5, Legendary=6

### 1.2 Map Generator
**File:** `src/lib/items/map-generator.ts` (NEW)

- `generateMap({ tier, rarity?, theme? }): MapItem`
- Floor scaling: T1=3-4, T5=6-7, T10=9-10
- Theme pools by tier bracket

### 1.3 Currency System
**File:** `src/lib/items/currency-generator.ts` (NEW)

| Currency | Effect |
|----------|--------|
| Orb of Alteration | Reroll magic map mods |
| Orb of Augmentation | Add 1 modifier |
| Orb of Alchemy | Normal → Rare (3-5 mods) |
| Orb of Scouring | Strip all modifiers |
| Orb of Chaos | Reroll all rare mods |
| Orb of Divine | Reroll modifier values |
| Orb of Exalted | Add high-tier modifier |

---

## Phase 2: Tavern Integration

### 2.1 Map Vendor Tab
**File:** `src/components/encounters/tavern.tsx`

- Remove Keysmith NPC (lines 191-259)
- Add "Cartographer Theron" - sells T1-T3 maps + currencies

### 2.2 Map Device Tab
**File:** `src/components/encounters/tavern.tsx`

- List player's maps from inventory
- MapCard shows tier, rarity, modifiers
- Activate → confirm → enter dungeon (map consumed)

### 2.3 Map Card Component
**File:** `src/components/world/map-card.tsx` (NEW)

---

## Phase 3: Dungeon Generation from Maps

### 3.1 Create Dungeon from Map
**File:** `src/lib/core/game-data.ts`

```typescript
function createDungeonFromMap(map: MapItem): DungeonCard {
  return {
    name: map.mapProps.theme,
    modifiers: map.mapProps.modifiers,  // KEY: Modifiers now populated!
    mapMetadata: { tier, quality },
  }
}
```

### 3.2 Remove Key Functions
- Delete `createMasterKey()`, `createDungeonKey()`, `generateDungeonSelection()`

---

## Phase 4: AI DM Integration

### 4.1 Event Chain API Enhancement
**File:** `src/app/api/event-chain/route.ts`

Pass modifier context to AI:
```typescript
const modifierContext = `
MAP MODIFIERS ACTIVE:
${modifiers.map(m => `- ${m.name}: ${m.description}`).join("\n")}

CRITICAL: These modifiers MUST influence enemy strength, loot quality, hazards, atmosphere.
`
```

---

## Phase 5: Loot System (Map Loop)

### 5.1 Map Drops
**File:** `src/lib/items/smart-loot-system.ts`

- 15% base drop, +30% from bosses, +1% per quality
- Drop tier = current (70%) or +1 (30%)

### 5.2 Currency Drops
- 8% base + 2% per tier
- Currency table scales with tier

---

## Phase 6: Migration

### 6.1 Save Migration
**File:** `src/lib/persistence/save-migration.ts` (NEW)

- Master key → 3x T1 maps
- Uncommon keys → T2 maps
- Rare keys → T3 rare maps

### 6.2 New Player Setup
```typescript
inventory: [
  generateMap({ tier: 1, rarity: "common" }) x3,
  orb_alteration x2,
]
```

---

## Critical Files

| Pri | File | Changes |
|-----|------|---------|
| 1 | `src/lib/core/game-types.ts` | Add MapItem, CraftingCurrency; remove DungeonKey |
| 1 | `src/lib/items/map-generator.ts` | NEW |
| 1 | `src/lib/items/currency-generator.ts` | NEW |
| 1 | `src/lib/core/game-data.ts` | createDungeonFromMap(), update createInitialPlayer() |
| 2 | `src/components/encounters/tavern.tsx` | Remove Keysmith, add Map Vendor + Device |
| 2 | `src/components/world/map-card.tsx` | NEW |
| 3 | `src/app/api/event-chain/route.ts` | Pass modifier context to AI |
| 3 | `src/lib/items/smart-loot-system.ts` | Map + currency drops |
| 3 | `src/lib/persistence/save-migration.ts` | NEW |

---

## AI DM Role

**Maps = constraints, AI = creativity**

1. Map metadata provides mechanical bounds (tier, modifiers, theme)
2. AI generates coherent content within those bounds
3. Modifiers are mechanical reality, not suggestions
4. AI adds narrative flavor around mechanical constraints
