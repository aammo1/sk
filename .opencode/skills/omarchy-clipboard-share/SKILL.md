---
name: omarchy-clipboard-share
description: >
  Cross-user clipboard sync on this Omarchy machine. Use when troubleshooting,
  extending, pausing, or uninstalling the shared clipboard between user
  accounts (tal7a, boil, new users), or when asked "how do I copy between
  users / why isn't my clipboard syncing". Covers /srv/clipshare,
  clipshare-sync, and the clipshare systemd user service.
---

# Omarchy Clipboard Share (cross-user sync)

Syncs the Wayland clipboard between desktop user sessions on this machine —
text and images, both directions, automatic. Password offers marked
"confidential" (KeePassXC hint, nspasteboard markers) are excluded.

## Architecture

| Piece | Role |
|---|---|
| `/usr/local/bin/clipshare-sync` | The engine: watcher + receiver, identical for every user |
| `/srv/clipshare/` | Shared spool; each clipboard event is a file `clip-<microseconds>-<user>.<txt|png|jpg>`, kept byte-exact, trimmed to the 10 newest |
| `~/.config/systemd/user/clipshare.service` (per account) | Starts with the desktop session, Omarchy pattern (`graphical-session.target`, `ConditionEnvironment=WAYLAND_DISPLAY`) |
| `~/.cache/clipshare/` | Per-user state: `state` (last applied timestamp), `last-sent-hash`, `last-recv-hash`, `paused` marker |

Flow: each user's service watches its clipboard (`wl-paste --watch`).
New content → spool file (hash-deduped vs last sent/received). Each session's
0.5 s receive loop applies the newest spool entry whose sender is the *other*
user via `wl-copy --type <mime>`. Relay login: a user logging in later
instantly receives the spool's latest entry.

## Key rules baked into the script (do not "simplify" these)

- `wl-paste` **appends a newline to text payloads by default**. Broadcast must
  use `wl-paste --no-newline` or every round trip grows the content by one
  `\n` and defeats hash dedupe → infinite ping-pong loop (observed in the wild).
- Spool writes go through a temp-file + `mv` (atomic) so receivers never read
  partial files.
- Broadcast/receive dedupe on content hash against `last-sent-hash` /
  `last-recv-hash` — this is the loop breaker.
- Supported MIME: `text/plain*` (prefix match, charset variants), `image/png`,
  `image/jpeg`. Other offers are intentionally ignored.

## Adding a new user

```bash
sudo clipshare-enable-user <username>
```

Installs + enables the service for that account (idempotent). Starts at once
if they're logged in, otherwise at next login. The spool itself needs no
per-user config (world-writable by design, local machine only).
Helper script lives at `/usr/local/bin/clipshare-enable-user`.

## Common operations

```bash
systemctl --user status clipshare            # health of my session
systemctl --user restart clipshare
journalctl --user -u clipshare -n 50         # logs
touch ~/.cache/clipshare/paused              # pause sync for my account
rm ~/.cache/clipshare/paused                 # resume
systemctl --user disable --now clipshare     # opt out of the sync
```

Uninstall entirely: `systemctl --user disable --now clipshare` per user,
remove `~/.config/systemd/user/clipshare.service` + wants symlink, plus
`/usr/local/bin/clipshare-sync` and `/srv/clipshare`.

## Removing a user from the sync

Run as root (or that user can do their own steps without sudo):

```bash
# stop and un-enable in the running session (root):
systemctl --user -M <user>@.host disable --now clipshare.service

# delete the per-account files (root):
rm  /home/<user>/.config/systemd/user/clipshare.service
rm  /home/<user>/.config/systemd/user/graphical-session.target.wants/clipshare.service
rm -rf /home/<user>/.cache/clipshare          # their per-user state
```

If the user is not logged in, only the two `rm` lines are needed — nothing is
running for them. No spool change required: `/srv/clipshare` keeps working for
the remaining users.

## Complete removal (uninstall the whole feature)

No dedicated uninstall helper is installed; do it manually:

```bash
# 1. Stop + un-enable for every account that has it (root):
for u in tal7a boil; do
  systemctl --user -M "$u@.host" disable --now clipshare.service 2>/dev/null
done
# repeat the loop line for any other users added later (clipshare-enable-user)

# 2. Remove per-account files for each of those users:
rm -i /home/<user>/.config/systemd/user/clipshare.service
rm  /home/<user>/.config/systemd/user/graphical-session.target.wants/clipshare.service
rm -rf /home/<user>/.cache/clipshare

# 3. Remove the shared pieces (root):
rm  /usr/local/bin/clipshare-sync
rm  /usr/local/bin/clipshare-enable-user
rm -rf /srv/clipshare

# 4. Sanity check — nothing of it should be left:
pgrep -a -f clipshare
ls /usr/local/bin/clipshare* /srv/clipshare 2>&1
```

After step 1–2, clipboards of currently-logged-in users keep whatever content
they last had; nothing new is synced, and both accounts work as normal,
separate Wayland sessions again. Re-adding later is just
`clipshare-enable-user` again (or a fresh install per the skill's history).

## Troubleshooting

- "Copies don't arrive" → is the service active on the *other* user's
  session? The spool only carries content both watchers round-trip.
- Clipboard content mutated/newline loops → check `broadcast()` still uses
  `--no-newline`; check for more than one running instance per user
  (`pgrep -a -f clipshare-sync`; note processes of the *other* user appear
  in a plain `pgrep -f`, so filter by cgroup, not by output).
- `journalctl --user` shows "no Wayland display available" → the service ran
  before the desktop env was imported; `systemctl --user restart clipshare`
  after login. The unit's `ConditionEnvironment=WAYLAND_DISPLAY` mirrors how
  Omarchy's own services gate this.
- Stale state messing with dedupe → `rm ~/.cache/clipshare/*` (harmless; next
  sync re-initializes).
