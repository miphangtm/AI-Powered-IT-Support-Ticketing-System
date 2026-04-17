"""
ClearDesk — AI Ticket Classifier (Google Gemini)
--------------------------------------------------
Isolates all Google Generative AI interaction behind a single public function,
`classify_ticket()`.  Nothing else in the application imports `google.genai`
directly — keeping AI concerns in one place makes it easy to swap models,
adjust prompts, or mock the client in tests.

Design decisions
----------------
- `make_client()` is a factory that builds a configured `genai.Client` and is
  called once at startup in app.py.  The client is then injected into
  classify_ticket() so tests can pass a mock without patching globals.
- The system instruction and generation config are sent per-call via
  `types.GenerateContentConfig` so the client itself stays stateless.
- JSON is extracted in three passes: direct parse → markdown-fence strip →
  regex {...} search.  If all three fail, ClassificationError is raised so
  the caller (app.py) decides the fallback.
"""

import json
import re
import time
from typing import TypedDict

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------
# Defined here (not in app.py) because these values drive the classifier
# prompt.  app.py imports them to keep validation in sync — single source
# of truth for what the AI is allowed to return.

VALID_CATEGORIES: frozenset[str] = frozenset({"Network", "Hardware", "Software", "Access", "Other"})
VALID_URGENCIES:  frozenset[str] = frozenset({"Low", "Medium", "High"})

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ClassificationResult(TypedDict):
    """
    Structured output returned by `classify_ticket()`.

    All fields are guaranteed to be present and contain valid values when
    this type is returned — callers don't need to do any further validation.
    """
    category:             str  # Member of VALID_CATEGORIES
    urgency:              str  # Member of VALID_URGENCIES
    suggested_resolution: str  # Non-empty actionable text


class ClassificationError(Exception):
    """
    Raised when classification cannot be completed or validated.

    The `raw_response` attribute carries whatever text Gemini returned (if
    anything) so callers can log it for debugging without catching and
    re-inspecting a generic Exception.
    """

    def __init__(self, message: str, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

# Static system instruction sent with every request via GenerateContentConfig.
_SYSTEM_PROMPT = (
    "You are an expert IT support analyst. "
    "When given an IT support ticket you respond with a JSON object and nothing else — "
    "no markdown fences, no explanation, no trailing text. "
    "Your response must be valid JSON that can be parsed by json.loads() directly."
)

# Gemini 2.5 Flash — the only model with free-tier quota on this key (5 RPM / 250K TPM).
_MODEL_NAME = "gemini-2.5-flash"


def _build_user_prompt(title: str, description: str) -> str:
    """Return the per-request classification prompt with the ticket data embedded."""
    categories = sorted(VALID_CATEGORIES)
    urgencies  = sorted(VALID_URGENCIES)

    return (
        f"Classify the following IT support ticket.\n\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
        f"Respond with a JSON object containing exactly these three keys:\n"
        f'  "category": one of {categories}\n'
        f'  "urgency": one of {urgencies}\n'
        f'  "suggested_resolution": a concise, actionable resolution (2–4 sentences)\n\n'
        f"Raw JSON only. No markdown. No explanation."
    )


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def make_client(api_key: str) -> genai.Client:
    """
    Build and return a configured Gemini client.

    Called once at application startup in app.py.  The returned client is
    thread-safe and reused across all requests.

    Args:
        api_key: Google Gemini API key (from GEMINI_API_KEY env var).

    Returns:
        A ready-to-use genai.Client instance.
    """
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """
    Parse a JSON object from raw model output.

    Strategy:
      1. Try a direct parse — succeeds when the model behaves correctly.
      2. If that fails, strip any markdown code fence (```json ... ```) and
         retry — Gemini sometimes wraps output despite instructions.
      3. As a last resort, use a regex to find the first {...} block in the
         text — handles models that add a preamble sentence before the JSON.

    Raises:
        ClassificationError: if no valid JSON object can be extracted.
    """
    # Pass 1 — direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Pass 2 — strip markdown code fence
    fence_stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.DOTALL).strip()
    try:
        return json.loads(fence_stripped)
    except json.JSONDecodeError:
        pass

    # Pass 3 — find first {...} block via regex
    match = re.search(r"\{[\s\S]*?\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ClassificationError(
        "Could not extract a valid JSON object from the model response.",
        raw_response=text,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_ticket(
    title: str,
    description: str,
    *,
    client: genai.Client,
) -> ClassificationResult:
    """
    Ask Gemini to classify an IT support ticket.

    Args:
        title:       Short issue summary from the ticket form.
        description: Full description provided by the submitter.
        client:      Pre-built Gemini client (keyword-only so it's never
                     accidentally passed positionally).

    Returns:
        ClassificationResult with validated category, urgency, and a
        suggested resolution string.

    Raises:
        ClassificationError: for any of:
          - Google API errors (auth, rate-limit, server error, network)
          - Unparseable model response (after all extraction strategies)
          - Model returns values outside the allowed sets

    Example:
        >>> result = classify_ticket("VPN won't connect", "Getting error 800...", client=client)
        >>> result["category"]
        'Network'
        >>> result["urgency"]
        'High'
    """
    # Retry up to 3 times on transient server errors (503 high-demand spikes).
    # Delays: 3s → 6s → 12s.  Client errors (4xx) are not retried.
    _MAX_RETRIES = 3
    _RETRY_DELAY = 3  # seconds; doubles each attempt

    last_exc: Exception | None = None
    delay = _RETRY_DELAY

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=_MODEL_NAME,
                contents=_build_user_prompt(title, description),
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    # 1024 tokens — Gemini 2.5 Flash uses chain-of-thought
                    # reasoning internally and needs more headroom than
                    # earlier models.
                    max_output_tokens=1024,
                ),
            )
            break  # success — exit the retry loop
        except genai_errors.ClientError as exc:
            # 4xx — bad key, quota exhausted, invalid request; no point retrying.
            raise ClassificationError(f"Gemini client error: {exc}") from exc
        except genai_errors.ServerError as exc:
            # 5xx — transient capacity/availability issue; retry with backoff.
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
        except Exception as exc:
            # Network failures, timeouts, or anything else unexpected.
            raise ClassificationError(f"Unexpected error during classification: {exc}") from exc
    else:
        # All retries exhausted.
        raise ClassificationError(
            f"Gemini unavailable after {_MAX_RETRIES} attempts: {last_exc}",
        ) from last_exc

    raw = response.text.strip()

    # _extract_json raises ClassificationError if it can't find a valid object.
    data = _extract_json(raw)

    # Validate that the returned values are within the allowed sets.
    # Raise rather than silently coerce so callers know the model drifted.
    category = data.get("category", "")
    urgency  = data.get("urgency", "")

    if category not in VALID_CATEGORIES:
        raise ClassificationError(
            f"Model returned unexpected category {category!r}. "
            f"Expected one of {sorted(VALID_CATEGORIES)}.",
            raw_response=raw,
        )

    if urgency not in VALID_URGENCIES:
        raise ClassificationError(
            f"Model returned unexpected urgency {urgency!r}. "
            f"Expected one of {sorted(VALID_URGENCIES)}.",
            raw_response=raw,
        )

    suggested_resolution = str(data.get("suggested_resolution", "")).strip()

    return ClassificationResult(
        category=category,
        urgency=urgency,
        suggested_resolution=suggested_resolution,
    )
