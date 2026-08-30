////////////////////////////////////////////////////////////////////////////////////////
//
// Data collection app for my boat, incl Emtrak GPS, Victron data, bluetooth etc.
// (c) 2026 Simon H. van Wijlen
//
// V4.1, adding logging (Sparkfun OpenLogger) and a RealTime Clock. For wiring/PINs, see bottom of this file
// V4.2, adding the waveshare e-ink display code
// V4.3, moving from Uno to ESP32-S3 N16R8 Devboard 16MB Flash en 8MB PSRAM >> see line 59-ish for flash/PSRAM instructions. This board was selected due to more memory to work with the waveshare e-ink screen. See bottom of sketch for Claude info.
// V4.3, replacing openlog by std SD card (adafruit MicroSD Card Breakout+) because the Sparkfun openlog is broken and had limited possibilities to do file handling
// V4.4, Fixed SDcard and matrix
// V4.5, more SD and BLE fixes. Runs well now. 
//
////////////////////////////////////////////////////////////////////////////////////////

// TODO 
// Card status: MISSING
// data logging / wegschrijven toch nog niet lekker
// AIS details : limiteren tot alles binnen 1km, tenzij sneller varend dan 10km en dan max 2km >> en in bold tonen
// NOTE : the vessel API key is only 90 days valid en max 150 gratis. Dus geen optie.... So if there are errors - get a new key and update the secrets file. Add a message / matrix indocator if the key is too old (store the date in the secrets file)
// the matrix displays a OK-checksign even when wifi does not work >> error displayling is clearly not yet working
// hij rapporteert een cerbo value dis mss bruikbaar is?
// matrix display aansluiten en oude code terughalen uit vorige versie. Daar zaten nog wel bugs in.
// GPS module : kml file laten genereren
// Bresser data inlezen en true windrichting uitrekenen
// klopt het dat hij in "DoFake" mode maar 1x per seconde data langsloopt?
// Indicators in het scherm, of er GPS data is, MQTT data, BLE data, etc
// DC voltage
// DC current
// 
// TTG is niet correct (bv 36 tov 44hrs in de app)
// inbouwen als tijdens het runnen bv AIS wegvalt, of MQTT, of... AIS indicator blijft maar op 1 staan
// Op 24v aansluiten
// Per dag een e-mail versturen
// Rutx temp info uitlezen via MQTT
// Hoe kun je via de cerbo de ruuvi gegevens uitlezen?
// Eerstvolgende brug/sluis tonen + VHF/telno. https://www.vaarweginformatie.nl/frp/main/#/page/downloads 

// The UNO R4 WiFi has one I2C bus which is marked with SCL and SDA. They are shared with A4 (SDA) and A5 (SCL) which owners of previous UNO's are familiar with. The pullups are not mounted on the PCB but there are footprints to do so if needed.
// The pins used for I2C on the UNO R4 WiFi are the following:
// SDA - D18, SCL - D19

#include <Arduino.h>
#include <WiFi.h>         // For ESP32S3 Dev Module
#include <ArduinoBLE.h>
#include "Mudbus.h"
#include <PubSubClient.h>
#include <TinyGPSPlus.h>
#include <ArduinoJson.h>
//#include <arduino_secrets.h> // voor op de boot
#include <arduino_secrets_home.h> // voor testen thuis
#include <SPI.h>
#include <SD.h>
#include <Wire.h>
#include <RTClib.h>
#include <MD_MAX72xx.h>

/* 
 * Hardware: ESP32-S3-DevKitC-1 N16R8 (16MB Flash, 8MB PSRAM). Partition scheme : 16Mb / 2mb; USB CDC On Boot ✅ Enabled; Upload Mode : UART0 / USB; Tools → Flash Mode : QIO 80mhz; flash sizer : 16mb; PSRAM : OPI PSRAM
 * 
 * Features:
 * - Card detect monitoring
 * - Auto-rotate log files at 4MB
 * - Delete oldest files when 90% full
 * - Custom log file names
 * - Timestamp-based file management
 * - E-ink display support
 * - MAX7219 LED Matrix display
 * 
 * Hardware Requirements:
 * - ESP32-S3 DevKitC-1 N16R8
 * - Adafruit MicroSD Card Breakout (3.3V compatible)
 * - DS3231 RTC Module (I2C)
 * - Waveshare E-ink Display (SPI)
 * - MAX7219 8x8 LED Matrix Module (SPI)
 * 
 */

// clock
RTC_DS3231 rtc;  // RTC object DS3231
#define rtc_I2C_SDA 8 // green
#define rtc_I2C_SCL 9 // yellow

// Pin Definitions for SDcard (HSPI bus)
#define SD_CS_PIN 10
#define SD_MOSI_PIN 11
#define SD_MISO_PIN 13
#define SD_SCK_PIN 12
#define CARD_DETECT_PIN 15

#define MAX_LOG_SIZE 4194304      // 4MB in bytes
#define DISK_FULL_THRESHOLD 90    // Delete oldest when 90% full
#define RETENTION_DAYS 14         // Also delete files older than 2 weeks
#define LOG_CHECK_INTERVAL 50000  // Check log size every 60 seconds
String logPrefix = "CarpeDiemLog_";     // Change this to customize log names
String logExtension = ".txt";     // File extension
File currentLogFile;
String currentLogFilename = "";
unsigned long lastLogCheck = 0;
bool cardPresent = false;
bool sdInitialized = false;

SPIClass spi(HSPI); // Use HSPI bus
// waveshere E-ink Display Pins
#define EINK_CS_PIN   14
#define EINK_DC_PIN   16
#define EINK_RST_PIN  17
#define EINK_BUSY_PIN 18
bool einkInitialized = false;

// MAX7219 LED Matrix Pins (VSPI bus - separate from SD card)
#define MAX7219_CS_PIN   21  // used to be 19-35-37-36 but this caused USB issues and reboots - see claude at the bottom
#define MAX7219_MOSI_PIN 40  // DIN
#define MAX7219_MISO_PIN 41  // Not used but needed for SPI init
#define MAX7219_SCK_PIN  42  // CLK
// MAX7219 Configuration
bool matrixInitialized = false;
unsigned long lastMatrixUpdate = 0;
// MAX7219 LED Matrix - uses shared SPI bus
#define MATRIX_UPDATE_INTERVAL 5000  // Update matrix display every 5 seconds
#define MAX_DEVICES 1  // Number of 8x8 matrix modules chained together
#define HARDWARE_TYPE MD_MAX72XX::FC16_HW  // Change if using different hardware

// Separate SPI buses for SD card and MAX7219
// ESP32 core 3.x doesn't use HSPI/VSPI constants
SPIClass spiSD(FSPI);     // SD card on FSPI (was HSPI)
SPIClass spiMatrix(HSPI); // MAX7219 on HSPI (was VSPI)

// MAX7219 uses its own SPI bus
MD_MAX72XX matrix = MD_MAX72XX(HARDWARE_TYPE, spiMatrix, MAX7219_CS_PIN, MAX_DEVICES);

// Icons for matrix display (8x8 patterns)
const uint8_t ICON_SD_OK[8] = {
  0b00111100,
  0b01000010,
  0b10111101,
  0b10100101,
  0b10111101,
  0b10000001,
  0b01111110,
  0b00000000
};

const uint8_t ICON_SD_MISSING[8] = {
  0b00111100,
  0b01000010,
  0b10000001,
  0b10000001,
  0b10000001,
  0b10000001,
  0b01111110,
  0b00000000
};

const uint8_t ICON_HEART[8] = {
  0b00000000,
  0b01100110,
  0b11111111,
  0b11111111,
  0b01111110,
  0b00111100,
  0b00011000,
  0b00000000
};

const uint8_t ICON_CHECKMARK[8] = {
  0b00000000,
  0b00000001,
  0b00000011,
  0b10000110,
  0b11001100,
  0b01111000,
  0b00110000,
  0b00000000
};

const uint8_t ICON_ERROR[8] = {
  0b10000001,
  0b01000010,
  0b00100100,
  0b00011000,
  0b00011000,
  0b00100100,
  0b01000010,
  0b10000001
};

// Matrix display frame mapping of numbers 0-9. Large number patterns for 12x8 LED matrix
const uint32_t matrixNumbers[10][8] = {
  // Number 0
  {
    0b011111100000,
    0b110000110000,
    0b110001110000,
    0b110011110000,
    0b110111110000,
    0b111100110000,
    0b110000110000,
    0b011111100000
  },
  // Number 1
  {
    0b000110000000,
    0b001110000000,
    0b000110000000,
    0b000110000000,
    0b000110000000,
    0b000110000000,
    0b000110000000,
    0b011111100000
  },
  
  // Number 2
  {
    0b011111100000,
    0b110000110000,
    0b000000110000,
    0b000001100000,
    0b000110000000,
    0b001100000000,
    0b110000000000,
    0b111111110000
  },
  
  // Number 3
  {
    0b011111100000,
    0b110000110000,
    0b000000110000,
    0b001111100000,
    0b000000110000,
    0b000000110000,
    0b110000110000,
    0b011111100000
  },
  
  // Number 4
  {
    0b000001100000,
    0b000011100000,
    0b000110100000,
    0b001100100000,
    0b011000100000,
    0b111111110000,
    0b000000100000,
    0b000000100000
  },
  
  // Number 5
  {
    0b111111110000,
    0b110000000000,
    0b110000000000,
    0b111111100000,
    0b000000110000,
    0b000000110000,
    0b110000110000,
    0b011111100000
  },
  
  // Number 6
  {
    0b001111100000,
    0b011000000000,
    0b110000000000,
    0b111111100000,
    0b110000110000,
    0b110000110000,
    0b110000110000,
    0b011111100000
  },
  
  // Number 7
  {
    0b111111110000,
    0b000000110000,
    0b000001100000,
    0b000011000000,
    0b000110000000,
    0b001100000000,
    0b011000000000,
    0b110000000000
  },
  
  // Number 8
  {
    0b011111100000,
    0b110000110000,
    0b110000110000,
    0b011111100000,
    0b110000110000,
    0b110000110000,
    0b110000110000,
    0b011111100000
  },
  
  // Number 9
  {
    0b011111100000,
    0b110000110000,
    0b110000110000,
    0b110000110000,
    0b011111110000,
    0b000000110000,
    0b000001100000,
    0b011111000000
  }
};
 


// For debug : focus on specific data sources only
int ShowLogLevel = 9;

bool DoWiFi     = true;
bool DoBLE      = true;
bool DoMODBUS   = true;
bool DoMQTT     = true;
bool DoGPS      = true;
bool DoFake     = true; // so I can program away from the devices at the boat using fake data
bool DoShow     = true;

// RETRY TO CONNECT TO A DEVICE ONCE EVERY 5 MINUTES
unsigned long previousMillis = 0;
const unsigned long interval = 5UL * 60UL * 1000UL; // 5 minutes in ms (300000 ms)

