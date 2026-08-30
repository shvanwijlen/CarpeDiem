/*
  AIS Nearby Vessels
  ------------------
  Connects over WiFi to an em-trak AIS unit's network NMEA server (GPS
  sentences + !AIVDM AIS target sentences on the same TCP stream), decodes
  the 6-bit armoured AIS payload for position reports, and prints nearby
  vessels sorted by distance from your own GPS fix.

  Handles:
    - Message types 1/2/3 (Class A position report)
    - Message types 18/19 (Class B position report)
    - Message type 24 part A (vessel name, single-fragment -> attached to MMSI)
    - Message type 5 (vessel name only, reassembled from its 2 fragments)
    - Own position from $..RMC or $..GGA
    - Vessel name lookup via AISstream.io (https://aisstream.io), a free
      WebSocket feed of decoded global AIS data. Rather than a per-MMSI
      pull/lookup, this subscribes to a bounding box around your own
      position filtered to ShipStaticData messages, and passively receives
      names as vessels broadcast them - anywhere in that region, not just
      ones your em-trak can hear locally. No monthly quota like VesselAPI.
    - Own-ship transmission counting via !AIVDO echoes, split by message
      type (18/19). This is a live tally since the ESP32 booted, not a
      lifetime device statistic - em-trak doesn't appear to expose that over
      NMEA/TCP; it's only visible in the Connect-AIS app / proAIS2 diagnostics.
    - $AIALR health/status alarms (Tx malfunction, VSWR, GPS issues, low
      forward power, etc.) printed to serial whenever one goes active.

  Does NOT handle (kept out to save RAM/flash on small boards):
    - Type 24 part B and the rest of type 5 (callsign/IMO/ship type/
      dimensions). Only the name field is decoded from either message.
    - Fragment counts other than 1 or 2 (not used by any message type here).
    - NMEA checksum verification (add if you see garbled decodes).

  Requires the "ArduinoJson" library (Benoit Blanchon, v7) and
  "ArduinoWebsockets" library (Gil Maimon) via Library Manager.

  Board: ESP32-S3. Joins your WiFi network, then opens a TCP connection to
  the em-trak's NMEA server (192.168.1.200:5000) and reads the stream from
  there. Both the ESP32 and the em-trak need to be on the same network for
  this to work (either both on your home WiFi, or on the em-trak's own
  access point if it runs one).
*/

#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
#include <ArduinoWebsockets.h>  // Library Manager: "ArduinoWebsockets" by Gil Maimon
#include <ArduinoJson.h>        // Library Manager: "ArduinoJson" by Benoit Blanchon (v7)
#include "arduino_secrets.h"

using namespace websockets;

// ---------- Configuration ----------
// Your WiFi credentials (define SECRET_SSID / SECRET_PASSWORD in arduino_secrets.h,
// kept out of this file so it's safe to share/commit without leaking your password)
const char* ssid     = SECRET_SSID;
const char* password = SECRET_PASSWORD;

const char* AIS_HOST      = "192.168.2.1";          // em-trak NMEA server address
const uint16_t AIS_PORT   = 5000;

// AISstream.io (define SECRET_AISSTREAM_API_KEY in arduino_secrets.h - free,
// no monthly quota). We subscribe to a bounding box around our own position,
// filtered to ShipStaticData messages only (that's the message type that
// carries vessel names - PositionReport traffic is left to the local em-trak
// feed, so we don't duplicate that over the internet too).
const char* AISSTREAM_API_KEY = SECRET_AISSTREAM_API_KEY;
const float AISSTREAM_BBOX_MARGIN_DEG = 1.0;       // roughly ~110km lat / less in lon, generous margin
const float AISSTREAM_RESUB_THRESHOLD_DEG = 0.5;   // resubscribe once we've drifted this far from the last box

#define DEBUG_BAUD      115200      // native USB CDC, Serial.begin() as usual

