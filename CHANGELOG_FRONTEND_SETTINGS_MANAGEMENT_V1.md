# KRTC Notification Host V5 - Frontend Settings Management V1

## Scope

Daily operational configuration is now available under `/dashboard/settings/` without using Django Admin.

## Added

- Frontend create/edit forms for inference hosts.
- Frontend create/edit forms for cameras.
- Frontend create/edit forms for AI models.
- Frontend create/edit forms for inference camera mappings.
- Frontend create/edit forms for audio files.
- Frontend create/edit forms for broadcast rules.
- Existing Speaker modal is now controlled by the same role permission.
- Maintainer and Administrator roles can manage operational settings.
- Operator remains read-only.
- Django Admin link is visible only to superusers and is labelled Developer Backend.
- Settings tabs can be restored through `?tab=` after saving.

## Safety

- No delete action is exposed in the frontend.
- Django Admin remains available for superuser-only repair and development tasks.
