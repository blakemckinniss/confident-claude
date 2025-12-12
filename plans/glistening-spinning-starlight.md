# Entity System Architecture Plan

## Goal
Convert Pantheon to an entity-based architecture to support:
- Party/hero system
- Map/dungeon system
- AI content generation
- Complex effect targeting

## Current State Analysis

**Existing data structures:**
- `SpellDef` + `SpellState` - split definition/runtime
- `Monster` - generated ad-hoc, no templates
- `Weapon/Armor/Chest/Crystal` - typed union, generated inline
- `UpgradeDef` - static array, effects hardcoded in hook
- `BuffState` - mix of temporary and permanent effects

**Key insight:** Already have definition/state split for spells. Extend this pattern.

---

## Phase 1: Core Entity System

### 1.1 Create Entity Types (`src/entities/types.ts`)

```typescript
// Base entity - all game objects inherit from this
interface BaseEntity {
  id: string
  type: EntityType
  name: string
  description?: string
  tags?: string[]  // AI filtering: ['fire', 'healing', 'tier1']
}

type EntityType = 'spell' | 'upgrade' | 'monster' | 'item' | 'hero' | 'room'

// Spell definition
interface SpellEntity extends BaseEntity {
  type: 'spell'
  category: 'healing' | 'damage' | 'debuff' | 'utility'
  requiredMagic: number
  arcaniaCost: number
  baseMana: number
  baseNextLevel: number
  effects: Effect[]
}

// Upgrade definition
interface UpgradeEntity extends BaseEntity {
  type: 'upgrade'
  exceliaCost: number
  required?: string  // prerequisite upgrade ID
  effects: Effect[]
}

// Monster template (not instance)
interface MonsterEntity extends BaseEntity {
  type: 'monster'
  tier: number
  isBoss: boolean
  baseStats: { strength: number, dexterity: number, constitution: number }
  scaling: { stat: string, perFloor: number }[]
  lootTable?: { itemId?: string, gold?: [number, number], chance: number }[]
}

// Item template
interface ItemEntity extends BaseEntity {
  type: 'item'
  itemType: 'weapon' | 'armor' | 'consumable' | 'chest' | 'crystal'
  slot?: 'weapon' | 'armor'
  stats?: Partial<Record<'damage' | 'defense' | 'speed' | 'magic', number>>
  effects?: Effect[]
}

// Hero template (for party system - future)
interface HeroEntity extends BaseEntity {
  type: 'hero'
  class: string
  baseStats: { strength: number, dexterity: number, constitution: number, speed: number, magic: number }
  startingSkills: string[]
}

// Room template (for dungeon system - future)
interface RoomEntity extends BaseEntity {
  type: 'room'
  roomType: 'combat' | 'treasure' | 'rest' | 'boss' | 'event'
  difficulty: number
  encounters?: string[]  // monster entity IDs
}
```

### 1.2 Create Effect System (`src/entities/effects.ts`)

```typescript
interface Effect {
  trigger: EffectTrigger
  target: TargetSelector
  action: EffectAction
}

type EffectTrigger =
  | 'immediate'      // on cast/use
  | 'onHit'          // when damage dealt
  | 'onDamaged'      // when taking damage
  | 'onTurnStart'    // each combat turn
  | 'onExplore'      // each exploration tick
  | 'onRest'         // while resting
  | 'onDeath'        // when dying
  | 'passive'        // always active

type TargetSelector =
  | { type: 'self' }
  | { type: 'currentEnemy' }
  | { type: 'party' }           // future: all party members
  | { type: 'allEnemies' }
  | { type: 'byTag', tag: string }

type EffectAction =
  | { type: 'heal', value: number | Formula }
  | { type: 'damage', value: number | Formula, damageType?: string }
  | { type: 'modifyStat', stat: string, value: number, duration?: number }
  | { type: 'grantResource', resource: 'gold' | 'excelia' | 'arcania' | 'mana', value: number | Formula }
  | { type: 'applyBuff', buffId: string, duration: number }
  | { type: 'spawn', entityId: string }

// Formula for scaling effects
interface Formula {
  base: number
  scaling?: { stat: string, ratio: number }[]  // e.g., { stat: 'magic', ratio: 0.5 }
}
```

### 1.3 Create Entity Registry (`src/entities/registry.ts`)

