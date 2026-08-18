#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MCP Client Tool Invocation Script (HTTP / SSE / Stdio)
"""

import sys
import json
import asyncio
import shlex
import argparse
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def run_tool(target: str, tool_name: str, arguments: dict):
    if target.startswith("http://") or target.startswith("https://"):
        client = Client(target)
    else:
        parts = shlex.split(target)
        transport = StdioTransport(command=parts[0], args=parts[1:])
        client = Client(transport)
        
    try:
        async with client:
            result = await client.call_tool(tool_name, arguments)
            
            content_str = str(result.content) if hasattr(result, "content") else str(result.data if hasattr(result, "data") else result)
            try:
                if hasattr(result, "content") and isinstance(result.content, list):
                    content_str = "\n".join([item.text for item in result.content if hasattr(item, "text")])
            except Exception:
                pass
                
            return {
                "status": "SUCCESS",
                "mcp_target": target,
                "tool_name": tool_name,
                "output": content_str
            }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Failed to execute tool '{tool_name}' on '{target}': {str(e)}"
        }


def main():
    parser = argparse.ArgumentParser(description="MCP tool executor")
    parser.add_argument("--url", required=True, help="MCP HTTP/SSE URL or Stdio command")
    parser.add_argument("--tool", required=True, help="MCP Tool Name")
    parser.add_argument("--args", required=True, help="JSON arguments string")
    
    args = parser.parse_args()
    
    try:
        parsed_args = json.loads(args.args)
        result = asyncio.run(run_tool(args.url, args.tool, parsed_args))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "ERROR", "message": str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
