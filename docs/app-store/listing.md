# App Store listing draft - Carpe Diem Boats

Everything to paste into App Store Connect, in the order it asks. Fill in the
`<...>` items. Field limits are Apple's; lengths are checked.

## App information

| Field | Value |
|---|---|
| Name (max 30) | `Carpe Diem Boats` (16) |
| Subtitle (max 30) | `Your boat's data, anywhere` (26) |
| Bundle ID | `com.vanwijlen.carpediem` |
| Primary category | Utilities |
| Secondary category | Lifestyle (or Navigation - see the note below) |
| Price | Free |
| Availability | All countries and regions (or restrict, your choice) |
| Privacy Policy URL | `<where docs/privacy.html is hosted - see below>` |
| Support URL | `<a page or a mailto: link with your contact address>` |
| Copyright | `2026 <your name>` |

**Category note:** Navigation makes reviewers look harder at accuracy and safety claims. The app is
informational (it shows boat data; it doesn't plot routes), so Utilities is the safer primary category.

## Version information

**Promotional text (max 170, editable without a new review)** - 124 characters:

```
Keep an eye on your boat from anywhere: position, power, weather, temperatures, nearby vessels and cameras in one dashboard.
```

**Keywords (max 100, comma-separated, no spaces after commas)** - 92 characters:

```
boat,yacht,AIS,marine,battery,Victron,Raspberry Pi,dashboard,wind,bridge,lock,monitor,vessel
```

**Description (max 4000):**

```
Carpe Diem Boats is the companion app for boats running the CarpeDiem system: a Raspberry Pi on board collects data from your boat's instruments and sends it to a data store that you host yourself. This app shows that data live on your iPhone, wherever you are.

IMPORTANT: to see your own boat, the CarpeDiem system has to be set up on it first. To look around without it, use Demo mode - it is on the first time you open the app and shows built-in sample data.

WHAT YOU CAN SEE

• Main - compass with speed and heading, true and relative wind, the next bridge or lock ahead, battery, house and starter voltage, alternator and solar power, and a radar of nearby vessels from AIS.

• AIS - the vessels around you with name, speed, heading, bearing and distance. Moored, underway, fast and overtaking traffic is colour-coded, plus the status of your AIS receivers.

• Weather - outside temperature, wind (as the sensor reports it and relative to your course), average wind, barometer, humidity, light, rain and UV index.

• Power - battery, house, starter, alternator, solar, shore power, AC loads and DC current, with a power-flow overview.

• Temps - temperature readings from every part of the boat, grouped by cabin and technical areas.

• Cam - the latest snapshots from your cameras with their battery and connection status. When you are on the boat's WiFi you can also open a camera's live view.

STATUS AT A GLANCE

A row of status lamps shows the health of the boat's systems. The link lamp tells you how fresh the data is: green when the boat is reporting, orange when your data store answers but the boat has stopped sending, red when the data store can't be reached.

PRIVATE BY DESIGN

No account, no ads, no analytics. Your data travels from your boat to your own server to your phone, and nowhere else. Optional Face ID lock, and your access keys are kept in the iOS Keychain.

NOT FOR NAVIGATION

Carpe Diem Boats is informational only. Never rely on it for navigation, collision avoidance or any safety decision.
```

**What's New (for the first release):**

```
First public release.
```

**Screenshots:** capture on the largest iPhone size App Store Connect asks for (it lists the current
required sizes), in Demo mode so the screens are full: Main, AIS radar, Power, Weather, Temps, Cam.
Don't show a real position, keys or camera images of people.

## App Privacy ("nutrition label")

Answer **Data Not Collected**. Reasoning, if you need it: the app has no developer-operated server, no
analytics or ads, and no third-party SDKs that collect data. The data it displays is loaded from a server
the user runs and is never sent to the developer.

Also answer:

| Question | Answer |
|---|---|
| Does the app use encryption? | Yes - only standard HTTPS. This is exempt; `ITSAppUsesNonExemptEncryption` is already `false` in `app.json`. |
| Tracking? | No |
| Age rating questionnaire | All "None" / "No" - expect **4+**. Unrestricted web access: No. |
| Uses the Advertising Identifier (IDFA)? | No |

## App Review notes

Paste into "Notes" under App Review Information. Sign-in required: **No** (leave the demo account fields empty).

```
Carpe Diem Boats is a companion app for a private boat-monitoring system (a Raspberry Pi on the developer's boat pushes its data to a server the owner hosts). Real data therefore needs that hardware and server, which we can't make available for review.

To review the app fully, no account or login is needed:

1. On first launch the app is in DEMO MODE. It shows built-in sample data (position, wind, battery, weather, temperatures, nearby AIS vessels) with a gentle live movement, on every tab: Main, AIS, Weather, Power, Temps, Cam.
2. Tap the gear icon (top right) to see the Settings sheet: the data store address and read key fields that live mode uses. Live mode is only used by owners of the system. Leave Demo mode on for review.
3. The Face ID lock and the live camera view are only active in live mode, so they don't appear in Demo mode.

Privacy: the app collects no data, has no accounts, and connects only to addresses the user enters. A local network permission prompt appears only if a user enters the address of their boat's Raspberry Pi, for the optional live camera view.

The app is informational only and states that it must not be used for navigation.
```

## Before you submit - checklist

- [ ] Privacy policy is hosted at a public URL and `YOUR-EMAIL-ADDRESS` / `YOUR NAME` are filled in
- [ ] Support URL works
- [ ] Screenshots taken in Demo mode
- [ ] Build number is new (EAS auto-increments) and the version matches the git tag (`npm run release:ios`)
- [ ] Release option: choose "Manually release" so you control when it goes live after approval
