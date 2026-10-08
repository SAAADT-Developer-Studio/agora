# Ranking engine and components (RANK-2 through RANK-10)

`rank_cluster(cluster, evaluated_at, config)` implements the complete pure ranking
function and returns the existing `RankingResult`. `explain_cluster_ranking()`
returns the same result together with every component, weighted term, gate, and
fallback decision. Scoring needs only one cluster snapshot, a supplied evaluation
time, and versioned configuration.

`score_article_contribution(cluster, evaluated_at, config)` calculates each
article's contribution to one event. It automatically detects families of shared
writing and limits their combined contribution. The result includes article
factors, syndication outcomes, family membership, a total, and a normalized
standalone `article_contribution_score`. The composed engine uses its quality and
source diagnostics instead of this age- and volume-adjusted total, avoiding
another reward for breadth and another application of age decay.

`score_coverage(cluster, evaluated_at, config)` separately measures how broadly
the event is independently covered, using at most one weighted contribution per
publisher. Its `coverage_score` supplies the coverage component of the later
event-ranking formula.

`score_publisher_authority(cluster, evaluated_at, config)` calculates the authority
component from normalized publisher values. `with_publisher_authority()` prepares
those values through a replaceable provider; `ManualAuthorityProvider` uses the
existing manual ranks. Ranking functions consume the same input fields regardless
of how authority was produced.

`score_freshness(cluster, evaluated_at, config)` decays the event from its latest
meaningful development, using a category-specific half-life. Copied reporting
and unverified new observations do not advance the event's meaningful-update clock.

`score_momentum(cluster, evaluated_at, config)` compares independently written
coverage in adjacent time windows. It measures publisher arrivals, new reporting,
velocity, and acceleration while limiting repeated posts by the same publisher.

`score_newsworthiness(cluster, evaluated_at, config)` aggregates existing article
LLM importance into the engine's `semantic_importance_score`. It combines the
strongest report with a few distinct reports, counting each publisher and shared
writing family at most once in the selected set.

`score_cluster_confidence(cluster, evaluated_at, config)` estimates whether the
reports describe a coherent event. `finalize_ranking()` applies this confidence
as a multiplicative gate when building a final `RankingResult`.

```python
from app.ranking import (
    ManualAuthorityProvider, RankingConfig, detect_syndication,
    score_article_contribution, score_coverage, score_freshness, score_publisher_authority,
    score_momentum, score_newsworthiness, score_cluster_confidence, with_publisher_authority,
    rank_cluster,
)

config = RankingConfig(
    version="ranking-v2",
    parameters={
        "ranking": {
            "article_contribution_weight": 1.0,
            "coverage_weight": 1.0,
            "momentum_weight": 1.0,
            "semantic_importance_weight": 1.0,
            "article_strength": {
                "authority_weight": 0.5,
                "data_quality_weight": 0.3,
                "source_weight": 0.2,
            },
        },
        "syndication": {
            "minimum_content_tokens": 50,
            "minimum_unique_shingles": 20,
            "similarity_threshold": 0.80,
        },
        "article_contribution": {
            "freshness_half_life_hours": 24,
            "publisher_repeat_decay": 0.5,
            "family_distribution_credit": 0.15,
            "family_distribution_decay": 0.5,
        },
        "coverage": {
            "normalization_scale": 5.0,
            "unknown_publisher_weight": 0.5,
            "syndicated_publisher_weight": 0.15,
            "family_distribution_credit": 0.15,
            "family_distribution_decay": 0.5,
        },
        "publisher_authority": {"unknown_authority": 0.5},
        "freshness": {
            "default_half_life_hours": 24.0,
            "minimum_novelty": 0.5,
            "minimum_new_text_fraction": 0.2,
        },
        "momentum": {
            "window_hours": 6.0,
            "new_publisher_weight": 0.5,
            "publisher_repeat_credit": 0.15,
            "publisher_repeat_decay": 0.5,
            "minimum_novelty": 0.5,
            "minimum_new_text_fraction": 0.2,
            "velocity_scale_per_hour": 0.5,
            "acceleration_weight": 0.4,
        },
        "newsworthiness": {
            "top_reports": 3,
            "strongest_weight": 0.5,
            "unknown_importance": 0.5,
            "cluster_score_weight": 1.0,
        },
        "cluster_confidence": {
            "outlier_similarity": 0.4,
            "weak_similarity": 0.75,
            "strong_similarity": 0.9,
            "outlier_membership": 0.2,
            "weak_membership": 0.5,
            "semantic_weight": 0.7,
            "unknown_similarity_score": 0.5,
            "unknown_membership_confidence": 0.5,
            "weak_relation_penalty": 0.5,
            "temporal_half_life_hours": 72.0,
            "temporal_penalty": 0.25,
            "gate_power": 1.0,
        },
    },
)
authority_provider = ManualAuthorityProvider()
prepared = with_publisher_authority(cluster, authority_provider)
ranked = rank_cluster(prepared, evaluated_at, config)

# Individual components remain available for standalone analysis:
result = score_article_contribution(prepared, evaluated_at, config)
coverage = score_coverage(prepared, evaluated_at, config)
authority = score_publisher_authority(prepared, evaluated_at, config)
freshness = score_freshness(prepared, evaluated_at, config)
momentum = score_momentum(prepared, evaluated_at, config)
newsworthiness = score_newsworthiness(prepared, evaluated_at, config)
confidence = score_cluster_confidence(prepared, evaluated_at, config)

# Detection is also available without scoring:
syndication = detect_syndication(prepared, evaluated_at, config)
```

The scoring and detection functions are pure: no I/O, model calls, database changes,
or input mutation. Authority preparation happens before scoring.
They use only the supplied snapshot, configuration, and timezone-aware evaluation
time. Articles published or first seen after that time are excluded and listed
in `excluded_article_ids`. Missing `first_seen_at` falls back to publication time.
Eligible reports are ordered by publication time, first-seen time, and article ID
using UTC instants. Input tuple order cannot affect the result.

## Three syndication outcomes

| Status | Meaning within this snapshot |
| --- | --- |
| `independently_written` | Sufficient body text, with no matching family |
| `syndicated_duplicated` | A member of a family with substantially shared writing |
| `unknown` | Body text is missing, too short, or too repetitive to compare reliably |

Every member of a shared-writing family has `syndicated_duplicated` status,
including its representative. The earliest observed member represents the
family for scoring; this does not identify the actual author or original
publisher. Family IDs use `cluster_id:representative_article_id` and are stable
for the same snapshot. An earlier report entering the snapshot can change them.

Detection compares extracted **body text only**. Matching titles, summaries,
embeddings, publisher names, or supplied `is_syndicated` flags do not establish
shared writing. Missing bodies stay unknown even when these other inputs match.
Independent means independent within the available comparison set, not verified
originality across the web. A lone sufficient report receives this status.

