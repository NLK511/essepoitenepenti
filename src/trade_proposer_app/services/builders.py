from sqlalchemy.orm import Session

from trade_proposer_app.repositories.sentiment_snapshots import SentimentSnapshotRepository
from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.macro_sentiment import MacroSentimentService
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.proposals import ProposalService
from trade_proposer_app.services.signals import SignalIngestionService
from trade_proposer_app.services.snapshot_resolver import SentimentSnapshotResolver
from trade_proposer_app.services.social import SocialIngestionService
from trade_proposer_app.services.summary import SummaryService


def create_proposal_service(session: Session) -> ProposalService:
    """Create the app-native proposal service with configured news and social ingestion."""
    repository = SettingsRepository(session)
    credentials = repository.get_provider_credential_map()
    news_service = NewsIngestionService.from_provider_credentials(credentials)
    social_service = SocialIngestionService.from_settings(repository.get_social_settings())
    signal_service = SignalIngestionService(social_service=social_service)
    summary_service = SummaryService(
        summary_settings=repository.get_summary_settings(),
        provider_credentials=credentials,
    )
    snapshot_resolver = SentimentSnapshotResolver(SentimentSnapshotRepository(session))
    return ProposalService(
        news_service=news_service,
        social_service=social_service,
        signal_service=signal_service,
        summary_service=summary_service,
        snapshot_resolver=snapshot_resolver,
    )


def create_macro_sentiment_service(session: Session) -> MacroSentimentService:
    repository = SettingsRepository(session)
    credentials = repository.get_provider_credential_map()
    news_service = NewsIngestionService.from_provider_credentials(credentials)
    social_service = SocialIngestionService.from_settings(repository.get_social_settings())
    snapshot_repository = SentimentSnapshotRepository(session)
    return MacroSentimentService(snapshot_repository, social_service=social_service, news_service=news_service)
