from sqlalchemy.orm import Session

from trade_proposer_app.repositories.settings import SettingsRepository
from trade_proposer_app.services.news import NewsIngestionService
from trade_proposer_app.services.proposals import ProposalService
from trade_proposer_app.services.summary import SummaryService


def create_proposal_service(session: Session) -> ProposalService:
    """Create the app-native proposal service with configured news ingestion."""
    repository = SettingsRepository(session)
    credentials = repository.get_provider_credential_map()
    news_service = NewsIngestionService.from_provider_credentials(credentials)
    summary_service = SummaryService(
        summary_settings=repository.get_summary_settings(),
        provider_credentials=credentials,
    )
    return ProposalService(news_service=news_service, summary_service=summary_service)