// Your WiFi credentials
const char* ssid     = SECRET_SSID; 
const char* password = SECRET_PASSWORD;

// em-trak TCP stream settings
const char* emtrakIP = "192.168.2.1";  // Change to your em-trak IP
const uint16_t emtrakPort = 5000;      // TCP port
int EmTrack_connect_attempts = 0; 
int EmTrack_connect_attemptsMAX = 2; // only try a limited nr of times in case stuff is switched off

// --- Cerbo GX settings ---
const char* cerboHost = "192.168.1.228";  // <-- Change to your Cerbo GX IP
const int cerboPort   = 502;

// ---- MQTT Broker (Venus OS or VRM) ----
const char* mqtt_server = "venus.local";   // Or IP address of Venus GX
const int   mqtt_port   = 1883;            // Default MQTT port

// ---- VRM Portal ID ----
const char* portalId = "c0619ab711a9";

// Modbus registers
struct RegInfo {
  char* label;
  int unitId;
  uint16_t reg;
  float scale;
};

// com.victronenergy.system       100
// com.victronenergy.battery      224 (278?)
// com.victronenergy.temperature  21 en 20
// com.victronenergy.solarcharger 223 (277?)
// com.victronenergy.multi        227
// VEbus 276
// GPS : not via modbus but via Em_Track AIS
RegInfo regs[] = {
  {"Grid (W)",                    100,  820,  1.0},  
  {"Active input source",         100,  826,  1.0}, // 0=Unknown;1=Grid;2=Generator;3=Shore power;240=Not connected
  {"AC Loads (W)",                100,  817,  1.0},
  {"Battery SOC (%)",             100,  843,  1.0},
  {"Battery Voltage (V)",         100,  840,  0.1},  //klopt
  //{"Battery Power (W)",           100,  865,    1}, // raar getal
  //{"Battery Current (A)",         100,  866,  0.1}, // raar getal
  //{"Battery Power (W)",           277,  258,    1}, // 
  //{"Battery Batt Current (A)",    224,  261,   10}, // raar getal  
  //{"Battery Time to Go (System)", 100,  846,    3600}, // deze is nog niet gelijk aan het display vd app, en is 0 when off grid
  //{"Battery Time to Go (Batt)",   224,  303,    3600}, // when off grid, altijd 0
  //{"DC Power (W)",                100,  860,  1.0},
  // missing : DC voltage, DC amperage
  {"PV Power (W)",                100,  850,  1.0},
  {"Starter battery (V)",         224,  260, 0.01}, 
  {"Electronics bay (C)",         20,   3304, 0.01},
  {"Engine room (C)",             21,   3304, 0.01},
};
const int numRegs = sizeof(regs) / sizeof(regs[0]);

// MQTT topics of the Victron installation
struct VictronMQTTinfo {
  String topic;
  float TheValue;
};
VictronMQTTinfo myVictronMQTT[] = {
      {"system/0/Dc/Battery/Current", -123456789.0},  // the -123456789.0 functions as "not yet read"
      {"system/0/Dc/Battery/Power", -123456789.0},
      {"system/0/Dc/Battery/Soc", -123456789.0},
      {"system/0/Dc/Battery/TimeToGo", -123456789.0},
      {"system/0/Dc/Battery/Voltage", -123456789.0},
      {"battery/278/TimeToGo", -123456789.0},
      {"battery/278/Dc/1/Current", -123456789.0},
      {"battery/278/Dc/1/Power", -123456789.0},
      {"battery/278/Dc/1/Voltage", -123456789.0},
      {"battery/278/Dc/0/Current", -123456789.0},    
      {"battery/278/Dc/0/Power", -123456789.0},        
      {"battery/278/Dc/0/Voltage", -123456789.0},
}; 
const int numVictronMQTTtopics = sizeof(myVictronMQTT) / sizeof(myVictronMQTT[0]);
// Create a JSON document (200 bytes is plenty for your example)
StaticJsonDocument<200> MQTTvaluestring;

// BLE Teltonika Blue Puck devices
const char* knownDevices[9] = { // Teltonika blue pucks
  "F3:06:2D:7C:87:AF",
  "FC:F1:E2:2A:95:C5",
  "C0:BB:A1:89:54:F4",
  "C2:D6:33:33:3B:31",
  "ED:2D:13:21:8C:58",
  "F3:86:A8:30:7B:AE",
  "F1:B1:FD:48:2B:78",
  "EA:4F:38:E0:93:D9",
  "F7:F7:21:2D:12:D4"
};
bool isTargetDevice(const String &addr) {
  for (int i = 0; i < 9; i++) {
    if (addr.equalsIgnoreCase(knownDevices[i])) return true;
  }
  return false;
}

// Setup the final data structure for use on the display
struct DisplayInfoStruct {
  char* internalLabel;
  char* displayLabel;
  float TheValue;
  char* TheStringValue;
};
DisplayInfoStruct DisplayInfo[] = {
  {"Active input source",         "Grid Status",              -123456789.0, ""}, // 0=Unknown;1=Grid;2=Generator;3=Shore power;240=Not connected
  {"Grid (W)",                    "Grid (W)",                 -123456789.0, ""},      
  {"AC Loads (W)",                "AC Loads (W)",             -123456789.0, ""},    
  {"Battery SOC (%)",             "Battery SOC (%)",          -123456789.0, ""}, 
  {"Battery0 Voltage (V)",        "Battery0 Voltage (V)",      -123456789.0, ""}, 
  {"Battery0 Power (W)",          "Battery0 Power (W)",        -123456789.0, ""}, 
  {"Battery0 Current (A)",        "Battery0 Current (A)",      -123456789.0, ""}, 
  {"Battery Time to Go (System)", "TTG (System)",             -123456789.0, ""}, // differs from the app
  {"Battery Time to Go (Batt)",   "TTG (Batt)",               -123456789.0, ""}, // differs from the app
  {"DC Power (W)",                "DC Power (W)",             -123456789.0, ""}, 
  {"DC Current (A)",              "DC Current (A)",           -123456789.0, ""},
  {"PV Power (W)",                "PV Power (W)",             -123456789.0, ""}, 
  {"Starter battery (V)",         "Starter battery (V)",      -123456789.0, ""}, 
  {"Electronics bay (C)",         "Electronics bay (C)",      -123456789.0, ""}, 
  {"Engine room (C)",             "Engine room (C)",          -123456789.0, ""}, 
  {"Lat",                         "Lat",                      -123456789.0, ""}, 
  {"Lng",                         "Lng",                      -123456789.0, ""}, 
  {"Speed",                       "Speed",                    -123456789.0, ""}, 
  {"Course",                      "Course",                   -123456789.0, ""}, 
  {"Master Bedroom Temp",         "Master Bedroom Temp",      -123456789.0, ""}, 
  {"Master Bedroom Humidity",     "Master Bedroom Humidity",  -123456789.0, ""}, 
  {"Engine Room Temp",            "Engine Room Temp",         -123456789.0, ""}, 
  {"Engine Room Humidity",        "Engine Room Humidity",     -123456789.0, ""},   
  {"Watertank SB Temp",           "Watertank SB Temp",        -123456789.0, ""}, 
  {"Watertank SB Humidity",       "Watertank SB Humidity",    -123456789.0, ""}, 
  {"Watertank PS Temp",           "Watertank PS Temp",        -123456789.0, ""}, 
  {"Watertank PS Humidity",       "Watertank PS Humidity",    -123456789.0, ""}, 
  {"Toilet Temp",                 "Toilet Temp",              -123456789.0, ""}, 
  {"Toilet Humidity",             "Toilet Humidity",          -123456789.0, ""}, 
  {"P RHT 900F0A Temp",           "Washcabin Temp",           -123456789.0, ""}, 
  {"P RHT 900F0A Humidity",       "Washcabin Humidity",       -123456789.0, ""}, 
  {"Voorin Temp",                 "Voorin Temp",              -123456789.0, ""}, 
  {"Voorin Humidity",             "Voorin Humidity",          -123456789.0, ""}, 
  {"Kajuit Temp",                 "Kajuit Temp",              -123456789.0, ""}, 
  {"Kajuit Humidity",             "Kajuit Humidity",          -123456789.0, ""}, 
  {"Buitenkraan Temp",            "Buitenkraan Temp",         -123456789.0, ""}, 
  {"Buitenkraan Humidity",        "Buitenkraan Humidity",     -123456789.0, ""}, 
  {"WiFi",                        "WiFi",                     -123456789.0, ""},   
  {"AIS",                         "AIS",                      -123456789.0, ""}, 
  {"MQTT",                        "MQTT",                     -123456789.0, ""}, 
  {"MODBUS",                      "MODBUS",                   -123456789.0, ""},     
  {"BLE",                         "BLE",                      -123456789.0, ""}, 
  {"Weather",                     "Weather",                  -123456789.0, ""},  
};
const int numDisplayTopics = sizeof(DisplayInfo) / sizeof(DisplayInfo[0]);

// my own global variables
char tmpStr[255] = "";
bool DoOnce = true;
String UserInput;

///////////// LOAD INSTANCES ////////////////
// ---- MQTT client ----
WiFiClient espClient; // for MQTT
WiFiClient Mclient; // For mudbus
WiFiClient GPS_WiFI_client; // for em-track
Mudbus mudbus(Mclient); // MODBUS instance
PubSubClient MQTTclient(espClient); // MQTT instance
TinyGPSPlus gps; // GPS instance, For AIS/GPS from Em-Track system
///////////// END LOAD INSTANCES ////////////////

// --- State variables ---
int currentFileIndex = 0;
String currentFileName;
String TimeSource;

void checkDiskUsage() {
  uint64_t usedBytes = SD.usedBytes();
  uint64_t totalBytes = SD.totalBytes();
  
  int usagePercent = (usedBytes * 100) / totalBytes;
  
  if (usagePercent >= DISK_FULL_THRESHOLD) {
    Serial.println("\n*** DISK USAGE WARNING ***");
    Serial.print("Usage: ");
    Serial.print(usagePercent);
    Serial.println("%");
    
    while (usagePercent >= DISK_FULL_THRESHOLD - 10) {
      if (!deleteOldestFile()) {
        break;
      }
      usedBytes = SD.usedBytes();
      usagePercent = (usedBytes * 100) / totalBytes;
    }
    
    Serial.println("*** Cleanup complete ***\n");
  }
}

