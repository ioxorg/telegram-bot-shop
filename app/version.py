from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

APP_VERSION: str = os.getenv("APP_VERSION", "dev")

_CHANGELOG_PATH = Path(__file__).parent.parent / "CHANGELOG.md"


def _parse_changelog(version: str) -> str:
    """Return the body of the changelog section that matches *version*.

    Matching rules:
    - Tagged releases (v1.2.3 / 1.2.3) → look for ## [1.2.3]
    - Anything else (edge-*, dev, sha-*) → look for ## [Unreleased]

    Returns an empty string when the file is missing or the section is not found.
    """
    if not _CHANGELOG_PATH.exists():
        return ""

    text = _CHANGELOG_PATH.read_text(encoding="utf-8")

    # Normalise version: strip leading "v"
    bare = version.lstrip("v")
    is_release = bool(re.match(r"^\d+\.\d+", bare))
    target_header = f"[{bare}]" if is_release else "[Unreleased]"

    # Split into sections on any "## " heading
    sections = re.split(r"(?m)^## ", text)
    for section in sections:
        header_line = section.splitlines()[0] if section.strip() else ""
        if target_header.lower() in header_line.lower():
            # Everything after the first line is the body; drop bare --- separators
            body_lines = [
                l for l in section.splitlines()[1:]
                if l.strip() != "---"
            ]
            body = "\n".join(body_lines).strip()
            if body:
                return body
    return ""


def _format_notification(version: str, changelog: str) -> str:
    lines = [f"🚀 <b>New deployment</b>  —  <code>{version}</code>"]
    if changelog:
        # Trim to ≤ 30 lines so the message stays readable
        trimmed = "\n".join(changelog.splitlines()[:30])
        lines.append(f"\n📋 <b>Changelog</b>\n{trimmed}")
    return "\n".join(lines)


async def announce_if_new(bot, admin_id: int, db) -> None:
    """Send a deployment notification to the admin if the version changed since last run.

    Reads / writes the `deployed_version` key in bot_settings.
    Safe to call on every startup — does nothing when the version matches.
    """
    from app.repo.bot_settings import get_setting, set_setting

    stored = await get_setting(db, "deployed_version")
    if stored == APP_VERSION:
        return

    await set_setting(db, "deployed_version", APP_VERSION)

    changelog = _parse_changelog(APP_VERSION)
    text = _format_notification(APP_VERSION, changelog)

    try:
        await bot.send_message(admin_id, text, parse_mode="HTML")
        logger.info("Deployment notification sent to admin (version=%s)", APP_VERSION)
    except Exception as exc:
        logger.warning("Could not send deployment notification: %s", exc)
