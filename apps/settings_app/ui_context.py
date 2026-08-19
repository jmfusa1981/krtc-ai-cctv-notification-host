from .models import UIConfiguration


def ui_configuration(request):
    try:
        config = UIConfiguration.load()
    except Exception:
        config = None
    return {"ui_config": config}