Bodies are Unicode-normalized, case-folded, and tokenized without punctuation.
Defaults require at least 50 tokens and 20 distinct five-token sequences
(shingles). Similarity is the shared shingle count divided by the larger body's
distinct shingle count. At least 80% of **both** bodies must match. This detects
exact copies and light edits while avoiding matches based on a common quotation
or a short excerpt of a substantially longer report. It can miss heavily edited
or substantially shortened copies; thresholds need calibration on real articles.

In chronological order, each usable article joins the family with the strongest
minimum pairwise match, provided it matches every member. Ties favor the earlier
family. Requiring every pair to match prevents chains of partial overlap from
merging substantially different reports. Unknown articles never form families.

`SyndicationResult` exposes each article's status, reason, family ID,
representative ID, maximum similarity to another eligible body, and estimated
`originality_score`. Originality is one minus the maximum fraction of its own
shingles reused from an earlier sufficient body. With no earlier usable body it
is 1; with insufficient content it is `None`. Families list their members and
minimum pairwise similarity. Classification uses all eligible bodies; originality
and novelty compare only with preceding reports.

## Contribution factors

| Factor | Default behavior |
| --- | --- |
| Publisher authority | Supplied 0–1 score; unknown = 0.5 |
| Originality | Supplied score, otherwise the body-based estimate above; unknown = 0.5; family copies are capped at 0.15 |
| Syndication | Family representative or independent body = 1; family copy or standalone `is_syndicated=True` = 0.35; unknown = 0.85 |
| Freshness | `2 ** (-age_hours / half_life_hours)`, with a 24-hour half-life |
| Breaking/source credit | `is_primary_source=True` earns 1; false earns 0; unknown = 0.25. Earliest published reports receive at least 0.75, including timestamp ties |
| Data quality | Required metadata earns 0.2; body length adds up to 0.5 at 200 tokens, summary up to 0.2 at 40 tokens, usable embedding adds 0.1 |
| Novelty | New text relative to all preceding reports combined with semantic difference from the most similar preceding embedding |
| Same-publisher repetition | Multipliers `1, 0.5, 0.25, ...`, using case-insensitive publisher keys |

Supplied originality and syndication fields remain optional upstream signals.
An explicit `is_syndicated=False` can supply the multiplier 1 for an unknown
body; it cannot override detected copying. An explicit true flag discounts a
standalone article even if no matching body is available. These flags do not
change the detector's three-way outcome. A family representative counts its
writing once even if all observed members are flagged syndicated; the real
original publisher may be absent from the snapshot.

Novelty separately permits body or summary text with at least 12 tokens. It
blends 30% new-text fraction and 70% semantic novelty when both are available;
otherwise it uses the available comparison, or 0.5 when neither is possible.
The first report with usable text or embedding receives novelty 1. Complete
text reuse receives novelty 0 even if its embedding differs. Semantic novelty
decreases linearly from 1 at cosine similarity 0.70 to 0 at 0.98. Zero vectors
are unavailable; comparisons require equal dimensions and the same embedding
model. Novelty estimates new information without verifying facts.

Article contribution results also expose `new_text_fraction`, the fraction of
comparison shingles absent from the union of preceding reports. It is `None`
when no text comparison is available (and 1 for the first usable text). This
diagnostic supports the event freshness decision without changing RANK-2 scores.

The base contribution averages authority (0.25), originality (0.20), novelty
(0.30), quality (0.15), and source credit (0.10), using the configured weights.
The result then multiplies by syndication, freshness, publisher repetition,
and `family_multiplier`. Missing signal fallbacks appear in `fallback_signals`.

## One report plus distribution credit

The representative keeps its contribution. Copies from its own publisher earn
no extra distribution credit. The first copy from each other publisher can earn
a small allowance, with subsequent copies from that publisher receiving zero.
For additional distinct publisher number `n`, starting at 1, the allowance is:

```text
representative_contribution × family_distribution_credit
    × (1 - family_distribution_decay) × family_distribution_decay ** (n - 1)
```

A copy receives the smaller of its ordinary contribution and this allowance.
`family_multiplier` records the reduction, and unused allowance is not
redistributed. Existing publisher, freshness, and quality discounts still apply.
If the representative contributes zero, its copies also contribute zero.

With default settings, the first three additional publishers can add at most
7.5%, 3.75%, and 1.875% of the representative's contribution. **Four copies count
at most as 1.13125 reports; any number of copies stays at or below 1.15.** New
copies cannot refresh the representative's age. Each separate family has its
own allowance; independently written reports keep their own contributions.

The cluster total sums the final article contributions. Its normalized component
is `1 - exp(-total / normalization_scale)`, with default scale 3. Results include
the ranking configuration version, contribution algorithm `article-contribution-v2`,
and detection algorithm `syndication-v1`. Detection options live under
`RankingConfig.parameters["syndication"]`; contribution options remain under
`["article_contribution"]`. The former `reuse_threshold` contribution option has
been replaced by the detector's `similarity_threshold` and body sufficiency rules.

## Publisher coverage (RANK-4)

Coverage starts with the same eligible articles and RANK-3 families. It groups
articles by case-insensitive `publisher_key`; surrounding whitespace is removed
by the article contract. Other publisher aliases or shared ownership need to be
resolved by the upstream loader. The raw distinct-publisher count is reported
separately from the effective count used for scoring.

Each publisher receives one basis and one weight, in the following priority order:

| Basis | Default weight |
| --- | --- |
| `independent` | 1, when at least one sufficient body is independently written and is not explicitly flagged syndicated |
| `family_representative` | 1, when it represents at least one shared-writing family |
| `syndicated` | A bounded family allowance, or 0.15 for explicitly syndicated reporting without a matched family |
| `unknown` | 0.5, when no available reporting establishes one of the other bases |

A representative counts a family's writing once, without establishing the true
original publisher. Explicit `is_syndicated=True` discounts standalone reporting
even if no matching family is observed. An explicit false flag or supplied
originality score does not establish independent coverage when body text is
insufficient, and cannot override a detected family.

Copies share a coverage allowance of up to 0.15 effective publishers per family.
The additional distinct publishers receive at most 0.075, 0.0375, 0.01875, and so
on, in order of their first appearance in that family. Each allowance is also
capped by `syndicated_publisher_weight`. A publisher already receiving full
credit for any independent report or family representation neither receives
extra credit nor consumes a distribution allowance.

A publisher appearing in several families keeps its **largest** applicable
weight. Those appearances are never summed. Repeated copies from the same
publisher do not consume additional allowances. Consequently, one publisher's
many independent articles still count as one publisher, while four publishers
sharing one report count at most as 1.13125 effective publishers. An arbitrarily
large single family stays at or below 1.15.

Known syndicated reporting takes precedence over unknown reporting from the
same publisher: adding an article with a missing body cannot upgrade a known
copy publisher to the 0.5 fallback. Actual independently written reporting can
upgrade that publisher to full credit. Classification changes can therefore
change its weight, but article volume itself earns nothing.

The effective publisher count sums these publisher weights. The normalized score is:

```text
coverage_score = 1 - exp(-effective_publisher_count / normalization_scale)
```

