# Sales Copilot — React Native (Expo) Companion App

This directory contains the **React Native (Expo)** mobile companion app for Sales Copilot, connecting directly to the FastAPI backend (`/`).

## In-Mobile Features

1. **Floating Live Hint HUD & Native Overlay Bridge (`src/screens/LiveCallScreen.js`, `src/services/nativeCallBridge.js`)**
   - Streams real-time playbook-grounded hints over `/ws/live` (`['copilot-v1', 'auth.<token>']`).
   - Bridges to Android `SYSTEM_ALERT_WINDOW` ("Draw over other apps") and iOS `ActivityKit` Live Activities while keeping a prominent floating HUD banner inside the app.
2. **Background Field-Meeting Audio & Screen Wake-Lock (`app.json`, `src/services/nativeCallBridge.js`)**
   - Declares iOS `UIBackgroundModes: ["audio", "voip"]` and Android `FOREGROUND_SERVICE_MICROPHONE` so microphone capture continues even when the phone screen locks during an in-person sales meeting.
3. **Truecaller-Style Post-Call Logger & Outcome Card (`src/screens/PostCallLoggerScreen.js`, `POST /api/calls/log-mobile`)**
   - Subscribes to call-end events (`SalesCopilotCallEnded`) or lets reps log completed SIM calls / in-person field visits with consent.
   - Runs the full backend AI/rules post-call pipeline (coaching score `/100`, disposition classification, coaching notes, follow-up draft) and distributes to **HubSpot CRM, WhatsApp, and signed Webhook nodes**, plus **1-tap Share to WhatsApp** (`whatsapp://send`).
4. **Mobile Call History, Coaching Analytics, & Team Settings (`src/screens/HistoryScreen.js`, `src/screens/SettingsScreen.js`)**
   - Displays org-level coaching metrics (`/api/calls/analytics`), outcome filters, full call timelines, WhatsApp recap preferences, and team members.

## Running

```bash
cd mobile
npm install
npx expo start
```

Point the **Backend Server URL** in the mobile login/settings screen to your computer's LAN IP (e.g., `http://192.168.1.10:8000`) or public HTTPS tunnel, and add that origin to `ALLOWED_ORIGINS` in the root `.env`.
