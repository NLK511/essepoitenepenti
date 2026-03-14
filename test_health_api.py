import asyncio
from trade_proposer_app.api.routes.health import prototype_health

async def test_prototype_health():
    try:
        result = await prototype_health()
        print("Success:", result.status)
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_prototype_health())