#define MAX_VESSELS     50          // ESP32-S3 has plenty of RAM, no need to be stingy
#define STALE_TIMEOUT_MS  600000UL  // drop a vessel if not heard from in 10 min
#define PRINT_INTERVAL_MS 5000UL    // how often to print the sorted list
#define RECONNECT_INTERVAL_MS 5000UL // how often to retry a dropped connection

#define LINE_BUF_LEN    100         // AIS sentences max ~82 chars; leave margin
#define DEBUG_RAW_NMEA  0           // set to 1 to echo every received line to Serial for debugging

WiFiClient aisClient;
unsigned long lastReconnectAttempt = 0;
unsigned long lastByteTime = 0;

WebsocketsClient aisStreamClient;
bool aisStreamConnected = false;
float aisStreamSubLat = 0, aisStreamSubLon = 0;
unsigned long lastAisStreamReconnectAttempt = 0;

// ---------- Multi-fragment reassembly (type 5 static/voyage data is always
// sent as exactly 2 fragments; we buffer the first half while waiting for
// the second so we can decode the vessel name out of it) ----------
char pendingPayload[100];
int pendingSeq = -1;
char pendingChannel = 0;

// ---------- Vessel table ----------
struct Vessel {
  uint32_t mmsi;
  float lat;
  float lon;
  float sog;        // speed over ground, knots
  float cog;         // course over ground, degrees
  unsigned long lastSeen;
  bool valid;         // slot in use
  bool hasPosition;   // we've received at least one position report
  bool hasName;
  char name[21];      // vessel name, max 20 chars + null terminator
};

Vessel vessels[MAX_VESSELS];

// ---------- Own position ----------
float ownLat = 0, ownLon = 0;
bool haveFix = false;
float ownCog = 0;
bool haveCog = false; // GPS course-over-ground is only meaningful while moving; blank at low speed

// ---------- Serial line buffer ----------
char lineBuf[LINE_BUF_LEN];
uint8_t lineLen = 0;

unsigned long lastPrint = 0;

// Own-ship transmission counters (from !AIVDO echoes) and health monitoring
unsigned long ownReportsType18 = 0;
unsigned long ownReportsType19 = 0;
unsigned long ownReportsOther = 0;

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print(F("Connecting to WiFi \""));
  Serial.print(ssid);
  Serial.println(F("\"..."));
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(300);
    Serial.print(F("."));
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("WiFi connected, IP: "));
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(F("WiFi connect timed out, will keep retrying"));
  }
}

void connectAIS() {
  if (aisClient.connected()) return;
  Serial.print(F("Connecting to em-trak at "));
  Serial.print(AIS_HOST); Serial.print(F(":")); Serial.println(AIS_PORT);
  if (aisClient.connect(AIS_HOST, AIS_PORT)) {
    Serial.println(F("Connected to em-trak NMEA server"));
  } else {
    Serial.println(F("Connection to em-trak failed, will retry"));
  }
}

// Handles incoming AISstream.io messages. We only subscribed to
// ShipStaticData, so every message that arrives here should carry a name -
// extract MMSI + Name and feed it into the same setVesselName() used by the
// local em-trak type 5/24 decode, so both sources merge into one table.
void onAisStreamMessage(WebsocketsMessage message) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, message.data());
  if (err) return;

  const char* msgType = doc["MessageType"];
  if (msgType == nullptr || strcmp(msgType, "ShipStaticData") != 0) return;

  uint32_t mmsi = doc["MetaData"]["MMSI"] | 0UL;
  const char* name = doc["Message"]["ShipStaticData"]["Name"];
  if (mmsi == 0 || name == nullptr || strlen(name) == 0) return;

  // AISstream names can carry the same trailing-space padding as raw AIS
  // text fields - trim it before storing.
  char trimmed[21];
  strncpy(trimmed, name, sizeof(trimmed) - 1);
  trimmed[sizeof(trimmed) - 1] = '\0';
  for (int i = strlen(trimmed) - 1; i >= 0 && trimmed[i] == ' '; i--) trimmed[i] = '\0';

  setVesselName(mmsi, trimmed);
}

