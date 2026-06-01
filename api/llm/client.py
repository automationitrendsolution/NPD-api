"""
OpenAI API client wrapper.

Why a wrapper instead of calling OpenAI directly in tier2c/tier3?
------------------------------------------------------------------
- One place to load the API key and choose the model.
- One place to add retry logic — OpenAI occasionally returns 429 (rate
  limit) or 500 errors. Retrying once or twice silently avoids false
  failures in long-running ingestion jobs.
- One place to log token usage so we can track cost across all LLM calls
  in the pipeline without scattering logging code everywhere.
- JSON mode enforcement — all structured LLM calls in this project return
  JSON. Centralising that here means tier2c.py and tier3.py never have to
  think about parsing or mode selection.

Required .env key
-----------------
    OPENAI_API_KEY=sk-...

Optional .env keys
------------------
    OPENAI_MODEL=gpt-4o          # default model for all calls
    OPENAI_MODEL_FAST=gpt-4o-mini  # cheaper model for simple generation tasks
"""

import json
import os
import time
from pathlib import Path

from openai import OpenAI, RateLimitError, APIStatusError


# ── Env loading (same pattern as the rest of the project) ─────────────────────

def _load_dotenv():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # Strip inline comments (e.g. VALUE=foo  # comment → "foo")
        value = value.split("#")[0] if '"' not in value and "'" not in value else value
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ── Model defaults ─────────────────────────────────────────────────────────────
# The "analysis" model handles complex synthesis (Tier 2C).
# The "fast" model handles structured generation (Tier 3 sub-calls).
MODEL_ANALYSIS = os.getenv("OPENAI_MODEL", "gpt-4o")
MODEL_FAST     = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")

MAX_RETRIES = 3       # Number of retry attempts on rate-limit or server errors
RETRY_DELAY = 10      # Seconds to wait before retrying


def _get_client() -> OpenAI:
    """
    Returns an authenticated OpenAI client.

    Raises EnvironmentError with a clear message if the key is missing
    so the developer knows exactly what to add to .env.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set.\n"
            "Add it to your .env file:\n"
            "    OPENAI_API_KEY=sk-..."
        )
    return OpenAI(api_key=api_key)


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.3,
    json_mode: bool = True,
    label: str = "",
) -> dict | str:
    """
    Makes a single OpenAI chat completion call.

    Parameters
    ----------
    system_prompt : str
        The system-level instruction that shapes the LLM's behaviour.
        E.g. "You are a product market analyst. Return only valid JSON."

    user_prompt : str
        The main content — the evidence, context, and task description
        built from the idea's data.

    model : str, optional
        Override the default model.  Pass MODEL_FAST for cheaper calls
        where deep reasoning is not needed.

    temperature : float
        0.0 = fully deterministic (use for structured data extraction)
        0.3 = slight variation (use for analysis and synthesis)
        0.7 = creative (use for listing copy, taglines)

    json_mode : bool
        If True, forces the response to be valid JSON via OpenAI's
        response_format={"type": "json_object"} parameter and returns
        a parsed dict.

        IMPORTANT: when json_mode=True, the system_prompt MUST mention
        the word "JSON" or OpenAI returns an error. All callers in this
        project already do this.

        If False, returns the raw response string.

    label : str
        A short label logged with token usage for cost tracking.
        E.g. "tier2c_analysis" or "tier3_listing".

    Returns
    -------
    dict
        Parsed JSON if json_mode=True.
    str
        Raw response text if json_mode=False.

    Raises
    ------
    RuntimeError
        After MAX_RETRIES failed attempts, or if the response cannot
        be parsed as JSON when json_mode=True.
    """
    chosen_model = model or MODEL_ANALYSIS
    client = _get_client()

    response_format = {"type": "json_object"} if json_mode else None

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            kwargs = dict(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=temperature,
            )
            if response_format:
                kwargs["response_format"] = response_format

            response = client.chat.completions.create(**kwargs)

            # Log token usage so costs are visible in server logs
            usage = response.usage
            print(
                f"[LLM] {label or chosen_model} | "
                f"prompt={usage.prompt_tokens} "
                f"completion={usage.completion_tokens} "
                f"total={usage.total_tokens}"
            )

            content = response.choices[0].message.content

            if json_mode:
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    raise RuntimeError(
                        f"LLM returned invalid JSON for '{label}'.\n"
                        f"Parse error: {e}\n"
                        f"Raw content (first 500 chars): {content[:500]}"
                    )

            return content

        except RateLimitError as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"[LLM] Rate limit hit (attempt {attempt}/{MAX_RETRIES}). "
                      f"Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

        except APIStatusError as e:
            last_error = e
            if e.status_code >= 500 and attempt < MAX_RETRIES:
                print(f"[LLM] Server error {e.status_code} (attempt {attempt}/{MAX_RETRIES}). "
                      f"Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(f"OpenAI API error: {e.status_code} — {e.message}")

    raise RuntimeError(
        f"OpenAI call failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )
