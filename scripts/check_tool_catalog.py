"""Measure the complete configured MCP catalog without invoking any provider."""
import asyncio
import json
from types import SimpleNamespace

from poe2_companion.capabilities import CapabilitiesRequest, inventory, canonical
from poe2_companion.server import build_server


async def main():
    stub=SimpleNamespace()
    server=build_server(stub,build_reader=stub,equipment=stub,trade=stub,
        engine=stub,characters=stub,accounts=stub)
    report=await inventory(server,CapabilitiesRequest(),{})
    sizes=[{'tool':tool.name,'bytes':len(canonical(tool.model_dump(mode='json',exclude_none=True)).encode())}
        for tool in await server.list_tools()]
    print(json.dumps({**report.model_dump(include={'server_version','configured_tool_count',
        'tool_catalog_bytes','input_schema_bytes','output_schema_bytes','description_bytes',
        'catalog_size_encoding','model_context_loading'}),
        'largest_tools':sorted(sizes,key=lambda row:row['bytes'],reverse=True)[:5]},indent=2))
    # A project regression budget, not a claimed ChatGPT or MCP protocol limit.
    assert report.tool_catalog_bytes<=900_000, 'Review catalog growth before increasing the project budget'


if __name__=='__main__':
    asyncio.run(main())