// (Re)send the subscription message, centered on our current position. Must
// be sent within 3 seconds of connecting or AISstream.io closes the socket.
void sendAisStreamSubscription() {
  char sub[256];
  float minLat = ownLat - AISSTREAM_BBOX_MARGIN_DEG;
  float maxLat = ownLat + AISSTREAM_BBOX_MARGIN_DEG;
  float minLon = ownLon - AISSTREAM_BBOX_MARGIN_DEG;
  float maxLon = ownLon + AISSTREAM_BBOX_MARGIN_DEG;
  snprintf(sub, sizeof(sub),
    "{\"APIKey\":\"%s\",\"BoundingBoxes\":[[[%.4f,%.4f],[%.4f,%.4f]]],\"FilterMessageTypes\":[\"ShipStaticData\"]}",
    AISSTREAM_API_KEY, minLat, minLon, maxLat, maxLon);
  aisStreamClient.send(sub);
  aisStreamSubLat = ownLat;
  aisStreamSubLon = ownLon;
}

// Diagnostic logging for the AISstream connection - connect() alone only
// gives a bool, this surfaces the actual event (open/close/ping/pong) so a
// failed connection isn't a total black box.
void onAisStreamEvent(WebsocketsEvent event, String data) {
  if (event == WebsocketsEvent::ConnectionOpened) {
    Serial.println(F("AISstream.io: connection opened"));
  } else if (event == WebsocketsEvent::ConnectionClosed) {
    Serial.print(F("AISstream.io: connection closed, data: "));
    Serial.println(data);
  } else if (event == WebsocketsEvent::GotPing) {
    Serial.println(F("AISstream.io: got ping"));
  } else if (event == WebsocketsEvent::GotPong) {
    Serial.println(F("AISstream.io: got pong"));
  }
}

// Only called once we have a GPS fix, since the subscription needs a real
// bounding box and has to go out within 3 seconds of connecting.
void connectAisStream() {
  aisStreamClient.onMessage(onAisStreamMessage);
  aisStreamClient.onEvent(onAisStreamEvent);
  aisStreamClient.setInsecure(); // skip TLS cert validation - same trade-off noted elsewhere in this sketch
  Serial.println(F("Connecting to AISstream.io..."));
  bool ok = aisStreamClient.connect("wss://stream.aisstream.io/v0/stream");
  if (ok) {
    sendAisStreamSubscription();
    aisStreamConnected = true;
    Serial.println(F("Connected to AISstream.io and subscribed"));
  } else {
    Serial.println(F("AISstream.io connection failed, will retry"));
  }
}

