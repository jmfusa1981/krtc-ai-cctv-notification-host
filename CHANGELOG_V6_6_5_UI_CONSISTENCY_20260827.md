# KRTC Notification Host V6.6.5 UI Consistency

Date: 2026-08-27
Scope: Development host only
Database migration: None

## Changes

1. Broadcast settings action links
   - Remove text underlines from "前往站區廣播系統", "新增音檔", and related primary action links.

2. Broadcast audio management form
   - Localize application-owned field labels and audio type choices to Traditional Chinese.
   - Keep professional terms such as MP3/WAV/OGG where appropriate.
   - Replace the browser-visible file selector surface with application labels "選擇檔案" / "尚未選擇檔案".
   - Align the cancel button typography and height with the save button while retaining outline styling.

3. Dashboard inference-host status
   - Keep the title "站區推論主機狀態" white even when one or more inference hosts are abnormal.
   - Only the status value and abnormal host details use red alert text.
   - Blue information strip background remains unchanged.

4. Camera / broadcast-speaker management consistency
   - "新增攝影機" and "新增廣播喇叭" now both open a full management page.
   - Speaker edit also uses the same management-page pattern instead of a modal dialog.
   - Existing speaker save API is retained for backward compatibility but is no longer used by this settings UI.
   - Speaker deployment-state choices are localized on the full-page form.

5. Camera / audio cancel buttons
   - Remove underline from cancel link.
   - Match save-button font family, size, weight, height, and vertical alignment.

## Validation

The installer runs:
- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- V6.6.5 UI consistency tests
- retained V6.6.4 localization/UI tests

Any validation failure triggers automatic rollback.
