import os, asyncio, json, argparse
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.panel import Panel
from pathlib import Path
import sys
from rich.console import Console
console = Console(file=sys.stderr)
load_dotenv()

async def main():
    ap = argparse.ArgumentParser(description="Evaluate a student prompt via MCP tool")
    ap.add_argument("-f","--file",required=True, help="Path to a text file with the student prompt")
    args = ap.parse_args()

    student_text = Path(args.file).read_text(encoding="utf-8")
    import os
    # Build a minimal env for the child:
    child_env = {
        "GEMINI_API_KEY": os.environ["GEMINI_API_KEY"],  # will raise if missing
        "LLM_MODEL": os.environ.get("LLM_MODEL", "gemini-2.0-flash"),
        # add anything else you truly need
    }

    server_params = StdioServerParameters(
        command="python",
        args=["tools/eval_tools.py"],
        env=child_env,   # <-- only these keys are passed down
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            console.print(Panel.fit("Calling evaluate_prompt(...) via MCP", border_style="cyan"))
            res = await session.call_tool("evaluate_prompt", arguments={"student_prompt": student_text})

            text = res.content[0].text if res and res.content else "{}"
            try:
                data = json.loads(text)
                out = Path("outputs") / (Path(args.file).stem + ".json")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                console.print(Panel.fit(f"Saved JSON → {out}", border_style="green"))
                console.print_json(data=data)
            except Exception:
                out = Path("outputs") / (Path(args.file).stem + ".txt")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                console.print(Panel.fit(f"Saved raw text → {out}", border_style="yellow"))

if __name__ == "__main__":
    asyncio.run(main())
