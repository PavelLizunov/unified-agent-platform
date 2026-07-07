# Hermes chat on another Windows PC (same LAN)

Replicate the "Hermes Chat" launcher on a second Windows machine. The launcher is just
**Git Bash → `ssh hermes`** in a reconnect loop; `ssh hermes` connects to **ops-1 (`192.168.0.203`, LAN)**
as `uap` and runs `~/bin/hermes-chat` there. So the new PC needs 4 things: an SSH client, an authorized key,
the ssh-config host block, and the launcher script. (The Hermes session is shared server-side, so you see the
same conversations from any device.)

## 1. Install Git for Windows
<https://git-scm.com/download/win> → gives **Git Bash** + `ssh`. (Windows Terminal / scoop are optional — only
for the pretty tab; Git Bash alone works.)

## 2. SSH key authorized for `uap@192.168.0.203` — pick ONE

**A. New key (cleaner, no private-key copying) — recommended.** In Git Bash on the new PC:
```bash
ssh-keygen -t ed25519 -C "$USERNAME-windows"      # press Enter through the prompts
cat ~/.ssh/id_ed25519.pub                          # send me this line -> I authorize it on ops-1
```
Send the owner/agent the printed `.pub` line; it gets appended to `uap@192.168.0.203:~/.ssh/authorized_keys`.

**B. Copy the existing key (fastest).** Copy from the first PC
`C:\Users\x3d_mutant\.ssh\id_ed25519` **and** `id_ed25519.pub` → new PC `C:\Users\<user>\.ssh\`.
Same key = already authorized. (Move it over USB/secure share, not e-mail.)

## 3. SSH config
Append to `C:\Users\<user>\.ssh\config` (create the file if absent):
```
Host hermes
    HostName 192.168.0.203
    User uap
    RequestTTY yes
    RemoteCommand ~/bin/hermes-chat
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist yes
    ServerAliveInterval 20
    ServerAliveCountMax 3
    TCPKeepAlive yes
    Compression no
    Ciphers aes128-gcm@openssh.com
```
> On tailnet but NOT the same LAN? Change `HostName` to ops-1's tailnet IP `100.82.241.121`.

## 4. Launcher script
In Git Bash: `mkdir -p ~/bin` then create `~/bin/hermes.sh`:
```bash
#!/usr/bin/env bash
# keep hermes-chat alive: reconnect on drop; clean exit stops.
while true; do
    ssh hermes && break
    echo -e "\n[reconnecting in 2s, Ctrl-C to quit]"
    sleep 2
done
```

## 5. Launch
Git Bash: `bash ~/bin/hermes.sh` → Hermes chat.

**Pretty one-click shortcut (optional):** create a Windows shortcut whose target is
`"C:\Program Files\Git\bin\bash.exe" -l -c "~/bin/hermes.sh"` (set an icon via Properties → Change Icon).
If you want the exact Windows-Terminal tab like the first PC, install Windows Terminal and use target
`wt.exe new-tab --title "Hermes Chat" --suppressApplicationTitle "C:\Program Files\Git\bin\bash.exe" -l -c "~/bin/hermes.sh"`.

## Verify
`ssh hermes` from Git Bash on the new PC should drop you straight into the Hermes chat TUI. If it asks for a
password, the key isn't authorized yet (redo step 2). If it hangs, the PC can't reach `192.168.0.203` (wrong
LAN — use the tailnet IP).
