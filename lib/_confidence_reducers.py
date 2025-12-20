#!/usr/bin/env python3
"""
Confidence Reducers - Backward compatibility shim.

This file re-exports from lib/reducers/ package for backward compatibility.
All reducers have been modularized into category-based files:

  lib/reducers/
  ├── _base.py          # ConfidenceReducer base class + IMPACT_* constants
  ├── _core.py          # Tool failures, cascades, sunk cost, goal drift
  ├── _behavioral.py    # Bad patterns (backup files, deferral, sycophancy)
  ├── _efficiency.py    # Sequential ops, verbose output, token waste
  ├── _verification.py  # Unbacked claims, test coverage
  ├── _code_quality.py  # Placeholder impl, silent failures, AST checks
  ├── _language.py      # Hedging, phantom progress, question avoidance
  ├── _framework.py     # Tool preferences (crawl4ai > WebFetch)
  ├── _stuck.py         # Stuck loops, no-research debugging
  └── _mastermind.py    # Drift detection for blueprint execution

New code should import from lib.reducers directly:
    from lib.reducers import REDUCERS, ConfidenceReducer
"""

# Re-export everything from the new package
from reducers import (
    # Base
    ConfidenceReducer,
    IMPACT_FAILURE,
    IMPACT_BEHAVIORAL,
    IMPACT_AMBIENT,
    # Aggregate list
    REDUCERS,
    # Core
    ToolFailureReducer,
    CascadeBlockReducer,
    SunkCostReducer,
    UserCorrectionReducer,
    EditOscillationReducer,
    ContradictionReducer,
    FollowUpQuestionReducer,
    # Behavioral
    BackupFileReducer,
    VersionFileReducer,
    MarkdownCreationReducer,
    OverconfidentCompletionReducer,
    DeferralReducer,
    ApologeticReducer,
    SycophancyReducer,
    UnresolvedAntiPatternReducer,
    SpottedIgnoredReducer,
    DebtBashReducer,
    LargeDiffReducer,
    # Efficiency
    SequentialRepetitionReducer,
    SequentialWhenParallelReducer,
    RereadUnchangedReducer,
    VerbosePreambleReducer,
    HugeOutputDumpReducer,
    RedundantExplanationReducer,
    TrivialQuestionReducer,
    ObviousNextStepsReducer,
    SequentialFileOpsReducer,
    # Verification
    UnbackedVerificationClaimReducer,
    FixedWithoutChainReducer,
    GitSpamReducer,
    UnverifiedEditsReducer,
    TestIgnoredReducer,
    ChangeWithoutTestReducer,
    TestsExistNotRunReducer,
    OrphanedTestCreationReducer,
    PreCommitNoTestsReducer,
    # Code quality
    PlaceholderImplReducer,
    SilentFailureReducer,
    HallmarkPhraseReducer,
    ScopeCreepReducer,
    IncompleteRefactorReducer,
    DeepNestingReducer,
    LongFunctionReducer,
    MutableDefaultArgReducer,
    ImportStarReducer,
    BareRaiseReducer,
    CommentedCodeReducer,
    PathHardcodingReducer,
    MagicNumbersReducer,
    EmptyTestReducer,
    OrphanedImportsReducer,
    # Language
    HedgingLanguageReducer,
    PhantomProgressReducer,
    QuestionAvoidanceReducer,
    DebugLoopNoPalReducer,
    # Framework
    WebFetchOverCrawlReducer,
    WebSearchBasicReducer,
    TodoWriteBypassReducer,
    RawSymbolHuntReducer,
    ComplexBashChainReducer,
    BashDataTransformReducer,
    # Stuck
    StuckLoopReducer,
    NoResearchDebugReducer,
    # Mastermind
    MastermindFileDriftReducer,
    MastermindTestDriftReducer,
    MastermindApproachDriftReducer,
)

__all__ = [
    # Base
    "ConfidenceReducer",
    "IMPACT_FAILURE",
    "IMPACT_BEHAVIORAL",
    "IMPACT_AMBIENT",
    # Aggregate list
    "REDUCERS",
    # Core
    "ToolFailureReducer",
    "CascadeBlockReducer",
    "SunkCostReducer",
    "UserCorrectionReducer",
    "EditOscillationReducer",
    "ContradictionReducer",
    "FollowUpQuestionReducer",
    # Behavioral
    "BackupFileReducer",
    "VersionFileReducer",
    "MarkdownCreationReducer",
    "OverconfidentCompletionReducer",
    "DeferralReducer",
    "ApologeticReducer",
    "SycophancyReducer",
    "UnresolvedAntiPatternReducer",
    "SpottedIgnoredReducer",
    "DebtBashReducer",
    "LargeDiffReducer",
    # Efficiency
    "SequentialRepetitionReducer",
    "SequentialWhenParallelReducer",
    "RereadUnchangedReducer",
    "VerbosePreambleReducer",
    "HugeOutputDumpReducer",
    "RedundantExplanationReducer",
    "TrivialQuestionReducer",
    "ObviousNextStepsReducer",
    "SequentialFileOpsReducer",
    # Verification
    "UnbackedVerificationClaimReducer",
    "FixedWithoutChainReducer",
    "GitSpamReducer",
    "UnverifiedEditsReducer",
    "TestIgnoredReducer",
    "ChangeWithoutTestReducer",
    "TestsExistNotRunReducer",
    "OrphanedTestCreationReducer",
    "PreCommitNoTestsReducer",
    # Code quality
    "PlaceholderImplReducer",
    "SilentFailureReducer",
    "HallmarkPhraseReducer",
    "ScopeCreepReducer",
    "IncompleteRefactorReducer",
    "DeepNestingReducer",
    "LongFunctionReducer",
    "MutableDefaultArgReducer",
    "ImportStarReducer",
    "BareRaiseReducer",
    "CommentedCodeReducer",
    "PathHardcodingReducer",
    "MagicNumbersReducer",
    "EmptyTestReducer",
    "OrphanedImportsReducer",
    # Language
    "HedgingLanguageReducer",
    "PhantomProgressReducer",
    "QuestionAvoidanceReducer",
    "DebugLoopNoPalReducer",
    # Framework
    "WebFetchOverCrawlReducer",
    "WebSearchBasicReducer",
    "TodoWriteBypassReducer",
    "RawSymbolHuntReducer",
    "ComplexBashChainReducer",
    "BashDataTransformReducer",
    # Stuck
    "StuckLoopReducer",
    "NoResearchDebugReducer",
    # Mastermind
    "MastermindFileDriftReducer",
    "MastermindTestDriftReducer",
    "MastermindApproachDriftReducer",
]
