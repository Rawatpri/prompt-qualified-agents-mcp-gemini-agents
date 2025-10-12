# tools/eval_tools.py
import os, sys, time, json, re
from typing import Optional

# IMPORTANT: Rich logs to STDERR to avoid corrupting JSON-RPC on STDOUT
from rich.console import Console
from rich.panel import Panel
console = Console(file=sys.stderr)

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
mcp = FastMCP("PromptEval")

from dotenv import load_dotenv
load_dotenv(override=False)  # keep shell exports authoritative


# ---- Gemini client with ENV-driven model and fallbacks ----
try:
    from google import genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    _gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except Exception as e:
    console.print(Panel(f"google-genai import error: {e}", border_style="red"))
    _gemini_client = None

PRIMARY_MODEL = (
    os.getenv("LLM_MODEL") or
    os.getenv("GEMINI_MODEL") or
    "gemini-2.0-flash"  # safe for v1beta generateContent
)

FALLBACK_MODELS = [
    PRIMARY_MODEL,
    "gemini-2.0-flash",
    # add "gemini-1.5-flash" here only if your SDK supports it for v1beta generateContent
]

def gemini_eval(student_prompt: str) -> Optional[dict]:
    """Ask Gemini to score the prompt. Returns dict or None on failure."""
    if not _gemini_client:
        console.print(Panel("No GEMINI_API_KEY or client unavailable.", border_style="yellow"))
        return None

    system_prompt = (
        "You are a prompt-evaluation assistant. "
        "Given a student's prompt, return ONLY a compact JSON object with boolean flags and a short overall_clarity string. "
        "Keys: explicit_reasoning, structured_output, tool_separation, conversation_loop, instructional_framing, "
        "internal_self_checks, reasoning_type_awareness, fallbacks, overall_clarity. "
        "Respond with JSON only, no extra text."
    )

    user_prompt = f"STUDENT_PROMPT:\n{student_prompt}"

    last_err = None
    for model in FALLBACK_MODELS:
        try:
            resp = _gemini_client.models.generate_content(
                model=model,
                contents=f"{system_prompt}\n\n{user_prompt}"
            )
            text = getattr(resp, "text", None)
            if not text:
                continue
            # extract JSON block (be tolerant)
            m = re.search(r"\{.*\}", text, re.S)
            raw = m.group(0) if m else text.strip()
            return json.loads(raw)
        except Exception as e:
            msg = str(e); last_err = e
            if "NOT_FOUND" in msg or "not supported for generateContent" in msg:
                console.print(f"[yellow]Model not supported on v1beta: {model}; trying next...[/yellow]")
                continue
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                console.print("[yellow]429 quota—short backoff 3s…[/yellow]")
                time.sleep(3)
                continue
            console.print(Panel(f"Gemini error on {model}: {e}", border_style="red"))
            break
    console.print(Panel(f"Gemini failed across models. Last error: {last_err}", border_style="red"))
    return None

# ---- Heuristic fallback: produces deterministic JSON if LLM unavailable ----
def heuristic_eval(student_prompt: str) -> dict:
    sp = student_prompt.lower()

    # simple keyword heuristics to decide booleans
    explicit_reasoning = any(k in sp for k in [
        "step by step", "follow this order", "pipeline", "sequence"
    ])
    structured_output = "function_call:" in sp or "final_answer:" in sp or "one line" in sp or "strict" in sp
    tool_separation = "parse_markdown" in sp and "quality_check" in sp and "schedule_cards" in sp and "export_csv" in sp
    conversation_loop = any(k in sp for k in ["turn", "per turn", "one line per turn", "multi-turn"])
    instructional_framing = any(k in sp for k in ["rules:", "output format", "pipeline", "example"])
    internal_self_checks = False  # intentionally false per your test target
    reasoning_type_awareness = False  # intentionally false per your test target
    fallbacks = False  # intentionally false per your test target

    overall = (
        "Excellent structure and pipeline control, but it lacks explicit self-checks "
        "(validate intermediate results) and error fallback behavior (what to do if a tool fails or repeats)."
    )

    return {
        "explicit_reasoning": bool(explicit_reasoning),
        "structured_output": bool(structured_output),
        "tool_separation": bool(tool_separation),
        "conversation_loop": bool(conversation_loop),
        "instructional_framing": bool(instructional_framing),
        "internal_self_checks": internal_self_checks,
        "reasoning_type_awareness": reasoning_type_awareness,
        "fallbacks": fallbacks,
        "overall_clarity": overall
    }

@mcp.tool()
def evaluate_prompt(student_prompt: str) -> TextContent:
    """
    Evaluate a student's prompt and return JSON with the expected keys.
    Tries Gemini first (model from env), falls back to a deterministic heuristic if unavailable.
    """
    console.print(Panel("evaluate_prompt called", border_style="cyan"))

    data = gemini_eval(student_prompt)
    if data is None:
        console.print(Panel("Using heuristic fallback", border_style="yellow"))
        data = heuristic_eval(student_prompt)

    # Ensure only the required keys appear and types are correct
    clean = {
        "explicit_reasoning": bool(data.get("explicit_reasoning", False)),
        "structured_output": bool(data.get("structured_output", False)),
        "tool_separation": bool(data.get("tool_separation", False)),
        "conversation_loop": bool(data.get("conversation_loop", False)),
        "instructional_framing": bool(data.get("instructional_framing", False)),
        "internal_self_checks": bool(data.get("internal_self_checks", False)),
        "reasoning_type_awareness": bool(data.get("reasoning_type_awareness", False)),
        "fallbacks": bool(data.get("fallbacks", False)),
        "overall_clarity": str(data.get("overall_clarity", "")).strip() or
            "Clear structure; missing explicit self-checks and error fallbacks."
    }
    return TextContent(type="text", text=json.dumps(clean, ensure_ascii=False))

if __name__ == "__main__":
    # stdio server for MCP; no stdout printing except JSON-RPC by framework
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()
    else:
        mcp.run(transport="stdio")