void setup() {
  Serial.begin(DEBUG_BAUD);
  delay(1000); // give the native USB CDC serial time to enumerate before we print
  for (uint8_t i = 0; i < MAX_VESSELS; i++) vessels[i].valid = false;
  Serial.println(F("AIS nearby-vessel tracker starting..."));
  connectWiFi();

  // ESP32's TLS stack can fail the WSS handshake to AISstream.io if the
  // clock is still at its power-on default (1970) - even with setInsecure(),
  // it still needs a sane time to work with. Sync via NTP before connecting.
  Serial.print(F("Syncing time via NTP"));
  configTime(0, 0, "pool.ntp.org"); // UTC, no DST offset needed
  time_t now = time(nullptr);
  unsigned long ntpStart = millis();
  while (now < 8 * 3600 * 2 && millis() - ntpStart < 10000) { // wait for a plausible time or 10s timeout
    delay(300);
    Serial.print(F("."));
    now = time(nullptr);
  }
  Serial.println();
  if (now < 8 * 3600 * 2) {
    Serial.println(F("NTP sync timed out - AISstream.io connection may fail until time is set"));
  } else {
    Serial.println(F("Time synced"));
  }

  connectAIS();
  lastPrint = millis(); // don't let the WiFi/TCP connect time count against the first print interval
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastReconnectAttempt > RECONNECT_INTERVAL_MS) {
      lastReconnectAttempt = millis();
      connectWiFi();
    }
    return;
  }

  if (!aisClient.connected()) {
    if (millis() - lastReconnectAttempt > RECONNECT_INTERVAL_MS) {
      lastReconnectAttempt = millis();
      connectAIS();
    }
    return;
  }

  while (aisClient.available()) {
    char c = aisClient.read();
    lastByteTime = millis();
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      if (lineLen > 0) processSentence(lineBuf);
      lineLen = 0;
    } else if (lineLen < LINE_BUF_LEN - 1) {
      lineBuf[lineLen++] = c;
    } else {
      // line too long / garbage, reset
      lineLen = 0;
    }
  }

  if (millis() - lastPrint > PRINT_INTERVAL_MS) {
    lastPrint = millis();
    if (lastByteTime == 0) {
      Serial.println(F("No data received yet from em-trak socket. If another app already"));
      Serial.println(F("has a connection open to it, the em-trak's TCP port may only allow"));
      Serial.println(F("one client at a time - try closing the other app's connection."));
    } else if (millis() - lastByteTime > 10000) {
      Serial.print(F("No data from em-trak for "));
      Serial.print((millis() - lastByteTime) / 1000);
      Serial.println(F("s - connection may be stale."));
    }
    pruneStale();
    printVesselsByProximity();
  }

  // AISstream.io needs a real bounding box, so we hold off connecting until
  // we have our own position from the em-trak feed.
  if (haveFix) {
    if (!aisStreamConnected) {
      if (millis() - lastAisStreamReconnectAttempt > RECONNECT_INTERVAL_MS) {
        lastAisStreamReconnectAttempt = millis();
        connectAisStream();
      }
    } else if (!aisStreamClient.available()) {
      aisStreamConnected = false; // dropped, will retry above next loop
    } else {
      aisStreamClient.poll();
      float latDrift = fabs(ownLat - aisStreamSubLat);
      float lonDrift = fabs(ownLon - aisStreamSubLon);
      if (latDrift > AISSTREAM_RESUB_THRESHOLD_DEG || lonDrift > AISSTREAM_RESUB_THRESHOLD_DEG) {
        sendAisStreamSubscription(); // moved far enough that the old box may no longer cover us
      }
    }
  }
}

// ---------- Sentence dispatch ----------
void processSentence(char* line) {
#if DEBUG_RAW_NMEA
  Serial.print(F("RAW: "));
  Serial.println(line);
#endif
  if (strncmp(line, "!AIVDM", 6) == 0) {
    parseAIVDM(line);
  } else if (strncmp(line, "!AIVDO", 6) == 0) {
    parseAIVDO(line);
  } else if (strncmp(line, "$AIALR", 6) == 0) {
    parseALR(line);
  } else if (strstr(line, "RMC") != NULL) {
    parseRMC(line);
  } else if (strstr(line, "GGA") != NULL) {
    parseGGA(line);
  }
}

// ---------- Own position parsing ----------
// NMEA lat/lon in ddmm.mmmm / dddmm.mmmm format -> decimal degrees
float nmeaToDecimal(float raw, char hemi) {
  int deg = (int)(raw / 100);
  float minutes = raw - (deg * 100);
  float dec = deg + minutes / 60.0;
  if (hemi == 'S' || hemi == 'W') dec = -dec;
  return dec;
}

void parseGGA(char* line) {
  char copy[LINE_BUF_LEN];
  strncpy(copy, line, LINE_BUF_LEN);
  char* fields[15];
  int fcount = splitFieldsKeepEmpty(copy, fields, 15);
  if (fcount < 6) return;

  if (strlen(fields[2]) > 0 && strlen(fields[4]) > 0) {
    ownLat = nmeaToDecimal(atof(fields[2]), fields[3][0]);
    ownLon = nmeaToDecimal(atof(fields[4]), fields[5][0]);
    haveFix = true;
  }
}

