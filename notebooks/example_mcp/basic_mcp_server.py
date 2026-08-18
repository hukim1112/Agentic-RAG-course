"""A minimal FastMCP server that exposes two simple tools."""

from fastmcp import FastMCP
import argparse

app = FastMCP(
    name="fastmcp-tool-demo",
    instructions="Simple demo MCP server with greeting and todo helper tools.",
)

@app.tool
def greet(name: str) -> str:
    return f"안녕하세요, {name}! FastMCP에 오신 것을 환영해요."

@app.tool(description="Collect action items from a short note.")
def extract_todos(note: str) -> list[str]:
    todos: list[str] = []
    for line in note.splitlines():
        line = line.strip("- •* ")
        if not line:
            continue
        if any(keyword in line.lower() for keyword in ["해야", "todo", "action", "해야 할"]):
            todos.append(line)
    if not todos:
        todos.append("추가할 할일이 보이지 않아요. 메모를 다시 확인해 주세요.")
    return todos

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=6001, help="Port to run MCP server on")
    args = parser.parse_args()

    app.run(transport="http", port=args.port)
