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

#define CMD_LD_OFF       0xFA
#define CMD_READ_COLOR   0xFB
#define CMD_READ_CURRENT 0xFC
#define CMD_ADDRESS      0xFD
#define CMD_BEAM_BLOCKED 0xFE
#define CMD_PD_VOLT      0xFF

// === MCP4922 DAC Pins ===
const int CS_PIN     = 10;
const int LDAC_PIN   = 9;
const int SHDN_PIN   = 8;


// === Digital Input Pin ===
const int BEAM_BLOCKED_PIN = 2;

// === Analog Input Pins ===
const int Pin_PD_VOLT     = A0;
const int Pin_LD_VOLTAGE  = A1;
const int Pin_LD_OFF      = A2;

// === EEPROM Memory Addresses ===
const int EEPROM_current = 0;
const int EEPROM_color   = 1;

// === Addressing ===
const int digitalPinCount = 5;  // Digital pins 3-7
const int analogPinCount = 2;   // A6 and A7
//const int digitalPins[digitalPinCount] = { 3, 4, 5, 6, 7, A7, A6 };
const int digitalPins[digitalPinCount] = { 3, 4, 5, 6, 7 };
const int analogPins[analogPinCount] = {A7, A6};
int Adresse[digitalPinCount + analogPinCount];
byte I2C_ADDRESS = 0x00;

// === Runtime Variables ===
int raw_threshold_game = 0;
int Beam_Blocked = 0;
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
  TURN_ON();
  Serial.print("Save Current: ");
  Serial.println(value);
}
void set_laser_color(byte color) {
  EEPROM.write(EEPROM_color, color);
}
void game_mode() {
  Beam_Blocked = 0;
  TURN_ON();
  rawPD_VOLT = analogRead(Pin_PD_VOLT);
  raw_threshold_game = rawPD_VOLT;
  set_PD_Threshold(raw_threshold_game);
}
void TURN_ON() {
  currentValue = EEPROM.read(EEPROM_current);
  digitalWrite(Pin_LD_OFF,LOW);
  Set_current(currentValue);
  set_PD_Threshold(0);
}

void TURN_OFF() {
  digitalWrite(Pin_LD_OFF,HIGH);
  currentValue = 0;
  Set_current(currentValue);


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
      Beam_Blocked = digitalRead(BEAM_BLOCKED_PIN);
      Wire.write((byte)Beam_Blocked);
      if (Beam_Blocked){
        TURN_OFF();
        set_PD_Threshold(0);
      }
      Serial.println("→ Beam Blocked read & Laser turn on");
      break;
    case CMD_PD_VOLT:
      rawPD_VOLT = analogRead(Pin_PD_VOLT);
      PD_VOLT = (rawPD_VOLT / 1023.0) * referenceVoltage;
      Serial.println(PD_VOLT);
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
      case CMD_LD_OFF:
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
  pinMode(Pin_LD_OFF, OUTPUT);
  digitalWrite(Pin_LD_OFF,HIGH);
  
  Serial.begin(9600);
  pinMode(BEAM_BLOCKED_PIN, INPUT);
  
  pinMode(CS_PIN, OUTPUT);
  pinMode(LDAC_PIN, OUTPUT);
  pinMode(SHDN_PIN, OUTPUT);
  
  analogReference(EXTERNAL);

  // Read digital pins
  for (int i = 0; i < digitalPinCount; i++) {
      pinMode(digitalPins[i], INPUT_PULLUP);
      Adresse[i] = digitalRead(digitalPins[i]);
  }

  // Read analog pins (A6/A7)
  // No pinMode needed as they are analog-only
   for (int i = 0; i < analogPinCount; i++) {
       // Read analog value and convert to digital (threshold at half of max reading)
       int analogValue = analogRead(analogPins[i]);
       Adresse[digitalPinCount + i] = (analogValue > 40) ? HIGH : LOW;
  }

  // Calculate I2C address
  I2C_ADDRESS = 0;
   for (int i = 0; i < (digitalPinCount + analogPinCount); i++) {
  //for (int i = 0; i < (digitalPinCount); i++) {
      I2C_ADDRESS |= (Adresse[i] == LOW ? 1 : 0) << (i);
  }

  Serial.print("I2C Address set to: 0x");
  Serial.println(I2C_ADDRESS, HEX);

  SPI.begin();
  SPI.beginTransaction(SPISettings(20000000, MSBFIRST, SPI_MODE0));
  digitalWrite(CS_PIN, HIGH);
  digitalWrite(LDAC_PIN, HIGH);
  digitalWrite(SHDN_PIN, HIGH);

  writeDAC(0,0);
  writeDAC(1, 0);
  
  Wire.begin(I2C_ADDRESS);
  Wire.onRequest(onRequest);
  Wire.onReceive(receiveCommand);
}


void loop() {
}