void parseRMC(char* line) {
  char copy[LINE_BUF_LEN];
  strncpy(copy, line, LINE_BUF_LEN);
  char* fields[13];
  int fcount = splitFieldsKeepEmpty(copy, fields, 13);
  if (fcount < 7) return;

  if (fields[2][0] == 'A' && strlen(fields[3]) > 0 && strlen(fields[5]) > 0) {
    ownLat = nmeaToDecimal(atof(fields[3]), fields[4][0]);
    ownLon = nmeaToDecimal(atof(fields[5]), fields[6][0]);
    haveFix = true;
  }
  if (fcount > 8 && strlen(fields[8]) > 0) {
    ownCog = atof(fields[8]);
    haveCog = true;
  }
}

// Own-ship echoes: every !AIVDO is the em-trak reporting a message it just
// transmitted itself. For a Class B unit these are type 18 or 19 position
// reports, so counting them gives a live tally of "reports sent" since the
// ESP32 booted (not a lifetime device total - the unit doesn't expose that
// over NMEA as far as em-trak's documentation shows).
void parseAIVDO(char* line) {
  char copy[LINE_BUF_LEN];
  strncpy(copy, line, LINE_BUF_LEN);
  char* fields[8];
  int fcount = splitFieldsKeepEmpty(copy, fields, 8);
  if (fcount < 6) return;

  int totalFragments = atoi(fields[1]);
  if (totalFragments != 1) return; // own-ship position reports are always single-fragment

  char* payload = fields[5];
  int payloadLen = strlen(payload);
  if (payloadLen < 6) return;

  uint32_t msgType = getBits(payload, payloadLen, 0, 6);
  if (msgType == 18) ownReportsType18++;
  else if (msgType == 19) ownReportsType19++;
  else ownReportsOther++;
}

// $AIALR health/status alarms, e.g. Tx malfunction, VSWR exceeded, GPS fix
// issues, low forward power. Format: $AIALR,time,alarmID,condition,ack,desc
// condition 'A' = alarm currently active, 'V' = not active (fine, ignored).
void parseALR(char* line) {
  char copy[LINE_BUF_LEN];
  strncpy(copy, line, LINE_BUF_LEN);
  char* fields[6];
  int fcount = splitFieldsKeepEmpty(copy, fields, 6);
  if (fcount < 6) return;

  if (fields[3][0] == 'A') { // alarm condition is active
    char desc[64];
    strncpy(desc, fields[5], sizeof(desc) - 1);
    desc[sizeof(desc) - 1] = '\0';
    char* star = strchr(desc, '*'); // strip trailing NMEA checksum
    if (star) *star = '\0';
    Serial.print(F("*** AIS ALARM ACTIVE: "));
    Serial.println(desc);
  }
}

// ---------- AIS 6-bit decoding ----------
// Extract 'len' bits starting at bit offset 'start' from the armoured payload
uint32_t getBits(const char* payload, int payloadLen, int start, int len) {
  uint32_t result = 0;
  for (int i = 0; i < len; i++) {
    int bitPos = start + i;
    int charIndex = bitPos / 6;
    int bitInChar = 5 - (bitPos % 6);
    if (charIndex >= payloadLen) {
      result <<= 1; // pad with 0 if we run off the end
      continue;
    }
    int v = payload[charIndex] - 48;
    if (v > 40) v -= 8;
    int bit = (v >> bitInChar) & 1;
    result = (result << 1) | bit;
  }
  return result;
}

int32_t signExtend(uint32_t val, int bits) {
  if (val & ((uint32_t)1 << (bits - 1))) {
    val -= ((uint32_t)1 << bits);
  }
  return (int32_t)val;
}

// Split a comma-delimited string in place, preserving EMPTY fields (unlike
// strtok, which silently collapses consecutive delimiters). AIS sentences
// routinely have empty fields (e.g. the sequence-ID in !AIVDM), and losing
// them shifts every field after it - which is what was breaking payload
// extraction here.
int splitFieldsKeepEmpty(char* str, char** fields, int maxFields) {
  int count = 0;
  fields[count++] = str;
  for (char* p = str; *p; p++) {
    if (*p == ',') {
      *p = '\0';
      if (count < maxFields) fields[count++] = p + 1;
    }
  }
  return count;
}