The default scale is 5. This is a fixed, increasing curve with diminishing
returns; it never depends on other clusters or their publisher counts.

| Independent publishers | Default coverage score |
| --- | --- |
| 1 | 0.181269 |
| 3 | 0.451188 |
| 20 | 0.981684 |
| 22 | 0.987723 |

Going from one to three raises the score by about 0.270, compared with about
0.006 from twenty to twenty-two. No eligible publishers produces score 0.
Freshness, publisher authority, embeddings, LLM rank, and the article-contribution
total are not additional coverage weights. Time is used to determine eligibility
and the detector's deterministic family ordering, without decaying coverage.

`CoverageResult` exposes the raw distinct count, effective count, normalized
score, family metadata, excluded article IDs, and a `PublisherCoverage` record
for every eligible publisher. Each record includes the canonical publisher key,
article IDs, basis, final coverage weight, and related family IDs. Results record
`coverage-v1`, the detector version, ranking configuration version, and evaluation
time. All result models are immutable.

Coverage weights and its curve are validated by `CoverageConfig` under
`RankingConfig.parameters["coverage"]`. Its distribution settings apply to
coverage only; article-contribution settings remain separate. Both components
share the detector configuration under `["syndication"]`.

## Publisher authority (RANK-5)

Manual authority starts with the existing tiers in `app/providers/ranks.py`,
which are also assigned to `NewsProvider.rank`. The tier table is unchanged.
`ManualAuthorityProvider()` takes an immutable copy of that table; callers can
instead pass already-loaded database ranks as a `{publisher_key: rank}` mapping.
Reading the table does not initialize scraping providers or application settings.

The fixed normalization treats tier 0 as highest and tier 4 as lowest:

| Manual rank | Normalized authority |
| --- | --- |
| 0 | 1.00 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3 | 0.25 |
| 4 | 0.00 |
| Missing or unlisted | `None` |

The formula is `1 - rank / 4`. It never rescales against the publishers currently
loaded or participating in an event. Rank 0 is a known top-tier value; normalized
0 is a known bottom-tier value. Neither is treated as missing. Invalid ranks,
including ranks outside 0–4, fractional ranks, and booleans, are rejected rather
than clamped. Canonical duplicate publisher keys are also rejected.

The source-independent boundary is `PublisherAuthorityProvider.get_authority()`:

```python
def get_authority(self, publisher_key: str) -> float | None:
    ...  # normalized, finite 0–1 score; None if unknown
```

A future dynamic implementation can satisfy this same protocol. Loading data or
calculating a dynamic authority snapshot belongs before ranking, using the desired
as-of time. The ranking function signature and formulas do not change when the
authority provider changes.

`with_publisher_authority(cluster, provider)` looks up each case-insensitive
publisher once, validates its returned value, and returns a new cluster with that
score on every corresponding `RankableArticle.publisher_authority_score`. It
replaces previous authority values, including clearing them to `None` when the
supplied provider has no value. The original cluster and its articles are
unchanged. Provider exceptions and invalid values propagate; a provider must
explicitly return `None` for an unknown value.

Both the existing article-contribution scorer and the new authority scorer read
only the normalized article field. Neither consults the manual tiers, calls a
provider, or branches on whether authority is manual or dynamic. Provider-specific
details live in `manual_authority.py`; the score consumer lives in
`publisher_authority.py`.

The event's authority component is the coverage-weighted mean across distinct
publishers:

```text
publisher_authority_score = sum(authority × coverage_weight) / sum(coverage_weight)
```

RANK-4 supplies the weights, so repeated articles from one publisher do not
multiply its authority, and syndicated publishers have limited influence. Two
independent publishers with authority 1.0 and 0.5 produce a component of 0.75.
Increasing any positively weighted publisher's authority increases the component.
Coverage breadth itself remains a separate component.

Missing authority uses the configured `unknown_authority` fallback, default 0.5,
and is marked by `used_fallback`. A known score on any eligible article applies to
that publisher's other articles with missing values. Conflicting known values
for one publisher are rejected: the input must represent one consistent authority
snapshot. A provider-prepared cluster supplies this consistency automatically.
No eligible publishers, or a total coverage weight of zero, produces component 0.

`PublisherAuthorityResult` exposes the normalized component, effective publisher
count, per-publisher scores, coverage weights, fallback indicators, article IDs,
excluded IDs, configuration version, and evaluation time. Results record
`publisher-authority-v1` together with the coverage and syndication algorithm
versions. The models remain immutable.

Authority-component options are validated by `PublisherAuthorityConfig` under
`RankingConfig.parameters["publisher_authority"]`. This component uses coverage
and syndication settings from their existing configuration sections. The
article-contribution component retains its own authority weight and unknown-value
fallback under `["article_contribution"]`.

## Event freshness and decay (RANK-6)

`score_freshness()` chooses the latest qualifying development and applies:

```text
freshness_score = 2 ** (-age_since_meaningful_update_hours / category_half_life_hours)
```

Publication time of the qualifying report is the proxy for the development's
time. The score is 1 at that time, 0.5 one half-life later, and 0.25 two half-lives
later. Every category starts at 1. Category changes only the decay rate and does
not apply an importance bonus, change contribution weights, or influence whether
an article qualifies as a development.

The initial category policy uses the application's category **keys**:

| Category key | Half-life in hours |
| --- | --- |
| `sport` | 6 |
| `kriminal` | 12 |
| `politika` | 24 |
| `lokalno` | 24 |
| `gospodarstvo` | 36 |
| `zdravje` | 48 |
| `okolje` | 48 |
| `kultura` | 72 |
| `tehnologija-znanost` | 72 |
| Missing or unconfigured | 24 |

Override these initial values through
`RankingConfig.parameters["freshness"]["category_half_lives_hours"]`. Partial
maps override named categories while retaining other defaults. Category keys are
case-insensitive and trimmed; duplicate canonical keys are rejected. A missing or
unconfigured `cluster.category` uses `default_half_life_hours` and is marked by
`used_default_half_life`. Per-article category tags do not choose the event's rate.

The scorer processes RANK-2's novelty results in their existing chronological
order and uses RANK-3's families to guard against copying. A subsequent article
qualifies only when:

1. Its body is sufficient for syndication detection.
2. It is not a non-representative family copy or explicitly `is_syndicated=True`.
3. It has an actual text comparison and does not use the unknown-novelty fallback.
4. Its combined novelty is at least `minimum_novelty` (default 0.5).
5. Its `new_text_fraction` is at least `minimum_new_text_fraction` (default 0.2).

The text threshold compares against the union of preceding reports. It prevents
a compilation of old reporting from refreshing the event even when an embedding
differs. Independently worded accounts with nearly identical embeddings usually
fail the combined novelty threshold. With no comparable embeddings, new wording
can qualify through text novelty alone. This remains a content-similarity
heuristic: it cannot verify facts, reliably distinguish every paraphrase, or
recognize every important change expressed in only a few words.

A new report from the same publisher can qualify; publisher repetition and
authority do not veto new developments. A high authority score, primary-source
flag, new publisher, new headline, or high article importance rank cannot grant
freshness by itself. Copies of a qualifying development keep that development's
time, including when it later becomes a syndicated family representative.

