import httpx

from poe2_companion.trade import TradeClient, TradeSearchRequest, TradeDetailRequest
from test_trade import TradeBackend, listing


async def test_advanced_query_and_complete_listing_description():
    row=listing(1)
    row['item'].update(name='Synthetic Unique',typeLine='Gold Ring',ilvl=82,frameType=3)
    # Unsupported socketed jewel import must not hide the item's description.
    row['item']['socketedItems']=[{'baseType':'Ruby','socket':0}]
    row['item']['explicitMods'].append('A special unrecognized game modifier')
    backend=TradeBackend([row])
    def respond(request):
        if request.url.path.endswith('/data/stats'):
            return httpx.Response(200,json={'result':[{'id':'explicit','entries':[
                {'id':'explicit.life','text':'+# to maximum Life'},
                {'id':'explicit.fire','text':'+#% to Fire Resistance'}]}]})
        return backend(request)
    client=TradeClient('test',transport=httpx.MockTransport(respond),interval=0)
    try:
        request=TradeSearchRequest(category='accessory.ring',exact_name='Synthetic Unique',base_type='Gold Ring',
            item_level_min=80,item_level_max=85,sort_by='ilvl',sort_direction='desc',
            stat_groups=[{'type':'count','minimum_match':1,'filters':[
                {'stat_id':'explicit.life','minimum':80},{'stat_id':'explicit.fire','minimum':20}]}])
        query=await client.query(request)
        assert query['query']['name']=='Synthetic Unique'
        assert query['query']['type']=='Gold Ring'
        assert any(group['filters'].get('ilvl')=={'min':80,'max':85} for group in query['query']['filters'].values())
        assert query['query']['stats'][1]['value']=={'min':1}
        assert query['sort']=={'ilvl':'desc'}
        result=await client.search(request)
        offset,mods=0,[]
        while offset is not None:
            page=await client.detail(TradeDetailRequest(search_id=result.search_id,listing_ref=row['id'],offset=offset,limit=1))
            mods.extend(page.modifiers)
            assert 'PRIVATE_ACCOUNT' not in page.model_dump_json()
            offset=page.next_offset
        assert len(mods)==3 and mods[0].stat_ids==['explicit.life']
        assert mods[2].status=='unrecognized' and mods[2].text==row['item']['explicitMods'][2]
        assert result.items[0].item_stats and not result.items[0].proxy_optimization_eligible
    finally:
        await client.close()
