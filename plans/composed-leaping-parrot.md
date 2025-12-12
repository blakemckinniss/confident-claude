# Plan: Foresight System - Outcome Visibility as Game Mechanic

## Design Vision
Outcome visibility is **earned through gameplay**, not given for free. Players start blind, but skills, effects, races, and items progressively reveal what will happen.

---

## Foresight Sources (Thematic Hierarchy)

### 1. Passive (Always-On)
| Source | Type | Reveals |
|--------|------|---------|
| Elf "Keen Senses" | Racial | Trap damage/effects (extend existing) |
| High Perception (15+) | Skill | Environmental interaction risk level |
| High Arcana (15+) | Skill | Magical effect types on shrines |
| High Wisdom (15+) | Skill | NPC true intentions |

### 2. Active Abilities (New)
| Class | Ability | Level | Reveals | Cooldown |
|-------|---------|-------|---------|----------|
| Ranger | "Hunt's Instinct" | 3 | Enemy next ability + damage range | 3 turns |
| Rogue | "Trap Sense" | 3 | Full trap mechanics + disarm bonus | 4 turns |
| Mage | "Arcane Analysis" | 4 | All magical effects in room | 5 turns |
| Cleric | "Divine Insight" | 4 | Shrine outcomes (blessing & curse) | 5 turns |

### 3. Status Effects (Temporary)
| Effect | Source | Duration | Reveals |
|--------|--------|----------|---------|
| "Prophetic Vision" | Shrine blessing | 10 turns | All outcomes at risk level |
| "Third Eye" | Rare consumable | 5 turns | Enemy ability + trap damage |
| "Foresight" | Spell (Mage) | 3 turns | Full outcome transparency |

### 4. Items
| Item | Type | Reveals |
|------|------|---------|
| "Seer's Draught" | Consumable | Grants Third Eye effect |
| "Oracle's Amulet" | Trinket (rare) | Passive trap foresight |
| "Tome of Futures" | Quest item | +5 Perception for outcome checks |

---

## Reveal Levels (What Player Sees)

```
HIDDEN (default)     → "???"
RISK ONLY            → "Risky" / border color
TYPE REVEALED        → "Damage: ???" or "May grant buff"
PARTIAL REVEALED     → "Damage: 10-20" or "Buff: attack related"
FULL REVEALED        → "Damage: 15, applies Burning for 3 turns"
```

---

## Implementation Phases

### Phase 1: Core Infrastructure
**Files to modify:**
- `src/lib/core/game-types.ts` - Add foresight types
- `src/lib/mechanics/game-mechanics-ledger.ts` - Add FORESIGHT_SOURCES registry

```typescript
// New types
type ForesightLevel = 'hidden' | 'risk' | 'type' | 'partial' | 'full'
type ForesightSource = 'perception' | 'arcana' | 'wisdom' | 'racial' | 'ability' | 'effect' | 'item'

interface ForesightResult {
  level: ForesightLevel
  source: ForesightSource
  revealedImpacts?: EntityImpact[]
  outcomeHint?: string
}

// Extend GameChoice
interface GameChoice {
  // ... existing fields
  foresight?: ForesightResult  // What player can see about this choice
}
```

### Phase 2: Foresight Calculator
**New file:** `src/lib/mechanics/foresight-system.ts`

```typescript
function calculateForesight(
  player: Player,
  choiceType: 'environmental' | 'combat' | 'trap' | 'shrine' | 'npc',
  entityTags: string[],
  action: string
): ForesightResult

// Checks in order:
// 1. Active foresight effects on player (highest priority)
// 2. Racial passive abilities (Elf Keen Senses)
// 3. Skill checks against difficulty (Perception vs trap DC)
// 4. Item bonuses
// Returns combined foresight level
```

### Phase 3: Extend Elf Racial
**File:** `src/lib/character/race-system.ts`

Update Elf "Keen Senses":
- Current: "Traps are revealed before triggering"
- New: Also reveals trap damage + effects (foresight level: 'full' for traps)

### Phase 4: Add Class Abilities
**File:** `src/lib/character/ability-system.ts`

Add 4 new foresight abilities (Ranger, Rogue, Mage, Cleric)
- Toggle-based or cooldown-based
- Sets a temporary foresight effect

### Phase 5: UI Components
**File:** `src/components/narrative/choice-buttons.tsx`

Add foresight-aware rendering:
- Hidden: Show "???" badge
- Risk: Border color (green/yellow/red)
- Type+: Show impact icons
- Full: Show outcome hint text

**New file:** `src/components/narrative/foresight-indicator.tsx`
- Visual component for foresight level
- Shows eye icon with fill based on level

### Phase 6: Wire All Choice Types
Progressive rollout:
1. Environmental interactions (tags available)
2. Trap encounters (damage/effect already in data)
3. Shrine interactions (blessing/curse outcomes)
4. Combat (enemy next ability)
5. NPC choices (true intentions)

---

## Critical Files

| File | Purpose |
|------|---------|
| `src/lib/core/game-types.ts` | ForesightLevel, ForesightResult types |
| `src/lib/mechanics/foresight-system.ts` | **NEW** - Foresight calculator |
| `src/lib/mechanics/game-mechanics-ledger.ts` | FORESIGHT_SOURCES registry |
| `src/lib/character/race-system.ts` | Extend Elf Keen Senses |
| `src/lib/character/ability-system.ts` | Add class foresight abilities |
| `src/lib/combat/effect-system.ts` | Add foresight effect type |
| `src/components/narrative/choice-buttons.tsx` | Foresight-aware UI |
| `src/components/narrative/foresight-indicator.tsx` | **NEW** - Visual indicator |

## Dependencies (Already Exist)
- ENTITY_IMPACTS array
- getPossibleImpacts() function
- Skill check system (skill-check.ts)
- Effect system (effect-system.ts)
- Elf Keen Senses racial (race-system.ts)

## Success Criteria
1. Default choices show "???" or just risk level
2. Elf racial reveals full trap outcomes
3. Using foresight ability reveals appropriate outcomes
4. Foresight effects (potions, spells) grant temporary visibility
5. High skill characters have baseline foresight chance
6. AI-generated outcomes respect foresight constraints