The first sufficient non-copied report can establish an event's initial clock.
When the event's creation time establishes older history but comparison reports
are absent, a first observed body cannot prove a new development. The scorer
conservatively retains the older anchor instead.

When no qualifying development is available, the result distinguishes a fallback
from a meaningful update. It uses the earlier of eligible observed publication
history and a valid event creation time. Missing or short later articles do not
replace this fallback with their newer timestamps. An explicitly copied-only
snapshot needs an existing event anchor; without one it receives freshness 0
with `anchor_basis="unavailable"`. No eligible articles also produces 0.

`first_seen_at` controls eligibility, without making an old publication fresh
when it is ingested late. Generic `cluster.changed_at` is never a freshness
anchor. Future publications and future first-seen observations are excluded;
future creation times are ignored. All time calculations use UTC instants,
including across daylight-saving changes.

`FreshnessResult` exposes `freshness_score`, the selected category half-life,
`last_meaningful_update_at`, the corresponding article ID, and the actual
`decay_started_at` anchor and age used in the formula. `anchor_basis` identifies
an initial report, a subsequent meaningful development, an event-creation
fallback, a first-report fallback, or unavailable history. Fallbacks leave
`last_meaningful_update_at=None`. Each `ArticleFreshnessDecision` records whether
the article qualifies and its reason, novelty, and new-text fraction. Results
also include excluded IDs, evaluation time, configuration version, and
`freshness-v1` with the contributing algorithm versions.

This event freshness component is separate from RANK-2's per-article freshness
factor. Article contribution still discounts each report by its own age. The
event's decay clock advances only when a report meets the development criteria.

## Coverage momentum (RANK-7)

`score_momentum()` compares the most recent six hours with the preceding six
hours by default. These are equal elapsed-time intervals in UTC:

```text
previous window: (evaluated_at - 12 hours, evaluated_at - 6 hours]
recent window:   (evaluated_at - 6 hours, evaluated_at]
```

The open start and closed end put boundary articles into exactly one interval.
`window_hours` configures both intervals, from one second to 8,760 hours. Reports
older than both windows still supply publisher, syndication, and novelty history;
their timestamps do not enter either window's velocity. All eligible history in
the supplied snapshot is used, so an established publisher is not counted as new
merely because its older articles fall outside the two windows.

### What earns momentum

The scorer reuses RANK-3's body-based syndication detection and RANK-2's novelty
diagnostics. It does not use final article-contribution amounts, authority,
category, source bonuses, or the per-article freshness multiplier.

- A publisher's first qualifying independently written report earns one new
  publisher credit and one article credit. Publisher keys are case-insensitive.
- A returning publisher needs both combined novelty of at least 0.5 and a
  new-text fraction of at least 0.2, with an actual comparison instead of an
  unknown-novelty fallback. Its first qualifying report in each window earns
  one article credit and no new publisher credit.
- Additional qualifying reports from that publisher in the same window earn
  article credits of 0.075, 0.0375, 0.01875, and so on. The entire extra allowance
  is bounded by 0.15, however many posts appear. Rejected reports do not consume
  this allowance. Limits reset per window; the new publisher credit never resets
  within the supplied event history.
- Non-representative family copies and explicitly syndicated articles earn zero,
  including copies published by new publishers. A family's earliest representative
  can stand for one independent report unless explicitly marked syndicated.
- Missing, short, or repetitive bodies earn zero. Summaries, embeddings, source
  flags, and claimed originality cannot bypass that requirement.
- A known new-text fraction below 0.2 blocks even a new publisher, preventing
  compilations of existing articles from being treated as new written coverage.

New independent coverage need not reveal a new fact: a new publisher's independently
worded account can broaden coverage and produce momentum without resetting RANK-6's
freshness clock. The stronger combined-novelty threshold applies to returning
publishers to prevent repeated recaps from driving the trend. Unknown or copied
earlier posts do not spend a publisher's first independent-report credit.

With the default equal weights, each window's coverage credit is:

```text
coverage_credit = 0.5 * new_independent_publisher_count
                + 0.5 * effective_article_count
velocity_per_hour = coverage_credit / window_hours
acceleration_per_hour_squared = (recent_velocity - previous_velocity) / window_hours
```

`effective_article_count` sums the limited article credits. A new publisher's
first report therefore contributes 1 coverage credit; an established publisher's
first novel report in a window contributes 0.5. Forty novel posts from one new
publisher remain bounded by 1.075 coverage credits. Three independent publishers
with one report each contribute 3 credits. Raw qualifying article counts are
diagnostics and do not enter the score directly.

### Normalized score and trend

The score combines saturating current velocity with the change between windows:

```text
relative_change = (recent_credit - previous_credit) / (recent_credit + previous_credit)
activity_score = 1 - exp(-recent_velocity / velocity_scale_per_hour)
trend_multiplier = 1 - acceleration_weight * (1 - relative_change) / 2
momentum_score = activity_score * trend_multiplier
```

When both credits are zero, relative change is defined as zero. Otherwise it
ranges from -1 (coverage stopped) through 0 (steady) to +1 (coverage started).
The default `acceleration_weight=0.4` yields a multiplier of 0.8 for steady
coverage, rising toward 1 for acceleration and falling toward 0.6 for slowing
coverage. `velocity_scale_per_hour=0.5` controls saturation. For identical current
coverage, greater acceleration yields a higher score. For identical trend, higher
current velocity yields a higher score with diminishing returns.

No current meaningful coverage always produces score 0. A negative acceleration
is still exposed when coverage stopped; an empty pair of windows is `inactive`.
The normalized score is higher-is-better in [0, 1], while `relative_change`,
`velocity_change_per_hour`, and `acceleration_per_hour_squared` preserve signed
trend information. A new observed event can accelerate from a zero previous rate
without division by zero.

`MomentumResult` exposes both `MomentumWindow` summaries, including their bounds,
article IDs, qualifying independent article count, active publisher count, new
publisher keys and count, effective article count, coverage credit, and velocity.
`ArticleMomentumDecision` explains each report's window, eligibility reason,
novelty, new-text fraction, publisher ordinal, and credits. Historical reports can
qualify as coverage while receiving zero window credit. Results also record
excluded IDs, evaluation time, configuration version, and `momentum-v1` together
with the article-contribution and syndication algorithm versions.

Publication time is the coverage-time proxy. First-seen time controls eligibility,
so ingesting old reporting today cannot produce current velocity. Generic event
creation/change timestamps do not generate momentum. Future publications and
future first-seen observations are excluded before comparisons. The function is
deterministic, immutable, and independent of other clusters.

Momentum settings live under `RankingConfig.parameters["momentum"]` and are
validated by `MomentumConfig`. `new_publisher_weight` selects the publisher share;
the article share is its complement. Novelty thresholds are separate from the
freshness component's thresholds, while both reuse the same contribution and
syndication diagnostics. The novelty comparisons remain heuristics: without
comparable embeddings, independently reworded recaps may pass through text
novelty alone. Missing historical reports can make an established publisher appear
new; rates describe the supplied snapshot, not verified completeness of coverage.

