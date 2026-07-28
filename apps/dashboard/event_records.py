from __future__ import annotations

import csv
from datetime import datetime
from io import BytesIO
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.ai_bridge.models import AIModel
from apps.cameras.models import Camera
from apps.events.models import Event


EVENT_EXPORT_HEADERS = [
    "事件編號",
    "發生時間",
    "事件類型",
    "攝影機編號",
    "區域",
    "處理狀態",
    "AI 模型",
    "來源推論主機",
    "事件說明",
    "快照",
]


def _parse_local_datetime(value: str):
    if not value:
        return None

    parsed = parse_datetime(value)
    if parsed is None:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M")
        except ValueError:
            return None

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _event_queryset(request: HttpRequest) -> QuerySet[Event]:
    queryset = Event.objects.select_related("camera", "ai_model").order_by(
        "-detected_at", "-id"
    )

    start_at = _parse_local_datetime(request.GET.get("start_at", "").strip())
    end_at = _parse_local_datetime(request.GET.get("end_at", "").strip())
    event_type = request.GET.get("event_type", "").strip()
    camera_id = request.GET.get("camera", "").strip()
    area = request.GET.get("area", "").strip()
    ai_model_id = request.GET.get("ai_model", "").strip()
    source_host = request.GET.get("source_host", "").strip()
    keyword = request.GET.get("q", "").strip()

    if start_at:
        queryset = queryset.filter(detected_at__gte=start_at)
    if end_at:
        queryset = queryset.filter(detected_at__lte=end_at)
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    if camera_id:
        queryset = queryset.filter(camera_id=camera_id)
    if area:
        queryset = queryset.filter(camera__area=area)
    if ai_model_id:
        queryset = queryset.filter(ai_model_id=ai_model_id)
    if source_host:
        queryset = queryset.filter(source_host=source_host)
    if keyword:
        keyword_filter = (
            Q(description__icontains=keyword)
            | Q(camera__camera_code__icontains=keyword)
            | Q(camera__area__icontains=keyword)
            | Q(source_host__icontains=keyword)
        )
        if keyword.isdigit():
            keyword_filter |= Q(id=int(keyword))
        queryset = queryset.filter(keyword_filter)

    return queryset


def _snapshot_url(request: HttpRequest, event: Event) -> str:
    snapshot = getattr(event, "snapshot", None)
    if snapshot:
        try:
            return request.build_absolute_uri(snapshot.url)
        except (ValueError, AttributeError):
            pass
    return getattr(event, "snapshot_url", "") or ""


def _event_row(request: HttpRequest, event: Event) -> list[str]:
    detected_at = timezone.localtime(event.detected_at).strftime("%Y-%m-%d %H:%M:%S")
    ai_model = str(event.ai_model) if event.ai_model else ""
    return [
        str(event.id),
        detected_at,
        event.get_event_type_display(),
        event.camera.camera_code,
        event.camera.area or "",
        event.get_status_display(),
        ai_model,
        event.source_host or "",
        event.description or "",
        _snapshot_url(request, event),
    ]


def _filter_context(request: HttpRequest) -> dict:
    return {
        "start_at": request.GET.get("start_at", ""),
        "end_at": request.GET.get("end_at", ""),
        "selected_event_type": request.GET.get("event_type", ""),
        "selected_camera": request.GET.get("camera", ""),
        "selected_area": request.GET.get("area", ""),
        "selected_ai_model": request.GET.get("ai_model", ""),
        "selected_source_host": request.GET.get("source_host", ""),
        "keyword": request.GET.get("q", ""),
    }


def _query_without_page(request: HttpRequest) -> str:
    params = request.GET.copy()
    params.pop("page", None)
    return urlencode(params, doseq=True)


@login_required
def event_record_list(request: HttpRequest) -> HttpResponse:
    queryset = _event_queryset(request)
    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    for event in page_obj.object_list:
        event.record_snapshot_url = _snapshot_url(request, event)

    areas = (
        Camera.objects.exclude(area="")
        .values_list("area", flat=True)
        .distinct()
        .order_by("area")
    )
    source_hosts = (
        Event.objects.exclude(source_host__isnull=True)
        .exclude(source_host="")
        .values_list("source_host", flat=True)
        .distinct()
        .order_by("source_host")
    )

    context = {
        "page_obj": page_obj,
        "record_count": paginator.count,
        "event_type_choices": Event.EVENT_TYPE_CHOICES,
        "cameras": Camera.objects.all().order_by("camera_code"),
        "areas": areas,
        "ai_models": AIModel.objects.all().order_by("name", "model_code"),
        "source_hosts": source_hosts,
        "query_without_page": _query_without_page(request),
        **_filter_context(request),
    }
    return render(request, "dashboard/event_record_list.html", context)


@login_required
def export_event_records_csv(request: HttpRequest) -> HttpResponse:
    queryset = _event_queryset(request)
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="event_records_{timestamp}.csv"'
    )
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(EVENT_EXPORT_HEADERS)
    for event in queryset.iterator(chunk_size=500):
        writer.writerow(_event_row(request, event))
    return response


@login_required
def export_event_records_excel(request: HttpRequest) -> HttpResponse:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        return HttpResponse(
            "缺少 openpyxl。請執行：python -m pip install openpyxl==3.1.5",
            status=500,
            content_type="text/plain; charset=utf-8",
        )

    queryset = _event_queryset(request)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "事件紀錄"
    worksheet.freeze_panes = "A2"
    worksheet.append(EVENT_EXPORT_HEADERS)

    for cell in worksheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for event in queryset.iterator(chunk_size=500):
        worksheet.append(_event_row(request, event))

    widths = [12, 20, 22, 16, 18, 14, 22, 28, 42, 48]
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width

    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    response = HttpResponse(
        output.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = (
        f'attachment; filename="event_records_{timestamp}.xlsx"'
    )
    return response
