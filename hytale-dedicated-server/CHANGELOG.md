# Changelog

## 3.2.0

- Shared supervisor **3.2**: Ingress toast when live status refresh fails (app stopped or unresponsive)
- Keep the downloader's complete `?user_code=` sign-in URL (the fallback URL without the code no longer overwrites it)
- Sign-in card: device code vs emailed login code; finish Hytale login first, then open the link to reach Authorize a device; 10-minute downloader wait
- Retry download sign-in with a fresh device code when the official downloader hits `error obtaining token: context deadline exceeded` (keeps waiting until sign-in succeeds or you stop the app)
- HA Logs print the coalesced sign-in URL (own line) and device code so you can finish OAuth from the Logs tab without Open Web UI

## 3.1.2

- Keep the downloader's complete `?user_code=` sign-in URL (the fallback URL without the code no longer overwrites it)
- Sign-in card copy: the code on the card is the device login; an emailed Hytale login code is a different code

## 3.1.1

- Store art: square tile is the official Hytale H; Info header wordmark is letterboxed so letters are not cropped

## 3.1.0

- First Hytale dedicated-server app on supervisor **3.1**
- Official Linux downloader (`package_install.kind: command`) plus Ingress sign-in card for the two device-code logins (download, then `/auth login device`)
- UDP **5520** QUIC; Java 25; universe folder backups; empty active log patterns until a live boot
