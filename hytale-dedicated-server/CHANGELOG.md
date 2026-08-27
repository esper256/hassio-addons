# Changelog

## 3.1.2

- Keep the downloader's complete `?user_code=` sign-in URL (the fallback URL without the code no longer overwrites it)
- Sign-in card copy: the code on the card is the device login; an emailed Hytale login code is a different code

## 3.1.1

- Store art: square tile is the official Hytale H; Info header wordmark is letterboxed so letters are not cropped

## 3.1.0

- First Hytale dedicated-server app on supervisor **3.1**
- Official Linux downloader (`package_install.kind: command`) plus Ingress sign-in card for the two device-code logins (download, then `/auth login device`)
- UDP **5520** QUIC; Java 25; universe folder backups; empty active log patterns until a live boot