// Decode a run of 6-bit AIS text characters (used for names/callsigns) into
// a null-terminated C string, trimming trailing '@' padding and spaces.
void decodeSixbitText(const char* payload, int payloadLen, int startBit, int numChars, char* out) {
  for (int i = 0; i < numChars; i++) {
    uint32_t v = getBits(payload, payloadLen, startBit + i * 6, 6);
    char c = (v < 32) ? (v + 64) : v;
    out[i] = c;
  }
  out[numChars] = '\0';
  // trim trailing '@' (padding) and spaces
  for (int i = numChars - 1; i >= 0; i--) {
    if (out[i] == '@' || out[i] == ' ') out[i] = '\0';
    else break;
  }
}

// Decode a reassembled type 5 (static/voyage data) payload just far enough
// to pull out the vessel name (bits 112-231). Skips IMO/callsign/ship type/
// dimensions - add more getBits() calls here later if you want those too.
void decodeType5(const char* payload, int payloadLen) {
  uint32_t msgType = getBits(payload, payloadLen, 0, 6);
  if (msgType != 5) return;
  uint32_t mmsi = getBits(payload, payloadLen, 8, 30);
  char name[21];
  decodeSixbitText(payload, payloadLen, 112, 20, name);
  setVesselName(mmsi, name);
}

void parseAIVDM(char* line) {
  char copy[LINE_BUF_LEN];
  strncpy(copy, line, LINE_BUF_LEN);

  char* fields[8];
  int fcount = splitFieldsKeepEmpty(copy, fields, 8);
  if (fcount < 6) return; // malformed

  int totalFragments = atoi(fields[1]);
  int fragNum = atoi(fields[2]);
  char channel = fields[4][0];

  if (totalFragments == 2) {
    // type 5 (static/voyage data incl. vessel name) always arrives as 2 fragments
    if (fragNum == 1) {
      strncpy(pendingPayload, fields[5], sizeof(pendingPayload) - 1);
      pendingPayload[sizeof(pendingPayload) - 1] = '\0';
      pendingSeq = atoi(fields[3]);
      pendingChannel = channel;
    } else if (fragNum == 2 && pendingSeq == atoi(fields[3]) && pendingChannel == channel) {
      char combined[200];
      strncpy(combined, pendingPayload, sizeof(combined) - 1);
      combined[sizeof(combined) - 1] = '\0';
      strncat(combined, fields[5], sizeof(combined) - strlen(combined) - 1);
      pendingSeq = -1; // consumed, don't let a stray later fragment 2 reuse it
      decodeType5(combined, strlen(combined));
    }
    return;
  }

  if (totalFragments != 1) return; // only 1- and 2-fragment messages are handled

  char* payload = fields[5];
  int payloadLen = strlen(payload);
  if (payloadLen < 20) return; // too short to be a position report

  uint32_t msgType = getBits(payload, payloadLen, 0, 6);
  uint32_t mmsi    = getBits(payload, payloadLen, 8, 30);

  if (msgType == 24) {
    uint32_t partNo = getBits(payload, payloadLen, 38, 2);
    if (partNo == 0) { // part A: vessel name
      char name[21];
      decodeSixbitText(payload, payloadLen, 40, 20, name);
      setVesselName(mmsi, name);
    }
    return; // part B (callsign/dimensions/type) not decoded
  }

  float lat, lon, sog, cog;

  if (msgType == 1 || msgType == 2 || msgType == 3) {
    sog = getBits(payload, payloadLen, 50, 10) / 10.0;
    lon = signExtend(getBits(payload, payloadLen, 61, 28), 28) / 600000.0;
    lat = signExtend(getBits(payload, payloadLen, 89, 27), 27) / 600000.0;
    cog = getBits(payload, payloadLen, 116, 12) / 10.0;
  } else if (msgType == 18 || msgType == 19) {
    sog = getBits(payload, payloadLen, 46, 10) / 10.0;
    lon = signExtend(getBits(payload, payloadLen, 57, 28), 28) / 600000.0;
    lat = signExtend(getBits(payload, payloadLen, 85, 27), 27) / 600000.0;
    cog = getBits(payload, payloadLen, 112, 12) / 10.0;
  } else {
    return; // not a position report we decode
  }

  // sanity check: lat/lon of 91 / 181 mean "not available"
  if (lat > 90.0 || lat < -90.0 || lon > 180.0 || lon < -180.0) return;

  updateOrAddVessel(mmsi, lat, lon, sog, cog);
}

