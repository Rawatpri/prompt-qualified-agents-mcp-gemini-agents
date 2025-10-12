# tools/srs_tools.py  (only key parts shown)

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from rich.console import Console
from rich.panel import Panel
import json, csv, io, sys, re
from datetime import date, timedelta

console = Console(file=sys.stderr)
mcp = FastMCP("SRS")

_QA_RE = re.compile(r'^\s*Q:\s*(.+?)\s*\nA:\s*(.+?)\s*(?:\n{1,2}|$)', re.M | re.S)

@mcp.tool()
def parse_markdown(md: str) -> TextContent:
    """Parse 'Q: ...\\nA: ...' pairs into JSON: {"cards":[{"q","a"}]}"""
    cards = []
    for m in _QA_RE.finditer(md.strip()):
        q = m.group(1).strip()
        a = m.group(2).strip()
        if q and a:
            cards.append({"q": q, "a": a})

    result = {"cards": cards}
    console.print(Panel(f"Parsed {len(cards)} cards", border_style="cyan"))

    # Fail fast on empty
    if len(cards) == 0:
        return TextContent(type="text", text=json.dumps({
            "ok": False, "error": "No Q/A pairs found. Ensure lines start with 'Q:' and 'A:'.",
            "cards": []
        }, ensure_ascii=False))
    return TextContent(type="text", text=json.dumps(result, ensure_ascii=False))

@mcp.tool()
def quality_check(cards_json: str, min_len: int = 3, max_len: int = 260) -> TextContent:
    """Validate cards; require >=1 valid card."""
    try:
        data = json.loads(cards_json)
        cards = data.get("cards", [])
    except Exception as e:
        return TextContent(type="text", text=json.dumps({"ok": False, "errors": [f"Invalid JSON: {e}"]}))

    errors = []
    if not cards:
        errors.append("No cards to check (empty).")
    for i, c in enumerate(cards):
        q, a = (c.get("q",""), c.get("a",""))
        if not q or not a:
            errors.append(f"Card {i+1}: missing q or a.")
            continue
        if not (min_len <= len(q) <= max_len):
            errors.append(f"Card {i+1} q length {len(q)} outside [{min_len},{max_len}].")
        if not (min_len <= len(a) <= max_len):
            errors.append(f"Card {i+1} a length {len(a)} outside [{min_len},{max_len}].")

    ok = len(errors) == 0
    console.print(Panel("QC passed" if ok else f"QC errors: {len(errors)}", border_style="green" if ok else "red"))
    return TextContent(type="text", text=json.dumps({"ok": ok, "errors": errors}, ensure_ascii=False))

@mcp.tool()
def schedule_cards(cards_json: str, start_date: str, daily_new: int, intervals: str) -> TextContent:
    """Create simple spaced schedule; fail if zero cards or QC not done."""
    try:
        data = json.loads(cards_json)
        cards = data.get("cards", [])
    except Exception as e:
        return TextContent(type="text", text=json.dumps({"error": f"Invalid JSON: {e}", "scheduled": []}))

    if not cards:
        return TextContent(type="text", text=json.dumps({"error": "No cards to schedule", "scheduled": []}))

    y, m, d = [int(x) for x in start_date.split("-")]
    start = date(y, m, d)
    ints = [int(x) for x in intervals.split(",")]

    scheduled = []
    for i, c in enumerate(cards):
        day_offset = (i // max(1, daily_new))  # simple batching by daily_new
        learn_on = start + timedelta(days=day_offset)
        reviews_on = [str(learn_on + timedelta(days=k)) for k in ints]
        scheduled.append({
            "q": c["q"], "a": c["a"],
            "learn_on": str(learn_on),
            "reviews_on": reviews_on
        })

    console.print(Panel(f"Scheduled {len(scheduled)} cards", border_style="cyan"))
    return TextContent(type="text", text=json.dumps({"scheduled": scheduled}, ensure_ascii=False))

@mcp.tool()
def export_csv(scheduled_json: str, filename: str) -> TextContent:
    """Write a CSV with columns: q,a,learn_on,reviews_on"""
    try:
        data = json.loads(scheduled_json)
        scheduled = data.get("scheduled", [])
    except Exception as e:
        return TextContent(type="text", text=json.dumps({"error": f"Invalid JSON: {e}"}))

    if not scheduled:
        return TextContent(type="text", text=json.dumps({"error": "No scheduled items to write"}))

    path = filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["q","a","learn_on","reviews_on"])
        for s in scheduled:
            w.writerow([s["q"], s["a"], s["learn_on"], "|".join(s["reviews_on"])])

    console.print(Panel(f"Wrote {len(scheduled)} rows → {path}", border_style="green"))
    return TextContent(type="text", text=path)

if __name__ == "__main__":
    mcp.run(transport="stdio")
