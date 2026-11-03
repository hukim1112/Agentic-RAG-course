#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
===============================================================================
[MCP Skill] MCP Client Invocation (Streamable HTTP / SSE / Stdio)
===============================================================================
MCP 서버의 도구 하나를 JSON 인자로 실행하고 결과를 JSON으로 출력합니다.

인증이 필요한 서버는 --token-env로 토큰이 담긴 환경 변수 이름을 넘깁니다.
토큰 값은 이 스크립트 내부에서만 읽으므로, 에이전트의 프롬프트나 명령어에 노출되지 않습니다.
"""

import os
import sys
import json
import asyncio
import shlex
import argparse
from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.client.transports import StdioTransport


def resolve_auth(token_env):
    """환경 변수(또는 .env)에서 Bearer 토큰을 읽어 인증 객체를 만듭니다."""
    if not token_env:
        return None
    if not os.environ.get(token_env):
        try:
            from dotenv import load_dotenv, find_dotenv
            load_dotenv(find_dotenv(usecwd=True))
        except ImportError:
            pass
    token = os.environ.get(token_env)
    if not token:
        raise ValueError(f"환경 변수 '{token_env}'에 인증 토큰이 없습니다.")
    return BearerAuth(token)


async def run_tool(target: str, tool_name: str, arguments: dict, auth=None):
    if target.startswith("http://") or target.startswith("https://"):
        print(f"[*] Connecting to remote MCP Server: {target} ...", file=sys.stderr)
        client = Client(target, auth=auth)
    else:
        print(f"[*] Spawning local Stdio MCP Server via StdioTransport: {target} ...", file=sys.stderr)
        parts = shlex.split(target)
        transport = StdioTransport(command=parts[0], args=parts[1:])
        client = Client(transport)

    try:
        async with client:
            result = await client.call_tool(tool_name, arguments)

            content_str = str(result.content)
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
    parser.add_argument("--url", required=True, help="MCP server URL or Stdio command")
    parser.add_argument("--tool", required=True, help="MCP Tool Name")
    parser.add_argument("--args", required=True, help="JSON arguments string")
    parser.add_argument("--token-env", default=None, help="Bearer 토큰이 담긴 환경 변수 이름 (인증 서버용)")

    args = parser.parse_args()

    try:
        auth = resolve_auth(args.token_env)
        parsed_args = json.loads(args.args)
        result = asyncio.run(run_tool(args.url, args.tool, parsed_args, auth))
    except Exception as e:
        result = {"status": "ERROR", "message": str(e)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "SUCCESS":
        sys.exit(1)


if __name__ == "__main__":
    main()
