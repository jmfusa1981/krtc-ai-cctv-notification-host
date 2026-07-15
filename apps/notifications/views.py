import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import BroadcastLog
from .services import process_pending_broadcast_logs


@csrf_exempt
@require_POST
def process_pending_broadcast_logs_api(request):
    """
    Step 20-1 API：
    手動處理 pending BroadcastLog。

    注意：
    目前是 PoC / local development 測試用 API。
    為了方便 PowerShell Invoke-RestMethod 測試，暫時使用 csrf_exempt。
    正式版應改回登入驗證與權限控管。

    Endpoint:
    POST /api/notifications/broadcast/process-pending/

    Body optional:
    {
        "limit": 10
    }
    """

    limit = 10

    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
            limit = int(payload.get("limit", 10))
        except Exception:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid JSON body.",
                },
                status=400,
            )

    if limit <= 0:
        return JsonResponse(
            {
                "success": False,
                "message": "limit must be greater than 0.",
            },
            status=400,
        )

    result = process_pending_broadcast_logs(limit=limit)

    return JsonResponse(
        {
            "success": True,
            "message": "Pending BroadcastLog processed.",
            "pending_count": BroadcastLog.objects.filter(
                status=BroadcastLog.STATUS_PENDING
            ).count(),
            **result,
        }
    )
