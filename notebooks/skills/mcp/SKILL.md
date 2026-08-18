---
name: mcp
description: "Model Context Protocol (MCP) dynamic interface skill. Use when the agent needs to dynamically discover, list, or execute tools on remote SSE/HTTP or local Stdio MCP servers (e.g. Finance, DB, Utilities) without hardcoded static tool schemas."
---

# MCP (Model Context Protocol) Interface Skill

This skill allows the agent to dynamically inspect and interact with any active Model Context Protocol (MCP) servers (HTTP/SSE or Stdio).

## Core Principle (Progressive Disclosure)
Instead of statically binding all tools to the agent context, follow this 3-step workflow:
1. **Server Identification**: Check `skills/mcp/references/mcp_servers.json` to find the target MCP server URL or endpoint.
2. **Tool Discovery**: Run `list_tools.py` to inspect available tool names, descriptions, and JSON parameter schemas on that server.
3. **Tool Execution**: Run `execute_tool.py` with the exact tool name and JSON arguments string.

## CLI Scripts

All scripts are located in `skills/mcp/scripts/` and should be executed using Python 3:

### 1. Discover Tools (`list_tools.py`)
- **Purpose**: Retrieves all tools and parameter schemas from a target MCP server.
- **Command**:
  ```bash
  python skills/mcp/scripts/list_tools.py --url <MCP_SERVER_URL>
  ```
- **Example**:
  ```bash
  python skills/mcp/scripts/list_tools.py --url http://localhost:6002/mcp
  ```

### 2. Execute Tool (`execute_tool.py`)
- **Purpose**: Executes a specific tool on the target MCP server with JSON parameters.
- **Command**:
  ```bash
  python skills/mcp/scripts/execute_tool.py --url <MCP_SERVER_URL> --tool <TOOL_NAME> --args '<JSON_STRING>'
  ```
- **Example**:
  ```bash
  python skills/mcp/scripts/execute_tool.py \
    --url http://localhost:6002/mcp \
    --tool stock_data \
    --args '{"input": "AAPL, NVDA"}'
  ```

## Reference Servers
See `skills/mcp/references/mcp_servers.json` for active local and remote server endpoints.