```typescript
class EntityRegistry {
  private entities = new Map<string, BaseEntity>()

  register(entity: BaseEntity): void
  get<T extends BaseEntity>(id: string): T | undefined
  getAll<T extends BaseEntity>(type: EntityType): T[]
  getByTag(tag: string): BaseEntity[]

  // For AI generation
  getSchema(type: EntityType): object  // JSON Schema
  validate(entity: unknown): { valid: boolean, errors?: string[] }
}

// Global registry instance
export const registry = new EntityRegistry()
```

### 1.4 Convert Existing Data

**`src/entities/data/spells.ts`**
```typescript
export const SPELL_ENTITIES: SpellEntity[] = [
  {
    id: 'cure',
    type: 'spell',
    name: 'Cure',
    category: 'healing',
    tags: ['healing', 'basic'],
    requiredMagic: 5,
    arcaniaCost: 0,
    baseMana: 15,
    baseNextLevel: 150,
    effects: [
      { trigger: 'immediate', target: { type: 'self' }, action: { type: 'heal', value: { base: 20, scaling: [{ stat: 'magic', ratio: 2 }] } } }
    ]
  },
  // ... convert all spells
]
```

**`src/entities/data/upgrades.ts`**
```typescript
export const UPGRADE_ENTITIES: UpgradeEntity[] = [
  {
    id: 'aetheric1',
    type: 'upgrade',
    name: 'Aetheric Attunement 1',
    tags: ['mana', 'passive'],
    exceliaCost: 10,
    effects: [
      { trigger: 'onExplore', target: { type: 'self' }, action: { type: 'grantResource', resource: 'mana', value: 1 } }
    ]
  },
  // ... convert all upgrades
]
```

---

## Phase 2: Integration

### 2.1 Update GameState
- Keep existing `SpellState[]` for runtime tracking
- Add entity lookup: `registry.get<SpellEntity>(spellState.id)`
- No breaking changes to UI

### 2.2 Effect Executor
```typescript
function executeEffect(effect: Effect, source: GameState, context: EffectContext): GameState
```
- Replace hardcoded spell/upgrade logic with effect execution
- Gradual migration: start with new spells, convert existing

---

## Phase 3: Monster & Item Templates

### 3.1 Monster Entities
```typescript
const MONSTER_ENTITIES: MonsterEntity[] = [
  { id: 'slime', type: 'monster', name: 'Slime', tier: 1, isBoss: false, baseStats: { strength: 2, dexterity: 1, constitution: 3 }, ... },
  // Floor scaling via formula instead of inline generation
]
```

### 3.2 Item Entities
- Define base item templates
- Generation becomes: pick template + apply rarity modifiers

---

## Phase 4: Future Extensions

### 4.1 Hero/Party System
- `HeroEntity` defines character classes
- `PartyState` tracks active heroes
- Effects can target `{ type: 'party' }`

### 4.2 Dungeon/Map System
- `RoomEntity` defines room templates
- `DungeonState` tracks current map
- Rooms reference monster/loot entities by ID

### 4.3 AI Content Generation
- Export JSON schemas for each entity type
- AI generates valid entities following schema
- Registry validates before adding

---

## File Structure

```
src/
  entities/
    types.ts          # Entity interfaces
    effects.ts        # Effect system
    registry.ts       # Entity registry
    executor.ts       # Effect executor
    data/
      spells.ts       # Spell entities
      upgrades.ts     # Upgrade entities
      monsters.ts     # Monster entities
      items.ts        # Item entities
    index.ts          # Re-exports
```

---

## Migration Strategy

1. **Non-breaking:** Add entity system alongside existing code
2. **Gradual:** Convert one system at a time (spells → upgrades → monsters → items)
3. **Test each phase:** Game should work identically after each phase
4. **No UI changes** until entity system is stable

---

## Implementation Order

1. `src/entities/types.ts` - All entity interfaces
2. `src/entities/effects.ts` - Effect system types
3. `src/entities/registry.ts` - Registry class
4. `src/entities/data/spells.ts` - Convert SPELLS
5. `src/entities/data/upgrades.ts` - Convert UPGRADES
6. Update `useGameState.ts` to use registry lookups
7. `src/entities/executor.ts` - Effect execution (optional, can defer)
