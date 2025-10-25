# Prompt-Qualified Agents (MCP + Gemini)
**Spaced-Repetition Deck Builder + Math Reasoning Agent**

Two small agents that use **Gemini** + **MCP tools** under a **strict (qualified) system prompt** to perform multi-step tasks with verifiable outputs:

- **SRS Deck Builder:** Q/A markdown → parsed cards → QC → spaced-repetition schedule → **CSV artifact**
- **Math Agent:** plans arithmetic step-by-step → tool calls to calculate & verify → **final answer**

**Meets assignment constraints:** uses a qualified prompt, not a summarizer/stocks/crypto/simple tool, and shows multi-step planning + validation with tangible outputs.

---

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Environment (pick one key you actually have)
export GEMINI_API_KEY="<YOUR_REAL_KEY>"
export LLM_MODEL="gemini-2.0-flash"
```

### Run SRS Agent (produces CSV)
```bash
SRS_MD_FILE=examples/cards.md python examples/srs_agent_client.py
cat outputs/flashcards_schedule.csv
```

### Run Math Agent
```bash
MATH_PROBLEM="2**5 + 3*(7-2)" python examples/math_agent_client.py
```

### Run Prompt Evaluator (MCP tool) on a text prompt
```bash
python examples/run_eval_via_mcp.py -f examples/weak_prompt.txt
# result → outputs/weak_prompt.json  (many falses by design)
```

---

## New Final Prompt (Qualified)

Save this as `examples/student_prompt_strong.txt`, then evaluate with the command below.

```
You are an SRS Assistant that turns markdown Q/A into a spaced-repetition deck. Think step by step and explicitly plan before each action. Use tool calls only for computation. Keep reasoning structured and separate from tool execution.

TOOLS:
- parse_markdown(md: str) -> JSON {"cards": [{"q": str, "a": str}]}
- quality_check(cards_json: str, min_len:int=3, max_len:int=260) -> JSON {"ok": bool, "errors": [str]}
- schedule_cards(cards_json: str, start_date: str, daily_new:int, intervals:str) -> JSON {"scheduled": [{"q": str, "a": str, "learn_on": str, "reviews_on": [str]}]}
- export_csv(scheduled_json: str, filename: str) -> str

PIPELINE (follow exactly, one step per turn):
1) [planning] Reason about the next step and inputs (no tool yet).
2) [parsing] FUNCTION_CALL: parse_markdown|<markdown>
3) [validation] FUNCTION_CALL: quality_check|<cards_json>|3|260
4) If quality_check.ok is false, [fixing] retry parse_markdown once with the same markdown; then quality_check again.
5) [planning] Choose scheduling parameters; then FUNCTION_CALL: schedule_cards|<cards_json>|<YYYY-MM-DD>|<daily_new ≤ 20>|1,3,7,14,30
6) [export] FUNCTION_CALL: export_csv|<scheduled_json>|outputs/flashcards_schedule.csv
7) [report] FINAL_ANSWER: [<count>]

OUTPUT FORMAT (STRICT; ONE LINE ONLY PER TURN):
- FUNCTION_CALL: function_name|param1|param2|...
- FINAL_ANSWER: [count]

INTERNAL SELF-CHECKS:
- After parse_markdown: ensure cards_json is valid JSON and has ≥1 items with both q and a (≤260 chars).
- After quality_check: require ok==true and errors==[]; otherwise retry QC once (then FINAL_ANSWER: [0] if still failing).
- After schedule_cards: every item has learn_on and reviews_on; count matches input cards.
- After export_csv: returned path is non-empty; then emit FINAL_ANSWER with scheduled count.

ERROR HANDLING / FALLBACKS:
- If any tool returns invalid JSON or errors: retry that tool once with the same inputs.
- If the retry fails: emit FINAL_ANSWER: [0].
- Never call the same tool more than twice in a row.

EXAMPLE (format only):
[planning] Decide to parse the provided markdown.
FUNCTION_CALL: parse_markdown|<markdown>
[validation] Inspect parsed cards and run quality checks.
FUNCTION_CALL: quality_check|{"cards":[{"q":"...","a":"..."}]}|3|260
[planning] Schedule with start date 2025-10-12 and daily_new 10.
FUNCTION_CALL: schedule_cards|{"cards":[{"q":"...","a":"..."}]}|2025-10-12|10|1,3,7,14,30
[export] Export the schedule to CSV.
FUNCTION_CALL: export_csv|{"scheduled":[{"q":"...","a":"...","learn_on":"...","reviews_on":["..."]}]}|outputs/flashcards_schedule.csv
[report] Output the final count.
FINAL_ANSWER: [3]
```

**Evaluate the prompt:**
```bash
python examples/run_eval_via_mcp.py -f examples/student_prompt_strong.txt
# result → outputs/student_prompt_strong.json  (expected: all true)
```

---

## Why this satisfies the assignment

- **Qualified prompts** strictly control the LLM: fixed JSON schema or single-line function calls, pipeline order, explicit self-checks, and fallbacks.  
- **Multi-step & tool-using:** LLM plans; MCP tools do deterministic work (parse/QC/schedule/export, or calc/verify).  
- **Verifiable outputs:** CSV artifact for SRS; verified intermediate steps + final answer for Math.  
- **Not** a summarizer / stock / crypto / “simple” tool.

---

## Repo Structure

```
examples/
  cards.md
  srs_agent_client.py
  math_agent_client.py
  run_eval_via_mcp.py
  student_prompt_strong.txt     # ← the qualified “final prompt” used for grading
tools/
  srs_tools.py         # parse_markdown, quality_check, schedule_cards, export_csv
  cot_tools.py         # show_reasoning, calculate, verify
  eval_tools.py        # evaluate_prompt (uses the evaluator system prompt)
outputs/
  .gitkeep             # CSVs & JSONs written here at runtime
README.md
requirements.txt
.env.example
```

**Suggested `.gitignore`:**
```
.venv/
__pycache__/
.DS_Store/
.env
outputs/*.csv
```

---

## Example Inputs / Outputs

**Input markdown (`examples/cards.md`):**
```md
Q: What is Bayes' theorem?
A: P(A|B) = [P(B|A) * P(A)] / P(B)

Q: Define precision in classification.
A: TP / (TP + FP)
```

**Output CSV (`outputs/flashcards_schedule.csv`):**
```
q,a,learn_on,reviews_on
"What is Bayes' theorem?","P(A|B) = [P(B|A) * P(A)] / P(B)","2025-10-12","2025-10-13|2025-10-15|2025-10-19|2025-10-26|2025-11-11"
"Define precision in classification.","TP / (TP + FP)","2025-10-12","2025-10-13|2025-10-15|2025-10-19|2025-10-26|2025-11-11"
```

---

## Troubleshooting

- **429 quota / rate limits:** rerun later; keep demo short.  
- **404 model not found:** use `gemini-2.0-flash` (supported for `v1beta` `generateContent`).  
- **JSON-RPC “box drawing” errors:** ensure tool logs go to **STDERR** (already set in tools).  
- **`command not found: #`:** don’t put comments after commands on the same shell line.

---

## Demo Video (YouTube)
Paste your link here: **https://youtu.be/OwcyiJnZipo**
