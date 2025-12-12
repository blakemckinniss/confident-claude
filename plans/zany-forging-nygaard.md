# Situational Capability-to-Choice Integration

## Goal
Enable dungeon choices to dynamically integrate with player capabilities (spells, items, abilities):
- Dark room + "Revealing Light" spell → "Light room with Revealing Light" choice
- Dark room + Torch item → "Light torch" choice
- Dead corpse + "Raise Dead" spell → Cast option
- Locked door + "Knock" spell OR lockpicks → Multiple bypass options
- Always-on spells like "Teleport" get dedicated UI section

## Design Decisions
1. **Hybrid UI**: Always-available spells (Teleport, etc.) → dedicated utility bar. Situational spells → appear in choice buttons.
2. **Unified System**: Generic "player capability" abstraction covering spells + items + abilities.

## Architecture Overview

The spell system already has perfect metadata:
- `usageContext`: `"exploration" | "anytime" | "targeted"` (vs `"combat_only"`)
- `utilityEffect.type`: `"light" | "unlock" | "reveal_traps" | "identify" | ...`
- `targetType`: `"environment" | "item" | "npc" | "location"`

Items have:
- `subType`: "torch", "lockpick", "key", etc.
- `effects`: potential trigger effects

Abilities have:
- `usageContext`: similar to spells

The gap: **No unified bridge between player capabilities and AI/choice generation.**

---

## Implementation Plan

### Phase 1: Unified Capability Extraction
**File:** `src/lib/mechanics/player-capabilities.ts` (new)

Create unified system to extract all player capabilities:

```typescript
type CapabilitySource = "spell" | "item" | "ability" | "innate"

interface PlayerCapability {
  id: string
  name: string
  source: CapabilitySource
  sourceId: string  // spell.id, item.id, ability.id

  // What it can do
  utilityType?: SpellUtilityType  // "light", "unlock", etc.
  targetType: "self" | "item" | "environment" | "npc" | "enemy"

  // Availability
  available: boolean  // Resources, cooldown, charges
  reason?: string     // Why unavailable

  // Cost (if any)
  cost?: { type: "mana" | "health" | "charges" | "consumable"; amount: number }

  // UI category
  category: "always" | "situational"  // Always-on vs contextual
}

interface PlayerCapabilities {
  // Always-available (Teleport, etc.) - for dedicated UI bar
  always: PlayerCapability[]

  // Situational (context-dependent) - for choice buttons
  situational: PlayerCapability[]

  // Utility types available across all sources
  utilityTypes: SpellUtilityType[]

  // Summary for AI prompt
  summary: string
}

function extractPlayerCapabilities(player: Player): PlayerCapabilities
```

