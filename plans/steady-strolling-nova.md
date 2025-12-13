# Main Menu & Deck Builder

## Goal
Add main menu entry point and deck builder with dev card generation for testing.

## Features
1. **Main Menu** - Entry point with deck selection and start run
2. **Deck Builder** - Build custom decks from unlocked + generated cards
3. **Dev Mode** - Generate cards via LLM and add to custom decks for testing

## Architecture

**Current Flow:**
```
App.tsx → GameScreen → roomSelect (immediate)
```

**New Flow:**
```
App.tsx → MenuScreen ─┬─→ Start Run (with deck) → GameScreen
                      └─→ Deck Builder ─────────→ DeckBuilderScreen
```

## Implementation Phases

### Phase 1: Database Schema (CustomDecks)

**File:** `src/stores/db.ts`

Add `customDecks` table (version 3):
```typescript
interface CustomDeckRecord {
  id?: number
  deckId: string        // UUID
  name: string
  heroId: string
  cardIds: string[]     // CardDefinition IDs
  createdAt: Date
  updatedAt: Date
}
```

CRUD functions: `saveCustomDeck`, `getCustomDecks`, `getCustomDeckById`, `updateCustomDeck`, `deleteCustomDeck`

### Phase 2: Types

**File:** `src/types/index.ts`

```typescript
type AppScreen = 'menu' | 'deckBuilder' | 'game'
```

### Phase 3: App Routing

**File:** `src/App.tsx`

Add app-level screen state:
```typescript
const [currentScreen, setCurrentScreen] = useState<AppScreen>('menu')
const [selectedDeckId, setSelectedDeckId] = useState<string | null>(null)

// Route to MenuScreen | DeckBuilderScreen | GameScreen
```

### Phase 4: Menu Screen

**File:** `src/components/screens/MenuScreen.tsx` (NEW)

```
┌─────────────────────────────────────┐
│          PANDEMONIUM                │
│                                     │
│  Select Deck:                       │
│  [Starter] [Custom 1] [Custom 2]    │
│                                     │
│       [ START RUN ]                 │
│       [ DECK BUILDER ]              │
│                                     │
│  Runs: 5  |  Wins: 2  |  Best: F8   │
└─────────────────────────────────────┘
```

Props: `onStartRun(deckId)`, `onDeckBuilder()`

### Phase 5: Deck Builder Screen

**File:** `src/components/screens/DeckBuilderScreen.tsx` (NEW)

```
┌──────────────────┬──────────────────────────────────────┐
│ SAVED DECKS      │  [Unlocked] [Generated] [Dev Mode]   │
│ ───────────────  │  ────────────────────────────────    │
│ > Starter        │                                      │
│   Custom 1       │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐    │
│   Custom 2       │  │Card │ │Card │ │Card │ │Card │    │
│                  │  └─────┘ └─────┘ └─────┘ └─────┘    │
│ ───────────────  │                                      │
│ CURRENT DECK     │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐    │
│ (12 cards)       │  │Card │ │Card │ │Card │ │Card │    │
│ Strike x5        │  └─────┘ └─────┘ └─────┘ └─────┘    │
│ Defend x4        │                                      │
│ ...              │                                      │
│                  │                                      │
│ [Save] [Clear]   │                                      │
└──────────────────┴──────────────────────────────────────┘
```

**Tabs:**
- **Unlocked** - Cards from `metaStore.unlockedCards`
- **Generated** - Cards from `db.generatedCards` (IndexedDB)
- **Dev Mode** - LLM generation controls + preview

**Dev Mode Panel:**
- Theme selector (attack/skill/power)
- Rarity selector (common/uncommon/rare)
- Hint text input
- Generate button → calls `generateRandomCard(options)`
- Preview generated card
- Add to current deck

### Phase 6: Run Integration

**File:** `src/game/new-game.ts`

Modify `createNewRun`:
```typescript
function createNewRun(heroId: string, customCardIds?: string[]): RunState
// Use customCardIds if provided, else hero.starterDeck
```

**File:** `src/components/screens/GameScreen.tsx`

Add props:
```typescript
interface GameScreenProps {
  deckId?: string | null
  onReturnToMenu?: () => void
}
```

- Load custom deck on init if `deckId` provided
- Game over → return to menu instead of restart

## Files Summary

| File | Action |
|------|--------|
| `src/stores/db.ts` | Add customDecks table + CRUD |
| `src/types/index.ts` | Add AppScreen type |
| `src/App.tsx` | Add screen routing |
| `src/game/new-game.ts` | Add customCardIds param |
| `src/components/screens/MenuScreen.tsx` | Create |
| `src/components/screens/DeckBuilderScreen.tsx` | Create |
| `src/components/screens/GameScreen.tsx` | Add props |

## Implementation Order

1. `db.ts` - CustomDecks persistence (foundation)
2. `types/index.ts` - AppScreen type
3. `new-game.ts` - Custom deck support in createNewRun
4. `MenuScreen.tsx` - Basic menu with deck list
5. `App.tsx` - Wire up routing
6. `DeckBuilderScreen.tsx` - Build incrementally:
   - Unlocked cards tab
   - Generated cards tab
   - Dev mode panel
   - Save/load logic
7. `GameScreen.tsx` - Accept deckId prop, add menu return

## Dev Mode Details

Uses existing `generateRandomCard(options)` from `src/game/card-generator.ts`:
- Cards auto-persist to IndexedDB
- Cards auto-register in card registry
- Immediately available in Generated tab after generation