void listAllFiles() {
  Serial.println("\n========== FILE LIST ==========");
  
  File root = SD.open("/");
  if (!root) {
    Serial.println("ERROR: Failed to open root directory");
    return;
  }
  
  Serial.println("Filename                          Modified Date/Time    Size");
  Serial.println("----------------------------------------------------------------------");
  
  int fileCount = 0;
  unsigned long totalSize = 0;
  
  File entry = root.openNextFile();
  while (entry) {
    if (!entry.isDirectory()) {
      String filename = String(entry.name());
      Serial.print(filename);
      
      if (filename == currentLogFilename) {
        Serial.print(" [ACTIVE]");
      }
      
      int nameLen = filename.length();
      if (filename == currentLogFilename) nameLen += 9;
      for (int i = nameLen; i < 34; i++) {
        Serial.print(" ");
      }
      
      time_t t = entry.getLastWrite();
      struct tm * tmstruct = localtime(&t);
      Serial.printf("%04d/%02d/%02d %02d:%02d:%02d  ",
                    (tmstruct->tm_year) + 1900,
                    (tmstruct->tm_mon) + 1,
                    tmstruct->tm_mday,
                    tmstruct->tm_hour,
                    tmstruct->tm_min,
                    tmstruct->tm_sec);
      
      Serial.print(entry.size());
      Serial.println(" bytes");
      
      fileCount++;
      totalSize += entry.size();
    }
    entry.close();
    entry = root.openNextFile();
  }
  
  root.close();
  
  Serial.println("----------------------------------------------------------------------");
  Serial.print("Total: ");
  Serial.print(fileCount);
  Serial.print(" files, ");
  Serial.print(totalSize);
  Serial.println(" bytes\n");
}

void setLogPrefix() {
  Serial.println("\n========== SET LOG PREFIX ==========");
  Serial.print("Current prefix: ");
  Serial.println(logPrefix);
  Serial.println("Enter new prefix (e.g., 'sensor', 'weather', 'test'):");
  Serial.println("Waiting for input (30s timeout)...");
  
  while (Serial.available()) Serial.read();
  
  String input = "";
  unsigned long timeout = millis() + 30000;
  
  while (millis() < timeout) {
    if (Serial.available()) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        if (input.length() > 0) break;
      } else {
        input += c;
      }
    }
  }
  
  if (input.length() > 0) {
    logPrefix = input;
    Serial.print("Log prefix set to: ");
    Serial.println(logPrefix);
    Serial.println("(New files will use this prefix)\n");
  } else {
    Serial.println("Timeout or no input\n");
  }
}

void setRTCTime() {
  Serial.println("\n========== SET RTC TIME ==========");
  Serial.println("Format: YYYY MM DD HH MM SS");
  Serial.println("Example: 2026 01 17 14 30 00");
  
  while (Serial.available()) Serial.read();
  
  String input = "";
  unsigned long timeout = millis() + 30000;
  
  while (millis() < timeout) {
    if (Serial.available()) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        if (input.length() > 0) break;
      } else {
        input += c;
      }
    }
  }
  
  if (input.length() == 0) {
    Serial.println("Timeout\n");
    return;
  }
  
  int year, month, day, hour, minute, second;
  if (sscanf(input.c_str(), "%d %d %d %d %d %d", 
             &year, &month, &day, &hour, &minute, &second) == 6) {
    
    DateTime newTime(year, month, day, hour, minute, second);
    rtc.adjust(newTime);
    
    Serial.print("Time set to: ");
    printDateTime(newTime);
    Serial.println("\n");
  } else {
    Serial.println("Invalid format!\n");
  }
}

void showCurrentTime() {
  DateTime now = rtc.now();
  Serial.print("\nCurrent: ");
  printDateTime(now);
  Serial.println("\n");
}

void showMenu() {
  Serial.println("\n========== MENU ==========");
  Serial.println("1 - List all files");
  Serial.println("2 - Delete files older than 2 weeks");
  Serial.println("3 - Write test entry to log");
  Serial.println("4 - Show disk info");
  Serial.println("5 - Set RTC time");
  Serial.println("6 - Show current time");
  Serial.println("7 - Set log file prefix");
  Serial.println("8 - Force rotate log file");
  Serial.println("9 - Delete oldest file");
  Serial.println("M - Show this menu");
  Serial.println("==========================");
  Serial.println("\nHardware Status:");
  Serial.print("Card detect: GPIO ");
  Serial.println(CARD_DETECT_PIN);
  Serial.print("Card status: ");
  Serial.println(cardPresent ? "PRESENT" : "MISSING");
  Serial.print("SD status:   ");
  Serial.println(sdInitialized ? "READY" : "NOT READY");
  Serial.println("\nPin Configuration:");
  Serial.printf("I2C:  SDA=GPIO%d, SCL=GPIO%d\n", rtc_I2C_SDA, rtc_I2C_SCL);
  Serial.printf("SPI:  MOSI=GPIO%d, MISO=GPIO%d, SCK=GPIO%d\n", SD_MOSI_PIN, SD_MISO_PIN, SD_SCK_PIN);
  Serial.printf("SD:   CS=GPIO%d, CD=GPIO%d\n", SD_CS_PIN, CARD_DETECT_PIN);
  Serial.printf("E-ink: CS=GPIO%d, DC=GPIO%d, RST=GPIO%d, BUSY=GPIO%d\n", 
                EINK_CS_PIN, EINK_DC_PIN, EINK_RST_PIN, EINK_BUSY_PIN);
  Serial.println();
}

void printDateTime(DateTime dt) {
  char buf[20];
  sprintf(buf, "%04d/%02d/%02d %02d:%02d:%02d",
          dt.year(), dt.month(), dt.day(),
          dt.hour(), dt.minute(), dt.second());
  Serial.print(buf);
}


// ---------------------------------------------------------------------------
// Variadic logger with log level as first parameter
// ---------------------------------------------------------------------------
template <typename... Args>
void myLog(int pLogLevel, const Args&... args) {

/*
  Usage of loglevel :
  - between 0 and +99 : with timestamp and linefeed
  - between 0 and -99 : without timestamp but with linefeed
  - (abs) >= 100 : no linefeeds  
*/

  bool WithTimeStamps = false;
  bool WithLF = true;

  // Determine options     myLog(-100, ".");
  if (pLogLevel >= 0) { 
    WithTimeStamps = true;
  } else {
    pLogLevel = abs(pLogLevel);
  }
  if (pLogLevel >= 100) {
    WithLF = false;
    pLogLevel = pLogLevel / 100;
  }

  if (pLogLevel <= ShowLogLevel) {

    // Build the complete log message in one variable
    String logMessage = "";

    if (WithTimeStamps) {

       DateTime now = rtc.now();

      // Add time with leading zeros
      logMessage += String(now.year()) + "-";
      logMessage += (now.month() < 10 ? "0" : "") + String(now.month()) + "-";
      logMessage += (now.day() < 10 ? "0" : "") + String(now.day()) + " ";
      logMessage += (now.hour() < 10 ? "0" : "") + String(now.hour()) + ":";
      logMessage += (now.minute() < 10 ? "0" : "") + String(now.minute()) + ":";
      logMessage += (now.second() < 10 ? "0" : "") + String(now.second()) + " ";
      // Add log level
      logMessage += "[Level " + String(pLogLevel) + "] ";
    }
    
    // Add all other arguments
    ((logMessage += String(args)), ...);

    // Output the complete message to IDE
    Serial.print(logMessage);
    if (WithLF) Serial.println("");
    Serial.flush(); // ensure everything is pushed out

    //Now write to the SD card
  //Serial.print("currentLogFile="); Serial.print(currentLogFile); Serial.print("; sdInitialized="); Serial.println(sdInitialized);
  //if (!currentLogFile || !sdInitialized) {
  if (!sdInitialized) {
    Serial.println("ERROR: Log file not open!");
    return;
  }
  
  // Write
  currentLogFile.print(logMessage);
  if (WithLF) currentLogFile.println("");
  currentLogFile.flush();
  }
}



