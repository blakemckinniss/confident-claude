#!/usr/bin/env python3
"""
Confidence Reducers Package.

Modularized from the original lib/_confidence_reducers.py (3000+ lines).
Each category file contains related reducers for easier maintenance.

Categories:
- _core: Tool failures, cascades, sunk cost, user correction, goal drift
- _behavioral: Bad patterns (backup files, deferral, sycophancy, etc.)
- _efficiency: Sequential operations, verbose output, token waste
- _verification: Unbacked claims, test coverage, verification theater
- _code_quality: Placeholder impl, silent failures, AST checks
- _language: Hedging, phantom progress, question avoidance
- _framework: Tool preferences (crawl4ai > WebFetch, serena > grep)
- _stuck: Stuck loops, no-research debugging
- _mastermind: Drift detection for blueprint execution
"""

from ._base import (
    ConfidenceReducer,
    IMPACT_FAILURE,
    IMPACT_BEHAVIORAL,
    IMPACT_AMBIENT,
)

# Core reducers
from ._core import (
    ToolFailureReducer,
    CascadeBlockReducer,
    SunkCostReducer,
    UserCorrectionReducer,
    EditOscillationReducer,
    ContradictionReducer,
    FollowUpQuestionReducer,
)

# Behavioral reducers (bad patterns)
from ._behavioral import (
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
)

# Efficiency reducers (token/process waste)
from ._efficiency import (
    SequentialRepetitionReducer,
    SequentialWhenParallelReducer,
    RereadUnchangedReducer,
    VerbosePreambleReducer,
    HugeOutputDumpReducer,
    RedundantExplanationReducer,
    TrivialQuestionReducer,
    ObviousNextStepsReducer,
    SequentialFileOpsReducer,
)

# Verification reducers (claims without evidence)
from ._verification import (
    UnbackedVerificationClaimReducer,
    FixedWithoutChainReducer,
    GitSpamReducer,
    UnverifiedEditsReducer,
    TestIgnoredReducer,
    ChangeWithoutTestReducer,
    TestsExistNotRunReducer,
    OrphanedTestCreationReducer,
    PreCommitNoTestsReducer,
)

# Code quality reducers (AST-based and pattern checks)
from ._code_quality import (
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
)

# Language pattern reducers
from ._language import (
    HedgingLanguageReducer,
    PhantomProgressReducer,
    QuestionAvoidanceReducer,
    DebugLoopNoPalReducer,
)

# Framework alignment reducers
from ._framework import (
    WebFetchOverCrawlReducer,
    WebSearchBasicReducer,
    TodoWriteBypassReducer,
    RawSymbolHuntReducer,
    ComplexBashChainReducer,
    BashDataTransformReducer,
)

# Stuck loop reducers
from ._stuck import (
    StuckLoopReducer,
    NoResearchDebugReducer,
)

# Mastermind drift reducers
from ._mastermind import (
    MastermindFileDriftReducer,
    MastermindTestDriftReducer,
    MastermindApproachDriftReducer,
)


# Assemble the complete REDUCERS list (same order as original)
REDUCERS: list[ConfidenceReducer] = [
    # Core reducers
    ToolFailureReducer(),
    CascadeBlockReducer(),
    SunkCostReducer(),
    UserCorrectionReducer(),
    EditOscillationReducer(),
    ContradictionReducer(),
    FollowUpQuestionReducer(),
    # Bad behavior reducers
    BackupFileReducer(),
    VersionFileReducer(),
    MarkdownCreationReducer(),
    OverconfidentCompletionReducer(),
    DeferralReducer(),
    ApologeticReducer(),
    SycophancyReducer(),
    UnresolvedAntiPatternReducer(),
    SpottedIgnoredReducer(),
    DebtBashReducer(),
    LargeDiffReducer(),
    SequentialRepetitionReducer(),
    SequentialWhenParallelReducer(),
    # Verification theater reducers
    UnbackedVerificationClaimReducer(),
    FixedWithoutChainReducer(),
    GitSpamReducer(),
    # Time waster reducers
    RereadUnchangedReducer(),
    VerbosePreambleReducer(),
    HugeOutputDumpReducer(),
    RedundantExplanationReducer(),
    TrivialQuestionReducer(),
    ObviousNextStepsReducer(),
    # Code quality reducers
    PlaceholderImplReducer(),
    SilentFailureReducer(),
    HallmarkPhraseReducer(),
    ScopeCreepReducer(),
    IncompleteRefactorReducer(),
    # Test coverage reducers
    TestIgnoredReducer(),
    ChangeWithoutTestReducer(),
    # AST-based code quality reducers
    DeepNestingReducer(),
    LongFunctionReducer(),
    MutableDefaultArgReducer(),
    ImportStarReducer(),
    BareRaiseReducer(),
    CommentedCodeReducer(),
    # Verification bundling
    UnverifiedEditsReducer(),
    # Framework alignment reducers (v4.8)
    WebFetchOverCrawlReducer(),
    WebSearchBasicReducer(),
    TodoWriteBypassReducer(),
    RawSymbolHuntReducer(),
    SequentialFileOpsReducer(),
    # Stuck loop reducers (v4.9)
    StuckLoopReducer(),
    NoResearchDebugReducer(),
    # Mastermind drift reducers (v4.10)
    MastermindFileDriftReducer(),
    MastermindTestDriftReducer(),
    MastermindApproachDriftReducer(),
    # Scripting escape hatch reducers (v4.11)
    ComplexBashChainReducer(),
    BashDataTransformReducer(),
    # Coverage gap reducers (v4.18)
    PathHardcodingReducer(),
    MagicNumbersReducer(),
    EmptyTestReducer(),
    OrphanedImportsReducer(),
    HedgingLanguageReducer(),
    PhantomProgressReducer(),
    QuestionAvoidanceReducer(),
    # PAL maximization reducers (v4.19)
    DebugLoopNoPalReducer(),
    # Test enforcement reducers (v4.20)
    TestsExistNotRunReducer(),
    OrphanedTestCreationReducer(),
    PreCommitNoTestsReducer(),
]


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
