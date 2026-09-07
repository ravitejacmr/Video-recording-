"""Validate the frozen server's actual MCP handshake/tool calls over stdio."""
import asyncio
from pathlib import Path
import sys
import tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run(executable,workspace):
    parameters = StdioServerParameters(command=str(Path(executable).resolve()),args=['--stdio','--workspace',workspace])
    async with stdio_client(parameters) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            listing = await session.list_tools()
            assert len(listing.tools)==24
            result = await session.call_tool('create_project',{'name':'Packaged MCP check'})
            assert not result.isError and result.structuredContent['project_id']
            print('Packaged MCP: 24 tools discovered; create_project passed.')

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='softenant-mcp-smoke-') as workspace:
        asyncio.run(run(sys.argv[1],workspace))
