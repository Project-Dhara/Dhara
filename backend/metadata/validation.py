"""Validation helpers for extracted Source Table ID / Table Title fields.

Two independent validators are provided, sharing a common result shape so
callers can inspect or compare them:

    {
        "valid": bool,
        "issues": [str, ...],
        "table_id": str,
        "title": str,
    }

* validate_table_fields_code -- fast, deterministic, regex/heuristic based.
* validate_table_fields_llm  -- asks an OpenAI model to judge the pair.
"""
import json
import os
import re
from typing import Dict, List, Optional

import openai

TABLE_MARKER_RE = re.compile(r"\bTABLE[\s:\-]", re.IGNORECASE)

OPENAI_VALIDATION_MODEL = "gpt-4o"


def validate_table_fields_code(table_id: str, title: str) -> Dict:
    """Deterministic, code-based validation of a table's ID/title pair.

    Flags the scenarios that commonly go wrong during extraction:
      - Source Table ID and Table Title appear swapped.
      - The ID part has no "TABLE" prefix at all.
      - Either the Source Table ID or the Table Title is missing.
    """
    table_id = (table_id or "").strip()
    title = (title or "").strip()
    issues: List[str] = []

    id_has_marker = bool(TABLE_MARKER_RE.search(table_id))
    title_has_marker = bool(TABLE_MARKER_RE.search(title))

    if not table_id and not title:
        issues.append("Source Table ID and Table Title are both missing")
    elif not table_id:
        issues.append("Source Table ID is missing")
    elif not title:
        issues.append("Table Title is missing")

    if table_id and title and title_has_marker and not id_has_marker:
        issues.append("Source Table ID and Table Title appear to be swapped")

    if table_id and not id_has_marker and not title_has_marker:
        issues.append('Source Table ID has no "TABLE" prefix')

    return {
        "valid": not issues,
        "issues": issues,
        "table_id": table_id,
        "title": title,
    }


def validate_table_fields_llm(
    table_id: str,
    title: str,
    api_key: Optional[str] = None,
    model: str = OPENAI_VALIDATION_MODEL,
) -> Dict:
    """Prompt-based validation using an OpenAI model to judge whether the
    extracted Source Table ID and Table Title are correctly identified and
    assigned (not swapped, not missing, well-formed)."""
    table_id = (table_id or "").strip()
    title = (title or "").strip()

    client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

# f"""You are validating two fields extracted from a statistical table sheet.

# Source Table ID (extracted): {table_id!r}

# Table Title (extracted): {title!r}

# Definitions:

# * **Source Table ID** is a short table identifier. A valid Source Table ID normally contains the word `"TABLE"` as an identifier marker, followed by the table code. Variations in spacing or punctuation are valid, for example:

#   * `"TABLE: D-12"`
#   * `"TABLE : D-12"`
#   * `"TABLE-D12"`
#   * `"TABLE D 12"`

#   The presence of `"TABLE"` in the **Source Table ID is expected and is NOT an error**.

# * **Table Title** is usually longer descriptive free text explaining what the table contains, for example:
#   `"PREGNANCY RELATED DEATHS BY AGE AND OCCUPATION (URBAN)"`.

# Check **ONLY** for the following problems. Do not invent or report any other issue:

# 1. **Swapped fields**

#    * The Source Table ID and Table Title appear to be swapped.
#    * For example, the Source Table ID contains long descriptive title-like text while the Table Title contains a short table identifier such as `"TABLE: D-18"`.

# 2. **Invalid marker in Table Title**

#    * The Table Title contains `"DESCRIPTION"` or `"SL.NO"` (case-insensitive) as a marker/header rather than as genuine descriptive content.
#    * Do **not** report `"TABLE"` in the Source Table ID as an issue.

# 3. **Missing field**

#    * The Source Table ID is missing, empty, null, or contains only whitespace.
#    * The Table Title is missing, empty, null, or contains only whitespace.

# Important constraints:

# * Do NOT report an issue merely because the Source Table ID contains `"TABLE"`. That is normal and expected.
# * Do NOT report an issue saying `"The Table Title contains 'TABLE' as a marker"` unless such a rule is explicitly listed above. It is **not** one of the allowed validation rules.
# * Do NOT check whether the Source Table ID is correctly formatted beyond what is necessary to detect swapped or missing fields.
# * Do NOT infer additional validation rules.
# * Report every applicable issue from the three categories above and no others.

# If none of the listed problems apply, return:

# {"valid": "true", "issues": []}

# Otherwise return:

# {"valid": "false", "issues": ["<issue 1>", "<issue 2>", ...]}

