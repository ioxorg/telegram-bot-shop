# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [Unreleased]

---

## [1.3.0] - 2026-06-01

### Added
- **Broadcast** — admin can send or forward any message (text, photo, video, sticker…) to all users with a Confirm / Cancel step before sending; progress shown every 50 users with final sent/failed summary
- **Deployment announcements** — bot notifies admin on first startup after a new image is deployed, including the relevant changelog section
- **CI/CD** — GitHub Actions now SSH-deploys to the remote server after every successful push to `main`; GHCR package is private (no anonymous pulls)

### Changed
- **PasarGuard panel support** — `PANEL_TYPE=pasarguard` switches from Marzban; user creation payload uses `group_ids` (integer list) instead of inbound fetching; group configured via `PASARGUARD_GROUP_ID`
- All panel error handling unified under `PanelError` (handlers no longer import directly from `app.marzban`)

---

## [1.2.0] - 2026-05-20

### Added
- **Sales representative system** — reps get a GB wallet, can charge it (with 5 % cashback on 40 GB+), and create configs for customers from their balance
- Min / max purchase rate limits for rep charges

---

## [1.1.0] - 2026-05-01

### Added
- NOWPayments crypto payment integration
- Telegram Stars payment support
- Force-join channel gate (admin-configurable)
- Phone-number verification flow

### Changed
- Plans no longer store a title column; display is computed from GB/days/users

---

## [1.0.0] - 2026-04-15

### Added
- Initial release: Marzban panel integration, card-to-card payment with admin receipt review, multi-language (fa/en), SQLite + PostgreSQL support
