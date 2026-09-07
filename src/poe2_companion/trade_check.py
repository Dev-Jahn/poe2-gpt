"""User-invoked homelab preflight for the experimental trade2 client."""
import argparse
import asyncio
import json
import os

from .trade import TradeClient, TradeError, TradeSearchRequest


async def check(search=False):
    client=TradeClient(os.environ.get("POE2_USER_AGENT","poe2-companion/0.4.0 (contact: https://github.com/Dev-Jahn)"))
    try:
        leagues=await client.data("leagues")
        filters=await client.data("filters")
        stats=await client.stats()
        result={"status":"ok","leagues":len(leagues),"filter_groups":len(filters),"numeric_stat_ids":len(stats),
            "search_tested":False,"authentication_cookies_sent":False}
        if search:
            page=await client.search(TradeSearchRequest(category="armour.helmet",rarity="rare",max_results=5))
            result.update(search_tested=True,matched_total=page.total_matches,returned=len(page.items),unparsed=page.unavailable_or_unparsed_in_page)
        return result
    except TradeError as error:
        return {"status":error.code,"retry_after_seconds":error.retry_after}
    finally:
        await client.close()


def main():
    parser=argparse.ArgumentParser(description="Check trade2 metadata; optionally issue one limited equipment search.")
    parser.add_argument("--search",action="store_true")
    args=parser.parse_args()
    result=asyncio.run(check(args.search))
    print(json.dumps(result))
    raise SystemExit(0 if result["status"]=="ok" else 1)


if __name__=="__main__":
    main()
