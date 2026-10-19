/*
 * RFID Student Attendance - Arduino Uno + RC522 + 16x2 I2C LCD
 * -------------------------------------------------------------
 * Reads an RFID card, sends its UID to the PC over USB serial,
 * then waits for the PC's reply and gives feedback (LCD + LEDs + buzzer).
 *
 * Messages sent to PC:   READY                 (after power-on / reset)
 *                        UID:04A1B2C3
 * Replies from PC:       IN|Juan Dela Cruz|PRESENT|7:21 AM   (morning or afternoon log in)
 *                        IN|Juan Dela Cruz|LATE|7:45 AM
 *                        OUT|Juan Dela Cruz|12:01 PM         (morning or afternoon log out)
 *                        DUP|Juan Dela Cruz                  (tapped again too soon)
 *                        DONE|Juan Dela Cruz                 (already logged out)
 *                        UNKNOWN                             (card not registered)
 *                        REG|04A1B2C3                        (teacher is registering this card)
 *                        SCHOOL|Corcuera NHS                 (name for the LCD idle screen)
 *
 * WIRING (RC522 -> Uno)          !!! RC522 runs on 3.3V, NOT 5V !!!
 *   SDA(SS) -> D10    SCK  -> D13    MOSI -> D11
 *   MISO    -> D12    RST  -> D9     3.3V -> 3.3V    GND -> GND   (IRQ not used)
 *
 * 16x2 I2C LCD (the small board on the back is the I2C "backpack")
 *   GND -> GND    VCC -> 5V    SDA -> A4    SCL -> A5
 *   If the screen lights up but shows nothing (or only boxes), turn the small
 *   blue potentiometer on the backpack with a screwdriver to adjust the contrast.
 *   The address (usually 0x27 or 0x3F) is found automatically.
 *
 * Feedback parts (optional)
 *   Green LED (+220 ohm) -> D5      Red LED (+220 ohm) -> D4
 *   Active buzzer (+)    -> D6
 *
 * Libraries (Arduino IDE > Tools > Manage Libraries):
 *   - "MFRC522" by GithubCommunity
 *   - "LiquidCrystal I2C" by Frank de Brabander
 */

#include <SPI.h>
#include <MFRC522.h>

#define USE_LCD 1          // set to 0 if no LCD is connected

#if USE_LCD
  #include <Wire.h>
  #include <LiquidCrystal_I2C.h>
  LiquidCrystal_I2C *lcd = nullptr;
#endif

const byte SS_PIN    = 10;
const byte RST_PIN   = 9;
const byte GREEN_LED = 5;
const byte RED_LED   = 4;
const byte BUZZER    = 6;

const unsigned long SAME_CARD_COOLDOWN_MS = 2500;  // ignore the same card held on the reader
const unsigned long REPLY_TIMEOUT_MS      = 1500;  // how long to wait for the PC
const unsigned long RESULT_SHOW_MS        = 2500;  // how long a result stays on the LCD

MFRC522 rfid(SS_PIN, RST_PIN);

String lastUid = "";
unsigned long lastReadAt = 0;
String schoolName = "";            // sent by the PC; empty = PC app not connected yet
unsigned long resultShownAt = 0;   // 0 = idle screen is showing

// ---------- LCD ----------
// Pads/cuts text to exactly 16 characters so old letters never stay on screen
String fit(String s) {
  if (s.length() > 16) s = s.substring(0, 16);
  while (s.length() < 16) s += ' ';
  return s;
}

// A long name like "Maria Cristina Dela Cruz" becomes "Maria C. Dela C." style text that fits
String shortName(const String &full) {
  if (full.length() <= 16) return full;
  int firstSpace = full.indexOf(' ');
  int lastSpace = full.lastIndexOf(' ');
  if (firstSpace < 0) return full.substring(0, 16);
  String first = full.substring(0, firstSpace);
  String last = full.substring(lastSpace + 1);
  String s = first + " " + last;                     // drop middle words
  if (s.length() <= 16) return s;
  s = first + " " + last.charAt(0) + ".";            // "Christopher D."
  return s.length() <= 16 ? s : s.substring(0, 16);
}

void showMessage(const String &line1, const String &line2) {
#if USE_LCD
  if (!lcd) return;
  lcd->setCursor(0, 0); lcd->print(fit(line1));
  lcd->setCursor(0, 1); lcd->print(fit(line2));
#endif
}

void showIdle() {
  resultShownAt = 0;
  showMessage("Tap your ID card", schoolName.length() ? schoolName : "Waiting for PC..");
}

void showResult(const String &line1, const String &line2) {
  showMessage(line1, line2);
  resultShownAt = millis();
  if (resultShownAt == 0) resultShownAt = 1;
}

