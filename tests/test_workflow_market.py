"""Provider cooldowns retain useful pages and repeated failures are bounded."""
import httpx
import pytest
from poe2_companion.trade import TradeClient, TradePageRequest, TradeSearchRequest, TradeError
from test_trade import TradeBackend


async def test_cooldown_and_blocked_metadata_preserve_cached_pages():
    backend = TradeBackend()
    client = TradeClient('synthetic',transport=httpx.MockTransport(backend),interval=0)
    try:
        request = TradeSearchRequest(category='accessory.ring')
        first = await client.search(request)
        before = len(backend.requests)
        client.metadata.clear()
        client.gate.until = client.gate.clock()+120
        client.blocked = 'trade_interactive_verification_required'
        cached = await client.search(request)
        assert cached.search_id == first.search_id and cached.items == first.items
        partial = await client.page(TradePageRequest(search_id=first.search_id,offset=3))
        assert len(partial.items) == 2 and partial.deferred_listing_count == 3
        assert partial.unavailable_or_unparsed_in_page == 0
        assert partial.provider_action == 'operator_configuration_required'
        assert partial.cache_state == 'partial_cached_page' and partial.page_offset == 3
        assert len(backend.requests) == before
    finally: await client.close()


async def test_zero_query_explains_constraints_and_does_not_relax_buyout():
    backend = TradeBackend()
    def response(request):
        if '/search/' in request.url.path:
            backend.requests.append(request)
            return httpx.Response(200,json={'id':'empty','result':[],'total':0})
        return backend(request)
    client = TradeClient('synthetic',transport=httpx.MockTransport(response),interval=0)
    try:
        result = await client.search(TradeSearchRequest(category='accessory.ring',base_type='Gold Ring',
            price_max={'amount':1.0,'currency':'divine'}))
        assert result.items == [] and result.total_matches == 0
        assert result.empty_result_scope == 'exact_query_filters_only'
        assert not result.market_has_no_matching_items_globally and result.instant_buyout_only
        assert {s.field for s in result.relaxation_suggestions} == {'base_type','price_max'}
        assert all(not s.new_search_performed for s in result.relaxation_suggestions)
        assert len([r for r in backend.requests if r.method == 'POST']) == 1
    finally: await client.close()


async def test_same_failed_query_stops_after_two_attempts():
    backend = TradeBackend()
    def response(request):
        if '/search/' in request.url.path:
            backend.requests.append(request)
            return httpx.Response(400,json={'error':{'code':2}})
        return backend(request)
    client = TradeClient('synthetic',transport=httpx.MockTransport(response),interval=0)
    request = TradeSearchRequest(category='accessory.ring')
    try:
        for _ in range(2):
            with pytest.raises(TradeError,match='trade_invalid_query'): await client.search(request)
        count = len(backend.requests)
        with pytest.raises(TradeError,match='trade_repeated_query_failed') as caught: await client.search(request)
        assert len(backend.requests) == count and caught.value.retry_after > 0
    finally: await client.close()