## Semantic newsworthiness (RANK-8)

The existing article analyzer assigns `llm_rank` from 1 to 10, with higher values
meaning more important. `normalize_llm_importance()` maps this fixed scale to:

```text
importance_score = (llm_rank - 1) / 9
```

Rank 1 becomes 0 and rank 10 becomes 1. Missing ranks remain unknown rather than
being converted to rank 1. Invalid values are rejected; normalization never
depends on another article, cluster, or the observed minimum/maximum ranks.

### Aggregation and duplicate handling

`score_newsworthiness()` uses RANK-3's eligible articles and shared-writing
families, then:

1. Collapses each family into one report. It retains the earliest representative's
   LLM rank, even if later copies have higher ranks. If that rank is missing, it
   uses the first scored family member in chronological order, with an explicit
   fallback flag. The report still belongs to the representative's publisher for
   publisher limits. A family with no ranks is left unscored.
2. Takes scored, sufficiently comparable independent bodies and family
   representatives as its main candidate pool. Each family's writing counts once
   even if its original publisher is absent or its representative is explicitly
   marked syndicated. The importance of the underlying event can still be assessed
   from copied reporting; this does not grant extra coverage or freshness.
3. Keeps the strongest candidate from each case-insensitive publisher, then selects
   the top three candidates by importance. Ties use the representative's publication
   time, first-seen time, and article ID. Input tuple order cannot change selection.
4. Blends the strongest selected importance with the mean of the selected set:

```text
article_newsworthiness_score = 0.5 * strongest_article_score
                            + 0.5 * top_reports_mean
```

For article ranks 10, 7, and 4 from three independent publishers, the normalized
scores are 1, 2/3, and 1/3. Their mean is 2/3 and the default cluster article score
is 5/6, approximately 0.833. With only one scored report, its normalized importance
is used directly; the mean is not padded to three entries.

There is no sum of article importance or count-based bonus. Identically scored
independent reports produce the same importance whether there is one or twenty.
Repeated same-publisher posts cannot fill multiple selected slots, and copied
scores cannot override a known representative's rank. Lower-scoring articles
outside the top set cannot dilute the score. A stronger independently written
report can replace a weaker selection, including from the same publisher.
Within an underfilled top set, a lower independent score can reduce the mean;
the strongest-report half of the score preserves the leading judgment.

`top_reports` and `strongest_weight` control this policy. Set `top_reports=1` or
`strongest_weight=1` for strongest-only scoring, or `strongest_weight=0` for the
top-report mean. These settings live in `RankingConfig.parameters["newsworthiness"]`
and are validated by `NewsworthinessConfig`.

### Missing and uncertain data

Reports with missing ranks are excluded from selection instead of receiving a
neutral score each. If every eligible rank is missing, the result uses one
configurable `unknown_importance` fallback, initially 0.5, with
`article_basis="missing_scores"` and `source="fallback"`. A known rank of 1 still
scores 0. No eligible articles yields 0 and `source="unavailable"`.

Missing, short, or repetitive bodies and explicitly syndicated standalone articles
without a detected family cannot displace a scored main-pool report. If no main-pool
rank is available, the strongest scored unverified report supplies a single-report
fallback, marked `article_basis="unverified_report"`. This preserves existing LLM
judgments when full bodies are unavailable without pretending those reports are
independent votes. Higher-scoring new unverified reports can change this fallback,
but their scores are never summed or averaged as multiple independent reports.

The result exposes `NewsworthinessReport` entries with all member article IDs,
the representative and score-source article IDs, canonical publisher, family ID,
raw and normalized rank, reporting basis, family fallback flag, and selection
reason. `selected_article_ids` identifies the score sources in descending-importance
order. `strongest_article_score`, `top_reports_mean`, `article_newsworthiness_score`,
and `article_basis` explain the aggregation. Results also record excluded IDs,
configuration/evaluation metadata, `newsworthiness-v1`, and the syndication version.

### Future cluster evaluations through the same engine contract

The component always returns `semantic_importance_score` in [0, 1], matching the
existing `RankingComponentScores` field. `RankableCluster` now accepts an optional
`newsworthiness: ClusterNewsworthiness` snapshot containing a normalized `score`,
an aware `evaluated_at` availability timestamp, and a producer `version`:

```python
from app.ranking import ClusterNewsworthiness, RankableCluster, score_newsworthiness

cluster = RankableCluster(
    cluster_id=7,
    articles=articles,
    newsworthiness=ClusterNewsworthiness(
        score=0.85,
        evaluated_at=evaluation_available_at,
        version="cluster-llm-v1",
    ),
)
result = score_newsworthiness(cluster, evaluated_at, config)
```

A supplied cluster evaluation replaces article aggregation by default. Set
`cluster_score_weight` between 0 and 1 to blend it with the article score, or 0
to disable it. When no article rank can be used, an available cluster evaluation
is used fully instead of being diluted by the unknown-importance fallback.
Evaluations whose availability time is in the future are ignored, as are cluster
evaluations when no articles are eligible. A cluster score of 0 is a real value,
not a missing evaluation.

`source` distinguishes article aggregation, a cluster evaluation, a blend, a
missing-score fallback, and unavailable input. `cluster_evaluation_status`,
`cluster_evaluation_score`, `cluster_evaluation_version`, and
`applied_cluster_weight` explain whether and how an evaluation was used. The
article aggregation remains available for comparison even when replaced.

This adds no LLM calls: a future producer must prepare the normalized evaluation
outside ranking, using information available at its recorded time. The scoring
function and engine's output contract remain the same for either source.

Newsworthiness does not apply authority, freshness, category bonuses, momentum,
or article-contribution weights. Eligible historical ranks retain their semantic
importance as time passes; separate components handle decay and coverage. The
existing analyzer's prompt already expresses preferences for Slovenian relevance
and politics, economics, crime, and local news. This aggregation inherits those
judgments and their limitations; it adds no category weighting and does not change
the prompt. Syndication remains a within-snapshot writing-similarity heuristic.

## Cluster confidence and final-score gating (RANK-9)

`score_cluster_confidence()` estimates whether a cluster represents one coherent
event using embeddings, supplied clustering membership confidence, relation
failures, and publication-time spread. The score is a bounded heuristic, not a
calibrated probability that the cluster is correct.

RANK-3 supplies the eligible reports and syndicated families. Each family uses
its earliest representative's embedding, membership confidence, publisher, and
publication time once. Copies cannot add votes, shift the time center, or wash
out an unrelated report. Missing representative signals use the same explicit
fallbacks as other missing data; a later copy does not replace them.

After collapsing families, a publisher's total weight is one, shared equally
among its reports. Ten reports from one publisher and one from another give
each publisher equal aggregate weight. All means and proportions below use
these weights, including dimension selection and temporal calculations. There
is no positive term for raw article count or publisher count.

### Semantic and membership signals

