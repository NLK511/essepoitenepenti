from sqlalchemy.orm import Session

from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.repositories.effective_plan_outcomes import EffectivePlanOutcomeRepository
from trade_proposer_app.repositories.recommendation_decision_samples import RecommendationDecisionSampleRepository
from trade_proposer_app.repositories.recommendation_plans import RecommendationPlanRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.repositories.broker_order_executions import BrokerOrderExecutionRepository
from trade_proposer_app.repositories.broker_positions import BrokerPositionRepository
from trade_proposer_app.services.alpaca_paper_client import AlpacaPaperClient
from trade_proposer_app.services.industry_context import IndustryContextService
from trade_proposer_app.services.industry_context_refresh import IndustryContextRefreshService
from trade_proposer_app.services.macro_context import MacroContextService
from trade_proposer_app.services.macro_context_refresh import MacroContextRefreshService
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.order_execution import OrderExecutionService
from trade_proposer_app.services.proposals import ProposalService
from trade_proposer_app.services.signals import SignalIngestionService
from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService
from trade_proposer_app.services.context_snapshot_resolver import ContextSnapshotResolver
from trade_proposer_app.services.social import SocialIngestionService
from trade_proposer_app.services.settings_domains import SettingsDomainService
from trade_proposer_app.services.summary import SummaryService
from trade_proposer_app.services.taxonomy import TickerTaxonomyService
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService
from trade_proposer_app.services.trade_decision_policy import TradeDecisionPolicyService
from trade_proposer_app.services.watchlist_cheap_scan import CheapScanSignalService
from trade_proposer_app.services.watchlist_orchestration import WatchlistOrchestrationService


def create_proposal_service(session: Session) -> ProposalService:
    """Create the app-native proposal service with configured news and social ingestion."""
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    ticker_limit = int(settings_map.get("news_ticker_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(
        credentials,
        max_articles=ticker_limit,
        historical_news=HistoricalNewsRepository(session),
    )
    operator_settings = SettingsDomainService(repository=repository).operator_settings()
    social_service = SocialIngestionService.from_settings(operator_settings.social)
    signal_service = SignalIngestionService(social_service=social_service)
    summary_service = SummaryService(
        summary_settings=operator_settings.summary,
        provider_credentials=credentials,
    )
    taxonomy_service = TickerTaxonomyService()
    snapshot_resolver = ContextSnapshotResolver(
        ContextSnapshotRepository(session),
        taxonomy_service=taxonomy_service,
    )
    return ProposalService(
        news_service=news_service,
        social_service=social_service,
        signal_service=signal_service,
        summary_service=summary_service,
        snapshot_resolver=snapshot_resolver,
        historical_market_data=HistoricalMarketDataRepository(session),
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
    trade_decision_policy = TradeDecisionPolicyService(session).active_policy()

    return WatchlistOrchestrationService(
        context_snapshots=ContextSnapshotRepository(session),
        recommendation_plans=RecommendationPlanRepository(session),
        decision_samples=RecommendationDecisionSampleRepository(session),
        cheap_scan_service=CheapScanSignalService(repository=HistoricalMarketDataRepository(session)),
        deep_analysis_service=create_ticker_deep_analysis_service(session, proposal_service=proposal_service),
        trade_decision_policy=trade_decision_policy,
        calibration_service=RecommendationPlanCalibrationService(EffectivePlanOutcomeRepository(session)),
    )


def create_macro_context_refresh_service(session: Session) -> MacroContextRefreshService:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    macro_limit = int(settings_map.get("news_macro_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(
        credentials,
        max_articles=macro_limit,
        historical_news=HistoricalNewsRepository(session),
    )
    operator_settings = SettingsDomainService(repository=repository).operator_settings()
    social_service = SocialIngestionService.from_settings(operator_settings.social)
    return MacroContextRefreshService(social_service=social_service, news_service=news_service)


def create_order_execution_service(session: Session) -> OrderExecutionService:
    repository = SettingsRepository(session)
    credentials = repository.get_provider_credential_map()
    alpaca = credentials.get("alpaca")
    client = None
    if alpaca and alpaca.api_key and alpaca.api_secret:
        client = AlpacaPaperClient(api_key=alpaca.api_key, api_secret=alpaca.api_secret)
    return OrderExecutionService(
        settings=repository,
        executions=BrokerOrderExecutionRepository(session),
        client=client,
        positions=BrokerPositionRepository(session),
    )


def create_macro_context_service(session: Session) -> MacroContextService:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    macro_limit = int(settings_map.get("news_macro_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(
        credentials,
        max_articles=macro_limit,
        historical_news=HistoricalNewsRepository(session),
    )
    summary_service = SummaryService(
        summary_settings=SettingsDomainService(repository=repository).operator_settings().summary,
        provider_credentials=credentials,
    )
    return MacroContextService(ContextSnapshotRepository(session), news_service=news_service, summary_service=summary_service)


def create_industry_context_refresh_service(session: Session) -> IndustryContextRefreshService:
    repository = SettingsRepository(session)
    social_service = SocialIngestionService.from_settings(SettingsDomainService(repository=repository).operator_settings().social)
    taxonomy_service = TickerTaxonomyService()
    return IndustryContextRefreshService(
        social_service=social_service,
        taxonomy_service=taxonomy_service,
    )


def create_industry_context_service(session: Session) -> IndustryContextService:
    repository = SettingsRepository(session)
    settings_map = repository.get_setting_map()
    credentials = repository.get_provider_credential_map()
    industry_limit = int(settings_map.get("news_industry_article_limit", "12"))
    news_service = NewsIngestionService.from_provider_credentials(
        credentials,
        max_articles=industry_limit,
        historical_news=HistoricalNewsRepository(session),
    )
    summary_service = SummaryService(
        summary_settings=SettingsDomainService(repository=repository).operator_settings().summary,
        provider_credentials=credentials,
    )
    taxonomy_service = TickerTaxonomyService()
    return IndustryContextService(
        ContextSnapshotRepository(session),
        news_service=news_service,
        summary_service=summary_service,
        taxonomy_service=taxonomy_service,
    )

