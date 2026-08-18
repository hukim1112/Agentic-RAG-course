#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Client Discovery Script (HTTP / SSE / Stdio)
"""

import sys
import json
import asyncio
import shlex
import argparse
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def fetch_tools(target: str):
    if target.startswith("http://") or target.startswith("https://"):
        client = Client(target)
    else:
        parts = shlex.split(target)
        transport = StdioTransport(command=parts[0], args=parts[1:])
        client = Client(transport)
        
    try:
        async with client:
            tools_response = await client.list_tools()
            
            tools_list = []
            for t in tools_response:
                tools_list.append({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": getattr(t, "inputSchema", getattr(t, "parameters", {}))
                })
            
            return {
                "status": "SUCCESS",
                "mcp_target": target,
                "tools": tools_list
            }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Failed to retrieve tools from '{target}': {str(e)}"
        }


def main():
    parser = argparse.ArgumentParser(description="MCP tools lister")
    parser.add_argument("--url", required=True, help="MCP HTTP/SSE URL or Stdio command")
    
    args = parser.parse_args()
    
    try:
        result = asyncio.run(fetch_tools(args.url))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "ERROR", "message": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
