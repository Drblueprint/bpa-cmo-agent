"""
BPA CMO Agent \u2014 conversational listener daemon (v2 with tools).

Polls the "BPA CMO Agent" Google Chat space.
When Dr. Gumm posts a message, sends it + recent context to Claude
(Opus 4.6 with adaptive thinking + tool access) and posts Claude's reply
back via the incoming webhook.

v2 changes from v1:
  - Model upgraded to claude-opus-4-6
  - Adaptive thinking + effort control
  - Prompt caching on the system block (stable prefix, big win on cost)
  - Tool-use loop via client.beta.messages.tool_runner
  - 7 read-only tools exposed (FB Ads, HubSpot, Hyros, chat history)
  - Max 6 tool iterations per trigger (bounded cost)

Trigger policy (Option A): only Dr. Gumm's messages auto-trigger replies.
Kurt / Toby messages are logged for context but no auto-reply.
"""
import argparse
import json
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from anthropic import Anthropic

sys.path.insert(0, str(Path(__file__).parent))
from cmo_tools import ALL_TOOLS


# --- Config --------------------------------------------------------------

BASE = Path(__file__).parent
ENV_PATH = BASE / ".env"
TOKEN_PATH = BASE / "gchat_token.json"
STATE_PATH = BASE / "gchat_listener_state.json"
LOG_PATH = BASE / "gchat_listener.log"

OPERATOR_ID = "103942791329982000538"   # Dr. Gumm
SENDER_NAMES = {
    "103942791329982000538": "Dr. Gumm",
    "117991766839002131558": "Kurt Kleinpeter",
    "114022495153014004089": "CMO Agent (bot)",
}
BOT_SENDER_ID = "114022495153014004089"

SCOPES = [
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
]

MODEL = "claude-opus-4-6"
MAX_CONTEXT_MESSAGES = 20
POLL_INTERVAL_SECONDS = 45
REPLY_COOLDOWN_SECONDS = 2
MAX_TOOL_ITERATIONS = 6
MAX_OUTPUT_TOKENS = 4096


SYSTEM_PROMPT = """You are the BPA CMO Agent for Dr. Aaron Gumm, CEO of Blueprint to Practice Automation (BPA \u2014 yourautomatedpractice.com). BPA's audience is chiropractors and private-practice specialists; BPA sells an operating system (5 domains x 24 modules) plus coaching to help those practices scale.

You're conversing in the "BPA CMO Agent" Google Chat space. Dr. Gumm is the operator; Kurt Kleinpeter (marketing manager) may also post. Only Dr. Gumm's messages trigger your responses. Kurt's messages appear in your context but you do not auto-reply to him.

Role \u2014 senior CMO voice:
- Strategic, direct, specific. Give the WHY behind the WHAT.
- Push back when you disagree. Don't suck up. Don't soften with hedging.
- Flag assumptions you're making out loud.
- Kurt's corrections are always welcome; receive them without defensiveness.

Voice & formatting:
- Write like a human. No corporate filler, no "I'd be happy to".
- Google Chat uses *single asterisks* for bold. Don't use markdown double-asterisks \u2014 they render as literal asterisks in chat.
- Use structure (short bullets, *bold* headings) only when it earns its keep. Scannable beats thorough.
- Keep most replies tight. Expand only when depth is warranted.
- No emojis unless Dr. Gumm uses one first.
- Never open with "Here's my analysis" or "Let me break this down". Just answer.

Tools \u2014 you have live read-only access:
- run_weekly_ad_report: full FB+Hyros+HubSpot weekly snapshot (slow, ~60s, only call when a full snapshot is truly needed)
- pull_ad_level_data: per-ad FB performance, optional substring filter
- run_creative_diagnostic: flags zero-lead / high-CPL / low-CTR ads + their copy & images
- pull_hubspot_funnel: HubSpot contacts + funnel + closed-won by source
- pull_hyros_attribution: Hyros lead + call attribution (note: Hyros sale events aren't wired, so revenue is unreliable)
- get_campaign_performance: specific campaign or talent by name
- search_chat_history: search older chat beyond the 20 most recent messages

Tool-use rules:
- Use tools when Dr. Gumm asks for fresh numbers, a specific campaign, or chat context older than ~20 messages.
- DO NOT use tools for strategic or opinion questions where you already have the context. Don't run a weekly report just to answer "what do you think about X."
- If two or three tools would answer the same question, pick one.
- Never call run_weekly_ad_report more than once per conversation.
- If a tool errors or times out, tell Dr. Gumm what you tried and what failed. Don't pretend the data is fine.

Context handling:
- The recent chat history (you/Kurt/Dr. Gumm) is in your message history. Use it.
- If Dr. Gumm references something older than what you see, use search_chat_history before asking him to re-explain.
- If Kurt posted something and Dr. Gumm asks your take, read Kurt's actual message in context, then answer. Don't fabricate what he said.

Format your reply as the message body that will be posted directly in chat. No preamble. No meta-commentary. Just the answer Dr. Gumm will read."""


