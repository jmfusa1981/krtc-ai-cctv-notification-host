from django.http import HttpResponse


def hidden_forbidden(request, exception=None):
    """Return the same minimal response for hidden/unknown protected resources."""
    return HttpResponse(
        "404 forbidden",
        status=404,
        content_type="text/plain; charset=utf-8",
    )
