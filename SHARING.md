# Sharing this tool with your colleague

Current setup: the app runs on your PC; your colleague reaches it over your office
network. This is a pilot ahead of moving it to the company server — no login,
no separate install on their end.

## One-time setup on your PC

1. **Allow the app through Windows Firewall** (only needs to be done once):
   - Open "Windows Defender Firewall with Advanced Security"
   - Inbound Rules → New Rule → Port → TCP → Specific local port: `8501` → Allow the connection → apply to your network profile (Private/Domain, not Public) → name it e.g. "Lead QA Automation"
2. **Turn off sleep while you're using it**: Settings → System → Power & battery → set "Screen and sleep" so the PC doesn't sleep on your usual working hours (locking the screen is fine — sleep is not, since that pauses the network connection).

## Every time you run it

Double-click `run.bat`. It prints a line like:

```
Share this with your colleague on the same network:
  http://192.168.1.42:8501
```

Send that address to your colleague — they paste it into their browser. Keep the
terminal window open; closing it stops the app.

## Setting up client files

When you add a client in Client Setup, use the paths to your team's shared
OneDrive folder (the same one everyone already has access to) for the
Accumulated Report, TAL, Exclusion, and Suppression files — not a local-only
folder. That way both of you are always working against the same files, and
OneDrive keeps them synced afterward.

If a file is open in Excel on someone else's machine at the exact moment a
check finalizes, OneDrive may create a conflict copy — rare for how this tool
is used (one run at a time), but if you ever see one, treat the copy the app
actually wrote to (the one with the newest timestamp) as the correct version.

## Known limits of this pilot setup

- Your PC needs to be on and connected whenever your colleague might need the
  tool — including outside your usual hours.
- Anyone on your office network with the address can open it (no login yet).
- If your PC is off or asleep, your colleague can't reach it — that's the
  main reason to move this to the company server once you're ready.
