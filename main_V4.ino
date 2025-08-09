#include <SPI.h>
#include <Wire.h>
#include <EEPROM.h>

// === Constants ===
const float referenceVoltage = 2.5;
const unsigned long interval = 1000;

// === DAC Command Constants ===
#define CMD_SAVE         0x01
#define CMD_GAME         0x02
#define CMD_TURN_ON      0x03
#define CMD_TURN_OFF     0x04
#define CMD_SET_COLOR    0x05
#define CMD_READ_COLOR   0xFB
#define CMD_READ_CURRENT 0xFC
#define CMD_ADDRESS      0xFD
#define CMD_BEAM_BLOCKED 0xFE
#define CMD_PD_VOLT      0xFF

// === MCP4922 DAC Pins ===
const int CS_PIN     = 10;
const int LDAC_PIN   = 9;
const int SHDN_PIN   = 8;
const int BEAM_BLOCKED_PIN = 2;

// === Analog Input Pins ===
const int Pin_PD_VOLT     = A0;
const int Pin_LD_VOLTAGE  = A1;
const int Pin_LD_OFF      = A2;

// === EEPROM Memory Addresses ===
const int EEPROM_current = 0;
const int EEPROM_color   = 1;

// === Addressing ===
const int pinCount = 5;
const int pins[pinCount] = {3, 4, 5, 6, 7};
int Adresse[pinCount];
byte I2C_ADDRESS = 0x00;

// === Runtime Variables ===
int raw_threshold_game = 0;
int Beam_Blocked = 0;
bool ASK_BEAM_BLOCKED = false;
int rawPD_VOLT = 0;
float PD_VOLT = 0;
int raw_LD_VOLTAGE = 0;
float LD_VOLTAGE = 0;
int currentValue = 0;

// === I2C ===
byte i2cCommand = 0x00;
uint8_t argument = 0;
volatile byte requestCode = 0;

// === Timing ===
unsigned long lastRun = 0;

// === DAC Write (12-bit) ===
void writeDAC(uint8_t channel, uint16_t value) {
  value &= 0x0FFF;
  uint16_t command = 0;

  if (channel == 1) command |= (1 << 15);
  command |= (1 << 14) | (1 << 13) | (1 << 12);
  command |= value;

  digitalWrite(CS_PIN, LOW);
  SPI.transfer16(command);
  digitalWrite(CS_PIN, HIGH);
  digitalWrite(LDAC_PIN, LOW);
  delayMicroseconds(1);
  digitalWrite(LDAC_PIN, HIGH);
}

// === Set PD Threshold ===
void set_PD_Threshold(int rawPD_VOLT) {
  int dac_rawPD_VOLT = map((rawPD_VOLT * 3) / 4, 0, 1023, 0, 4095);
  writeDAC(1, dac_rawPD_VOLT);
}

// === Set Laser Current ===
void Set_current(float current) {
  float bit_current = (current + 0.2372) / 0.0301;
  writeDAC(0, bit_current);
}

void change_current(int value) {
  EEPROM.write(EEPROM_current, value);
  currentValue = EEPROM.read(EEPROM_current);
  Serial.print("Save Current: ");
  Serial.println(value);
}

void set_laser_color(byte color) {
  EEPROM.write(EEPROM_color, color);
}

void game_mode() {
  Beam_Blocked = 0;
  ASK_BEAM_BLOCKED = false;
  currentValue = EEPROM.read(EEPROM_current);
  rawPD_VOLT = analogRead(Pin_PD_VOLT);
  raw_threshold_game = rawPD_VOLT;
  set_PD_Threshold(raw_threshold_game);
}



void TURN_ON() {
  currentValue = EEPROM.read(EEPROM_current);
  Set_current(currentValue);
  set_PD_Threshold(0);
}

void TURN_OFF() {
  currentValue = 0;
}

// === I2C: Handle Master Request ===
void onRequest() {
  switch (requestCode) {
    case CMD_ADDRESS:
      Wire.write(I2C_ADDRESS);
      Serial.print("→ ADDRESS ");
      break;
    case CMD_READ_CURRENT:
      Wire.write((byte)currentValue);
      Serial.print("→ currentValue ");
      break;
    case CMD_READ_COLOR:
      Wire.write(EEPROM.read(EEPROM_color));
      Serial.print("→ color ");
      break;
    case CMD_BEAM_BLOCKED:
      Wire.write((byte)Beam_Blocked);
      if (Beam_Blocked){
        TURN_OFF();
        set_PD_Threshold(0);
      }

      Serial.println("→ Beam Blocked read & Laser turn on");
      break;
    case CMD_PD_VOLT:
      Wire.write((byte*)&PD_VOLT, 4);
      break;
    default:
      Wire.write(I2C_ADDRESS);
      break;
  }
}

// === I2C: Handle Master Command ===
void receiveCommand(int numBytes) {
  if (numBytes >= 1) {
    byte received = Wire.read();
    switch (received) {
      case CMD_ADDRESS:
        requestCode = received;
        break;
      case CMD_READ_CURRENT:
        requestCode = received;
        break;
      case CMD_READ_COLOR:
        requestCode = received;
        break;
      case CMD_BEAM_BLOCKED:
        requestCode = received;
        break;
      case CMD_PD_VOLT:
        requestCode = received;
        break;
      case CMD_SAVE:
        if (numBytes >= 2) change_current(Wire.read());
        break;
      case CMD_SET_COLOR:
        if (numBytes >= 2) set_laser_color(Wire.read());
        break;
      case CMD_TURN_ON:
        TURN_ON();
        break;
      case CMD_GAME:
        game_mode();
        break;
      case CMD_TURN_OFF:
        TURN_OFF();
        break;
    }
  }
}

void setup() {
  Serial.begin(9600);
  pinMode(BEAM_BLOCKED_PIN, INPUT);

  pinMode(CS_PIN, OUTPUT);
  pinMode(LDAC_PIN, OUTPUT);
  pinMode(SHDN_PIN, OUTPUT);
  digitalWrite(CS_PIN, HIGH);
  digitalWrite(LDAC_PIN, HIGH);
  digitalWrite(SHDN_PIN, HIGH);

  analogReference(EXTERNAL);

  for (int i = 0; i < pinCount; i++) {
    pinMode(pins[i], INPUT_PULLUP);
    Adresse[i] = digitalRead(pins[i]);
  }

  I2C_ADDRESS = 0;
  for (int i = 0; i < pinCount; i++) {
    I2C_ADDRESS |= (Adresse[i] == LOW ? 1 : 0) << (pinCount - 1 - i);
  }

  Serial.print("I2C Address set to: 0x");
  Serial.println(I2C_ADDRESS, HEX);

  currentValue = EEPROM.read(EEPROM_current);

  SPI.begin();
  SPI.beginTransaction(SPISettings(20000000, MSBFIRST, SPI_MODE0));

  Wire.begin(I2C_ADDRESS);
  Wire.onRequest(onRequest);
  Wire.onReceive(receiveCommand);
}

void loop() {
  Set_current(currentValue);
  Beam_Blocked = digitalRead(BEAM_BLOCKED_PIN);


  rawPD_VOLT = analogRead(Pin_PD_VOLT);
  PD_VOLT = (rawPD_VOLT / 1023.0) * referenceVoltage;

  raw_LD_VOLTAGE = analogRead(Pin_LD_VOLTAGE);
  LD_VOLTAGE = (raw_LD_VOLTAGE / 1023.0) * referenceVoltage;
}