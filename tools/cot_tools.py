from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from rich.console import Console
from rich.panel import Panel
import sys, re

# IMPORTANT: log to STDERR so MCP JSON-RPC on STDOUT isn't polluted
console = Console(file=sys.stderr)
mcp = FastMCP("CoTCalculator")

ALLOWED_EXPR = re.compile(r"^[0-9.\s+\-*/%()]+$")  # only arithmetic tokens

@mcp.tool()
def show_reasoning(steps: list) -> TextContent:
    """Show the step-by-step reasoning process"""
    console.print(Panel("Showing reasoning steps", border_style="cyan"))
    for i, step in enumerate(steps, 1):
        console.print(Panel(f"{step}", title=f"Step {i}", border_style="cyan"))
    return TextContent(type="text", text="Reasoning shown")

@mcp.tool()
def calculate(expression: str) -> TextContent:
    """Calculate the result of an expression"""
    expression = (expression or "").strip()
    if not ALLOWED_EXPR.match(expression):
        return TextContent(type="text", text="Error: disallowed characters in expression")
    try:
        # sandbox eval: demo-only
        result = eval(expression, {"__builtins__": {}}, {})
        console.print(Panel(f"Calculating: {expression} = {result}", border_style="green"))
        return TextContent(type="text", text=str(result))
    except Exception as e:
        console.print(Panel(f"Error: {e}", border_style="red"))
        return TextContent(type="text", text=f"Error: {str(e)}")

@mcp.tool()
def verify(expression: str, expected: float) -> TextContent:
    """Verify if a calculation is correct"""
    expression = (expression or "").strip()
    if not ALLOWED_EXPR.match(expression):
        return TextContent(type="text", text="Error: disallowed characters in expression")
    try:
        actual = float(eval(expression, {"__builtins__": {}}, {}))
        ok = abs(actual - float(expected)) < 1e-10
        if ok:
            console.print(Panel(f"✓ Verified: {expression} = {expected}", border_style="green"))
        else:
            console.print(Panel(f"✗ Mismatch: {expression} evaluated to {actual}, expected {expected}", border_style="red"))
        return TextContent(type="text", text=str(ok))
    except Exception as e:
        console.print(Panel(f"Error: {e}", border_style="red"))
        return TextContent(type="text", text=f"Error: {str(e)}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()
    else:
        mcp.run(transport="stdio")
