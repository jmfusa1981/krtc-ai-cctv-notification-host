from .models import UIConfiguration
from .services.frontend_assets import resolve_login_background_url


def ui_configuration(request):
    try:
        config = UIConfiguration.load()
    except Exception:
        config = None
    resolver_match = getattr(request, "resolver_match", None)
    is_frontend_login = bool(resolver_match and resolver_match.url_name == "login")
    return {
        "ui_config": config,
        "login_background_url": (
            resolve_login_background_url(config)
            if config and is_frontend_login
            else ""
        ),
    }