# --- env / auth ----------------------------------------------------------

def load_env():
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def load_creds() -> Credentials:
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    return creds


# --- state ---------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def log(line: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with LOG_PATH.open("a") as f:
        f.write(f"{ts}  {line}\n")
    print(f"{ts}  {line}", flush=True)


# --- chat I/O ------------------------------------------------------------

def resolve_cmo_space(svc) -> str:
    page = None
    while True:
        resp = svc.spaces().list(pageSize=100, pageToken=page).execute()
        for s in resp.get("spaces", []):
            if (s.get("displayName") or "").strip().lower() == "bpa cmo agent":
                return s["name"]
        page = resp.get("nextPageToken")
        if not page:
            break
    raise SystemExit("Couldn't find 'BPA CMO Agent' space. Check membership.")


def fetch_messages_since(svc, space: str, since_iso: str) -> list:
    out, page = [], None
    flt = f'createTime > "{since_iso}"'
    while True:
        resp = (
            svc.spaces().messages()
            .list(parent=space, pageSize=100, pageToken=page,
                  filter=flt, orderBy="createTime ASC")
            .execute()
        )
        out.extend(resp.get("messages", []))
        page = resp.get("nextPageToken")
        if not page:
            break
    return out


def fetch_recent_context(svc, space: str, limit: int) -> list:
    """Pull the last `limit` messages for Claude's context window."""
    out, page = [], None
    while True:
        resp = (
            svc.spaces().messages()
            .list(parent=space, pageSize=min(limit, 100), pageToken=page,
                  orderBy="createTime DESC")
            .execute()
        )
        out.extend(resp.get("messages", []))
        if len(out) >= limit:
            break
        page = resp.get("nextPageToken")
        if not page:
            break
    return list(reversed(out[:limit]))


def post_reply(webhook: str, text: str, thread_name: str = None) -> None:
    payload = {"text": text}
    url = webhook
    if thread_name:
        payload["thread"] = {"name": thread_name}
        url = f"{webhook}&messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status >= 300:
            log(f"WEBHOOK non-2xx: {r.status} {r.read().decode()[:200]}")


# --- claude --------------------------------------------------------------

def name_of(sender_id: str) -> str:
    return SENDER_NAMES.get(sender_id, f"Unknown ({sender_id[-6:]})")


def build_claude_messages(history: list, trigger_msg: dict) -> list:
    msgs = []
    for m in history:
        sid = (m.get("sender") or {}).get("name", "").split("/")[-1]
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if sid == BOT_SENDER_ID:
            msgs.append({"role": "assistant", "content": text})
        else:
            speaker = name_of(sid)
            msgs.append({"role": "user", "content": f"[{speaker}] {text}"})

    collapsed = []
    for m in msgs:
        if collapsed and collapsed[-1]["role"] == m["role"]:
            collapsed[-1]["content"] += "\n\n" + m["content"]
        else:
            collapsed.append(m)

    trigger_text = (trigger_msg.get("text") or "").strip()
    trigger_sid = (trigger_msg.get("sender") or {}).get("name", "").split("/")[-1]
    trigger_line = f"[{name_of(trigger_sid)}] {trigger_text}"

    if collapsed and collapsed[-1]["role"] == "user":
        if trigger_line not in collapsed[-1]["content"]:
            collapsed[-1]["content"] += "\n\n" + trigger_line
    else:
        collapsed.append({"role": "user", "content": trigger_line})

    return collapsed


