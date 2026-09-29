import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET


@require_GET
@login_required
def protected_media(request, path):
    """
    Serve KRTC operational media only to authenticated users.

    Covers:
    - event snapshots
    - event recordings
    - uploaded / recorded audio

    Prevents path traversal outside MEDIA_ROOT.
    """

    media_root = Path(settings.MEDIA_ROOT).resolve()
    requested_file = (media_root / path).resolve()

    try:
        requested_file.relative_to(media_root)
    except ValueError:
        raise Http404("Invalid media path.")

    if not requested_file.exists():
        raise Http404("Media file not found.")

    if not requested_file.is_file():
        raise Http404("Media resource is not a file.")

    content_type, _ = mimetypes.guess_type(str(requested_file))

    response = FileResponse(
        open(requested_file, "rb"),
        content_type=content_type or "application/octet-stream",
    )

    response["X-Content-Type-Options"] = "nosniff"

    return response
