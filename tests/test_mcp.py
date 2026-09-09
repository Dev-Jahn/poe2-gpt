import asyncio
import socket

import httpx
import uvicorn
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from poe2_companion.scout import Scout
from poe2_companion.server import build_server
from poe2_companion import __version__
from test_scout import Backend
from test_trade import TradeBackend
from test_equipment import NOW, imported, optimizer
from poe2_companion.trade import TradeClient
from poe2_companion.equipment import EquipmentService
from poe2_companion.access import CloudflareAccessMiddleware
from test_access import verifier, token


@pytest.mark.parametrize("authenticated", [False, True])
async def test_real_streamable_http_protocol(tmp_path, authenticated):
    scout = Scout(user_agent="test", transport=httpx.MockTransport(Backend()), interval=0)
    dataset_id, directory = imported(tmp_path)
    trade = TradeClient("test",transport=httpx.MockTransport(TradeBackend()),interval=0,clock=lambda:NOW)
    server = build_server(scout,equipment=EquipmentService(directory,scout,clock=lambda:NOW),trade=trade)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    access = verifier() if authenticated else None
    app = server.streamable_http_app()
    if access:
        app = CloudflareAccessMiddleware(app, access)
    http = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    task = asyncio.create_task(http.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not http.started:
                await asyncio.sleep(0.01)
        headers = {"Cf-Access-Jwt-Assertion": token()} if authenticated else {}
        async with httpx.AsyncClient(trust_env=False, headers=headers) as client:
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "POE2 GPT"
                    assert initialized.serverInfo.version == __version__
                    assert initialized.serverInfo.websiteUrl == "https://github.com/Dev-Jahn/poe2-gpt"
                    tool_list = await session.list_tools()
                    assert len(tool_list.tools) == 17
                    assert all(t.annotations.readOnlyHint for t in tool_list.tools)
                    found = await session.call_tool("search_currency_prices", {"query":"디바인", "category":"currency"})
                    assert not found.isError
                    item = found.structuredContent["items"][0]
                    quote = await session.call_tool("quote_currency_items", {"items":[{"item_id":item["item_id"],"category":"currency","quantity":2}]})
                    assert not quote.isError
                    assert quote.structuredContent["estimated_total"] == 2*item["unit_price"]
                    invalid = await session.call_tool("get_currency_prices", {"category":"currency","limit":10000})
                    assert invalid.isError
                    wrong = await session.call_tool("get_currency_prices", {"category":"currency","league":"does-not-exist"})
                    assert wrong.isError
                    listings = await session.call_tool("search_trade_equipment", {"request":{"category":"accessory.ring"}})
                    assert not listings.isError and listings.structuredContent["items"]
                    upgrade = await session.call_tool("recommend_trade_upgrades", {"request":{
                        "optimization":optimizer(dataset_id).model_dump(),"search_ids":[listings.structuredContent["search_id"]]}})
                    assert not upgrade.isError and upgrade.structuredContent["optimization"]["plans"]
            denied = await client.post(f"http://127.0.0.1:{port}/mcp", headers={"Host":"untrusted.example"}, json={})
            assert denied.status_code == 421
    finally:
        http.should_exit = True
        await task
        sock.close()
        await scout.close()
        await trade.close()
        if access:
            await access.close()
