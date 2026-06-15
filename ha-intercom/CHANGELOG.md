# Changelog — Intercom

## 1.0.4
- Incoming call notification now uses full-screen intent on Android: shows full-screen on locked device (like a phone call) and as a floating heads-up banner when the device is in use

## 1.0.3
- Fix: notification not dismissed after reject — Reject button now calls a server-side GET endpoint (`/api/call/reject-notify/<id>`) that rejects the call and clears the notification without requiring JS execution in a WebView

## 1.0.2
- Fix: `external_url` field in HA config can be null — use `or ''` instead of default to avoid crash on startup
- Fix: removed `/config/config_entries` call that returned 404 via Supervisor proxy; device auto-detection falls back to manual selection in the UI

## 1.0.1
- Fix: notification URL now uses HA's `external_url` combined with the addon ingress path, so the call screen opens correctly when the callee's app is closed or on a different network (mobile data, external WiFi)

## 1.0.0
- Initial release
- Bidirectional WebRTC audio between HA mobile_app devices (P2P, no relay server)
- Auto-discovers all registered mobile_app devices on startup — no manual configuration needed
- Detects the current user's device automatically via HA ingress headers
- Sidebar panel with device list and one-tap Call button per device; hides own device to prevent self-calls
- Push notification to callee with Answer and Reject action buttons
- Answer opens the call screen and connects automatically; Reject dismisses immediately
- Notification cleared on both devices after answer or reject
- Active calls section in the panel with hang-up button
- Mute button on the call screen
- Call screen closes automatically 2 seconds after the call ends
