import asyncio
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from trade_proposer_app.api.routes.settings import list_settings
from trade_proposer_app.db import get_db_session
from trade_proposer_app.config import settings

async def test_list_settings():
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        result = await list_settings(session)
        print("Success:", result.keys())
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    asyncio.run(test_list_settings())
