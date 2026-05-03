"""
Email monitoring agent for Raj's Robot Rentals.

Polls the Gmail inbox on a configurable interval, reads unread threads,
and drafts context-appropriate replies using Claude Opus 4.7.

Usage:
    python agent.py            # runs continuously (default: every 5 minutes)
    python agent.py --once     # runs one cycle and exits
"""

import argparse
import json
import logging
import os
import time
from typing import Any

import anthropic
from dotenv import load_dotenv

from config import SYSTEM_PROMPT
from gmail_client import GmailClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[anthropic.types.ToolParam] = [
    {
        "name": "search_emails",
        "description": (
            "Search for email threads in the Gmail inbox. Returns a list of threads "
            "with their IDs, subjects, senders, dates, and snippets. Threads already "
            "processed by the agent are automatically excluded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query, e.g. 'is:unread in:inbox' or "
                        "'is:unread from:customer@example.com'"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of threads to return (default 10, max 50).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_email_thread",
        "description": (
            "Fetch the full content of an email thread, including all messages, "
            "senders, recipients, dates, and bodies."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The Gmail thread ID.",
                }
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "create_reply_draft",
        "description": (
            "Create a draft reply to an email thread. The draft will appear in the "
            "Gmail Drafts folder for Raj to review and send. Never call this twice "
            "for the same thread."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The thread ID to reply to.",
                },
                "message_id": {
                    "type": "string",
                    "description": "The ID of the specific message being replied to.",
                },
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses.",
                },
                "subject": {
                    "type": "string",
                    "description": "Reply subject line (usually 'Re: <original subject>').",
                },
                "body": {
                    "type": "string",
                    "description": "Plain-text body of the reply.",
                },
            },
            "required": ["thread_id", "message_id", "to", "subject", "body"],
        },
    },
    {
        "name": "mark_thread_processed",
        "description": (
            "Apply the 'AI-Agent-Processed' label to a thread so the agent won't "
            "revisit it on future cycles. Call this after creating a draft OR after "
            "deciding to skip a thread."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The thread ID to mark as processed.",
                }
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "skip_thread",
        "description": (
            "Skip a thread that does not require a reply (e.g. newsletter, automated "
            "notification, spam, or thread where Raj already replied). Still marks "
            "the thread processed so it won't appear again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "The thread ID to skip.",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for skipping.",
                },
            },
            "required": ["thread_id", "reason"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


def execute_tool(gmail: GmailClient, name: str, inputs: dict) -> Any:
    if name == "search_emails":
        return gmail.search_threads(
            query=inputs["query"],
            max_results=inputs.get("max_results", 10),
        )

    if name == "get_email_thread":
        return gmail.get_thread(inputs["thread_id"])

    if name == "create_reply_draft":
        return gmail.create_draft(
            thread_id=inputs["thread_id"],
            message_id=inputs["message_id"],
            to=inputs["to"],
            subject=inputs.get("subject", ""),
            body=inputs["body"],
            html_body=inputs.get("html_body"),
        )

    if name == "mark_thread_processed":
        return gmail.mark_processed(inputs["thread_id"])

    if name == "skip_thread":
        # Mark processed even when skipping so it won't resurface
        result = gmail.mark_processed(inputs["thread_id"])
        result["skipped_reason"] = inputs.get("reason", "")
        return result

    return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Agent cycle
# ---------------------------------------------------------------------------

USER_KICKOFF = (
    "Please check my inbox for new unread emails that need replies. "
    "Search for unread messages in the inbox, read each thread carefully, "
    "and draft a professional reply where appropriate. "
    "Skip newsletters, automated notifications, and threads where I've already replied. "
    "Mark every thread as processed when you're done with it."
)


def run_cycle(client: anthropic.Anthropic, gmail: GmailClient) -> None:
    log.info("Starting email check cycle…")

    messages: list[anthropic.types.MessageParam] = [
        {"role": "user", "content": USER_KICKOFF}
    ]

    while True:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Cache the stable system prompt so repeated cycles are cheap
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        log.info(
            "Response: stop_reason=%s | cache_read=%s input_tokens=%s output_tokens=%s",
            response.stop_reason,
            response.usage.cache_read_input_tokens,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        # Append assistant turn to maintain conversation history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    log.info("Agent summary: %s", block.text)
            break

        if response.stop_reason != "tool_use":
            log.warning("Unexpected stop_reason: %s", response.stop_reason)
            break

        # Execute every tool call in this turn
        tool_results: list[anthropic.types.ToolResultBlockParam] = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            log.info("Tool call: %s(%s)", block.name, _short(block.input))
            result = execute_tool(gmail, block.name, block.input)
            log.info("Tool result: %s", _short(result))

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    log.info("Cycle complete.")


def _short(obj: Any, limit: int = 200) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    return text[:limit] + "…" if len(text) > limit else text


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Raj's Robot Rentals — email agent")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle then exit instead of looping.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("CHECK_INTERVAL_SECONDS", "300")),
        help="Seconds between checks (default 300 / 5 min).",
    )
    args = parser.parse_args()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    gmail = GmailClient()

    if args.once:
        run_cycle(client, gmail)
        return

    log.info("Email agent started — checking every %d seconds.", args.interval)
    while True:
        try:
            run_cycle(client, gmail)
        except Exception:
            log.exception("Error during cycle; will retry next interval.")

        log.info("Sleeping %d seconds until next check…", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
