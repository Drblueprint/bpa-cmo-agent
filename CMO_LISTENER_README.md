# BPA CMO Listener — Quick Reference

**Status: Live.** A macOS background service (launchd agent) polls the "BPA CMO Agent" Google Chat space every 45 seconds. When you post a message, it replies via Claude. Kurt's/Toby's messages are read but not auto-replied to.

## How you use it

Just post in the **BPA CMO Agent** Google Chat space. Wait up to 45 seconds. Done.

No need to tag, prefix, or address the agent specifically. Every message from you is treated as a trigger.

## Check that it's running

```bash
launchctl list | grep cmo-listener
```

What the output tells you:
- `<PID>  0  com.bpa.cmo-listener` → running, healthy
- `-     2  com.bpa.cmo-listener` → crashed, will auto-restart in 30s
- _(no output)_ → not loaded

## Watch the live log

```bash
tail -f ~/bpa-cmo-agent/gchat_listener.log
```

Shows every poll cycle, every trigger, every reply. Ctrl-C to stop tailing (the daemon keeps running).

## Stop / start / restart

```bash
# stop
launchctl unload ~/Library/LaunchAgents/com.bpa.cmo-listener.plist

# start
launchctl load ~/Library/LaunchAgents/com.bpa.cmo-listener.plist

# restart (stop + start)
launchctl unload ~/Library/LaunchAgents/com.bpa.cmo-listener.plist && \
  launchctl load ~/Library/LaunchAgents/com.bpa.cmo-listener.plist
```

## Change the trigger policy

Edit `~/bpa-cmo-agent/gchat_listener.py` around line 33-36.

Current (Option A — you only):
```python
OPERATOR_ID = "103942791329982000538"   # Dr. Gumm
```

To let Kurt trigger too:
```python
OPERATOR_IDS = ["103942791329982000538", "117991766839002131558"]
```
_(Also change the `sid != OPERATOR_ID` check to `sid not in OPERATOR_IDS`.)_

Restart the agent after editing.

## Change what Claude knows / how it behaves

Edit the `SYSTEM_PROMPT` constant at the top of `gchat_listener.py`. Restart the agent.

## Cost

Every trigger = one Anthropic API call. Typical reply ≈ 1,500–2,000 output tokens on Sonnet 4.5. Roughly $0.03–$0.05 per reply at current pricing. Check usage at [console.anthropic.com/settings/usage](https://console.anthropic.com/settings/usage).

## Files

All in `~/bpa-cmo-agent/` (symlinked from `~/Desktop/bpa-cmo-agent` for convenience):

| File | Purpose |
|---|---|
| `gchat_listener.py` | The daemon |
| `gchat_poller.py` | Utility — read messages on-demand |
| `gchat_auth.py` | One-time OAuth setup (already done) |
| `gchat_token.json` | OAuth refresh token — **do not commit, do not share** |
| `gchat_oauth.json` | OAuth client secret — **do not commit, do not share** |
| `gchat_listener_state.json` | Cursor — which messages have been seen |
| `gchat_listener.log` | Running log of triggers and replies |
| `launchd.stdout.log` / `launchd.stderr.log` | launchd boot/crash output |
| `.env` | All API keys |

## Troubleshooting

**Agent isn't replying to my messages:**
1. `launchctl list | grep cmo-listener` — is it running?
2. `tail ~/bpa-cmo-agent/gchat_listener.log` — did it see your message?
3. `tail ~/bpa-cmo-agent/launchd.stderr.log` — any crash?

**Replies are wrong / bot is hallucinating data:**
It has no live data access yet. It reasons over chat history only. If you need fresh FB Ads, HubSpot, or Hyros numbers, either:
- Run the relevant script from Claude Code (e.g., `weekly_report_v3.py`)
- Paste the numbers into the chat and ask it to analyze

**Want to pause autonomous replies temporarily:**
`launchctl unload ~/Library/LaunchAgents/com.bpa.cmo-listener.plist` — immediate stop. Load it again when you want to resume.

## What's next (potential expansions)

1. Give the agent **tool access** — let it actually run the FB ads / HubSpot / Hyros pullers when asked, instead of just reasoning over chat
2. Expand trigger policy to let Kurt / Toby @-mention the agent
3. Threaded replies (currently replies post to the existing thread of the triggering message)
4. Scheduled pro-active posts (weekly CMO summary, etc.) tied into the listener

Say the word when you want any of these.
