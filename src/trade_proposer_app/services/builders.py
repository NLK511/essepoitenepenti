from sqlalchemy.orm import Session

from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_outcomes import RecommendationOutcomeRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.support_snapshots import SupportSnapshotRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.plan_generation_tuning import PlanGenerationTuningRepository
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.industry_support import IndustrySupportRefreshService
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.macro_support import MacroSupportRefreshService
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.proposals import ProposalService
from trade_proposer_app.services.signals import SignalIngestionService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.support_snapshot_resolver import SupportSnapshotResolver
from trade_proposer_app.services.social import SocialIngestionService
from trade_proposer_app.services.summary import SummaryService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignalService
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService


def create_proposal_service(session: Session) -> ProposalService:
    """Create the app-native proposal service with configured news and social ingestion."""
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    ticker_limit = int(settings_map.get("news_ticker_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(credentials, max_articles=ticker_limit)
    social_service = SocialIngestionService.from_settings(repository.get_social_settings())
    signal_service = SignalIngestionService(social_service=social_service)
    summary_service = SummaryService(
        summary_settings=repository.get_summary_settings(),
        provider_credentials=credentials,
    )
    taxonomy_service = TickerTaxonomyService()
    snapshot_resolver = SupportSnapshotResolver(
        SupportSnapshotRepository(session),
        taxonomy_service=taxonomy_service,
        context_repository=ContextSnapshotRepository(session),
    )
    return ProposalService(
        news_service=news_service,
        social_service=social_service,
        signal_service=signal_service,
        summary_service=summary_service,
        snapshot_resolver=snapshot_resolver,
    )


def create_ticker_deep_analysis_service(
    session: Session,
    proposal_service: ProposalService | None = None,
) -> TickerDeepAnalysisService:
    return TickerDeepAnalysisService(proposal_service or create_proposal_service(session))


def create_watchlist_orchestration_service(
    session: Session,
    proposal_service: ProposalService | None = None,
) -> WatchlistOrchestrationService:
    settings_repository = SettingsRepository(session)
    setting_map = settings_repository.get_setting_map()
    raw_threshold = setting_map.get("confidence_threshold", "60")
    try:
        confidence_threshold = float((raw_threshold or "").strip())
    except (TypeError, ValueError):
        confidence_threshold = 60.0

    return WatchlistOrchestrationService(
        context_snapshots=ContextSnapshotRepository(session),
        recommendation_plans=RecommendationPlanRepository(session),
        decision_samples=RecommendationDecisionSampleRepository(session),
        cheap_scan_service=CheapScanSignalService(),
        deep_analysis_service=create_ticker_deep_analysis_service(session, proposal_service=proposal_service),
        confidence_threshold=confidence_threshold,
        signal_gating_tuning_config=settings_repository.get_signal_gating_tuning_config(),
        plan_generation_tuning_config=settings_repository.get_plan_generation_active_config(PlanGenerationTuningRepository(session)),
        calibration_service=RecommendationPlanCalibrationService(RecommendationOutcomeRepository(session)),
    )


def create_macro_support_service(session: Session) -> MacroSupportRefreshService:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    macro_limit = int(settings_map.get("news_macro_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(credentials, max_articles=macro_limit)
    social_service = SocialIngestionService.from_settings(repository.get_social_settings())
    snapshot_repository = SupportSnapshotRepository(session)
    return MacroSupportRefreshService(snapshot_repository, social_service=social_service, news_service=news_service)


def create_macro_context_service(session: Session) -> MacroContextService:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    macro_limit = int(settings_map.get("news_macro_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(credentials, max_articles=macro_limit)
    summary_service = SummaryService(
        summary_settings=repository.get_summary_settings(),
        provider_credentials=credentials,
    )
    return MacroContextService(ContextSnapshotRepository(session), news_service=news_service, summary_service=summary_service)


def create_industry_support_service(session: Session) -> IndustrySupportRefreshService:
    repository = SettingsRepository(session)
    social_service = SocialIngestionService.from_settings(repository.get_social_settings())
    snapshot_repository = SupportSnapshotRepository(session)
    taxonomy_service = TickerTaxonomyService()
    return IndustrySupportRefreshService(
        snapshot_repository,
        social_service=social_service,
        taxonomy_service=taxonomy_service,
    )


def create_industry_context_service(session: Session) -> IndustryContextService:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    industry_limit = int(settings_map.get("news_industry_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(credentials, max_articles=industry_limit)
    summary_service = SummaryService(
        summary_settings=repository.get_summary_settings(),
        provider_credentials=credentials,
    )
    taxonomy_service = TickerTaxonomyService()
    return IndustryContextService(
        ContextSnapshotRepository(session),
        news_service=news_service,
        summary_service=summary_service,
        taxonomy_service=taxonomy_service,
    )