**Capability Sources:**
- **Spells**: `usageContext !== "combat_only"` + `utilityEffect.type`
- **Items**: Torches (light), lockpicks (unlock), keys (unlock specific), rope (traverse)
- **Abilities**: Class abilities with exploration use (e.g., Rogue's trap sense)

### Phase 2: AI Context Enhancement
**File:** `src/app/api/event-chain/route.ts`

Add capability context to the AI prompt (lines 260-266):

```typescript
PLAYER CONTEXT:
- Inventory: ${context.playerInventory || "basic gear"}
- Class: ${context.playerClass || "adventurer"}
// ... existing ...

PLAYER CAPABILITIES (non-combat):
- Utility types: ${capabilities.utilityTypes.join(", ")}
- Available now: ${capabilities.summary}
- Light sources: ${capabilities.situational.filter(c => c.utilityType === "light").map(c => c.name).join(", ") || "none"}
- Can unlock: ${capabilities.situational.some(c => c.utilityType === "unlock")}

CAPABILITY INTEGRATION:
Generate situations where player capabilities could help:
- "light" capability → dark areas, pits, obscured passages
- "unlock" capability → locked doors, sealed chests, magical barriers
- "reveal_traps/reveal_secrets" → suspicious areas, hidden compartments
- "transmute" → material puzzles, cursed objects, blocked paths
```

### Phase 3: Capability-Aware Interaction Schema
**File:** `src/lib/ai/ai-schemas.ts`

Add optional capability hints to room event schema:

```typescript
// Add to environmentalEntitySchema
capabilityRelevance: z.object({
  utilityType: z.enum([...SpellUtilityTypes]).nullish(),
  itemTag: z.string().nullish(),  // "torch", "lockpick", "rope"
  description: z.string().nullish(),
}).nullish().describe("If a player capability could interact with this entity")

// Add to roomEventSchema
capabilityOpportunities: z.array(z.object({
  situation: z.string(),
  utilityTypes: z.array(z.string()),  // What would help
  outcomeHint: z.string(),
})).nullish().describe("Situations where player capabilities could help")
```

### Phase 4: Choice Generation with Capability Integration
**File:** `src/lib/world/environmental-system.ts`

Extend `getInteractionsForEntity()` to include capability-based options:

```typescript
function getCapabilityInteractionsForEntity(
  entity: EnvironmentalEntity,
  capabilities: PlayerCapabilities
): EnvironmentalInteraction[] {
  const interactions: EnvironmentalInteraction[] = []

  // Match entity tags/class to player capabilities
  const matchingCaps = matchCapabilitiesToSituation(entity, capabilities.situational)

  for (const cap of matchingCaps) {
    interactions.push({
      id: `cap_${cap.id}`,
      action: cap.source === "spell" ? "cast_spell" : cap.source === "item" ? "use_item" : "use_ability",
      label: cap.source === "spell" ? `Cast ${cap.name}` : `Use ${cap.name}`,
      requiresCapability: cap.id,
      dangerLevel: "safe",
      hint: cap.outcomeHint,
      disabled: !cap.available,
      disabledReason: cap.reason,
    })
  }

  return interactions
}

// Matching logic
function matchCapabilitiesToSituation(
  entity: EnvironmentalEntity,
  capabilities: PlayerCapability[]
): PlayerCapability[] {
  const matches: PlayerCapability[] = []

  // Dark room/area → light capabilities
  if (entity.interactionTags?.includes("dark") || entity.description?.includes("dark")) {
    matches.push(...capabilities.filter(c => c.utilityType === "light"))
  }

  // Locked → unlock capabilities
  if (entity.interactionTags?.includes("locked") || entity.entityClass === "mechanism") {
    matches.push(...capabilities.filter(c => c.utilityType === "unlock"))
  }

  // etc for other utility types
  return matches
}
```

### Phase 5: Capability Execution in Environmental Context
**File:** `src/components/core/dungeon-game.tsx` → `handleEnvironmentalInteraction`

Add capability execution paths:

```typescript
case "cast_spell": {
  const spell = player.spellBook.spells.find(s => s.id === interaction.requiresCapability)
  if (!spell) break

  const result = castSpell(spell, {
    inCombat: false,
    player,
    spellBook: player.spellBook,
    target: { type: "environment", entity: entity },
    room: { /* current room context */ }
  })
  // Apply result, update UI, consume resources
  break
}

case "use_item": {
  const item = player.inventory.find(i => i.id === interaction.requiresCapability)
  if (!item) break

  // Consume if consumable (torch, lockpick may break)
  // Apply effect to room/entity
  break
}

case "use_ability": {
  const ability = player.abilities.find(a => a.id === interaction.requiresCapability)
  if (!ability) break

  // Execute ability in exploration context
  break
}
```

### Phase 6: Utility Bar UI for Always-On Capabilities
**File:** `src/components/world/utility-bar.tsx` (new)

Create dedicated UI for always-available capabilities (Teleport, etc.):

```typescript
interface UtilityBarProps {
  capabilities: PlayerCapability[]  // The "always" category
  onUse: (capability: PlayerCapability) => void
}

export function UtilityBar({ capabilities, onUse }: UtilityBarProps) {
  return (
    <div className="flex gap-2 p-2 border-t border-stone-700">
      {capabilities.map(cap => (
        <button
          key={cap.id}
          onClick={() => onUse(cap)}
          disabled={!cap.available}
          className="px-3 py-1 bg-stone-800 hover:bg-stone-700 rounded text-sm"
          title={cap.available ? cap.name : cap.reason}
        >
          {cap.name}
        </button>
      ))}
    </div>
  )
}
```

Place in dungeon-game.tsx below path choices or in sidebar.

---

## Files to Modify

### New Files
1. `src/lib/mechanics/player-capabilities.ts` - Unified capability extraction system
2. `src/components/world/utility-bar.tsx` - Always-on capability UI bar

### Modified Files
1. `src/app/api/event-chain/route.ts` (lines 260-270) - Add capability context to AI prompt
2. `src/lib/ai/ai-schemas.ts` - Add capability relevance fields to schemas
3. `src/lib/world/environmental-system.ts` - Add capability-based interactions
4. `src/components/core/dungeon-game.tsx` (handleEnvironmentalInteraction) - Add capability execution
5. `src/lib/core/game-types.ts` - Add `requiresCapability` to EnvironmentalInteraction

---

## Capability-to-Situation Mapping

| Utility Type | Triggers For | Sources |
|--------------|--------------|---------|
| `light` | Dark rooms, deep pits, obscured areas | Spell, Torch item |
| `unlock` | Locked doors, sealed chests, magical barriers | Spell, Lockpick item, Key item |
| `reveal_traps` | Suspicious corridors, trapped areas | Spell, Rogue ability |
| `reveal_secrets` | Hidden passages, secret compartments | Spell |
| `identify` | Unknown items, magical inscriptions | Spell |
| `charm` | Hostile NPCs, guard encounters | Spell |
| `transmute_item` | Cursed items, material puzzles | Spell |
| `teleport` | **Always-on** (utility bar) | Spell |
| `dispel` | Magical barriers, enchanted locks | Spell |
| `ward_area` | Hazardous rooms, ambient damage areas | Spell |
| `traverse` | Gaps, chasms, vertical climbs | Rope item |

---

## Validation Requirements

1. Only show capability choices if:
   - **Spells**: `usageContext !== "combat_only"`, has resources, not on cooldown
   - **Items**: Item exists in inventory, has charges (if applicable)
   - **Abilities**: Off cooldown, resources available

2. Resource/item consumption happens on use

3. AI receives updated capability availability each room (cooldowns/charges change)

---

## Resolved Design Decisions

1. **Capability format for AI**: Names + utility types only (token efficient)
2. **Always-on vs situational**: Hybrid - dedicated utility bar for always-on, choice buttons for situational
3. **Failure handling**: Validation layer filters AI suggestions against actual capabilities
4. **Unified system**: Single abstraction covers spells + items + abilities
