# examples/srs_agent_client.py
import os, asyncio, json
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Gemini (google-genai)
from google import genai

# ---------- setup ----------
console = Console()
load_dotenv()

# Read markdown source (file or fallback)
MD_FILE = os.getenv("SRS_MD_FILE", "examples/cards.md")
if Path(MD_FILE).exists():
    EXAMPLE_MD = Path(MD_FILE).read_text(encoding="utf-8")
else:
    EXAMPLE_MD = (
        "Q: What is Bayes' theorem?\n"
        "A: P(A|B) = [P(B|A) * P(A)] / P(B)\n\n"
        "Q: Define precision in classification.\n"
        "A: TP / (TP + FP)\n\n"
        "Q: What does 'idempotent' mean in computing?\n"
        "A: An operation that can be applied multiple times without changing the result beyond the initial application.\n"
    )

# Gemini client
MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

# Strict system prompt (prevents invented args & enforces pipeline)
SYSTEM_PROMPT = (
    "You are an SRS Assistant that turns markdown Q/A into a spaced-repetition deck.\n"
    "TOOLS:\n"
    "- parse_markdown(md: str) -> JSON {'cards': [{q,a}]}\n"
    "- quality_check(cards_json: str, min_len:int=3, max_len:int=260) -> JSON {'ok': bool, 'errors': []}\n"
    "- schedule_cards(cards_json: str, start_date: str, daily_new:int, intervals:str) -> JSON {'scheduled': [...]}\n"
    "- export_csv(scheduled_json: str, filename: str) -> path\n\n"
    "PIPELINE (follow exactly): parse_markdown → quality_check → schedule_cards → export_csv → FINAL_ANSWER.\n\n"
    "STRICT OUTPUT: ONE line per turn, exactly one of:\n"
    "  FUNCTION_CALL: function_name|param1|param2|...\n"
    "  FINAL_ANSWER: [count]\n\n"
    "HARD RULES:\n"
    "1) Do NOT invent inputs. NEVER add extra labels like 'md|' and NEVER change argument counts.\n"
    "   - parse_markdown MUST take exactly 1 argument: the provided markdown string.\n"
    "   - quality_check MUST take exactly 3 args: cards_json, 3, 260.\n"
    "   - schedule_cards MUST take exactly 4 args: cards_json, YYYY-MM-DD, daily_new (<=20), '1,3,7,14,30'.\n"
    "   - export_csv MUST take exactly 2 args: scheduled_json, 'outputs/flashcards_schedule.csv'.\n"
    "2) Pass the previous tool's JSON/text output VERBATIM into the next tool. Do not reformat or invent JSON.\n"
    "3) If a tool returns an error or empty result, retry that tool ONCE with the SAME inputs; if it still fails, emit FINAL_ANSWER: [0].\n"
)

ARG_COUNTS = {
    "parse_markdown": 1,
    "quality_check": 3,
    "schedule_cards": 4,
    "export_csv": 2,
}

def validate_call_line(line: str) -> tuple[bool, str]:
    """
    Validate 'FUNCTION_CALL: fn|arg1|arg2|...' format and arity.
    Returns (ok, error_msg). If not ok, error_msg explains what to fix.
    """
    if not line.startswith("FUNCTION_CALL:"):
        return True, ""  # FINAL_ANSWER handled elsewhere
    try:
        _, payload = line.split(":", 1)
        parts = [p.strip() for p in payload.split("|")]
        fn = parts[0]
        args = parts[1:]
    except Exception:
        return False, "Malformed FUNCTION_CALL; expected 'FUNCTION_CALL: fn|arg1|...'."

    if fn not in ARG_COUNTS:
        return False, f"Unknown function '{fn}'. Allowed: {', '.join(ARG_COUNTS)}."

    need = ARG_COUNTS[fn]
    if len(args) != need:
        return False, f"{fn} expects {need} arguments; got {len(args)}. Do not add extra labels like 'md|'."
    return True, ""

import time

async def generate_with_timeout(prompt: str, timeout: float = 15.0) -> str | None:
    """
    Call Gemini with a short timeout and light retry on 429.
    Returns the plaintext model output (single line instruction) or None.
    """
    if not client:
        console.print(Panel("LLM unavailable — set GEMINI_API_KEY or GOOGLE_API_KEY", border_style="red"))
        return None

    def _run_sync():
        # Synchronous call (what run_in_executor/to_thread expects)
        return client.models.generate_content(model=MODEL, contents=prompt)

    loop = asyncio.get_event_loop()

    try:
        # first try
        resp = await asyncio.wait_for(loop.run_in_executor(None, _run_sync), timeout=timeout)
        text = getattr(resp, "text", None)
        return text.strip() if text else None

    except Exception as e:
        msg = str(e)
        # brief backoff on rate limit
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            try:
                await asyncio.sleep(3)
                resp = await asyncio.wait_for(loop.run_in_executor(None, _run_sync), timeout=timeout)
                text = getattr(resp, "text", None)
                return text.strip() if text else None
            except Exception as e2:
                console.print(Panel(f"LLM Error: {e2}", border_style="red"))
                return None
        console.print(Panel(f"LLM Error: {e}", border_style="red"))
        return None