void UpdateDisplayTable(const char* pLabel, float pValue, String pSource) {  // store the data that we gather from various sources, in 1 structure.
  int i = 0;
  while (i < numDisplayTopics) {
    if (pSource == "T") {
        myLog(9, "i=", i, "; pLabel=", pLabel, "; IL=", DisplayInfo[i].internalLabel, "; val=", pValue);
    }
    if (String(DisplayInfo[i].internalLabel) == String(pLabel)) {
      if (pSource == "T") {
        myLog(9, "^^^ same");
      }
      DisplayInfo[i].TheValue = pValue;
      if (pSource == "T") {
        myLog(9, "Found (", pSource, "): ", DisplayInfo[i].internalLabel, "  Value=", pValue);
      }
      if (pSource == "B") {
        myLog(10, "BLE info (", pSource, "): ", DisplayInfo[i].internalLabel, "  Value=", pValue);
      }
      return;
    }
    i++;
  }
  if (pSource == "T") {
    delay(15000);
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  String message;
  String tmpMsg;
  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  //myLog(9, "@callback, Topic received: ", topic, " | Message: ", message); //uit-commenten later

  // find the sent MQTT data in our own MQTT construct
  int j = 0;
  while (j < numVictronMQTTtopics) {
    UpdateDisplayTable("MQTT", 1, "S");
    tmpMsg = String(topic);
    int index = tmpMsg.indexOf(myVictronMQTT[j].topic); // because indexOf does not work on a char* (which topic is)
    if (index > -1) {
      //myLog(9, ">>>> MQTT item found:"); myLog(9, tmpMsg);
      // Parse the JSON message
      DeserializationError error = deserializeJson(MQTTvaluestring, message);
      // Check for parsing errors
      if (error) {
        myLog(9, "deserializeJson() failed: ", error.f_str());
        return;
      }
      // Access the "value" field
      float JSONvalue = MQTTvaluestring["value"];
      myVictronMQTT[j].TheValue = JSONvalue;
      //myLog(9, tmpMsg, " ", "✅ JSON value=", JSONvalue);

      // Update into the Display data, but only if we need it - we use modbus as preference
        /*
        17:47:45.143 -> system/0/Dc/Battery/Current=-9.10
        17:47:45.143 -> system/0/Dc/Battery/Power=-112.86
        17:47:45.143 -> system/0/Dc/Battery/Soc=-123456792.00
        17:47:45.143 -> system/0/Dc/Battery/TimeToGo=60180.00
        17:47:45.143 -> system/0/Dc/Battery/Voltage=12.54
        17:47:45.143 -> battery/278/Dc/0/Current=-9.00
        17:47:45.143 -> battery/278/Dc/0/Power=-112.86
        17:47:45.143 -> battery/278/Dc/0/Voltage=12.54
        17:47:45.143 -> battery/278/Dc/1/Voltage=-123456792.00
        17:47:45.143 -> battery/278/TimeToGo=60180.00
        17:47:45.186 -> battery/278/Dc/0/Power=-112.86
        17:47:45.186 -> battery/278/Dc/0/Current=-9.00
        */      
      //battery/278/Dc/0/Power
      if (myVictronMQTT[j].topic == "battery/278/Dc/0/Power") {
        UpdateDisplayTable("Battery0 Power (W)", JSONvalue, "Q");
      } else {
        if (myVictronMQTT[j].topic == "battery/278/Dc/0/Current") {
          UpdateDisplayTable("Battery0 Current (A)", JSONvalue, "Q");
        } else {
          if (myVictronMQTT[j].topic == "system/0/Dc/Battery/TimeToGo") {
            UpdateDisplayTable("Battery Time to Go (System)", JSONvalue/3600, "Q"); // TTG is in seconds
          } else {
            if (myVictronMQTT[j].topic == "battery/278/TimeToGo") {
              UpdateDisplayTable("Battery Time to Go (Batt)", JSONvalue/3600, "Q");
            } else {
              if (myVictronMQTT[j].topic == "system/0/Dc/Battery/Power") {
                UpdateDisplayTable("Battery Power (W)", JSONvalue, "Q");
              } else {
                if (myVictronMQTT[j].topic == "system/0/Dc/System/Current") { 
                  UpdateDisplayTable("DC Current (A)", JSONvalue, "Q");
                  //myLog(9, "DC-Current");
                } else { 
                  if (myVictronMQTT[j].topic == "battery/278/Dc/1/Voltage") {
                    //myLog(9, "----------------> ", myVictronMQTT[j].topic), JSONvalue);
                    UpdateDisplayTable("Battery1 Voltage (V)", JSONvalue, "Q");
                  } else { 
                    if (myVictronMQTT[j].topic == "system/0/Dc/System/Power") {
                      //myLog(9, "----------------> ", myVictronMQTT[j].topic, JSONvalue);
                      UpdateDisplayTable("DC Power (W)", JSONvalue, "Q");
                    } else { 
                      if (myVictronMQTT[j].topic == "system/0/Dc/System/Current") {
                        //myLog(9, "----------------> ", myVictronMQTT[j].topic), JSONvalue);
                        UpdateDisplayTable("DC Current (A)", JSONvalue, "Q");
                      } else { 
                        if (myVictronMQTT[j].topic == "system/0/Dc/Battery/Current") {
                          UpdateDisplayTable("Battery Current (A)", JSONvalue, "Q");
                        } else { 
                          if (myVictronMQTT[j].topic == "system/0/Dc/Battery/Voltage") {
                            //myLog(9, "----------------> ", myVictronMQTT[j].topic), JSONvalue);
                            // UpdateDisplayTable("Battery Voltage (W)", JSONvalue, "Q"); // Not using since modbus gives us this reliably
                          } else { 
                            if (myVictronMQTT[j].topic == "battery/278/Dc/1/Current") {
                              //myLog(9, "----------------> ", myVictronMQTT[j].topic), JSONvalue);
                              UpdateDisplayTable("Battery1 Current (A)", JSONvalue, "Q"); // Not using since modbus gives us this reliably
                            } else { 
                              if (myVictronMQTT[j].topic == "battery/278/Dc/0/Voltage") {
                                //myLog(9, "----------------> ", myVictronMQTT[j].topic), JSONvalue);
                                UpdateDisplayTable("Battery0 Voltage (V)", JSONvalue, "Q"); // Not using since modbus gives us this reliably
                              } else { 
                                if (myVictronMQTT[j].topic == "battery/278/Dc/1/Power") {
                                  //myLog(9, "----------------> ", myVictronMQTT[j].topic), JSONvalue);
                                  UpdateDisplayTable("Battery1 Power (W)", JSONvalue, "Q"); // Not using since modbus gives us this reliably
                                } else { 
                                  myLog(9, "Not yet covered:", myVictronMQTT[j].topic, "; value=", JSONvalue);
                                  //  Not yet covered:system/0/Dc/Battery/Soc
                                  delay(10000);
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  } 
                } 
              } 
            } 
          } 
        }       
      }
    }
    j++;
  }
}

void reconnect() {
  bool alldata = false;
  String myTopic;
  while (!MQTTclient.connected()) {
    //myLog(9, "Attempting MQTT connection...");
    if (MQTTclient.connect("ArduinoClient")) {
      //myLog(9, "connected");
      UpdateDisplayTable("MQTT", 1, "S");

      // ---- Subscribe to specific topics we cannot get via modbus registers ----
      // ---- Subscribe to ALL topics for debugging ----
      if (alldata) {
        MQTTclient.subscribe("#");
        //myLog(9, "Subscribed to all topics.");
      } else {
        String base = "N/" + String(portalId) + "/";
        int j = 0;
        while (j < numVictronMQTTtopics) {
          myTopic = base + String(myVictronMQTT[j].topic);
          //myLog(9, "Subscribing to : ", myTopic);
          MQTTclient.subscribe((myTopic).c_str());
          j++;
        }
      }
    } else {
      myLog(9, "failed, rc=", MQTTclient.state(), "; try again in 5 seconds");
      delay(5000);
    }
  }
}

// Function to connect to em-trak TCP server
void connectToEmtrak() {
  while ((!GPS_WiFI_client.connect(emtrakIP, emtrakPort)) and (EmTrack_connect_attempts < EmTrack_connect_attemptsMAX)) {
    myLog(9, "Failed to connect to em-trak TCP server, retrying in 5 seconds...");
    delay(5000);
    EmTrack_connect_attempts = EmTrack_connect_attempts + 1;
    UpdateDisplayTable("AIS", 0, "S");
  }
  if (EmTrack_connect_attempts < EmTrack_connect_attemptsMAX) {
    //myLog(9, "Connected to em-trak TCP stream!");
    UpdateDisplayTable("AIS", 1, "S");
    EmTrack_connect_attempts = 0;
  }
}


// ------------------------
// Teltonika Blue Puck BLE Parser
// ------------------------
void parseTeltonikaAdv(uint8_t *bytes, int count, const char* pName) {

  float temperature = NAN;
  float humidity = NAN;
  const char* pNameCopyT;
  const char* pNameCopyH;
  char myNameT[100] = "";
  char myNameH[100] = "";

  myLog(10, "Parsing Teltonika for ", pName);
  //myLog(9, "1___pName=", pName); 
  strcpy(myNameT, pName);
  //myLog(9, "2___pName=", pName); 
  strcpy(myNameH, pName);
  //myLog(9, "3___pName=", pName); 

  for (int i = 0; i < count;) {
    uint8_t len = bytes[i];
    if (len == 0) break;
    uint8_t type = bytes[i + 1];

    if (type == 0x16 && len >= 3) {   // Service Data
      uint16_t uuid = bytes[i + 2] | (bytes[i + 3] << 8);

      if (uuid == 0x2A6E) {  // Temperature
        //myLog(9, "temp flag found, len=", len);
        if (len >= 5) {
          int16_t raw = bytes[i + 4] | (bytes[i + 5] << 8);
          temperature = raw / 100.0;
          //myLog(9, ">>>>>>>>>>>>>>=6 Temperature=", temperature);
        }
      }
      else if (uuid == 0x2A6F) {  // Humidity
        //myLog(9, "hum flag found, len=", len);
        if (len == 4) {  // 1 byte
          uint8_t raw = bytes[i + 4];
          humidity = raw * 1.0;
          //myLog(9, ">>>>>>>>>>>>>>=4 Humidity=", humidity);
        } else if (len >= 6) {  // 2 bytes
          uint16_t raw = bytes[i + 4] | (bytes[i + 5] << 8);
          humidity = raw / 100.0;
          //myLog(9, ">>>>>>>>>>>>>>=6 Humidity=", humidity);
        }
      }
    }

    i += (len + 1);
  }

  if (!isnan(temperature)) {
    //myLog(9, "Temperature: ", temperature, " °C", "; T___pName=", pName); 
    char* postfix = (char*)" Temp";
    strcat(myNameT, postfix);
    //myLog(9, "   ___myNameT=", myNameT);
    UpdateDisplayTable(myNameT, temperature, "B");
  }
  if (!isnan(humidity)) {
    //myLog(9, "Humidity: ", humidity, " %RH", "; T___pName=", pName); 
    char* postfix = (char*)" Humidity";
    strcat(myNameH, postfix);
    //myLog(9, "   ___myNameH=", myNameH);
    UpdateDisplayTable(myNameH, humidity, "B");
  }
}

void BLEstartScan() {
  if (BLE.scan()) {
    //myLog(9, "BLE scan started so Bluetooth radio is working...");
    UpdateDisplayTable("BLE", 1, "S");
  } else {
    myLog(9, "❌ Failed to start BLE scan!");
    UpdateDisplayTable("BLE", 0, "S");
  }
}

void ProcessIncomingSerial() {
  
   // Check if data is available
   myLog(10, "processing incoming serial...");
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n'); // read until newline (Enter)
    input.trim(); // remove any \r or whitespace

    if (input.length() > 0) {
      myLog(9, "You typed: ", input);
      UserInput = input;

      // Example: custom responses
      if (input.equalsIgnoreCase("hello")) {
        myLog(9, "Hi there! 👋");
      } else if (input.equalsIgnoreCase("ble on")) {
        DoBLE = true;
      } else if (input.equalsIgnoreCase("ble off")) {
        DoBLE = false;
      } else if (input.equalsIgnoreCase("show on")) {
        DoShow = true;
      } else if (input.equalsIgnoreCase("show off")) {
        DoShow = false;  
      } else if (input.equalsIgnoreCase("modbus on")) {
        DoMODBUS = true;
      } else if (input.equalsIgnoreCase("modbus off")) {
        DoMODBUS = false;
      } else if (input.equalsIgnoreCase("mqtt on")) {
        DoMQTT = true;
      } else if (input.equalsIgnoreCase("mqtt off")) {
        DoMQTT = false;          
      } else if (input.equalsIgnoreCase("gps on")) {
        DoGPS = true;
      } else if (input.equalsIgnoreCase("gps off")) {
        DoGPS = false;    
      } 
      else if (input.equalsIgnoreCase("help")) {
          myLog(9, "Available commands :");
          myLog(9, "   help");
          myLog(9, "   cls");
          myLog(9, "   ble on");
          myLog(9, "   ble off");
          myLog(9, "   show on");
          myLog(9, "   show off");
          myLog(9, "   modbus on");
          myLog(9, "   modbus off");
          myLog(9, "   mqtt on");
          myLog(9, "   mqtt off");
          myLog(9, "   gps on");
          myLog(9, "   gps off");          
          myLog(9, "   1 - List all files");
          myLog(9, "   2 - Delete files older than 2 weeks");
          myLog(9, "   3 - Write test entry to log");
          myLog(9, "   4 - Show disk info");
          myLog(9, "   5 - Set RTC time");
          myLog(9, "   6 - Show current time");
          myLog(9, "   7 - Set log file prefix");
          myLog(9, "   8 - Force rotate log file");
          myLog(9, "   9 - Delete oldest file");          
      }         
      else if (input.equalsIgnoreCase("cls")) { 
        for (int i = 1; i < 10; i++) {
          myLog(9, "                 ");
        }
      }  
      else if (input.equalsIgnoreCase("1")) {
            if (sdInitialized) listAllFiles();
            else Serial.println("SD card not available!\n");
      } 
      else if (input.equalsIgnoreCase("2")) {
            if (sdInitialized) deleteOldFiles();
            else Serial.println("SD card not available!\n");
      } 
      else if (input.equalsIgnoreCase("3")) {
            if (sdInitialized) writeToLog("Manual log entry from menu");
            else Serial.println("SD card not available!\n");
      } 
      else if (input.equalsIgnoreCase("4")) {
            if (sdInitialized) showDiskInfo();
            else Serial.println("SD card not available!\n");
      }
      else if (input.equalsIgnoreCase("5")) {
            setRTCTime();
      } 
      else if (input.equalsIgnoreCase("6")) {
            showCurrentTime();
      } 
      else if (input.equalsIgnoreCase("7")) {
            if (sdInitialized) setLogPrefix();
            else Serial.println("SD card not available!\n");
      } 
      else if (input.equalsIgnoreCase("9")) {
            if (sdInitialized) deleteOldestFile();
            else Serial.println("SD card not available!\n");
      } 
      else {
        myLog(9, "Unknown command 🤔");
      }
    }
  }
}

void SetFakeData() {
  UpdateDisplayTable("Active input source",         1		    , "F"); // 0=Unknown;1=Grid;2=Generator;3=Shore power;240=Not connected
  UpdateDisplayTable("Grid (W)",                    45		  , "F");
  UpdateDisplayTable("AC Loads (W)",           		  26      , "F");
  UpdateDisplayTable("Battery SOC (%)",             65		  , "F");
  UpdateDisplayTable("Battery0 Voltage (V)",        12.4	  , "F");
  UpdateDisplayTable("Battery0 Power (W)",          23		  , "F");
  UpdateDisplayTable("Battery0 Current (A)",        2.97234	, "F");
  UpdateDisplayTable("Battery Time to Go (System)", 47.87		  , "F"); // is 0 als we aan grid hangen
  UpdateDisplayTable("Battery Time to Go (Batt)",   -123456792.000000		  , "F");
  UpdateDisplayTable("DC Power (W)",                -123456792.000000		  , "F");
  UpdateDisplayTable("DC Current (A)",              -123456792.000000		  , "F");
  UpdateDisplayTable("PV Power (W)",                89		  , "F");
  UpdateDisplayTable("Starter battery (V)",         26.37	  , "F");
  UpdateDisplayTable("Electronics bay (C)",         21.1	  , "F");
  UpdateDisplayTable("Engine room (C)",             25.719999	  , "F");
  UpdateDisplayTable("Lat",                         52.171959	, "F");
  UpdateDisplayTable("Lng",                         4.515833	, "F");
  UpdateDisplayTable("Speed",                       8.45	, "F");
  UpdateDisplayTable("Course",                      271		, "F");
  UpdateDisplayTable("Master Bedroom Temp",         20.5	, "F");
  UpdateDisplayTable("Master Bedroom Humidity",     71		, "F");
  UpdateDisplayTable("Engine Room Temp",            19.6	, "F");
  UpdateDisplayTable("Engine Room Humidity",        78		, "F");
  UpdateDisplayTable("Watertank SB Temp",           18.5	, "F");
  UpdateDisplayTable("Watertank SB Humidity",       44		, "F");
  UpdateDisplayTable("Watertank PS Temp",           33.9	, "F");
  UpdateDisplayTable("Watertank PS Humidity",       87.4	, "F");
  UpdateDisplayTable("Toilet Temp",                 12.56	, "F");
  UpdateDisplayTable("Toilet Humidity",             88		, "F");
  UpdateDisplayTable("P RHT 900F0A Temp",           23.6	, "F");
  UpdateDisplayTable("P RHT 900F0A Humidity",       66		, "F");
  UpdateDisplayTable("Voorin Temp",                 34.6	, "F");
  UpdateDisplayTable("Voorin Humidity",             78.6	, "F");
  UpdateDisplayTable("Kajuit Temp",                 21.5	, "F");
  UpdateDisplayTable("Kajuit Humidity",             97.2	, "F");
  UpdateDisplayTable("Buitenkraan Temp",            -123456792.000000	, "F");
  UpdateDisplayTable("Buitenkraan Humidity",        -123456792.000000	, "F");
  UpdateDisplayTable("WiFi",                        1		, "F");
  UpdateDisplayTable("AIS",                         1		, "F");
  UpdateDisplayTable("MQTT",                        0		, "F");
  UpdateDisplayTable("MODBUS",                      1		, "F");
  UpdateDisplayTable("BLE",                         1		, "F");
}
// ==================== MATRIX DISPLAY FUNCTIONS ====================

void displayIcon(const uint8_t icon[8]) {
  if (!matrixInitialized) return;
  matrix.clear();
  for (int row = 0; row < 8; row++) {
    matrix.setRow(0, row, icon[row]);
  }
}

void displayStartupAnimation() {
  if (!matrixInitialized) return;
  
  for (int i = 0; i < 8; i++) {
    matrix.setRow(0, i, 0xFF);
    delay(50);
    matrix.setRow(0, i, 0x00);
  }
  
  for (int i = 0; i < 3; i++) {
    for (int row = 0; row < 8; row++) {
      matrix.setRow(0, row, 0xFF);
    }
    delay(100);
    matrix.clear();
    delay(100);
  }
}

void displayError() {
  if (!matrixInitialized) return;
  displayIcon(ICON_ERROR);
}

void updateMatrixDisplay() {
  if (!matrixInitialized) return;
  
  static int displayMode = 0;
  
  switch (displayMode) {
    case 0:
      if (sdInitialized) {
        displayIcon(ICON_SD_OK);
      } else {
        displayIcon(ICON_SD_MISSING);
      }
      break;
    case 1:
      displayIcon(ICON_HEART);
      break;
    case 2:
      displayTimeOnMatrix();
      break;
  }
  
  displayMode = (displayMode + 1) % 3;
}



// ==================== SD CARD FUNCTIONS ====================

void checkCardPresence() {
  // Card detection not used - we rely on SD initialization success
  // This function kept for compatibility
  cardPresent = sdInitialized;
}

void initializeSD() {
  Serial.println("Initializing SD card...");
  Serial.println("Using custom SPI pins:");
  Serial.printf("  CS:   GPIO %d\n", SD_CS_PIN);
  Serial.printf("  MOSI: GPIO %d\n", SD_MOSI_PIN);
  Serial.printf("  MISO: GPIO %d\n", SD_MISO_PIN);
  Serial.printf("  SCK:  GPIO %d\n", SD_SCK_PIN);
  
  Serial.print("Attempting SD.begin()");
  Serial.flush();
  
  // Try SD.begin with lower 4MHz clock speed for reliability
  bool success = false;
  for (int attempt = 0; attempt < 3 && !success; attempt++) {
    Serial.print(".");
    Serial.flush();
    success = SD.begin(SD_CS_PIN, spiSD, 4000000);
    if (!success) delay(500);
  }
  Serial.println();
  
  if (!success) {
    Serial.println(" FAILED!");
    Serial.println("\nTroubleshooting steps:");
    Serial.println("1. Check SD card is inserted");
    Serial.println("2. Verify wiring matches pin definitions");
    Serial.println("3. Ensure card is formatted as FAT32");
    Serial.println("4. Confirm 3.3V power (NOT 5V!)");
    Serial.println("5. Try different SD card");
    Serial.println("6. Check solder connections");
    Serial.flush();
    sdInitialized = false;
    displayError();
    return;
  }
  
  Serial.println(" SUCCESS!");
  displayIcon(ICON_CHECKMARK);
  delay(500);
  
  // Check SD card type
  uint8_t cardType = SD.cardType();
  if (cardType == CARD_NONE) {
    Serial.println("No SD card detected by controller");
    sdInitialized = false;
    displayError();
    return;
  }
  
  Serial.print("SD Card Type: ");
  switch(cardType) {
    case CARD_MMC:  Serial.println("MMC"); break;
    case CARD_SD:   Serial.println("SDSC"); break;
    case CARD_SDHC: Serial.println("SDHC"); break;
    default:        Serial.println("UNKNOWN"); break;
  }
  
  uint64_t cardSize = SD.cardSize() / (1024 * 1024);
  Serial.print("SD Card Size: ");
  Serial.print(cardSize);
  Serial.println(" MB");
  
  uint64_t totalBytes = SD.totalBytes();
  uint64_t usedBytes = SD.usedBytes();
  Serial.print("Total Space: ");
  Serial.print(totalBytes / (1024 * 1024));
  Serial.println(" MB");
  Serial.print("Used Space: ");
  Serial.print(usedBytes / (1024 * 1024));
  Serial.println(" MB\n");
  
  sdInitialized = true;
  
  Serial.println("\n=== SD Card Ready ===");
  Serial.println("Note: Log file will be created on first write");
  Serial.println("Use menu option 3 to test writing\n");
}

void openOrCreateLogFile() {
  DateTime now = rtc.now();
  
  char filename[50];
  sprintf(filename, "/%s_%04d%02d%02d_%02d%02d%02d%s",
          logPrefix.c_str(),
          now.year(), now.month(), now.day(),
          now.hour(), now.minute(), now.second(),
          logExtension.c_str());
  
  currentLogFilename = String(filename);
  
  Serial.print("Opening log file: ");
  Serial.println(currentLogFilename);
  
  // FIXED: Ensure file is opened in append mode
  currentLogFile = SD.open(currentLogFilename, FILE_APPEND);
  
  if (!currentLogFile) {
    Serial.println("ERROR: Could not open log file!");
    Serial.println("Attempting to create new file...");
    
    // Try FILE_WRITE mode
    currentLogFile = SD.open(currentLogFilename, FILE_WRITE);
    
    if (!currentLogFile) {
      Serial.println("CRITICAL: Cannot create log file!");
      displayError();
      return;
    }
  }
  
  // Write header
  currentLogFile.println("=== Log Started ===");
  currentLogFile.print("Date/Time: ");
  currentLogFile.print(now.year());
  currentLogFile.print('/');
  if (now.month() < 10) currentLogFile.print('0');
  currentLogFile.print(now.month());
  currentLogFile.print('/');
  if (now.day() < 10) currentLogFile.print('0');
  currentLogFile.print(now.day());
  currentLogFile.print(" ");
  if (now.hour() < 10) currentLogFile.print('0');
  currentLogFile.print(now.hour());
  currentLogFile.print(':');
  if (now.minute() < 10) currentLogFile.print('0');
  currentLogFile.print(now.minute());
  currentLogFile.print(':');
  if (now.second() < 10) currentLogFile.print('0');
  currentLogFile.print(now.second());
  currentLogFile.println();
  currentLogFile.println("==================\n");
  
  // CRITICAL: Always flush after writes
  currentLogFile.flush();
  
  Serial.print("Log file opened successfully! Size: ");
  Serial.print(currentLogFile.size());
  Serial.println(" bytes\n");
}

void writeToLog(String message) {
  if (!sdInitialized) {
    Serial.println("ERROR: SD not initialized!");
    return;
  }
  
  // Build filename if we don't have one yet
  if (currentLogFilename == "") {
    DateTime now = rtc.now();
    char filename[50];
    sprintf(filename, "/%s_%04d%02d%02d_%02d%02d%02d%s",
            logPrefix.c_str(),
            now.year(), now.month(), now.day(),
            now.hour(), now.minute(), now.second(),
            logExtension.c_str());
    currentLogFilename = String(filename);
    Serial.print("Creating log file: ");
    Serial.println(currentLogFilename);
  }
  
  DateTime now = rtc.now();
  
  // Build timestamp
  char timestamp[32];
  sprintf(timestamp, "[%04d/%02d/%02d %02d:%02d:%02d] ",
          now.year(), now.month(), now.day(),
          now.hour(), now.minute(), now.second());
  
  // SIMPLE APPROACH: Open file, write, close (like the working test)
  File logFile = SD.open(currentLogFilename, FILE_APPEND);
  
  if (!logFile) {
    Serial.println("ERROR: Could not open log file for writing!");
    Serial.println("Trying FILE_WRITE mode...");
    
    logFile = SD.open(currentLogFilename, FILE_WRITE);
    if (!logFile) {
      Serial.println("CRITICAL: Cannot open/create log file!");
      displayError();
      return;
    }
  }
  
  // Write to file
  logFile.print(timestamp);
  logFile.println(message);
  logFile.close();  // Close immediately like the test sketch
  
  Serial.print("✓ Logged: ");
  Serial.println(message);
  
  // Brief confirmation on matrix
  displayIcon(ICON_CHECKMARK);
  delay(200);
}

void manageLogs() {
  if (!sdInitialized) return;
  
  // Check current log file size if it exists
  if (currentLogFilename != "" && SD.exists(currentLogFilename)) {
    File checkFile = SD.open(currentLogFilename);
    if (checkFile) {
      unsigned long fileSize = checkFile.size();
      checkFile.close();
      
      if (fileSize >= MAX_LOG_SIZE) {
        Serial.println("\n*** Log file size limit reached ***");
        Serial.print("Current size: ");
        Serial.print(fileSize);
        Serial.println(" bytes");
        rotateLogFile();
      }
    }
  }
  
  checkDiskUsage();
  deleteOldFiles();
}

void rotateLogFile() {
  Serial.println("Rotating log file...");
  
  // Simply reset the filename - next write will create new file
  currentLogFilename = "";
  
  Serial.println("Log file rotated - new file will be created on next write\n");
}

void forceRotateLog() {
  Serial.println("\n*** Forcing log rotation ***\n");
  rotateLogFile();
}

bool deleteOldestFile() {
  File root = SD.open("/");
  if (!root) return false;
  
  String oldestFilename = "";
  time_t oldestTime = 0xFFFFFFFF;
  
  File entry = root.openNextFile();
  while (entry) {
    if (!entry.isDirectory()) {
      String filename = String(entry.name());
      
      if (filename != currentLogFilename) {
        time_t fileTime = entry.getLastWrite();
        
        if (oldestTime == 0xFFFFFFFF || fileTime < oldestTime) {
          oldestTime = fileTime;
          oldestFilename = filename;
        }
      }
    }
    entry.close();
    entry = root.openNextFile();
  }
  root.close();
  
  if (oldestFilename.length() > 0) {
    String path = oldestFilename.startsWith("/") ? oldestFilename : "/" + oldestFilename;
    myLog(9, "Deleting oldest file: ", path);
    return SD.remove(path);
  }
  
  return false;
}

void deleteOldFiles() {

  DateTime now = rtc.now();
  DateTime cutoffDate = now - TimeSpan(RETENTION_DAYS, 0, 0, 0);
  time_t cutoffTimestamp = cutoffDate.unixtime();
  
  myLog(9, "RETENTION_DAYS=", RETENTION_DAYS, "; cutoffTimestamp=", cutoffTimestamp);

  File root = SD.open("/");
  if (!root) return;
  
  int deletedCount = 0;
  
  File entry = root.openNextFile();
  while (entry) {
    if (!entry.isDirectory()) {
      String filename = String(entry.name());
      String path = filename.startsWith("/") ? filename : "/" + filename;
      
      if (filename != currentLogFilename) {
        time_t fileTime = entry.getLastWrite();
        
        if (fileTime < cutoffTimestamp) {
          myLog(9, "Deleting old file: ", path);
          entry.close();
          
          if (SD.remove(path)) {
            deletedCount++;
          }
        } else {
          entry.close();
        }
      } else {
        entry.close();
      }
    } else {
      entry.close();
    }
    
    entry = root.openNextFile();
  }
  
  root.close();
  
  if (deletedCount > 0) {
    Serial.print("Deleted ");
    Serial.print(deletedCount);
    Serial.println(" old files");
  }
}



void showDiskInfo() {
  Serial.println("\n========== DISK INFO ==========");
  
  uint64_t cardSize = SD.cardSize() / (1024 * 1024);
  uint64_t usedBytes = SD.usedBytes();
  uint64_t totalBytes = SD.totalBytes();
  
  Serial.print("Card Size:        ");
  Serial.print(cardSize);
  Serial.println(" MB");
  
  Serial.print("Total Space:      ");
  Serial.print(totalBytes / (1024 * 1024));
  Serial.println(" MB");
  
  Serial.print("Used Space:       ");
  Serial.print(usedBytes / (1024 * 1024));
  Serial.println(" MB");
  
  Serial.print("Free Space:       ");
  Serial.print((totalBytes - usedBytes) / (1024 * 1024));
  Serial.println(" MB");
  
  Serial.print("Usage:            ");
  Serial.print((usedBytes * 100) / totalBytes);
  Serial.println("%");
  
  Serial.print("Current log:      ");
  Serial.println(currentLogFilename != "" ? currentLogFilename : "None");
  
  Serial.print("Current log size: ");
  if (currentLogFilename != "" && SD.exists(currentLogFilename)) {
    File checkFile = SD.open(currentLogFilename);
    if (checkFile) {
      Serial.print(checkFile.size());
      Serial.println(" bytes");
      checkFile.close();
    } else {
      Serial.println("N/A");
    }
  } else {
    Serial.println("N/A");
  }
  
  Serial.print("Max log size:     ");
  Serial.print(MAX_LOG_SIZE);
  Serial.println(" bytes");
  Serial.println("===============================\n");
}

void displayChar(char c) {
  // Very simple character display - you can enhance this
  // For now, just show a pattern for common chars
  matrix.clear();
  
  if (c >= '0' && c <= '9') {
    // Display digit
    int digit = c - '0';
    for (int row = 0; row < 8; row++) {
      matrix.setRow(0, row, getDigitPattern(digit, row));
    }
  } else {
    // For other characters, show a generic pattern
    for (int i = 0; i < 8; i++) {
      matrix.setColumn(0, i, 1 << i);
    }
  }
}

uint8_t getDigitPattern(int digit, int row) {
  // Simple 8x8 patterns for digits 0-9
  const uint8_t digits[10][8] = {
    // 0
    {0b00111100, 0b01100110, 0b01100110, 0b01100110, 0b01100110, 0b01100110, 0b00111100, 0b00000000},
    // 1
    {0b00011000, 0b00111000, 0b00011000, 0b00011000, 0b00011000, 0b00011000, 0b01111110, 0b00000000},
    // 2
    {0b00111100, 0b01100110, 0b00000110, 0b00001100, 0b00110000, 0b01100000, 0b01111110, 0b00000000},
    // 3
    {0b00111100, 0b01100110, 0b00000110, 0b00011100, 0b00000110, 0b01100110, 0b00111100, 0b00000000},
    // 4
    {0b00001100, 0b00011100, 0b00111100, 0b01101100, 0b01111110, 0b00001100, 0b00001100, 0b00000000},
    // 5
    {0b01111110, 0b01100000, 0b01111100, 0b00000110, 0b00000110, 0b01100110, 0b00111100, 0b00000000},
    // 6
    {0b00111100, 0b01100000, 0b01111100, 0b01100110, 0b01100110, 0b01100110, 0b00111100, 0b00000000},
    // 7
    {0b01111110, 0b00000110, 0b00001100, 0b00011000, 0b00110000, 0b00110000, 0b00110000, 0b00000000},
    // 8
    {0b00111100, 0b01100110, 0b01100110, 0b00111100, 0b01100110, 0b01100110, 0b00111100, 0b00000000},
    // 9
    {0b00111100, 0b01100110, 0b01100110, 0b00111110, 0b00000110, 0b00001100, 0b00111000, 0b00000000}
  };
  
  return digits[digit][row];
}

void displayTimeOnMatrix() {
  if (!matrixInitialized) return;
  
  DateTime now = rtc.now();
  int hour = now.hour();
  int minute = now.minute();
  
  matrix.clear();
  
  for (int i = 0; i < min(hour, 8); i++) {
    matrix.setColumn(0, i, 0xFF >> (8 - (hour - i * 8)));
  }
  
  int minBars = (minute * 32) / 60;
  for (int i = 4; i < 8; i++) {
    int colIndex = (i - 4) * 8;
    if (minBars > colIndex) {
      matrix.setColumn(0, i, 0xFF >> max(0, 8 - (minBars - colIndex)));
    }
  }
}

void setMatrixBrightness() {
  Serial.println("\n========== SET MATRIX BRIGHTNESS ==========");
  Serial.println("Enter brightness (0-15):");
  Serial.println("Waiting for input (10s timeout)...");
  
  while (Serial.available()) Serial.read();
  
  String input = "";
  unsigned long timeout = millis() + 10000;
  
  while (millis() < timeout) {
    if (Serial.available()) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        if (input.length() > 0) break;
      } else {
        input += c;
      }
    }
  }
  
  if (input.length() > 0) {
    int brightness = input.toInt();
    if (brightness >= 0 && brightness <= 15) {
      matrix.control(MD_MAX72XX::INTENSITY, brightness);
      Serial.print("Brightness set to: ");
      Serial.println(brightness);
      
      // Flash to show change
      displayIcon(ICON_CHECKMARK);
      delay(500);
    } else {
      Serial.println("Invalid brightness (must be 0-15)");
    }
  } else {
    Serial.println("Timeout or no input\n");
  }
}

void testMatrixDisplay() {
  Serial.println("\n========== TESTING MATRIX ==========");
  
  Serial.println("Test 1: All LEDs ON");
  for (int row = 0; row < 8; row++) {
    matrix.setRow(0, row, 0xFF);
  }
  delay(1000);
  
  Serial.println("Test 2: All LEDs OFF");
  matrix.clear();
  delay(500);
  
  Serial.println("Test 3: Scanning rows");
  for (int row = 0; row < 8; row++) {
    matrix.setRow(0, row, 0xFF);
    delay(100);
    matrix.setRow(0, row, 0x00);
  }
  
  Serial.println("Test 4: Scanning columns");
  for (int col = 0; col < 8; col++) {
    matrix.setColumn(0, col, 0xFF);
    delay(100);
    matrix.setColumn(0, col, 0x00);
  }
  
  Serial.println("Test 5: Show all icons");
  displayIcon(ICON_SD_OK);
  delay(1000);
  displayIcon(ICON_HEART);
  delay(1000);
  displayIcon(ICON_CHECKMARK);
  delay(1000);
  
  Serial.println("Test 6: Display digits 0-9");
  for (int i = 0; i < 10; i++) {
    displayChar('0' + i);
    delay(500);
  }
  
  Serial.println("Matrix test complete!\n");
  matrix.clear();
}

///////////////////////// END OF MATRIX ////////////////////////


void setup() {

  Wire.begin(rtc_I2C_SDA, rtc_I2C_SCL); // for the clock
  //Wire.setClock(100000);  // 20251101 Reduce to 100kHz for stability

  // Let's go. First, initialise default serial (to/from IDE)
  int MaxSerialAttempts = 100;
  int CurrentSerialAttempt = 0;
  Serial.begin(115200);
  delay(2000); // Give serial time to initialize
  while ((!Serial) and (CurrentSerialAttempt <= MaxSerialAttempts))  { // while (!Serial); the unit needs to run on its own without a laptop so without serial connectivity
    delay(10);   // wait for CDC
    CurrentSerialAttempt++;
  }
  delay(1000); // allow USB to settle in

  // Setup the clock
  // You can use the default I2C pins for the ESP32-S3, which are GPIO 8 (SDA) and GPIO 9 (SCL) in the Arduino IDE by default, or you can configure almost any other available GPIO pins. 
    if (!rtc.begin()) { // initialize DS3231
    Serial.println("❌ DS3231 not found!");
  } else {
      Serial.println("✅ DS3231 RTC clock found");

      // pushing the rtc clock time into the ESP32 board so that file timestamps are checked correctly
      DateTime rtcNow = rtc.now();
      struct timeval tv;
      tv.tv_sec = rtcNow.unixtime();
      tv.tv_usec = 0;
      settimeofday(&tv, NULL);      
  }
  delay(2000); // allow clock to settle
  // Check for serial input
  // Check for serial input
  if (Serial.available() > 0) { // get time from laptop clock
    Serial.println("Serial is available");
    String input = Serial.readStringUntil('\n');
    input.trim();

    // Only process commands starting with SET
    if (input.startsWith("SET ")) {
      String datetime = input.substring(4); // remove 'SET '
      // Parse the datetime string
      int year = datetime.substring(0,4).toInt();
      int month = datetime.substring(5,7).toInt();
      int day = datetime.substring(8,10).toInt();
      int hour = datetime.substring(11,13).toInt();
      int minute = datetime.substring(14,16).toInt();
      int second = datetime.substring(17,19).toInt();

      rtc.adjust(DateTime(year, month, day, hour, minute, second));
      Serial.println("⏰ RTC updated successfully!");
    } else {
      Serial.println("Unknown command. Format: SET YYYY-MM-DD HH:MM:SS");
    }
  } else {
    Serial.println("Serial is not available");
  }

  Serial.println("====================================");
  Serial.println("ESP32-S3 SD Logger with Displays");
  Serial.println("v6 - Dual SPI Buses");
  Serial.println("====================================");
  
  // Set all CS pins HIGH (deselected) BEFORE initializing SPI
  Serial.println("setting CS pins high");
  pinMode(SD_CS_PIN, OUTPUT);
  pinMode(MAX7219_CS_PIN, OUTPUT);
  pinMode(EINK_CS_PIN, OUTPUT);
  digitalWrite(SD_CS_PIN, HIGH);
  digitalWrite(MAX7219_CS_PIN, HIGH);
  digitalWrite(EINK_CS_PIN, HIGH);
  Serial.println("CS pins configured (all deselected)");
  
  // Initialize FSPI for SD card
  Serial.println("Initialize FSPI for SD card");
  spiSD.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN);
  // Initialize SD card
  Serial.println("============ SD Card Initialization =============");
  initializeSD();  
  Serial.println("\nFSPI bus initialized (SD card):");
  Serial.printf("  MOSI: GPIO %d\n", SD_MOSI_PIN);
  Serial.printf("  MISO: GPIO %d\n", SD_MISO_PIN);
  Serial.printf("  SCK:  GPIO %d\n", SD_SCK_PIN);
  Serial.printf("  CS:   GPIO %d\n", SD_CS_PIN);
  Serial.println("next : opening the log file...");
  openOrCreateLogFile();
  
  // Initialize HSPI for MAX7219
  Serial.println("Initialize HSPI for MAX7219");
  spiMatrix.begin(MAX7219_SCK_PIN, MAX7219_MISO_PIN, MAX7219_MOSI_PIN);
  Serial.println("\nHSPI bus initialized (MAX7219):");
  Serial.printf("  MOSI (DIN): GPIO %d\n", MAX7219_MOSI_PIN);
  Serial.printf("  SCK (CLK):  GPIO %d\n", MAX7219_SCK_PIN);
  Serial.printf("  CS:         GPIO %d\n\n", MAX7219_CS_PIN);
  
  // Initialize MAX7219 LED Matrix
  Serial.println("Initializing MAX7219...");
  matrix.begin();
  matrix.control(MD_MAX72XX::INTENSITY, 2);
  matrix.clear();
  matrixInitialized = true;
  Serial.println("MAX7219 OK\n");
  displayStartupAnimation();

  // Setup pins for E-ink
  Serial.println("Setup pins for E-ink");
  pinMode(CARD_DETECT_PIN, INPUT_PULLUP);
  pinMode(EINK_CS_PIN, OUTPUT);
  pinMode(EINK_DC_PIN, OUTPUT);
  pinMode(EINK_RST_PIN, OUTPUT);
  pinMode(EINK_BUSY_PIN, INPUT);
  digitalWrite(EINK_CS_PIN, HIGH);
  Serial.println("E-ink pins configured\n");
  
  Serial.println("before showMenu");
  showMenu();
  Serial.println("Before displayIcon");
  displayIcon(ICON_CHECKMARK);

  delay(1000);
  myLog(9, "========================================");
  myLog(9, TimeSource);


  ///////////////// TEST RAM 
  myLog(9, "=== ESP32-S3 PSRAM Test ===");
  char sDebugText[255] = "";
  // Total PSRAM
  size_t psram_size = ESP.getPsramSize();
  sprintf(sDebugText,"PSRAM Size: %u bytes (%.2f MB)", psram_size, psram_size / 1024.0 / 1024.0);
  myLog(9, sDebugText);
  // Heap info
  sprintf(sDebugText,"Free internal heap: %u bytes", ESP.getFreeHeap());
  myLog(9, sDebugText);
  sprintf(sDebugText,"Free PSRAM heap: %u bytes", ESP.getFreePsram());
  myLog(9, sDebugText);
  myLog(9,ESP.getPsramSize() / (1024 * 1024), "MB");
  // Try allocating memory in PSRAM
  const size_t test_size = 1024 * 1024; // 1 MB
  uint8_t* buffer = (uint8_t*)ps_malloc(test_size);
  if (buffer) {
    sprintf(sDebugText,"Successfully allocated %u bytes in PSRAM", test_size);
    myLog(9, sDebugText);
    free(buffer);
  } else {
    sprintf(sDebugText,"Failed to allocate %u bytes in PSRAM", test_size);
    myLog(9, sDebugText);
  }
  myLog(9, "PSRAM test done!");
  /////////////////////////// END OF RAM TESTING
   
  // Work with fake data during display changes at home?
  if (DoFake) { 
    DoWiFi = true;
    DoBLE = false;
    DoMODBUS = false;
    DoMQTT = false;
    DoGPS = false;
    DoShow = true;    
    SetFakeData();
  }  


  // Set general status. We use the bit on-board matrix panel to communicate status for when the Arduino is mounted in the boat without a serial connection to the laptop.
  // We display big number 0-9 as "master status", and individual pixels in the right most column. Pixel On=service working. No pixel=no service
  // Pixels in column 12 enabled mean : row1=wifi, row2=MQTT

  // WiFi? // WARNING the ESP32 board can only use SSIDs of 2.4ghz!!!
  if (DoWiFi) {
    myLog(100, "Connecting to WiFi : ");
    myLog(-100, "SSID=", ssid);
    myLog(-100, "; Connection trying to establish...");
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    int retries = 0;
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      myLog(-100, ".");
      retries++;
      if (retries > 40) {
        myLog(-1," ");
        myLog(1, "WiFi failed!!!!");
        myLog(1, "-------- failed (Wifi)!");
        UpdateDisplayTable("WiFi", 0, "S");        
        //ESP.restart();
      }
    }    
    if (WiFi.status() != WL_CONNECTED) { // beetje overbodig maar ja
      myLog(1, "Wifi is NOT connected to ", ssid);
      UpdateDisplayTable("WiFi", 0, "S");      
    } else {
      myLog(-9, "Wifi is connected to ", WiFi.SSID());
      UpdateDisplayTable("WiFi", 1, "S");
    }
  }
  //wifi found)

  if (DoMQTT) {
    myLog(9, "MQTT to Cerbo initialized...");
    MQTTclient.setServer(mqtt_server, mqtt_port); //   client.setServer(mqtt_server, mqtt_port);
    MQTTclient.setKeepAlive(9999999);
    MQTTclient.setCallback(callback);
    String pokeTopic = "R/" + String(portalId) + "/system/0/Serial";
    MQTTclient.publish(pokeTopic.c_str(), "");  // poke the MQTT so it starts sending data
    Serial.print("Poked by sending : "); myLog(9, pokeTopic);
  }

/*
  if (DoBLE) { // this code causes a crash
    // Ensure any leftover BLE activity is stopped
    myLog(9, "Stopping any leftover BLE activity...");
    BLE.stopScan();
    BLE.end();  
    delay(500); // small pause to allow cleanup    
    // Initializing bluetooth
    if (!BLE.begin()) { // Re-initialize
      myLog(9, "Starting BLE failed!");
    } else {
      myLog(9, "BLE Central - Scanning for devices...");
      BLEstartScan();
    }
  }
*/

if (DoBLE) {
  static bool bleInitialized = false;

  if (bleInitialized) {
    myLog(9, "Stopping any leftover BLE activity...");
    BLE.stopScan();
    BLE.end();
    delay(500);
  }

  if (!BLE.begin()) {
    myLog(9, "Starting BLE failed!");
  } else {
    bleInitialized = true;
    myLog(9, "BLE Central - Scanning for devices...");
    BLEstartScan();
  }
}
  myLog(9, "special test if the logging works");

} // end of setup

void loop() {

  // Periodic log management
  if (sdInitialized && millis() - lastLogCheck > LOG_CHECK_INTERVAL) {
    manageLogs();
    lastLogCheck = millis();
  }
  
  // Update matrix display
  if (millis() - lastMatrixUpdate > MATRIX_UPDATE_INTERVAL) {
    updateMatrixDisplay();
    lastMatrixUpdate = millis();
  }

  // To check connections once every <x> minutes
  unsigned long currentMillis = millis();

  int StatusScanIndex = 0;
  while (StatusScanIndex < numDisplayTopics) {
    myLog(10, "StatusScanIndex=", StatusScanIndex, "; ", DisplayInfo[StatusScanIndex].internalLabel, "; val=", DisplayInfo[StatusScanIndex].TheValue);
    if (DisplayInfo[StatusScanIndex].internalLabel == "WiFi") {
      myLog(10, "          wifi found");
    } else if (DisplayInfo[StatusScanIndex].internalLabel == "MQTT") {
      myLog(10, "          MQTT found");
    } else if (DisplayInfo[StatusScanIndex].internalLabel == "BLE") {
      myLog(10, "          BLE found");
    }  else if (DisplayInfo[StatusScanIndex].internalLabel == "MODBUS") {
      myLog(10, "          MODBUS found");
    } else if (DisplayInfo[StatusScanIndex].internalLabel == "AIS") {
      myLog(10, "          AIS found");
    }
    StatusScanIndex++;
  }
  //while (1); //for debug : stop after 1st loop is done

  // Getting the registry values
  if (!DoOnce) {

    // Check data entered by the user
    ProcessIncomingSerial();

    // Do connection stuff, but only once every 5 mins
    // sprintf(tmpStr,"Cur=%d; prev=%d; I=%d; EM=%d",currentMillis,previousMillis,interval,EmTrack_connect_attempts); myLog(9, tmpStr);
    if ((currentMillis - previousMillis >= interval) or (currentMillis < interval)) { // when starting to run, the currmili is less than interval

      //myLog(9, "Additional connections stuff...");

      // connecting to the Cerbo modbus
      if (DoMODBUS) {
        if (!Mclient.connected()) {
          UpdateDisplayTable("MODBUS", 0, "S");
          //Serial.print("Connecting to Cerbo GX...");
          if (!Mclient.connect(cerboHost, cerboPort)) {
            myLog(9, " Connection failed (Cerbo).");
            delay(2000);
            return;
          }
        }
        if (Mclient.connected()) {
          //myLog(9, "Connected to Cerbo MODBUS.");
          UpdateDisplayTable("MODBUS", 1, "S");
        }
      }
      
      // other data via MQTT
      //myLog(9, "Getting MQTT data...");
      if (DoMQTT) {
        if (!MQTTclient.connected()) {
          UpdateDisplayTable("MQTT", 0, "S");
          myLog(9, "MQTT not connected, reconnecting...");
          reconnect();
        } 
        if (MQTTclient.connected()) {
          //myLog(9, "MQTT is connected.");
          UpdateDisplayTable("MQTT", 1, "S");   
        }
      }

      // Em-Track AIS for GPS data : If disconnected, try to reconnect
      if (DoGPS) {
        if ((!GPS_WiFI_client.connected()) and (EmTrack_connect_attempts < EmTrack_connect_attemptsMAX)) { // often needs a re-try to be successful
          //myLog(9, "Connecting to Em-Track...");
          UpdateDisplayTable("AIS", 0, "S");
          connectToEmtrak();
        }
        if (GPS_WiFI_client.connected()) {
          //myLog(9, "Em-Track is connected.");
          UpdateDisplayTable("AIS", 1, "S");
        }
      }

      //delay(10000);

      // reset the timer
      previousMillis = currentMillis; // reset timer
    } // connecting stuff ended

    // Get the modbus register values
    if (DoMODBUS) {
      uint16_t value;
      uint16_t valRaw;
      float val;    
      for (int i = 0; i < numRegs; i++) {
      valRaw = mudbus.readHoldingRegister(regs[i].unitId, regs[i].reg, value);
        if (valRaw != 0xFFFF) {
          val = value * regs[i].scale;
          sprintf(tmpStr,"%s: %.2f", regs[i].label, val);
          UpdateDisplayTable(regs[i].label, val, "M");
        } else {
          sprintf(tmpStr,"%s: <no valid data returned (%d)>", regs[i].label, valRaw);
        }
        //myLog(9, tmpStr);
      }
    }

    // Tell MQTT to send data
    if (DoMQTT) {
      MQTTclient.loop();    
      //myLog(9, "MQTT looping.");
      // Keep MQQ alive, send keepalive message every 30 seconds
      static unsigned long lastMsg = 0;
      unsigned long now = millis();
      if (now - lastMsg > 30000) {
        lastMsg = now;
        String topic = "R/" + String(portalId) + "/system/0/Serial";
        MQTTclient.publish(topic.c_str(), "");  // Empty payload, just to poke it
        //Serial.print("Sent keepalive to: ");
        //myLog(9, topic);
      }   
    }

    if (DoGPS) {
      // Em-TRACK GPS DATA
      // Read data from em-trak TCP stream
      while (GPS_WiFI_client.available()) {
        char c = GPS_WiFI_client.read();
        if (gps.encode(c)) {
          if (gps.location.isUpdated()) {
            //Serial.print("Lat: "); myLog(9, gps.location.lat(), 6);
            UpdateDisplayTable("Lat", gps.location.lat(), "G");
            //Serial.print("Lng: "); myLog(9, gps.location.lng(), 6);
            UpdateDisplayTable("Lng", gps.location.lng(), "G");
            //Serial.print("Satellites: "); myLog(9, gps.satellites.value());
            //Serial.print("Speed (knots): "); myLog(9, gps.speed.knots());
            UpdateDisplayTable("Speed", gps.speed.kmph(), "G");
            UpdateDisplayTable("Course", gps.course.deg(), "G");
            //Serial.print("Course (deg): "); myLog(9, gps.course.deg());
            //Serial.print("Course (Val): "); myLog(9, gps.course.value());
            //myLog(9, "-------------------");
          }
        }
      }  
    }

    if (DoBLE) {
      // Teltonika BLE Blue Puck device
      myLog(10, "Doing the BLE stuff...");
      const char* myLocalName;
      BLEDevice peripheral = BLE.available();
      //Serial.print("Checking device=", peripheral.localName(), " ");
      if (peripheral && isTargetDevice(peripheral.address())) {
        myLog(10,"✅ BLE Device found: Localname=", peripheral.localName(), "; address=", peripheral.address());

        // Get raw advertisement data and process it ourselves
        uint8_t advData[64];
        int advLen = peripheral.advertisementData(advData, sizeof(advData));
        String myLocalNameStr = peripheral.localName();
        const char* myLocalName = myLocalNameStr.c_str();
        //myLog(9, "myLocalName=", myLocalName);
        parseTeltonikaAdv(advData, advLen, myLocalName);
      }
    }

    // Show Display Data
    if (DoShow) {
      int i = 0;
      if (i == 0) {
        myLog(9, "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++");
      }
      while (i <= numDisplayTopics-1) {
        if (DisplayInfo[i].displayLabel != "xxxBattery Power (W)") {
          sprintf(tmpStr,"Display : %s : %2f",DisplayInfo[i].displayLabel,DisplayInfo[i].TheValue);
          myLog(9, tmpStr);
        }
        i++;
      } 
      // only during debug phase
      if (!DoFake) {
        delay(1000); // so I can copy data   
      }
      //DoOnce = true;
    }

  } // end of "do once"

  //myLog(9, "At the end of the main loop");
} // end of main loop

/*

Settings depend a bit on which ESP32-S3 module variant is on your board (check the silkscreen on the metal can, e.g. ESP32-S3-WROOM-1 N8R8, N16R8, N8R2, etc.), but here's what to set in Arduino IDE / PlatformIO's Tools menu:

Board: "ESP32S3 Dev Module" (or your board's specific entry if listed, e.g. "ESP32S3 Dev Module (with USB CDC)")

USB CDC On Boot: Enabled — if you want Serial output over the native USB port immediately at boot (before Serial.begin()), and for most dev boards that use USB-native for programming/serial. Disable if you're using a separate USB-UART bridge chip for serial and want CDC off.

USB Mode: "Hardware CDC and JTAG" for boards using the native USB-OTG peripheral (most S3 dev boards). Use "USB-OTG (TinyUSB)" only if you're implementing custom USB device classes (HID, MSC, etc.) in your sketch.

Flash Mode: QIO (Quad I/O) — standard for almost all S3 dev boards. Use DIO only if you get boot/flash instability.

Flash Size: Match your board — commonly 8MB or 16MB. Check silkscreen or esptool.py flash_id.

PSRAM:

OPI PSRAM — for modules with "R8" or "R16" suffix (octal PSRAM, e.g. N8R8, N16R8) — this is the most common on dev boards like ESP32-S3-DevKitC-1.
QSPI PSRAM — for modules with "R2" suffix (quad PSRAM, older/smaller PSRAM variant).
Disabled — if your module has no PSRAM (plain N8, N16 with no R suffix).

Partition Scheme: Depends on flash size and use case:

8MB flash: "

*/

/*
Found it — this is a hardware pin conflict, not a software bug. Two separate GPIO collisions in your MAX7219 wiring:

1. GPIO19 conflicts with native USB (root cause of the USB dropout)

cpp
#define MAX7219_CS_PIN   19

On the ESP32-S3, GPIO19/GPIO20 are hardwired to the native USB D-/D+ lines. They can't be reassigned — it's fixed in silicon. Since your build uses "USB CDC On Boot: Enabled" (native USB serial), the moment setup() does pinMode(MAX7219_CS_PIN, OUTPUT) and starts toggling GPIO19 for SPI chip-select, it's yanking on the USB data line itself. That's exactly what "USB device not recognized" + COM5 dropping/reappearing repeatedly looks like — the S3 is corrupting its own USB connection every time it drives that pin.

2. GPIO35/36/37 conflict with Octal PSRAM (root cause of the reboot)

cpp
#define MAX7219_MOSI_PIN 35  // DIN
#define MAX7219_MISO_PIN 37
#define MAX7219_SCK_PIN  36

Your board is an N16R8 with Octal PSRAM (you've got "OPI PSRAM" set in Tools, per your own comment at the top). On Octal-PSRAM S3 modules, GPIO35–37 are internally wired to the extra PSRAM data lines — they are not available as general GPIO. Driving them as an SPI bus for the matrix corrupts the PSRAM bus, which is a near-guaranteed crash/panic → reboot loop, especially since spiMatrix.begin() and matrix.begin() run early in setup().

So you have both a PSRAM-corrupting SPI bus and a USB-killing chip-select pin, both on the same MAX7219 wiring — which is why it looks like "boots, runs setup, reboots, USB drops in a loop."

Fix: move the entire MAX7219 SPI bus off 19/35/36/37. Safe, unused pins on your board (not strapping pins, not flash, not PSRAM, not USB) — for example:

cpp
#define MAX7219_CS_PIN   21
#define MAX7219_MOSI_PIN 40  // DIN
#define MAX7219_MISO_PIN 41  // unused but needed for SPI init
#define MAX7219_SCK_PIN  42  // CLK

(GPIO 1,2,4,5,6,7,21,38–42,47,48 are all free and safe on the DevKitC-1 N16R8 given your current pin map — pick any four for the matrix bus, just avoid 0/3/45/46 which are strapping pins.)

After rewiring physically and updating those four #defines, re-upload — the reboot/USB-dropout loop should be gone.
*/