# Pandemonium - Project Plan

## Overview
"Slay the Spire" inspired roguelike card game with unique mechanics:
- **Player cards** (heroes) and **enemies** are cards in the field
- **Dungeon Deck** replaces map pathing (pick 1 of 3 rooms)
- **4 unified card types**: Player, Hand, Enemy, Room
- **Core mechanic**: Drag hand cards onto targets for effects

## Tech Stack
| Layer | Choice |
|-------|--------|
| Framework | React 18 + TypeScript |
| Bundler | Vite |
| Animation | GSAP + Draggable + Flip |
| State (combat) | useState + Immer ActionManager |
| State (meta) | Zustand |
| Persistence | Dexie (IndexedDB) |
| Styling | Tailwind v4 |

## Project Structure
```
/home/jinx/projects/pandemonium/
├── src/
│   ├── types/index.ts              # All interfaces
│   ├── game/
│   │   ├── actions.ts              # State mutations (Immer)
│   │   ├── action-manager.ts       # Queue + dequeue
│   │   ├── cards.ts                # Card registry
│   │   └── new-game.ts             # Game factory
│   ├── content/
│   │   ├── cards/                  # Card definitions
│   │   ├── monsters.ts
│   │   └── heroes.ts
│   ├── components/
│   │   ├── Card/Card.tsx           # Unified (4 variants)
│   │   ├── Hand/Hand.tsx
│   │   ├── Field/Field.tsx
│   │   ├── DungeonDeck/DungeonDeck.tsx
│   │   ├── CombatNumbers/CombatNumbers.tsx
│   │   └── screens/GameScreen.tsx
│   ├── lib/
│   │   ├── animations.ts           # GSAP effects
│   │   └── dragdrop.ts             # Draggable wrapper
│   └── stores/
│       ├── metaStore.ts            # Zustand
│       └── db.ts                   # Dexie
```

## Game Design Decisions
| Aspect | Choice |
|--------|--------|
| Heroes | Start with 1, unlock more (flexible party) |
| Energy | Pool per turn (StS style: 3/turn) |
| Deck size | 40 cards, draw 5/turn |
| Room selection | Pick 1 of 3 from Dungeon Deck |
| Room types | Combat only (MVP) |
| Progression | Meta progression (unlock cards/heroes) |
| Platform | Desktop web first |

## Approach
**Build fresh** - Clean slate implementation using proven patterns (not copying Pandora code).

## Implementation Phases

### Phase 1: MVP Core
1. Vite + React + TS scaffold
2. `src/types/index.ts` - all interfaces
3. `src/game/actions.ts` - core mutations
4. `src/game/action-manager.ts` - queue system
5. `src/components/Card/Card.tsx` - hand variant
6. `src/components/Hand/Hand.tsx` - static layout
7. `src/components/screens/GameScreen.tsx` - click-to-play MVP
8. Hardcoded enemy, win/lose detection

### Phase 2: Polish Combat
9. `src/lib/animations.ts` - GSAP effects (dealCards, playCard, discardHand)
10. `src/lib/dragdrop.ts` - Draggable integration
11. `src/components/Field/Field.tsx` - player + enemies
12. Card variants (player, enemy, room) + HealthBar
13. `src/components/CombatNumbers/CombatNumbers.tsx` - floating numbers
14. Enemy intent system

### Phase 3: Dungeon Loop
15. Dungeon deck system (draw 3 rooms, pick 1)
16. `src/components/DungeonDeck/DungeonDeck.tsx`
17. Room progression (normal → elite → boss)
18. Card reward screen

### Phase 4: Meta Progression
19. `src/stores/metaStore.ts` - Zustand for unlocks
20. `src/stores/db.ts` - Dexie for run saves
21. Menu screens (main, collection)
22. Run history tracking

### Phase 5: Content & Polish
23. 20+ cards
24. 5+ monsters + 1 boss
25. Sound effects
26. Second hero
27. Card upgrades

## Key Patterns

### Unified Card Component
```tsx
<Card variant="hand" name="Strike" energy={1} description="Deal 6 damage" />
<Card variant="player" name="Warrior" currentHealth={50} maxHealth={50} />
<Card variant="enemy" name="Slime" currentHealth={12} maxHealth={12} intent="attack" />
<Card variant="room" icon="sword" difficulty="normal" />
```

### GSAP Drag-to-Target
```ts
Draggable.create(".Hand .Card", {
  onDrag() { highlight valid targets via hitTest },
  onRelease() {
    if (hitTest target) playCard(cardId, targetId)
    else snapBack()
  }
})
```

### Combat Numbers
Float up from target with GSAP:
- Red for damage
- Green for healing
- Blue for block

## Dependencies
```json
{
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "gsap": "^3.13.0",
    "immer": "^10.1.3",
    "zustand": "^5.0.0",
    "dexie": "^4.0.0"
  }
}
```
