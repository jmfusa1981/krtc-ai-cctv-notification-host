from django.db.models.signals import post_migrate

_registered = False


def _ensure_default_admin_after_migrate(**kwargs):
    from .bootstrap import ensure_default_admin

    ensure_default_admin(reset_password=False)


def register_default_admin_bootstrap():
    global _registered
    if _registered:
        return
    post_migrate.connect(
        _ensure_default_admin_after_migrate,
        dispatch_uid="krtc.accounts.ensure_default_admin",
        weak=False,
    )
    _registered = True
