# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **Primary: admin/registrar staff** using the dashboard on desktop browsers in the school office: managing students, sections, imports, daily logs, monthly reports, and settings.
- **Secondary: students** at the school entrance, who tap an RFID card and read the kiosk screen on an entrance TV/monitor from a distance.
- Teachers/advisers also view Today, daily log, and reports (device mix not confirmed).

## Product Purpose
Corcuera National High School logs entrance taps four times a day (morning in/out, afternoon in/out). It marks students Late against configured start times and gives staff a live Today view, a daily log, and per-section monthly reports. Success: accurate attendance with little manual work, and a kiosk that gives each student instant, unambiguous feedback.

## Positioning
A self-hosted, local-network attendance system tied to physical RFID readers (Arduino + RC522, ACS ACR122U, or keyboard-type readers), with no cloud dependency.

## Operating Context
- Flask + SQLite app run on a school PC (`run.bat`); readers connect via USB serial or PC/SC.
- The kiosk is a separate full-screen page (`/kiosk`) on an entrance TV/monitor.
- Staff review and correct attendance through the dashboard, and export CSVs.

## Capabilities and Constraints
- **Must work fully offline:** local network only, no internet, CDNs, or hosted fonts.
- **Low-end hardware:** older school PCs and browsers; keep pages and scripts light.
- **Student privacy matters:** photos and names are shown on a public kiosk, so what appears there needs care.
- Terminology: Present, Late, Absent, Excused, Half-day; sections; "taps".
- Device mix for staff beyond desktop is undecided.

## Brand Commitments
- Keep the school name ("Corcuera National High School") and uploaded school logo central to the identity.

## Evidence on Hand
- Real code, templates and a demo seed (`seed_demo.py`). No screenshots, testimonials or external metrics; do not fabricate any.

## Product Principles
1. Unambiguous status first: a tap or an absence is understood at a glance, never by colour alone.
2. Works anywhere in a school: offline, light, resilient to hardware flakiness.
3. The kiosk serves a crowd at distance; the dashboard serves a careful operator at a desk.
4. Protect students: expose only what the context needs.

## Accessibility & Inclusion
Aim for WCAG AA (the existing code already checks contrast, focus and reduced-motion). Large, legible type on the kiosk.
