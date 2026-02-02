import asyncio
import json

import httpx

class ConfigClient:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url)

    async def get_config(self) -> list[str]:
        r = await self._client.get("/config")
        r.raise_for_status()
        return r.json()

    async def get(self, file: str) -> str:
        r = await self._client.get("/", params={"file": file})
        r.raise_for_status()
        return r.text

    async def close(self):
        await self._client.aclose()

async def load_ice_servers(base_url: str):
    cli = ConfigClient(base_url)
    try:
        files = await cli.get_config()
        return [
            json.loads(await cli.get(f))
            for f in files
        ]
    finally:
        await cli.close()


if __name__ == "__main__":
    async def main():
        c = ConfigClient("http://127.0.0.1:8080")

        files = await c.get_config()
        print("config:", files)

        for f in files:
            text = await c.get(f)
            print(f"\n==== {f} ====\n{text}")

        await c.close()
    asyncio.run(main())