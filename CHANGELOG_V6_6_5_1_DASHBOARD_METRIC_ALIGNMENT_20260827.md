# KRTC Notification Host V6.6.5.1 - Dashboard Metric Alignment

Date: 2026-08-27
Scope: Development machine UI micro-adjustment

## Change
- Align the title baseline of the Dashboard blue information-bar cards for:
  - Station cameras
  - Station broadcast speakers
- These two simple metric cards now begin at the same top content baseline as the other information blocks instead of being vertically centered lower due to their shorter content height.
- No data logic, API, database model, or migration changes.

## Expected UI
- The titles for the station camera and station broadcast speaker cards are visually level with the neighboring information-card headings.
- Existing speaker abnormal red text and inference-host abnormal styling remain unchanged.
