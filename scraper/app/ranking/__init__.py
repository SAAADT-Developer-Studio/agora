"""Public contracts and ranking components with source-independent authority."""

from app.ranking.engine import (
    ArticleStrengthConfig,
    ArticleStrengthResult,
    ClusterRankingConfig,
    ClusterRankingExplanation,
    PublisherArticleStrength,
    WeightedRankingTerm,
    explain_cluster_ranking,
    rank_cluster,
)

from app.ranking.cluster_confidence import (
    ClusterConfidenceConfig,
    ClusterConfidenceResult,
    ConfidenceReport,
    apply_confidence_gate,
    finalize_ranking,
    score_cluster_confidence,
)

from app.ranking.newsworthiness import (
    NewsworthinessConfig,
    NewsworthinessReport,
    NewsworthinessResult,
    normalize_llm_importance,
    score_newsworthiness,
)

from app.ranking.momentum import (
    ArticleMomentumDecision,
    MomentumConfig,
    MomentumResult,
    MomentumWindow,
    score_momentum,
)

from app.ranking.freshness import (
    ArticleFreshnessDecision,
    FreshnessConfig,
    FreshnessResult,
    score_freshness,
)

from app.ranking.manual_authority import ManualAuthorityProvider, normalize_manual_authority
from app.ranking.publisher_authority import (
    PublisherAuthority,
    PublisherAuthorityConfig,
    PublisherAuthorityResult,
    score_publisher_authority,
    with_publisher_authority,
)

from app.ranking.coverage import (
    CoverageBasis,
    CoverageConfig,
    CoverageResult,
    PublisherCoverage,
    score_coverage,
)

from app.ranking.syndication import (
    ArticleSyndication,
    SyndicatedFamily,
    SyndicationConfig,
    SyndicationResult,
    SyndicationStatus,
    detect_syndication,
)

from app.ranking.article_contribution import (
    ArticleContribution,
    ArticleContributionConfig,
    ArticleContributionResult,
    score_article_contribution,
)

from app.ranking.contracts import (
    ClusterNewsworthiness,
    PublisherAuthorityProvider,
    RankableArticle,
    RankableCluster,
    RankingComponentScores,
    RankingConfig,
    RankingFunction,
    RankingResult,
)

__all__ = [
    "ArticleStrengthConfig",
    "ArticleStrengthResult",
    "ClusterRankingConfig",
    "ClusterRankingExplanation",
    "PublisherArticleStrength",
    "WeightedRankingTerm",
    "explain_cluster_ranking",
    "rank_cluster",
    "ClusterConfidenceConfig",
    "ClusterConfidenceResult",
    "ConfidenceReport",
    "apply_confidence_gate",
    "finalize_ranking",
    "score_cluster_confidence",
    "ClusterNewsworthiness",
    "NewsworthinessConfig",
    "NewsworthinessReport",
    "NewsworthinessResult",
    "normalize_llm_importance",
    "score_newsworthiness",
    "ArticleMomentumDecision",
    "MomentumConfig",
    "MomentumResult",
    "MomentumWindow",
    "score_momentum",
    "ArticleFreshnessDecision",
    "FreshnessConfig",
    "FreshnessResult",
    "score_freshness",
    "ManualAuthorityProvider",
    "normalize_manual_authority",
    "PublisherAuthority",
    "PublisherAuthorityConfig",
    "PublisherAuthorityProvider",
    "PublisherAuthorityResult",
    "score_publisher_authority",
    "with_publisher_authority",
    "CoverageBasis",
    "CoverageConfig",
    "CoverageResult",
    "PublisherCoverage",
    "score_coverage",
    "ArticleSyndication",
    "SyndicatedFamily",
    "SyndicationConfig",
    "SyndicationResult",
    "SyndicationStatus",
    "detect_syndication",
    "ArticleContribution",
    "ArticleContributionConfig",
    "ArticleContributionResult",
    "score_article_contribution",
    "RankableArticle",
    "RankableCluster",
    "RankingComponentScores",
    "RankingConfig",
    "RankingFunction",
    "RankingResult",
]
