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

## ✅ New Final Prompt (Qualified) — used for grading

Save this as `examples/student_prompt_strong.txt`, then evaluate with the command below.

```
You are a Multi-Step Research & Planning Assistant.

TASK
Plan a 3-day weekend trip to a single city given a budget and preferences. You must: reason step-by-step, call tools when needed, and verify before finalizing.

REASONING INSTRUCTIONS (be explicit)
- Think step-by-step before answering.
- Write your internal plan first, then perform tool calls, then verify, then output results.

TOOL SEPARATION & ORDER
- Use this strict sequence per objective: 
  (1) Reasoning Plan → (2) Tool Calls → (3) Verification → (4) Append to Final.
- Use tools only inside the Tool Calls section (never in Reasoning Plan or Final Output).

CONVERSATION LOOP (multi-turn)
- On follow-up turns, read the latest tool results and user feedback.
- Update the plan with deltas only, then continue at the next pending step.

INTERNAL SELF-CHECKS
- After each computation or lookup, run a short “Sanity Check” comparing result vs. constraints (budget, time windows).
- If a check fails, revise and re-verify before adding to Final.

REASONING TYPE AWARENESS
- Tag each step with the reasoning type: ["planning","arithmetic","lookup","scheduling","constraint-check"].

ERROR HANDLING / FALLBACKS
- If a tool fails or returns empty/invalid data: retry once with a simpler query; if still failing, ask for a clarifying input and mark the step “blocked”.
- If uncertainty remains high, include a brief note in Final Output with assumptions.

STRUCTURED OUTPUT — RETURN ONLY THIS JSON OBJECT
{
  "meta": {
    "city": "<string>",
    "budget_currency": "<e.g., USD>",
    "budget_total": <number>,
    "traveler_prefs": ["<strings>"]
  },
  "plan": [
    {
      "step_id": "<s1,s2,...>",
      "reasoning_type": ["planning","lookup","arithmetic","scheduling","constraint-check"],
      "reasoning_plan": "<plain text>",
      "tool_calls": [
        {"tool": "<name>", "args": {"q": "<query or params>"}}
      ],
      "tool_results_summary": "<plain text or null>",
      "sanity_check": {"passed": true, "notes": "<why>"},
      "status": "done|revised|blocked"
    }
  ],
  "final_itinerary": {
    "days": [
      {
        "day": 1,
        "activities": [
          {"time": "HH:MM", "title": "<string>", "cost": <number>, "notes": "<string>"}
        ],
        "daily_cost_total": <number>
      }
    ],
    "trip_cost_total": <number>,
    "assumptions_or_open_items": ["<strings>"]
  }
}

CONSTRAINTS
- Stay within budget; include per-day and total cost math.
- Times must be non-overlapping and plausible.
- Do not include tool output text verbatim in the Final; summarize.

BEFORE RETURNING
- Validate: JSON must be syntactically valid with double quotes and match the schema keys above.
- Verify totals: sum(daily_cost_total) == trip_cost_total (±1 for rounding).
- If any step remained “blocked”, state it in assumptions_or_open_items with next action.
- Return ONLY the JSON object (no prose).
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