Usable embeddings are normalized to unit length with magnitude scaling to avoid
overflow and underflow. The scorer selects the dimension with the greatest
publisher-balanced weight, breaking ties by the smaller dimension. Other
dimensions remain in the confidence calculation as missing semantic comparisons;
they are not silently dropped from the denominator. Input vectors must come from
the same embedding model: equal dimension alone cannot establish that.

For each compatible report, the scorer constructs a weighted centroid of
compatible reports from **other publishers** and measures cosine similarity to
that centroid. Posts from the same outlet are not peers, so one outlet cannot
raise confidence by agreeing with itself. A single-publisher cluster, including
a single article, has no such comparison and scores 0.5. If multiple available
peer directions cancel, the scorer treats that as measured incoherence rather
than missing information.

The cosine is mapped to a unit score:

```text
similarity_score = clip((cosine - outlier_similarity)
                        / (strong_similarity - outlier_similarity), 0, 1)
```

Defaults give zero at cosine 0.4 or lower and full semantic coherence at 0.9 or
higher. A report is flagged weakly related below 0.75 and an outlier below 0.4. Those
flags do not change the score. Missing,
zero, incompatible, and unpaired embeddings use `unknown_similarity_score=0.5`,
with explicit per-report status and fallback flags. They are not automatically
classified as observed outliers or weak relations.

`cluster_membership_confidence` is consumed as a higher-is-better value in [0, 1].
Known membership below 0.5 marks a weak relation; below 0.2 marks an outlier.
Missing values use `unknown_membership_confidence=0.5`. A known zero remains zero.
The current live clustering pipeline stores labels and does not yet populate this
optional ranking-input field; its absence is reflected in diagnostics.

`semantic_coherence_score` and `membership_confidence_score` are weighted means,
including the explicit missing-value fallbacks. Their default combination is:

```text
signal_confidence_score = 0.7 * semantic_coherence_score
                        + 0.3 * membership_confidence_score
```

A report is flagged an outlier or weakly related when either measured signal
crosses its corresponding threshold. Outliers are also included in the weak
proportion. Those flags are diagnostics. The score uses the continuous
similarity and membership values in `signal_confidence_score`, then the temporal
multiplier. A hard step at 0.75 is not applied.

### Temporal coherence and combined confidence

The time center is the weighted median publication instant. Temporal deviation
is the weighted mean absolute distance from this center, in elapsed UTC hours:

```text
temporal_coherence_score = 2 ** (-mean_temporal_deviation_hours / 72)
temporal_multiplier = 1 - 0.25 * (1 - temporal_coherence_score)

cluster_confidence_score = signal_confidence_score * temporal_multiplier
```

Outlier and weak-relation proportions remain on the result for inspection. They
are not additional multipliers. `weak_relation_penalty` is still accepted so
older configuration files validate, and it does not change the score.

An event with reports concentrated in time has temporal coherence near one.
Widely scattered reports reduce confidence. Shifting every report equally into
the past does not change this signal: it measures event spread, while RANK-6
handles event age. The bounded temporal penalty permits genuine events to develop
over several days. Category, generic creation/change timestamps, article importance,
publisher authority, and source flags do not directly increase confidence.

For three matching embeddings, membership confidence 0.9, and simultaneous
publication, confidence is 0.97. If membership values are absent, the same reports
receive 0.85 with membership fallback flags. A single article, and any
single-publisher cluster, receives 0.5 even when membership confidence is
present. No eligible reports yields zero, explicitly marked `basis="unavailable"`
instead of an unknown-data fallback.

`ClusterConfidenceResult` exposes all signal scores, data-availability fractions,
weighted outlier and weak-relation proportions, chosen dimension, compared report
count, effective report weight, temporal center and deviation, and the final
confidence and `gate_multiplier`. `ConfidenceReport` records member article IDs,
the representative, publisher, weight, embedding status, peer-centroid cosine,
membership value, fallback flags, relation classifications, and temporal deviation.
`basis` distinguishes measured signals from entirely fallback-based confidence.
Results include excluded IDs, configuration/evaluation metadata,
`cluster-confidence-v1`, and the syndication algorithm version.

### Applying the gate to the final ranking score

Confidence is applied after the other components have produced a normalized
base score. It is not another positive term in a weighted sum:

```text
final_score = base_score * freshness_score * cluster_confidence_score ** gate_power
```

The default `gate_power=1` multiplies by confidence itself. Confidence 0.2 caps
the final score at 0.2 even when every other component is maximal. Confidence
0.5 caps it at 0.5; confidence 1 preserves the base score. `gate_power` must be
at least one, so the gate cannot weaken this ceiling or boost the base score.
Invalid, nonfinite, or unbounded base scores are rejected instead of allowing
large article totals to bypass the gate. Similarity is a continuous ramp from
the outlier threshold to the strong threshold. Weak and outlier flags are still
recorded, but they do not apply a step penalty, so a cosine of 0.749 and 0.751
do not jump the score. Peer similarity uses other publishers only. A cluster
with a single publisher, including a single article and one outlet posting many
times, has confidence 0.5.

`apply_confidence_gate(base_score, cluster_confidence_score, config)` exposes
the confidence-only numerical operation. Since RANK-10, `finalize_ranking()` first
applies the event freshness component and then the confidence gate when building
the existing `RankingResult`. Its input base score must be before both gates.
The normal entry point computes the base and finalizes the result automatically:

```python
from app.ranking import rank_cluster

ranked = rank_cluster(prepared, evaluated_at, config)
```

Custom callers of `finalize_ranking()` must call it once, after computing a
normalized base score; do not pre-apply either gate or add freshness/confidence
as positive components. Directly constructing `RankingResult` only validates its
data and does not perform scoring. The RANK-10 engine implements the base-score
combination below; database loading and persistence remain external.

Settings are validated under `RankingConfig.parameters["cluster_confidence"]`.
The scorer, gate, and finalizer share that policy and perform no I/O or model calls.
Future publications and future first-seen observations are excluded before
building families, centroids, or time statistics. Input order cannot affect the
result. Thresholds require calibration against the actual embedding model and
cluster examples; semantic similarity alone cannot distinguish every separate
event discussing the same subject.

## Final cluster score (RANK-10)

`rank_cluster()` composes all the components through the original three-argument
`RankingFunction` contract. Initial base weights are equal:

```text
base_score = 0.25 * article_contribution_score
           + 0.25 * coverage_score
           + 0.25 * momentum_score
           + 0.25 * semantic_importance_score

cluster_score = base_score * freshness_score * cluster_confidence_score ** gate_power
```

The final score, every component, the base, and both multiplicative factors are
in [0, 1]. `gate_power` defaults to 1. The confidence exponent comes from the
existing `gate_power` policy.
No additive freshness or confidence bonus can counteract a weak gate, and no
other score can push the final result above either gate's ceiling.

### Signal ownership and ranges