# Respond with ONLY the JSON object. Do not include explanations, markdown, or additional text.
# """
    prompt = f"""Validate a Source Table ID / Table Title pair extracted from a statistics sheet.

Source Table ID: {table_id!r}
Table Title: {title!r}

Source Table ID is valid if it contains "TABLE" as a marker, any spacing/punctuation
(e.g. "TABLE: D-12", "TABLE :D-14", "TABLE-D12"). Title is free text and may
be short (e.g. "INFANTS DEATHS BY AGE AND SEX") -- never judge its wording,
length, or plausibility.

List ONLY issues that apply, nothing else:
1. swapped: title-like text is in the ID field, or vice versa.
2. Title contains "DESCRIPTION" or "SL.NO" as a marker.
3. ID or Title is missing/empty.

Example: id="TABLE :D-14", title="INFANTS DEATHS BY AGE AND SEX" -> valid=true, issues=[]

Respond with ONLY: {{"valid": true or false, "issues": ["...", ...]}}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    text = response.choices[0].message.content or "{}"

    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {}
    except (json.JSONDecodeError, AttributeError):
        parsed = {}

    issues = parsed.get("issues", [])
    # Trust the issues list over the model's own "valid" flag -- models
    # occasionally return valid=false with an empty issues list, which is
    # a self-contradiction we shouldn't propagate to the caller.
    valid = not issues

    return {
        "valid": bool(valid),
        "issues": list(issues),
        "table_id": table_id,
        "title": title,
    }


def _title_looks_like_headers(title: str, columns: Optional[List] = None) -> bool:
    text = " ".join(str(title or "").split()).strip().upper()
    if not text:
        return False
    if TABLE_MARKER_RE.search(text) and len(text) < 40:
        return True
    if re.search(r"\bSL\.?\s*NO\.?\b", text, re.I):
        return True
    cols = [str(c).strip().upper() for c in (columns or []) if str(c).strip()]
    if len(cols) >= 2:
        hits = sum(1 for c in cols[:6] if c and c in text)
        if hits >= max(2, int(min(4, len(cols[:6])) * 0.5)):
            return True
    return False


def repair_table_id_title_llm(
    table_id: str,
    title: str,
    *,
    context_rows: Optional[List[str]] = None,
    columns: Optional[List] = None,
    api_key: Optional[str] = None,
    model: str = OPENAI_VALIDATION_MODEL,
) -> Optional[Dict[str, str]]:
    """
    Small repair call: return corrected Source Table ID and/or Table Title when
    extraction/validation left them empty, swapped, or header-like.

    Returns ``{"table_id": str, "title": str}`` with only fields that should
    replace the current values (omitted keys mean "leave unchanged"), or None
    when nothing usable was produced.
    """
    table_id = (table_id or "").strip()
    title = (title or "").strip()
    lines = [str(x).strip() for x in (context_rows or []) if str(x).strip()]
    col_preview = ", ".join(str(c) for c in (columns or [])[:8] if str(c).strip())

    context_block = "\n".join(f"- {ln}" for ln in lines[:6]) or "(none)"
    prompt = f"""Return the correct Source Table ID and Table Title for this statistics table.

Source Table ID (current): {table_id!r}
Table Title (current): {title!r}
Leading rows:
{context_block}
Column headers (hint): {col_preview or "(unknown)"}

Definitions:
- Source Table ID = short identifier, usually containing TABLE plus a code (e.g. "TABLE: B-6", "Table : D-12").
- Table Title = descriptive caption of what the table measures (not the TABLE id, not column headers like SL. NO. / AGE).
- If a subtitle banner follows the main caption, join with " — ".
- Keep original wording/casing from the leading rows when possible.
- If a field is already correct, return it unchanged.
- Respond with ONLY JSON: {{"table_id": "...", "title": "..."}}
"""

    try:
        client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=280,
        )
        text = response.choices[0].message.content or ""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {}
        out: Dict[str, str] = {}

        repaired_id = str(parsed.get("table_id") or "").strip()
        if repaired_id and repaired_id != table_id:
            out["table_id"] = repaired_id

        repaired_title = str(parsed.get("title") or "").strip()
        if repaired_title and repaired_title != title:
            if _title_looks_like_headers(repaired_title, columns):
                repaired_title = ""
            elif TABLE_MARKER_RE.search(repaired_title) and len(repaired_title) < 48:
                repaired_title = ""
            if repaired_title:
                out["title"] = repaired_title

        return out or None
    except Exception as exc:
        print(f"[validation] id/title repair skipped ({exc})", flush=True)
        return None


def repair_table_title_llm(
    table_id: str,
    title: str,
    *,
    context_rows: Optional[List[str]] = None,
    columns: Optional[List] = None,
    api_key: Optional[str] = None,
    model: str = OPENAI_VALIDATION_MODEL,
) -> Optional[str]:
    """Backward-compatible wrapper — returns only a repaired title string."""
    repaired = repair_table_id_title_llm(
        table_id,
        title,
        context_rows=context_rows,
        columns=columns,
        api_key=api_key,
        model=model,
    )
    if not repaired:
        return None
    return repaired.get("title")