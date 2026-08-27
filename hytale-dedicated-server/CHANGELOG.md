# Changelog

## 3.3.1

- Listen on UDP **25565**, the Hytale client Direct Connect default when you omit the port (the join box hint is `:25565`). The dedicated-server binary still defaults to 5520 if you omit `--bind`; we pass `--bind 0.0.0.0:25565`. After updating, forward **UDP 25565** and join with the host IP alone (or `:25565`). A previous 5520 forward will not match.

## 3.3.0

- Shared supervisor **3.3**: a Home Assistant stop (SIGTERM) during first install exits cleanly instead of crashing with `package install failed`; install commands notice stop without waiting for the next log line; `/healthz` stays reachable for watchdog and Docker healthchecks when Ingress peer checks apply. Vendored `game_server/` sync.
- If the app restarts during the first Hytale sign-in, press **Start** again — a new device code is issued. Uninstall is not required.

## 3.2.1

- Strip ANSI color resets from Java `/auth` device-code lines so `user_code` is not `KuFxp9fw` plus ESC[m

## 3.2.0

- Shared supervisor **3.2**: Ingress toast when live status refresh fails (app stopped or unresponsive)
- Keep the downloader's complete `?user_code=` sign-in URL (the fallback URL without the code no longer overwrites it)
- Sign-in card: device code vs emailed login code; finish Hytale login first, then open the link to reach Authorize a device; 10-minute downloader wait
- Retry download sign-in with a fresh device code when the official downloader hits `error obtaining token: context deadline exceeded` (keeps waiting until sign-in succeeds or you stop the app)

## 3.1.2

- Keep the downloader's complete `?user_code=` sign-in URL (the fallback URL without the code no longer overwrites it)
- Sign-in card copy: the code on the card is the device login; an emailed Hytale login code is a different code

## 3.1.1

- Store art: square tile is the official Hytale H; Info header wordmark is letterboxed so letters are not cropped

## 3.1.0

- First Hytale dedicated-server app on supervisor **3.1**
- Official Linux downloader (`package_install.kind: command`) plus Ingress sign-in card for the two device-code logins (download, then `/auth login device`)
- UDP **5520** QUIC; Java 25; universe folder backups; empty active log patterns until a live boot
