#!/usr/bin/env python3
"""Validate public, sanitized n8n workflow templates using the standard library."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "n8n" / "workflows"

EXPECTED_WORKFLOWS = {
    "ai-assistant-v1.json": "AI Assistant - V1",
    "calendar-availability-tool.json": "AI Assistant - Calendar Availability Tool",
    "google-calendar-booking-tool.json": "AI Assistant - Google Calendar Booking Tool",
    "calendar-slot-finder-tool.json": "AI Assistant - Calendar Slot Finder Tool",
    "lead-capture-tool.json": "AI Assistant - Lead Capture Tool",
}

SECRET_PATTERNS = {
    "Google API key": r"\bAIza[0-9A-Za-z_-]{30,}\b",
    "Google OAuth client secret": r"\bGOCSPX-[A-Za-z0-9_-]+\b",
    "Google access token": r"\bya29\.[A-Za-z0-9._-]{20,}\b",
    "Telegram bot token": r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b",
    "GitHub token": (
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "Private key header": (
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ),
    "Bearer token": r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}",
}

EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)


def walk(value, path="$"):
    """Yield every JSON path and value without exposing values in errors."""
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        yield path, value
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")
    else:
        yield path, value


def validate_workflow(path, expected_name):
    errors = []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read valid JSON ({type(exc).__name__})"]

    if not isinstance(data, dict):
        return ["top-level JSON value must be an object"]

    if data.get("name") != expected_name:
        errors.append("workflow name does not match the expected name")

    if data.get("active") is not False:
        errors.append("workflow must be explicitly inactive")

    if data.get("pinData") != {}:
        errors.append("pinned execution data must be empty")

    for field in ("id", "versionId", "meta", "tags"):
        if field in data:
            errors.append(f"instance metadata field must be removed: {field}")

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes must be a non-empty array")
        nodes = []

    # Credential bindings, webhook IDs and cached URLs are not for public templates.
    for location, item in walk(data):
        if not isinstance(item, dict):
            continue

        for forbidden_key in ("credentials", "webhookId", "cachedResultUrl"):
            if forbidden_key in item:
                errors.append(
                    f"instance-specific field remains at {location}.{forbidden_key}"
                )

    raw = json.dumps(data, ensure_ascii=False)

    if EMAIL_PATTERN.search(raw):
        errors.append("email-like value detected")

    for label, pattern in SECRET_PATTERNS.items():
        if re.search(pattern, raw, re.IGNORECASE):
            errors.append(f"{label} pattern detected")

    if "ngrok" in raw.lower():
        errors.append("ngrok reference detected")

    # Verify references between the main assistant and its four sub-workflows
    # are deliberately cleared while retaining readable dependency names.
    if path.name == "ai-assistant-v1.json":
        tool_nodes = [
            node for node in nodes
            if "toolWorkflow" in node.get("type", "")
        ]

        if len(tool_nodes) != 4:
            errors.append("main workflow must contain four workflow-tool nodes")
        else:
            expected_dependencies = {
                "AI Assistant - Calendar Availability Tool",
                "AI Assistant - Google Calendar Booking Tool",
                "AI Assistant - Calendar Slot Finder Tool",
                "AI Assistant - Lead Capture Tool",
            }
            actual_dependencies = set()

            for node in tool_nodes:
                params = node.get("parameters") or {}
                reference = params.get("workflowId")

                if not isinstance(reference, dict):
                    errors.append(
                        "a sub-workflow reference has an unexpected structure"
                    )
                    continue

                if reference.get("value") != "":
                    errors.append("a sub-workflow instance ID is not cleared")

                name = reference.get("cachedResultName")
                if not isinstance(name, str) or not name:
                    errors.append("a sub-workflow name is missing")
                else:
                    actual_dependencies.add(name)

            if actual_dependencies != expected_dependencies:
                errors.append(
                    "main workflow dependency names do not match the expected set"
                )

    # Each Google Calendar node must use the explicit setup placeholder.
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.googleCalendar":
            continue

        calendar = (node.get("parameters") or {}).get("calendar")
        if not isinstance(calendar, dict):
            errors.append("Google Calendar node has no calendar selector")
        elif calendar.get("value") != "YOUR_GOOGLE_CALENDAR_ID":
            errors.append("Google Calendar selector lacks the setup placeholder")

    # Booking workflow also stores the selected calendar ID in Supabase.
    if path.name == "google-calendar-booking-tool.json":
        mapped_values = []
        for node in nodes:
            params = node.get("parameters") or {}
            for field in (
                (params.get("fieldsUi") or {}).get("fieldValues") or []
            ):
                if field.get("fieldId") == "calendar_id":
                    mapped_values.append(field.get("fieldValue"))

        if mapped_values != ["YOUR_GOOGLE_CALENDAR_ID"]:
            errors.append(
                "Supabase calendar_id mapping must use the calendar placeholder"
            )

    # The n8n Data Table selection is tied to the importing instance.
    if path.name == "lead-capture-tool.json":
        table_nodes = [
            node for node in nodes if node.get("name") == "Insert row"
        ]

        if len(table_nodes) != 1:
            errors.append("expected exactly one Insert row Data Table node")
        else:
            reference = (
                table_nodes[0].get("parameters", {}).get("dataTableId")
            )

            if not isinstance(reference, dict):
                errors.append("Data Table reference has an unexpected structure")
            else:
                if reference.get("value") != "":
                    errors.append("Data Table instance ID must be cleared")
                if reference.get("cachedResultName") != (
                    "Select your Data Table after import"
                ):
                    errors.append("Data Table setup placeholder is missing")

    return errors


def main():
    if not WORKFLOW_DIR.is_dir():
        print("FAIL: n8n/workflows directory is missing.")
        return 1

    found_files = {
        path.name for path in WORKFLOW_DIR.glob("*.json")
    }
    expected_files = set(EXPECTED_WORKFLOWS)

    if found_files != expected_files:
        missing = sorted(expected_files - found_files)
        unexpected = sorted(found_files - expected_files)
        if missing:
            print("FAIL: expected workflow file(s) missing:", ", ".join(missing))
        if unexpected:
            print("FAIL: unexpected JSON file(s):", ", ".join(unexpected))
        return 1

    failed = False

    for filename, expected_name in EXPECTED_WORKFLOWS.items():
        errors = validate_workflow(
            WORKFLOW_DIR / filename,
            expected_name,
        )

        if errors:
            failed = True
            print(f"FAIL: {filename}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASS: {filename}")

    if failed:
        print("\nSanitized n8n workflow validation failed.")
        return 1

    print("\nAll five sanitized n8n workflow templates passed validation.")
    print("Note: automated checks cannot detect every possible secret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