// ---------- Vessel table management ----------
void updateOrAddVessel(uint32_t mmsi, float lat, float lon, float sog, float cog) {
  int freeSlot = -1;
  unsigned long oldest = 0xFFFFFFFF;
  int oldestSlot = 0;

  for (uint8_t i = 0; i < MAX_VESSELS; i++) {
    if (vessels[i].valid && vessels[i].mmsi == mmsi) {
      vessels[i].lat = lat;
      vessels[i].lon = lon;
      vessels[i].sog = sog;
      vessels[i].cog = cog;
      vessels[i].lastSeen = millis();
      vessels[i].hasPosition = true;
      return;
    }
    if (!vessels[i].valid && freeSlot == -1) freeSlot = i;
    if (vessels[i].lastSeen < oldest) {
      oldest = vessels[i].lastSeen;
      oldestSlot = i;
    }
  }

  int slot = (freeSlot != -1) ? freeSlot : oldestSlot; // overwrite oldest if table is full
  vessels[slot].mmsi = mmsi;
  vessels[slot].lat = lat;
  vessels[slot].lon = lon;
  vessels[slot].sog = sog;
  vessels[slot].cog = cog;
  vessels[slot].lastSeen = millis();
  vessels[slot].valid = true;
  vessels[slot].hasPosition = true;
  vessels[slot].hasName = false;
  vessels[slot].name[0] = '\0';
}

// Attach a decoded name to a vessel entry, creating a name-only slot if the
// vessel hasn't sent a position report yet (it'll be filled in once it does).
void setVesselName(uint32_t mmsi, const char* name) {
  if (name[0] == '\0') return; // nothing decoded, don't overwrite with blank

  int freeSlot = -1;
  unsigned long oldest = 0xFFFFFFFF;
  int oldestSlot = 0;

  for (uint8_t i = 0; i < MAX_VESSELS; i++) {
    if (vessels[i].valid && vessels[i].mmsi == mmsi) {
      strncpy(vessels[i].name, name, sizeof(vessels[i].name) - 1);
      vessels[i].name[sizeof(vessels[i].name) - 1] = '\0';
      vessels[i].hasName = true;
      vessels[i].lastSeen = millis();
      return;
    }
    if (!vessels[i].valid && freeSlot == -1) freeSlot = i;
    if (vessels[i].lastSeen < oldest) {
      oldest = vessels[i].lastSeen;
      oldestSlot = i;
    }
  }

  int slot = (freeSlot != -1) ? freeSlot : oldestSlot;
  vessels[slot].mmsi = mmsi;
  vessels[slot].valid = true;
  vessels[slot].hasPosition = false; // no position yet, won't show in proximity list until one arrives
  vessels[slot].hasName = true;
  vessels[slot].lastSeen = millis();
  strncpy(vessels[slot].name, name, sizeof(vessels[slot].name) - 1);
  vessels[slot].name[sizeof(vessels[slot].name) - 1] = '\0';
}

void pruneStale() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < MAX_VESSELS; i++) {
    if (vessels[i].valid && (now - vessels[i].lastSeen > STALE_TIMEOUT_MS)) {
      vessels[i].valid = false;
    }
  }
}