| Engine component | Range | Role in composition |
| --- | --- | --- |
| `article_contribution_score` | 0–1 | Intrinsic article strength: publisher authority, data quality, source credit |
| `coverage_score` | 0–1 | Accumulated publisher breadth with syndication discounts and exponential saturation |
| `momentum_score` | 0–1 | Recent qualified reporting velocity and its change between windows, with saturation |
| `semantic_importance_score` | 0–1 | Duplicate-adjusted article LLM importance or an available prepared cluster judgment |
| `publisher_authority_score` | 0–1 | Diagnostic component already included inside article strength; no extra base term |
| `freshness_score` | 0–1 | Event decay from the latest meaningful development; multiplied once |
| `cluster_confidence_score` | 0–1 | Event coherence; its configured power is multiplied once |

Accumulated breadth and recent momentum use shared observations but different
measurements: all-history publisher breadth versus recent velocity and change.
The engine does not additionally add their raw counts, velocities, acceleration,
or intermediate activity scores. Syndication and novelty checks are shared
eligibility rules, not extra numeric bonuses. Category chooses the event's decay
rate rather than adding importance.

### Article strength without counting breadth or decay again

RANK-2's standalone contribution total already accumulates reports and discounts
each one by age. Adding that total to publisher coverage and multiplying it by
event freshness would duplicate those effects. Composition therefore uses an
explicit projection of RANK-2's underlying quality/source diagnostics:

1. Each syndicated family supplies its earliest representative once. Other family
   members are skipped. Explicitly syndicated standalone articles cannot supply
   an additional quality report.
2. Each publisher supplies its strongest remaining report by the configured
   data-quality/source blend. Ties keep the earliest report. Quality and source
   values always come from the same selected report.
3. Selected data quality and source credit are averaged across publishers.
4. The publisher-authority component is blended in once, initially as:

```text
article_contribution_score = 0.5 * publisher_authority_score
                           + 0.3 * mean_data_quality
                           + 0.2 * mean_source_credit
```

Source credit includes RANK-2's existing primary-source and breaking credit.
There is no article count, freshness multiplier, originality bonus, novelty
bonus, or sum of article contributions in this projection. More reports of the
same quality do not create additional strength votes from one publisher. A
stronger report may replace that publisher's previous selection. Mean quality
does not rise merely because more equally strong publishers appear.

Authority is consumed through RANK-5's source-independent normalized result.
Its unknown-value policy is owned by `publisher_authority.unknown_authority`.
RANK-2's separate unknown-authority setting and contribution weights still affect
its standalone diagnostic total, but do not add another authority term here.

`ArticleStrengthResult` exposes the selected publisher reports, their quality and
source values, unknown-content flags, aggregate means, authority, normalized
strength weights, and the value used in the final component. In an explanation,
`result.components.article_contribution_score` is this intrinsic strength, while
`article_contribution.article_contribution_score` is the original standalone
RANK-2 diagnostic. The latter is retained for inspection and is not added to base.

### Configuration and saturation

`ClusterRankingConfig` validates `RankingConfig.parameters["ranking"]`. Set
`article_contribution_weight`, `coverage_weight`, `momentum_weight`, and
`semantic_importance_weight` to any finite nonnegative values with at least one
positive value. They are normalized to sum to one. Scaling all four weights by
the same constant does not change the result; very large or small positive
weights are normalized safely. A zero weight disables that term without removing
its diagnostics. These are initial configurable weights, not calibrated ones.

The nested `ranking.article_strength` object uses `ArticleStrengthConfig` with
`authority_weight`, `data_quality_weight`, and `source_weight`, also normalized
to sum to one. At least one must be positive. Freshness, confidence, novelty,
and extra publisher-authority weights are not accepted as additional base terms.

Every component is bounded before composition. Quality uses a mean and a
publisher limit; coverage and momentum saturate; LLM importance uses normalized,
duplicate-adjusted aggregation. A convex weighted mean of these terms cannot
grow above one. Raw totals remain available only as diagnostics. Normalization
uses fixed input scales and configured weights, never other current clusters,
batch minima/maxima, or percentiles. Scoring another cluster cannot change this
cluster's result.

### Explicit fallbacks and reproducibility

| Missing or uncertain input | Composed behavior |
| --- | --- |
| Unknown publisher authority | RANK-5's configured fallback, initially 0.5, used once inside strength |
| Missing article body or source flag | RANK-2's partial-data quality and source fallback; selected unknown content is marked |
| No qualifying quality report | Article strength 0 with an explicit basis |
| Unknown independent publisher coverage | RANK-4's fractional publisher weight, initially 0.5, before coverage saturation |
| No recent qualifying reporting | Momentum 0 |
| Missing article LLM ranks | RANK-8's single configured importance fallback, initially 0.5; an available cluster judgment can replace it |
| No verified meaningful-update clock | RANK-6's marked conservative event/first-report anchor, or freshness 0 if no anchor exists |
| Missing embeddings or membership confidence | RANK-9's explicit signal fallbacks and resulting confidence gate |
| No eligible articles | All components, base score, and final score are 0 |

Known zero values remain zero. Missing data does not cause weight redistribution
to the remaining terms. Invalid configuration, conflicting publisher authority,
and invalid input values raise errors instead of being silently classified as
unknown. Future publications, observations, and cluster evaluations retain the
existing eligibility rules across every component.

`explain_cluster_ranking()` returns a `ClusterRankingExplanation` with the final
`RankingResult`, ungated base score, four `WeightedRankingTerm` entries, freshness
and confidence factors, article-strength projection, and every standalone
component result. Each term records its component value, normalized weight, and
weighted contribution. Component results retain fallback reasons, excluded IDs,
evaluation/configuration metadata, and their algorithm versions; the composition
records `cluster-ranking-v1`. For example:

```python
from app.ranking import explain_cluster_ranking

explanation = explain_cluster_ranking(prepared, evaluated_at, config)
ranked = explanation.result
assert 0.0 <= ranked.score <= 1.0
```

Both entry points are deterministic and perform no database access, model calls,
provider lookups, or input mutation. Prepare authority and optional cluster LLM
evaluations before calling them. Live loading and persistence stay outside this
engine. Thresholds and weights remain initial policies requiring calibration.


## Saving scores and running a batch

The pure engine remains database-independent. `persistence.py` adapts stored
articles and memberships to its contracts and saves the latest result on
`cluster_v2`. Run commands from the Agora repository root:

```bash
make migrate
make rank-clusters
make rank-clusters ARGS="--dry-run"
make rank-clusters ARGS="--days 7 --batch-size 50"
make rank-clusters ARGS="--config /absolute/path/ranking-config.json"
```

Run `make migrate` to apply the ranking columns and the `ranking_run` migration
(`a62f4c9d810b`). Supply `DATABASE_URL` using your normal environment setup.
The ranking command loads the **repo-root `.env`**, without overriding exported
variables, and needs no LLM API keys.
`--help` needs no configuration at all. Config files use the existing
`{"version": "my-config-v1", "parameters": {...}}` contract; omitted settings
are materialized and saved, and unknown sections or invalid values are rejected.

