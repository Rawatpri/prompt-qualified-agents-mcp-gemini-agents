import os, asyncio, re, json, time
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.panel import Panel
import sys
from rich.console import Console
console = Console(file=sys.stderr)
load_dotenv()

# --- Gemini only ---
from google import genai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-1.5-flash")
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))
client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = (
    "You are a mathematical reasoning agent that solves problems step by step.\n"
    "TOOLS:\n"
    "- show_reasoning(steps: list)  # steps must be a JSON array of strings\n"
    "- calculate(expression: str)   # arithmetic only: digits, + - * / % ( ) . and spaces\n"
    "- verify(expression: str, expected: float)\n\n"
    "- Never call verify on the same expression more than once. If an expression has been verified, proceed to the next step."
    "RULES:\n"
    "1) Never output prose, markdown, or code blocks.\n"
    "2) Respond with EXACTLY ONE line per turn in one of these formats:\n"
    "   FUNCTION_CALL: function_name|param1|param2|...\n"
    "   FINAL_ANSWER: [answer]\n"
    "3) If your last output violated the format, immediately output a corrected single line now.\n"
    "4) First show_reasoning (JSON array), then calculate, then verify each step, then final answer.\n"
)

ALLOWED_EXPR = re.compile(r"^[0-9.\s+\-*/%()]+$")

def first_line(s: str) -> str:
    return (s or "").splitlines()[0].strip()

def strip_code_fences(s: str) -> str:
    return re.sub(r"```.*?```", "", s or "", flags=re.S)

def clean_arg(s: str) -> str:
    s = strip_code_fences(s).strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1].strip()
    return s

def sanitize_expr(expr: str) -> str:
    expr = clean_arg(expr)
    if not ALLOWED_EXPR.match(expr):
        raise ValueError(f"Unsafe or invalid expression: {expr!r}")
    return expr

def parse_steps(steps_txt: str):
    steps_txt = clean_arg(steps_txt)
    steps = json.loads(steps_txt)
    if not isinstance(steps, list) or not all(isinstance(x, str) for x in steps):
        raise ValueError("steps must be a JSON array of strings.")
    return steps

def llm_call_sync(prompt: str):
    # Backoff on 429/RESOURCE_EXHAUSTED
    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = client.models.generate_content(model=LLM_MODEL, contents=prompt)
            text = getattr(resp, "text", None)
            return text.strip() if text else None
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "RetryInfo" in msg:
                time.sleep(10 * (attempt + 1))  # 10s, 20s, 30s, ...
                continue
            console.print(Panel(f"LLM Error: {e}", border_style="red"))
            return None
    return None

async def generate_with_timeout(prompt, timeout=90):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: llm_call_sync(prompt))

async def main():
    problem = os.getenv("MATH_PROBLEM", "(23 + 7) * (15 - 8)")
    console.print(Panel(f"Problem: {problem}", border_style="cyan"))
    server_params = StdioServerParameters(command="python", args=["tools/cot_tools.py"])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            prompt = f"{SYSTEM_PROMPT}\n\nSolve this problem step by step: {problem}"
            history = []

            while True:
                result = await generate_with_timeout(prompt)
                if not result:
                    break
                result = first_line(result)
                console.print(f"[yellow]Assistant:[/yellow] {result}")

                if result.startswith("FUNCTION_CALL:"):
                    _, info = result.split(":", 1)
                    parts = [p.strip() for p in info.split("|")]
                    fn = parts[0]

                    if fn == "show_reasoning":
                        try:
                            steps = parse_steps(parts[1])
                        except Exception as e:
                            prompt += f"\nUser: steps must be JSON array of strings ({e}). Return: FUNCTION_CALL: show_reasoning|[\"step1\",\"step2\"]"
                            continue
                        await session.call_tool("show_reasoning", arguments={"steps": steps})
                        prompt += "\nUser: Next step?"

                    elif fn == "calculate":
                        try:
                            expr = sanitize_expr(parts[1])
                        except Exception as e:
                            prompt += f"\nUser: Invalid expression ({e}). Return: FUNCTION_CALL: calculate|<digits and + - * / % ( ) . only>"
                            continue
                        calc = await session.call_tool("calculate", arguments={"expression": expr})
                        if calc.content:
                            val_txt = (calc.content[0].text or "").strip()
                            if val_txt.startswith("Error:"):
                                prompt += f"\nUser: Tool error ({val_txt}). Retry with clean arithmetic."
                                continue
                            try:
                                val = float(val_txt)
                            except Exception:
                                prompt += f"\nUser: Non-numeric output ({val_txt}). Retry calculate."
                                continue
                            prompt += f"\nUser: Result is {val}. Let's verify this step."
                            history.append((expr, val))

                    elif fn == "verify":
                        try:
                            expr = sanitize_expr(parts[1])
                            expected = float(clean_arg(parts[2]))
                        except Exception:
                            prompt += "\nUser: verify expected must be numeric and expr arithmetic-only. Retry verify."
                            continue
                        await session.call_tool("verify", arguments={"expression": expr, "expected": expected})
                        prompt += "\nUser: Verified. Next step?"

                elif result.startswith("FINAL_ANSWER:"):
                    try:
                        final = float(result.split("[", 1)[1].split("]", 1)[0])
                    except Exception:
                        prompt += "\nUser: FINAL_ANSWER must be like: FINAL_ANSWER: [123.45]"
                        continue
                    if history:
                        await session.call_tool("verify", arguments={"expression": problem, "expected": final})
                    break

                prompt += f"\nAssistant: {result}"

    console.print(Panel("Calculation completed!", border_style="green"))

if __name__ == "__main__":
    asyncio.run(main())