def run_agent(client: Anthropic, messages: list) -> tuple:
    """Run the tool-use loop. Returns (final_text, usage_summary)."""
    system_blocks = [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_blocks,
        tools=ALL_TOOLS,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
    )

    iterations = 0
    last_msg = None
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    tool_calls_made = []

    for msg in runner:
        iterations += 1
        last_msg = msg
        u = getattr(msg, "usage", None)
        if u:
            totals["input"] += getattr(u, "input_tokens", 0) or 0
            totals["output"] += getattr(u, "output_tokens", 0) or 0
            totals["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
            totals["cache_create"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        for block in (getattr(msg, "content", []) or []):
            if getattr(block, "type", "") == "tool_use":
                tool_calls_made.append(block.name)

        if iterations >= MAX_TOOL_ITERATIONS:
            log(f"WARN: hit MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS}; stopping early")
            break

    text_chunks = []
    for block in (getattr(last_msg, "content", []) or []):
        if getattr(block, "type", "") == "text":
            text_chunks.append(block.text)
    reply = "\n".join(text_chunks).strip()

    return reply, {**totals, "iterations": iterations, "tool_calls": tool_calls_made}


# --- main loop -----------------------------------------------------------

def process_new_messages(svc, space: str, env: dict, state: dict,
                          dry_run: bool, client: Anthropic) -> int:
    since = state.get(space) or (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    new_msgs = fetch_messages_since(svc, space, since)
    replied = 0

    for m in new_msgs:
        create_time = m.get("createTime")
        sender = (m.get("sender") or {}) or {}
        sid = sender.get("name", "").split("/")[-1]
        stype = sender.get("type", "HUMAN")
        text = (m.get("text") or "").strip()
        who = name_of(sid)

        state[space] = create_time

        if stype != "HUMAN":
            log(f"skip  [{who}] non-human ({stype})")
            continue
        if not text:
            log(f"skip  [{who}] empty")
            continue
        if sid != OPERATOR_ID:
            log(f"read  [{who}] {text[:80]}")
            continue

        log(f"TRIGGER  [{who}] {text[:140]}")

        try:
            history = fetch_recent_context(svc, space, MAX_CONTEXT_MESSAGES)
            claude_msgs = build_claude_messages(history, m)
            t0 = time.time()
            reply, usage = run_agent(client, claude_msgs)
            elapsed = time.time() - t0
        except Exception as e:
            log(f"ERROR generating reply: {e}")
            log(traceback.format_exc())
            continue

        log(
            f"REPLY ({len(reply)}ch, {elapsed:.1f}s, "
            f"iter={usage['iterations']}, tools={usage['tool_calls']}, "
            f"in={usage['input']}, out={usage['output']}, "
            f"cache_r={usage['cache_read']}, cache_w={usage['cache_create']})"
        )
        if not reply:
            log("WARN: empty reply \u2014 skipping post")
            continue

        if dry_run:
            log("DRY RUN \u2014 not posting")
            log(f"REPLY TEXT:\n{reply}")
        else:
            try:
                post_reply(env["GCHAT_CMO_WEBHOOK"], reply,
                           thread_name=(m.get("thread") or {}).get("name"))
                replied += 1
                time.sleep(REPLY_COOLDOWN_SECONDS)
            except Exception as e:
                log(f"ERROR posting reply: {e}")

    save_state(state)
    return replied


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--loop", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--since-hours", type=float)
    args = p.parse_args()

    env = load_env()
    if "ANTHROPIC_API_KEY" not in env:
        raise SystemExit("ANTHROPIC_API_KEY missing from .env")
    if "GCHAT_CMO_WEBHOOK" not in env:
        raise SystemExit("GCHAT_CMO_WEBHOOK missing from .env")

    client = Anthropic(api_key=env["ANTHROPIC_API_KEY"])

    creds = load_creds()
    svc = build("chat", "v1", credentials=creds)
    space = resolve_cmo_space(svc)
    log(f"v2 listening on {space}  model={MODEL}  tools={len(ALL_TOOLS)}  dry_run={args.dry_run}")

    state = load_state()
    if args.since_hours:
        state[space] = (
            datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        log(f"cursor overridden: {args.since_hours}h back to {state[space]}")

    if not args.loop:
        n = process_new_messages(svc, space, env, state, args.dry_run, client)
        log(f"done \u2014 replied to {n} message(s)")
        return

    while True:
        try:
            n = process_new_messages(svc, space, env, state, args.dry_run, client)
            if n:
                log(f"cycle: replied to {n}")
        except Exception as e:
            log(f"CYCLE ERROR: {e}")
            log(traceback.format_exc())
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