async def main():
    console.print(Panel("# output → outputs/flashcards_schedule.csv", border_style="cyan"))

    # Start the MCP tool server (srs_tools.py)
    server_params = StdioServerParameters(
        command="python",
        args=["tools/srs_tools.py"],
        env=dict(os.environ)  # forward env just in case
    )

    today = str(date.today())
    intervals = "1,3,7,14,30"
    daily_new = 10  # safe default ≤ 20

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Seed conversation with system prompt + concrete markdown
            prompt = f"{SYSTEM_PROMPT}\n\nMake a deck from this markdown:\n{EXAMPLE_MD}"

            # We keep the raw JSON outputs to pass VERBATIM to the next tool
            last_cards_json = None
            last_scheduled_json = None
            retries = {"parse_markdown": 0, "quality_check": 0, "schedule_cards": 0, "export_csv": 0}
            MAX_RETRIES = 1

            for turn in range(1, 40):
                result = await generate_with_timeout(prompt)
                if not result:
                    console.print(Panel("LLM returned no content; exiting.", border_style="red"))
                    break

                console.print(f"Assistant: {result}")

                # Validate format / arity before calling a tool
                ok, err = validate_call_line(result)
                if not ok:
                    prompt += f"\nUser: ERROR — {err} Fix the call and try again using exact arity and verbatim JSON from the previous tool."
                    continue

                if result.startswith("FUNCTION_CALL:"):
                    _, payload = result.split(":", 1)
                    parts = [p.strip() for p in payload.split("|")]
                    fn = parts[0]
                    args = parts[1:]

                    # enforce retry policy on the client side too
                    if retries[fn] > MAX_RETRIES:
                        prompt += "\nUser: ERROR — too many retries on the same tool. Emit FINAL_ANSWER: [0]."
                        continue

                    if fn == "parse_markdown":
                        # exactly one arg: the markdown text
                        md_arg = args[0]
                        # if model sent placeholder like "<markdown>", replace with our given markdown
                        if md_arg == "<markdown>":
                            md_arg = EXAMPLE_MD

                        res = await session.call_tool("parse_markdown", arguments={"md": md_arg})
                        out = res.content[0].text if res and res.content else "{}"
                        # Fail fast if tool indicates no cards
                        try:
                            obj = json.loads(out)
                            if obj.get("ok") is False or (obj.get("cards") == []):
                                retries["parse_markdown"] += 1
                                prompt += f"\nUser: parse_markdown returned {out}. Retry once with the SAME markdown (no changes)."
                                continue
                        except Exception:
                            pass
                        last_cards_json = out
                        prompt += f"\nUser: parse_markdown returned {out}"

                    elif fn == "quality_check":
                        # exactly three args: cards_json, 3, 260
                        cards_json_arg = args[0]
                        res = await session.call_tool("quality_check", arguments={
                            "cards_json": cards_json_arg, "min_len": 3, "max_len": 260
                        })
                        out = res.content[0].text if res and res.content else "{}"
                        prompt += f"\nUser: quality_check returned {out}"
                        try:
                            qc = json.loads(out)
                            if not qc.get("ok"):
                                retries["quality_check"] += 1
                                if retries["quality_check"] <= MAX_RETRIES:
                                    prompt += "\nUser: QC failed; retry quality_check ONCE with the SAME cards_json."
                                    continue
                                else:
                                    prompt += "\nUser: QC failed again. Emit FINAL_ANSWER: [0]."
                        except Exception:
                            retries["quality_check"] += 1
                            prompt += "\nUser: QC parse error; retry quality_check ONCE with the SAME cards_json."
                            continue

                    elif fn == "schedule_cards":
                        # exactly four args: cards_json, start_date, daily_new, intervals
                        cards_json_arg, start_date_arg, daily_new_arg, intervals_arg = args
                        res = await session.call_tool("schedule_cards", arguments={
                            "cards_json": cards_json_arg,
                            "start_date": start_date_arg or today,
                            "daily_new": int(daily_new_arg),
                            "intervals": intervals_arg or intervals
                        })
                        out = res.content[0].text if res and res.content else "{}"
                        prompt += f"\nUser: schedule_cards returned {out}"
                        try:
                            sched = json.loads(out)
                            scheduled = sched.get("scheduled", [])
                            if not scheduled:
                                retries["schedule_cards"] += 1
                                if retries["schedule_cards"] <= MAX_RETRIES:
                                    prompt += "\nUser: No items scheduled; retry schedule_cards ONCE with the SAME inputs."
                                    continue
                                else:
                                    prompt += "\nUser: Scheduling failed again. Emit FINAL_ANSWER: [0]."
                            else:
                                last_scheduled_json = out
                        except Exception:
                            retries["schedule_cards"] += 1
                            prompt += "\nUser: schedule_cards parse error; retry ONCE with the SAME inputs."
                            continue

                    elif fn == "export_csv":
                        # exactly two args: scheduled_json, filename
                        scheduled_json_arg, filename_arg = args
                        res = await session.call_tool("export_csv", arguments={
                            "scheduled_json": scheduled_json_arg,
                            "filename": filename_arg
                        })
                        out = res.content[0].text if res and res.content else ""
                        prompt += f"\nUser: export_csv returned {out}"

                elif result.startswith("FINAL_ANSWER:"):
                    # done
                    break

                # Keep conversation flowing
                prompt += f"\nAssistant: {result}"

            console.print(Panel("SRS pipeline completed!", border_style="green"))

if __name__ == "__main__":
    asyncio.run(main())
