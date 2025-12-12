# Balance System: Entity Levels Matter

## User Decisions
- **Balance**: Floor-only scaling (enemies don't adjust to player level)
- **Companions**: No independent leveling (keep recruitment level)
- **UI**: Always visible ("Lv.X" on all entities)

## Problem Summary
- Enemies have NO level property - scale by floor multipliers only
- Level difference has ZERO impact on combat damage or XP
- Taming uses crude expReward/15 estimate instead of actual level

## Design

### 1. Level Constants (game-mechanics-ledger.ts)
```typescript
ENTITY_LEVEL_CONFIG = {
  levelsPerFloor: 2,
  rankBonus: { normal: 0, rare: 1, unique: 2, boss: 3, elite_boss: 5 },
  variance: 1
}

LEVEL_COMBAT_SCALING = {
  damagePerLevelAdvantage: 0.05,    // +5% per level above target
  damagePerLevelDisadvantage: 0.03, // -3% per level below target  
  maxBonus: 0.50, maxPenalty: 0.30
}

LEVEL_XP_SCALING = {
  xpPerLevelBelow: 0.10,      // -10% per level below player
  xpPerLevelAbove: 0.05,      // +5% per level above player
  minimum: 0.10, maximum: 1.50,
  grayThreshold: 5            // 5+ below = minimum XP
}
```

### 2. Level Formula
```
enemyLevel = 1 + (floor-1)*2 + rankBonus ± variance
```

Expected ranges:
| Floor | Normal | Rare | Boss |
|-------|--------|------|------|
| 1 | 1-2 | 2-3 | 4-5 |
| 3 | 5-6 | 6-7 | 8-9 |
| 5 | 9-10 | 10-11 | 12-13 |

### 3. Companion Level
- Tamed enemy: inherit enemy.level
- Rescued NPC: player.level - 1 (min 1)
- No subsequent leveling

---

## Implementation Order

### Phase 1: Core Types & Constants
1. **game-mechanics-ledger.ts** (~100 lines)
   - Add ENTITY_LEVEL_CONFIG, LEVEL_COMBAT_SCALING, LEVEL_XP_SCALING
   - Add calculateEntityLevel(), getLevelDamageModifier(), getXpModifier()
   - Add generateLevelSystemPrompt() for AI

2. **game-types.ts** (~5 lines)
   - Add `level: number` to Enemy interface
   - Ensure `stats.level: number` is required in Companion

### Phase 2: Entity Generation
3. **enemy-rank-system.ts** (~15 lines)
   - Import level config from ledger
   - Calculate and assign level in upgradeEnemyRank()

4. **game-data.ts** (~10 lines)
   - Add level to generateEnemy() using calculateEntityLevel()
   - Add level to boss generation

5. **entity-factory.ts** (~10 lines)
   - Add level to AI-generated enemies

### Phase 3: Combat Integration
6. **combat-system.ts** (~20 lines)
   - Integrate getLevelDamageModifier() into calculateDamageWithType()
   - Integrate into calculateIncomingDamage()

7. **companion-system.ts** (~15 lines)
   - Update createBasicCompanionFromEnemy() to inherit level
   - Update createBasicCompanionFromNPC() to calculate level
   - Replace expReward/15 estimate with actual level in canTameEnemy()

### Phase 4: XP & UI
8. **dungeon-game.tsx** (~20 lines)
   - Apply getXpModifier() to combat victory XP calculation
   - Add level display to enemy name in combat UI

---

## Files Summary
| File | Changes | Lines |
|------|---------|-------|
| game-mechanics-ledger.ts | New level system section | ~100 |
| game-types.ts | Add level to Enemy | ~5 |
| enemy-rank-system.ts | Calculate level | ~15 |
| game-data.ts | Assign level | ~10 |
| entity-factory.ts | AI enemy level | ~10 |
| combat-system.ts | Level damage mods | ~20 |
| companion-system.ts | Level inheritance | ~15 |
| dungeon-game.tsx | XP mods + UI | ~20 |

Total: ~195 lines of changes across 8 files