// ---------- Distance / bearing ----------
float distanceKm(float lat1, float lon1, float lat2, float lon2) {
  const float R_KM = 6371.0; // earth radius in kilometers
  float dLat = radians(lat2 - lat1);
  float dLon = radians(lon2 - lon1);
  float a = sin(dLat / 2) * sin(dLat / 2) +
            cos(radians(lat1)) * cos(radians(lat2)) *
            sin(dLon / 2) * sin(dLon / 2);
  float c = 2 * atan2(sqrt(a), sqrt(1 - a));
  return R_KM * c;
}

float bearingTo(float lat1, float lon1, float lat2, float lon2) {
  float dLon = radians(lon2 - lon1);
  float y = sin(dLon) * cos(radians(lat2));
  float x = cos(radians(lat1)) * sin(radians(lat2)) -
            sin(radians(lat1)) * cos(radians(lat2)) * cos(dLon);
  float brng = degrees(atan2(y, x));
  return fmod(brng + 360.0, 360.0);
}

// ---------- Sorted output ----------
void printVesselsByProximity() {
  if (!haveFix) {
    Serial.println(F("Waiting for own GPS fix..."));
    return;
  }

  uint8_t idx[MAX_VESSELS];
  float dist[MAX_VESSELS];
  uint8_t n = 0;

  for (uint8_t i = 0; i < MAX_VESSELS; i++) {
    if (vessels[i].valid && vessels[i].hasPosition) {
      idx[n] = i;
      dist[n] = distanceKm(ownLat, ownLon, vessels[i].lat, vessels[i].lon);
      n++;
    }
  }

  // simple insertion sort by distance (n is small, no need for anything fancier)
  for (uint8_t i = 1; i < n; i++) {
    float d = dist[i];
    uint8_t id = idx[i];
    int j = i - 1;
    while (j >= 0 && dist[j] > d) {
      dist[j + 1] = dist[j];
      idx[j + 1] = idx[j];
      j--;
    }
    dist[j + 1] = d;
    idx[j + 1] = id;
  }

  Serial.println(F("---- Nearby vessels ----"));
  Serial.print(F("Own Class B reports sent (since boot) - type18: "));
  Serial.print(ownReportsType18);
  Serial.print(F("  type19: "));
  Serial.print(ownReportsType19);
  if (ownReportsOther > 0) {
    Serial.print(F("  other: "));
    Serial.print(ownReportsOther);
  }
  Serial.println();
  if (n == 0) {
    Serial.println(F("(none heard yet)"));
  } else {
    for (uint8_t i = 0; i < n; i++) {
      Vessel& v = vessels[idx[i]];
      float brg = bearingTo(ownLat, ownLon, v.lat, v.lon);
      unsigned long ageSec = (millis() - v.lastSeen) / 1000;
      Serial.print(F("MMSI ")); Serial.print(v.mmsi);
      Serial.print(F("  ")); Serial.print(v.hasName ? v.name : "(name unknown)");
      Serial.print(F("  dist ")); Serial.print(dist[i], 2); Serial.print(F(" km"));
      Serial.print(F("  brg ")); Serial.print(brg, 0); Serial.print(F(" deg"));
      if (haveCog) {
        float rel = fmod((brg - ownCog) + 540.0, 360.0) - 180.0; // normalize to -180..180
        char dir = (rel >= 0) ? 'R' : 'L';
        Serial.print(F("  look ")); Serial.print(dir); Serial.print(fabs(rel), 0); Serial.print(F("deg"));
      } else {
        Serial.print(F("  look ?")); // no reliable own course yet (need to be moving)
      }
      Serial.print(F("  SOG ")); Serial.print(v.sog * 1.852, 1); Serial.print(F(" km/h"));
      Serial.print(F("  COG ")); Serial.print(v.cog, 0); Serial.print(F(" deg"));
      Serial.print(F("  age ")); Serial.print(ageSec); Serial.println(F("s"));
    }
  }
  Serial.println();
}
