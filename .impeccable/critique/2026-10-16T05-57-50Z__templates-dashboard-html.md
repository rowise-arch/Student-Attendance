---
target: Today dashboard and kiosk
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:D:\\Student Attendance\\templates\\dashboard.html"
target_fingerprint: "sha256:ef8b5a49e2caa9023a17b1f3ac0e0d8c04e74d8cfa13bb99b29312a962105938"
target_path: "D:\\Student Attendance\\templates\\dashboard.html"
timestamp: 2026-10-16T05-57-50Z
slug: templates-dashboard-html
---
# Critique: Today dashboard + kiosk
Method: dual-agent. Score 27/40 (Good). P1: Today lacks primary focus (missing list buried); P1: kiosk small text + exposes other students' status/raw UID + 3.9:1 contrast on fullscreen button; P2: silent refresh failures; P2: generic visual identity; P3: redundancy, hardcoded chart colours, unconfirmed Mark dropdown.
Heuristics: 1:3 2:3 3:3 4:3 5:3 6:3 7:2 8:2 9:3 10:2
Detector: 2 low-contrast hits in kiosk.html (#6a7489 on #0b1324, 3.9:1), likely .fs button opacity .6.
