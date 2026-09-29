from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from apps.accounts.permissions import can_view_advanced_settings, can_view_security_audit, hidden_forbidden_response
from apps.station_api.models import DeviceFaultLog, SecurityAuditLog

DEVICE_LABELS = dict(DeviceFaultLog.DEVICE_TYPE_CHOICES)
SEVERITY_LABELS = {"info": "資訊", "warning": "警告", "critical": "嚴重"}
STATUS_LABELS = {"active": "異常中", "recovered": "已恢復"}
AUDIT_RESULT_LABELS = {"success": "成功", "failed": "失敗", "info": "紀錄"}
AUDIT_ACTION_LABELS = {
    "LOGIN_SUCCESS": "登入成功",
    "LOGIN_FAILED": "登入失敗",
    "LOGOUT": "登出",
    "USB_VERIFY_SUCCESS": "USB Key 驗證成功",
    "USB_VERIFY_FAILED": "USB Key 驗證失敗",
    "USB_KEY_REGISTERED": "USB Key 建立／登錄",
    "USB_KEY_DISABLED": "USB Key 驗證停用",
    "USER_CREATED": "建立使用者",
    "USER_UPDATED": "修改使用者",
    "USER_DISABLED": "停用使用者",
    "USER_ENABLED": "啟用使用者",
    "STATION_SETTINGS_UPDATED": "修改本站設定",
}


@login_required
def system_log_list(request):
    if not can_view_advanced_settings(request.user):
        return hidden_forbidden_response()

    category = (request.GET.get("category") or "device").strip().lower()
    if category not in {"device", "security"}:
        category = "device"
    if category == "security" and not can_view_security_audit(request.user):
        return hidden_forbidden_response()

    keyword = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if category == "security":
        qs = SecurityAuditLog.objects.all()
        selected_result = request.GET.get("result", "").strip()
        selected_action = request.GET.get("action", "").strip()
        if selected_result in dict(SecurityAuditLog.RESULT_CHOICES):
            qs = qs.filter(result=selected_result)
        if selected_action:
            qs = qs.filter(action=selected_action)
        if keyword:
            qs = qs.filter(Q(username__icontains=keyword) | Q(display_name__icontains=keyword) | Q(role__icontains=keyword) | Q(client_ip__icontains=keyword) | Q(detail__icontains=keyword))
        if date_from:
            qs = qs.filter(occurred_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(occurred_at__date__lte=date_to)
        summary = {
            "total": SecurityAuditLog.objects.count(),
            "success": SecurityAuditLog.objects.filter(result="success").count(),
            "failed": SecurityAuditLog.objects.filter(result="failed").count(),
            "login_failed": SecurityAuditLog.objects.filter(action="LOGIN_FAILED").count(),
        }
        paginator = Paginator(qs.order_by("-occurred_at", "-id"), 50)
        page_obj = paginator.get_page(request.GET.get("page"))
        for item in page_obj.object_list:
            item.result_label_ui = AUDIT_RESULT_LABELS.get(item.result, item.result)
            item.action_label_ui = AUDIT_ACTION_LABELS.get(item.action, item.action)
        context = {
            "category": category,
            "page_obj": page_obj,
            "summary": summary,
            "security_result_choices": SecurityAuditLog.RESULT_CHOICES,
            "security_action_choices": sorted({(row.action, AUDIT_ACTION_LABELS.get(row.action, row.action)) for row in SecurityAuditLog.objects.only("action")}),
            "selected_result": selected_result,
            "selected_action": selected_action,
            "keyword": keyword,
            "date_from": date_from,
            "date_to": date_to,
            "can_view_security_audit": True,
        }
    else:
        qs = DeviceFaultLog.objects.all()
        selected_status = request.GET.get("status", "").strip()
        selected_severity = request.GET.get("severity", "").strip()
        selected_device_type = request.GET.get("device_type", "").strip()
        if selected_status in dict(DeviceFaultLog.STATUS_CHOICES): qs = qs.filter(status=selected_status)
        if selected_severity in dict(DeviceFaultLog.SEVERITY_CHOICES): qs = qs.filter(severity=selected_severity)
        if selected_device_type in dict(DeviceFaultLog.DEVICE_TYPE_CHOICES): qs = qs.filter(device_type=selected_device_type)
        if keyword:
            qs = qs.filter(Q(device_code__icontains=keyword) | Q(device_name__icontains=keyword) | Q(area__icontains=keyword) | Q(fault_code__icontains=keyword) | Q(fault_description__icontains=keyword))
        if date_from: qs = qs.filter(occurred_at__date__gte=date_from)
        if date_to: qs = qs.filter(occurred_at__date__lte=date_to)
        summary_base = DeviceFaultLog.objects.all()
        summary = {
            "total": summary_base.count(),
            "active": summary_base.filter(status=DeviceFaultLog.STATUS_ACTIVE).count(),
            "recovered": summary_base.filter(status=DeviceFaultLog.STATUS_RECOVERED).count(),
            "critical_active": summary_base.filter(status=DeviceFaultLog.STATUS_ACTIVE, severity=DeviceFaultLog.SEVERITY_CRITICAL).count(),
        }
        paginator = Paginator(qs.order_by("-occurred_at", "-id"), 50)
        page_obj = paginator.get_page(request.GET.get("page"))
        for item in page_obj.object_list:
            item.device_type_label_ui = DEVICE_LABELS.get(item.device_type, item.device_type)
            item.severity_label_ui = SEVERITY_LABELS.get(item.severity, item.severity)
            item.status_label_ui = STATUS_LABELS.get(item.status, item.status)
        context = {
            "category": category,
            "page_obj": page_obj,
            "summary": summary,
            "device_type_choices": DeviceFaultLog.DEVICE_TYPE_CHOICES,
            "severity_choices": DeviceFaultLog.SEVERITY_CHOICES,
            "status_choices": DeviceFaultLog.STATUS_CHOICES,
            "selected_status": selected_status,
            "selected_severity": selected_severity,
            "selected_device_type": selected_device_type,
            "keyword": keyword,
            "date_from": date_from,
            "date_to": date_to,
            "can_view_security_audit": can_view_security_audit(request.user),
        }

    query = request.GET.copy(); query.pop("page", None)
    context["query_without_page"] = query.urlencode()
    return render(request, "dashboard/system_log_list.html", context)
