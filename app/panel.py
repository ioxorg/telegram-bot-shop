from __future__ import annotations

from configs.configs import settings

if settings.panel_type == "pasarguard":
    from app.pasarguard import (
        PasarGuardError as PanelError,
        check_username_available,
        create_subscription,
        fetch_individual_links,
        validate_config_name,
    )
else:
    from app.marzban import (
        MarzbanError as PanelError,
        check_username_available,
        create_subscription,
        fetch_individual_links,
        validate_config_name,
    )

__all__ = [
    "PanelError",
    "create_subscription",
    "check_username_available",
    "validate_config_name",
    "fetch_individual_links",
]