This score is **observation-only**. Nothing in the reader, feed order, or page
cache reads it to decide what a person sees. The scheduled job and the hook at
the end of `run_clustering` only write ranking columns and `ranking_run` rows.

The default selection is the **latest production clustering run** (`cluster_run.is_production`,
newest `created_at`, then highest id). That is the run the site shows. Clusters
from older runs, non-production runs, and the previous 30 days of history are
not scored. `--run-id` scores one specific run for backfill; the default remains
the latest production run. `run_clustering` also ranks the run it just wrote.
The timer remains the fallback when that hook does not run.

Expiry is a separate pass and does not wait for scoring. It leaves the latest
production run untouched. Other runs are cleared when their snapshot is older
than `--days` (default 30) or they already have a score. Already expired zeroes
are left untouched. Widening `--days` does not start scoring an older run;
pass `--run-id` to backfill one. Article dates still determine story freshness
inside the engine.

The command pages by cluster ID, saves at most 100 clusters per transaction, and
reports progress. Empty clusters and clusters that cannot be scored (empty title,
non-finite embedding, membership from another run) are skipped. The skip is
logged with the cluster id and the error, the rest of the run continues, and
`ranking_run.skipped_count` includes them. A fatal error still rolls back the
current batch; completed batches remain saved. Rerunning replaces each current
cluster's latest summary and creates a new `ranking_run` record. `--dry-run`
calculates scores and counts would-be expirations without saving anything,
including run records. The full explanation is returned to the caller on a
dry-run and is not written to `cluster_v2`.

Each run records UTC `started_at`, `evaluated_at`, `finished_at`, status, window,
engine version, effective configuration, and committed scored/expired/skipped
counts. Failure records include an error and, when known, the offending cluster ID.
Counts commit in the same transaction as their cluster results. Runs can therefore
have partial progress when they fail; successful earlier batches remain inspectable.
Only the latest per-cluster score and explanation are retained; run metadata is
historical, but this is not a per-run archive of every cluster's score.

A PostgreSQL transaction advisory lock prevents overlapping manual/scheduled
runs, including through transaction pooling. A concurrent invocation logs a skip
and does not create a run. Graceful termination marks the run `interrupted`.
The next non-dry run recovers abandoned `running` records after acquiring the lock;
their `finished_at` is the detection time, with the actual stop time unknown.

The Ansible deployment installs `agora-ranking.timer`, running at **:00 and :30 UTC**
using the scraper image and deployed `DATABASE_URL`. The service limits each worker
to 25 minutes and logs to journald. Missed schedules are caught up once on startup.
This schedule becomes active on deployment, after migrations; local `make` commands
remain one-off runs. The job only writes backend observation fields and run records.

Inspect runs:

```sql
SELECT id, started_at, evaluated_at, finished_at,
       finished_at - started_at AS duration,
       status, scored_count, expired_count, skipped_count,
       failed_cluster_id, error
FROM ranking_run
ORDER BY id DESC
LIMIT 20;
```

On the deployed host:

```bash
systemctl list-timers agora-ranking.timer
journalctl -u agora-ranking.service --since today
```

Saved cluster fields:

- `rank_score`: final bounded score; NULL means unranked, zero is a valid score.
- `ranked_at`: timezone-aware evaluation time.
- `ranking_run_id`: run that last scored or expired this snapshot; legacy results
  remain NULL until processed.
- `rank_components`: summary fields only. The seven normalized components, base
  score, weighted terms, applied freshness/confidence factors, component versions,
  decay anchor, and latest meaningful-development time when available. The full
  per-article explanation is not stored.
- `rank_version`: engine algorithm version.
- `ranking_run_id`: the run whose `ranking_run.config` holds the effective
  configuration, including defaults. Configuration is not copied onto each cluster.
- `rank_category`: category used for decay. One primary-category vote per publisher
  from its earliest categorized eligible report, excluding detected family copies;
  ties break alphabetically. Unknown-content reports may vote. Missing category
  uses the engine's configured default half-life.

`rank_and_save_cluster(..., dry_run=True)` returns the full `ClusterRankingExplanation`
and writes nothing. A real save stores the summary above. Reranking replaces that
summary rather than keeping a history. Article text and embedding vectors remain
in their source tables.

Inspect one cluster and the configuration for its run:

```sql
SELECT c.rank_score, c.ranked_at, c.rank_components, r.config
FROM cluster_v2 c
LEFT JOIN ranking_run r ON r.id = c.ranking_run_id
WHERE c.id = :cluster_id;
```

New scraping runs record article `first_seen_at` after discovery and before
extraction/analysis. Historical values stay NULL, preserving the engine's existing
publication-time fallback. HDBSCAN's `probabilities_` are saved as
`article_cluster.membership_confidence` in normal and bootstrap clustering runs.
Noise converted into a singleton, legacy imports, and old memberships have unknown
confidence. HDBSCAN never assigned those articles to their newly created singleton
clusters. `cluster_run.params` now records the actual HDBSCAN parameters and input
policy. Snapshot creation time is never used to make an old event fresh again;
the loader supplies the earliest member publication as the available event anchor.

The sister web app displays a temporary **Ocena** badge when a score exists,
including zero. Cards on home/category pages and cluster detail pages show it;
feed ordering still uses the web app's existing ranking. Existing KV/page caches
may delay score updates until they refresh. The badge is optional for older cached
payloads and the reader tolerates databases without the new column. No web-side
schema migration or generated Drizzle schema edit is needed for this test display.

Run PostgreSQL integration checks against a disposable database with
`RANKING_TEST_DATABASE_URL` set in addition to the usual test environment. These
tests create and remove isolated temporary schemas; they never connect to the
application's `DATABASE_URL` for test writes.

## Clustering imported articles in dev

Cluster and run creation timestamps are stored as timezone-aware UTC values, so
newly created snapshots are immediately eligible for ranking. The database loader
treats article LLM ranks outside 1–10 as unknown importance and logs the article
ID; the original article row is preserved.

After manually importing articles, run the existing clustering command from the
repository root:

```bash
make run-clustering ARGS="--dev --bootstrap --days 5"
```

`--dev` loads `DEV_DATABASE_URL` from the root `.env` before the database engine
is initialized. `--bootstrap --days 5` clusters articles published in the last five
days, using their embeddings and the existing HDBSCAN algorithm. Omit `--days` to
cluster all existing articles. It needs no previous
run and makes no external API calls. Titles use member article titles; membership
confidences are saved. A new run is created without deleting articles or clusters.
Omitting these flags preserves the normal incremental clustering command.

For future article exports:

```bash
make export-articles DAYS=5 OUTPUT=/tmp/articles-5d.sql
```

The export reads `SOURCE_DATABASE_URL`, falling back to `DATABASE_URL`, from root
`.env`. It selects by publication time and outputs INSERT statements for articles
and required publishers. Dev allocates article IDs; matching URLs are refreshed,
legacy cluster references are cleared, and existing publishers are preserved.
It exports no clusters, runs or memberships. Import the SQL file manually as usual.
The old `export-ranking-sample` target is an alias for this article-only export.