#if USE_LCD
// Finds the LCD backpack on the I2C bus (common addresses first)
byte findLcdAddress() {
  const byte common[] = {0x27, 0x3F};
  for (byte a : common) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) return a;
  }
  for (byte a = 0x20; a <= 0x3F; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) return a;
  }
  return 0;
}
#endif

// ---------- LEDs + buzzer ----------
void beep(int times, int onMs, int offMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(BUZZER, HIGH); delay(onMs);
    digitalWrite(BUZZER, LOW);  delay(offMs);
  }
}

void feedbackOk() {
  digitalWrite(GREEN_LED, HIGH);
  beep(1, 120, 0);
  delay(600);
  digitalWrite(GREEN_LED, LOW);
}

void feedbackWarn() {          // duplicate / already done
  digitalWrite(GREEN_LED, HIGH);
  digitalWrite(RED_LED, HIGH);
  beep(2, 80, 80);
  delay(500);
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, LOW);
}

void feedbackError() {         // unknown card / no reply
  digitalWrite(RED_LED, HIGH);
  beep(3, 70, 70);
  delay(500);
  digitalWrite(RED_LED, LOW);
}

// ---------- serial ----------
// Returns the part of "A|B|C" at position index
String part(const String &s, int index) {
  int start = 0;
  for (int i = 0; i < index; i++) {
    start = s.indexOf('|', start);
    if (start < 0) return "";
    start++;
  }
  int end = s.indexOf('|', start);
  return end < 0 ? s.substring(start) : s.substring(start, end);
}

// Messages the PC can send at any time (not a reply to a tap)
bool handleInfo(const String &line) {
  if (line.startsWith("SCHOOL|")) {
    schoolName = line.substring(7);
    if (resultShownAt == 0) showIdle();
    return true;
  }
  return false;
}

String waitForReply() {
  unsigned long start = millis();
  while (millis() - start < REPLY_TIMEOUT_MS) {
    if (Serial.available()) {
      String reply = Serial.readStringUntil('\n');
      reply.trim();
      if (reply.length() == 0 || handleInfo(reply)) continue;
      return reply;
    }
  }
  return "";
}

// ---------- RFID ----------
String readUid() {
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

void handleReply(const String &reply, const String &uid) {
  String kind = part(reply, 0);
  String name = shortName(part(reply, 1));

  if (kind == "IN") {
    String status = part(reply, 2);
    String at = part(reply, 3);                      //  "IN  7:21 AM  OK" / "IN 12:59 PM LATE"
    String line2 = "IN " + at;
    String tag = status == "LATE" ? "LATE" : "OK";
    while (line2.length() + tag.length() < 16) line2 += ' ';
    showResult(name, line2 + tag);
    feedbackOk();
  } else if (kind == "OUT") {
    showResult(name, "OUT " + part(reply, 2) + " Bye");
    feedbackOk();
  } else if (kind == "DUP") {
    showResult(name, "Already recorded");
    feedbackWarn();
  } else if (kind == "DONE") {
    showResult(name, "Already out");
    feedbackWarn();
  } else if (kind == "REG") {
    showResult("Card captured", part(reply, 1));
    feedbackOk();
  } else if (kind == "UNKNOWN") {
    showResult("Unknown card", uid);
    feedbackError();
  } else {
    showResult("No response", "Is the PC app on?");
    feedbackError();
  }
}

void setup() {
  Serial.begin(9600);
  Serial.setTimeout(200);
  SPI.begin();
  rfid.PCD_Init();

  pinMode(GREEN_LED, OUTPUT);
  pinMode(RED_LED, OUTPUT);
  pinMode(BUZZER, OUTPUT);

#if USE_LCD
  Wire.begin();
  byte addr = findLcdAddress();
  if (addr) {
    lcd = new LiquidCrystal_I2C(addr, 16, 2);
    lcd->init();
    lcd->backlight();
    showMessage("RFID Attendance", "Starting...");
  }
#endif

  // Startup check: both LEDs blink once
  digitalWrite(GREEN_LED, HIGH); digitalWrite(RED_LED, HIGH);
  beep(1, 60, 0);
  delay(300);
  digitalWrite(GREEN_LED, LOW); digitalWrite(RED_LED, LOW);

  Serial.println("READY");
  showIdle();
}

void loop() {
  // Messages from the PC between taps (school name); anything else is stale and dropped
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    handleInfo(line);
  }

  // Return to the idle screen after a result has been shown long enough
  if (resultShownAt && millis() - resultShownAt > RESULT_SHOW_MS) showIdle();

  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;

  String uid = readUid();
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  // Same card still sitting on the reader -> ignore
  if (uid == lastUid && millis() - lastReadAt < SAME_CARD_COOLDOWN_MS) return;
  lastUid = uid;
  lastReadAt = millis();

  showMessage("Reading card...", "");
  Serial.print("UID:");
  Serial.println(uid);

  handleReply(waitForReply(), uid);
}
