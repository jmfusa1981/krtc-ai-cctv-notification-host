from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.usb_key import create_or_register_master_key, list_removable_drives, verify_trusted_key
from apps.accounts.permissions import hidden_forbidden_response
from apps.settings_app.models import UIConfiguration
from apps.station_api.security_audit import record_security_audit


@login_required
def superuser_usb_manager(request):
    if not request.user.is_superuser:
        return hidden_forbidden_response()

    config = UIConfiguration.load()

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        drive = (request.POST.get("drive") or "").strip()

        if action == "create_register":
            try:
                result = create_or_register_master_key(drive)
            except Exception as exc:
                messages.error(request, f"USB Key 建立／登錄失敗：{exc}")
                record_security_audit(action="USB_KEY_REGISTER_FAILED", result="failed", request=request, user=request.user, auth_method="PASSWORD+USB", detail=str(exc))
            else:
                config.superuser_usb_required = True
                config.superuser_usb_token_sha256 = result["token_sha256"]
                config.superuser_usb_key_id = result["key_id"]
                config.superuser_usb_updated_at = timezone.now()
                config.save(update_fields=[
                    "superuser_usb_required", "superuser_usb_token_sha256",
                    "superuser_usb_key_id", "superuser_usb_updated_at", "updated_at",
                ])
                verb = "建立" if result["created"] else "登錄"
                messages.success(request, f"已{verb} KRTC Master USB Key：{result['key_id']}。USB 二次驗證已啟用。")
                record_security_audit(action="USB_KEY_REGISTERED", result="success", request=request, user=request.user, auth_method="PASSWORD+USB", metadata={"key_id": result.get("key_id", "")})

        elif action == "verify":
            ok, info = verify_trusted_key(config.superuser_usb_token_sha256)
            if ok:
                messages.success(request, f"USB Key 驗證成功：{info.get('key_id') or 'KRTC Master Key'} ({info.get('drive')})")
                record_security_audit(action="USB_VERIFY_SUCCESS", result="success", request=request, user=request.user, auth_method="PASSWORD+USB", metadata={"key_id": info.get("key_id", "")})
            else:
                messages.error(request, "未找到目前主機已信任的 USB Key。")
                record_security_audit(action="USB_VERIFY_FAILED", result="failed", request=request, user=request.user, auth_method="PASSWORD+USB", detail="Trusted USB key not found")

        elif action == "disable":
            config.superuser_usb_required = False
            config.superuser_usb_token_sha256 = ""
            config.superuser_usb_key_id = ""
            config.superuser_usb_updated_at = timezone.now()
            config.save(update_fields=[
                "superuser_usb_required", "superuser_usb_token_sha256",
                "superuser_usb_key_id", "superuser_usb_updated_at", "updated_at",
            ])
            messages.warning(request, "此主機的 Superuser USB 二次驗證已停用。USB 內的 Master Key 檔案未刪除。")
            record_security_audit(action="USB_KEY_DISABLED", result="success", request=request, user=request.user, auth_method="PASSWORD+USB")

        return redirect("superuser_usb_manager")

    verified, verified_info = verify_trusted_key(config.superuser_usb_token_sha256)
    context = {
        **admin.site.each_context(request),
        "title": "Superuser USB Key 管理",
        "config": config,
        "drives": list_removable_drives(),
        "verified": verified,
        "verified_info": verified_info,
    }
    return render(request, "admin/superuser_usb_key.html", context)
