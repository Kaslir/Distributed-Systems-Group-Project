import argparse
import asyncio
from collections import Counter

import aiohttp


async def fetch(session: aiohttp.ClientSession, url: str) -> str:
    # Return the responding server's label so callers can measure distribution
    async with session.get(url) as response:
        data = await response.json()
        return data.get("message", "unknown")


async def run(url: str, requests: int, concurrency: int) -> Counter:
    counter: Counter = Counter()
    # The connector caps simultaneous connections while the full request set is queued
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        pending = [fetch(session, url) for _ in range(requests)]
        # Count results as requests finish rather than waiting for submission order
        for task in asyncio.as_completed(pending):
            try:
                counter[await task] += 1
            except Exception as exc:
                counter[f"ERROR: {exc}"] += 1
    return counter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:5000/home")
    parser.add_argument("--requests", type=int, default=10000)
    parser.add_argument("--concurrency", type=int, default=200)
    args = parser.parse_args()

    counts = asyncio.run(run(args.url, args.requests, args.concurrency))
    for server, count in counts.most_common():
        print(f"{server}: {count}")


if __name__ == "__main__":
    main()
