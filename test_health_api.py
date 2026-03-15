import asyncio
from trade_proposer_app.api.routes.health import preflight_health

async def test_preflight_health():
    try:
        result = await preflight_health()
        print("Success:", result.status)
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_preflight_health())
