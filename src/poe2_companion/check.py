"""Explicit live preflight. A failing request yields a nonzero exit status."""
import argparse
import asyncio
import json
import os
import sys
from .scout import CATEGORIES, Scout, ScoutError


async def check(league: str, all_categories: bool):
    scout = Scout(user_agent=os.environ.get("POE2_USER_AGENT", "poe2-companion/0.4.0 (contact: https://github.com/Dev-Jahn)"))
    try:
        catalog = await scout.catalog(league)
        available = {v["api_id"] for v in catalog["data"]["categories"]}
        selected = list(CATEGORIES) if all_categories else ["currency"]
        results = []
        for category in selected:
            if category not in available:
                results.append({"category": category, "status": "not_priced_in_league"})
                continue
            data = await scout.prices(category, league, "exalted", limit=1)
            results.append({"category": category, "status": "ok", "count": data["data"]["matched_total"],
                            "retrieved_at": data["retrieved_at"]})
        divine = await scout.search("디바인", league, category="currency")
        if len(divine["items"]) != 1:
            raise ScoutError("smoke_failed", "Divine Orb did not resolve uniquely.")
        quote = await scout.quote([{"item_id": divine["items"][0]["item_id"], "category": "currency", "quantity": 2}], league)
        print(json.dumps({"status": "ok", "league": catalog["data"]["league"]["value"],
                          "categories": results, "divine_quote": quote}, ensure_ascii=False, indent=2))
    finally:
        await scout.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", default="Forbidden Rites")
    parser.add_argument("--all-categories", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(check(args.league, args.all_categories))
    except ScoutError as exc:
        print(json.dumps({"status":"failed", "code":exc.code, "message":str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
