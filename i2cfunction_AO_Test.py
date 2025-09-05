import smbus # pyright: ignore[reportMissingImports]
import RPi.GPIO as gpio # pyright: ignore[reportMissingModuleSource]
import time
import struct

#  bus
bus = None

# Global timer variables
start = 0
penalty = 0

# Arduino command codes
CMD_SET_CURRENT = 0x01      # Set laser current
CMD_GAME = 0x02             # Activate game mode
CMD_TURN_ON = 0x03          # Turn laser ON
CMD_TURN_OFF = 0x04         # Turn laser OFF
CMD_SET_COLOR = 0x05        # Set laser color

CMD_READ_COLOR = 0xFB       # Read stored laser color
CMD_READ_CURRENT = 0xFC     # Read current laser current
CMD_ADDRESS = 0xFD          # Request device address
CMD_BEAM_BLOCKED = 0xFE     # Check if beam is blocked
CMD_PD_VOLT = 0xFF          # Read photodiode voltage


# Set the global I2C bus, typically called from main.
def set_bus(b):
    global bus
    bus = b


# Send a command to an Arduino, with optional value
def send_command(address, command, value=None):
    if value is not None:
        bus.write_i2c_block_data(address, command, [value])
        print(f"sent '{value}'")
    else:
        bus.write_byte(address, command)

# Read a response from Arduino depending on command type
def read_response(address, command):
    bus.write_byte(address, command)
    time.sleep(0.001)
    value = 404  # Default error code
    if command == CMD_PD_VOLT:
        data = bus.read_i2c_block_data(address, 0, 4)
        value = struct.unpack('f', bytes(data))[0]  # Read float
    else:
        value = bus.read_byte(address)  # Read byte
    return value

# Scan I2C bus for connected devices and return their addresses
def SCAN_I2C_BUS():
    print("Scanning I2C bus for devices...")
    found_devices = []
    for address in range(0x01, 0x78):
        try:
            received = bus.read_byte(address)
            found_devices.append(address)
        except Exception:
            pass
    if not found_devices:
        print("No I2C devices found")
    else:
        print(f"Total devices found: {len(found_devices)} ")
    return found_devices

# Turn off all lasers
def TURN_ALL_OFF(ADDRESSES):
    for address in ADDRESSES:
        send_command(address, CMD_TURN_OFF)
        

# Turn off a single laser
def TURN_ONLY_ONE_OFF(ADDRESS):
    send_command(ADDRESS, CMD_TURN_OFF)

# Turn on all lasers
def TURN_ALL_ON(ADDRESSES):
    for address in ADDRESSES:
        send_command(address, CMD_TURN_ON)
    time.sleep(2)


# Turn on a single laser
def TURN_ONLY_ONE_ON(ADDRESS):
    send_command(ADDRESS, CMD_TURN_ON)
    time.sleep(2)

# Set the current of a laser (0 < Value < 120)
def SET_LASER_CURRENT(ADDRESS, Value):
    if isinstance(Value, int) and Value > 0 and Value < 120:
        send_command(ADDRESS, CMD_SET_CURRENT, Value)
        print(f"Current change to {Value} mA")
    else:
        print("The value does not respect the condition: must be an int, positive, and < 120")

# Set laser color using one-hot encoding
# blue: 0x01, green: 0x02, red: 0x04
def SET_LASER_COLOR(ADDRESS, color):
    if color == "blue":
        Value = 0x01
    elif color == "green":
        Value = 0x02
    elif color == "red":
        Value = 0x04
    send_command(ADDRESS, CMD_SET_COLOR, Value)
    print(f"Color change to {color} ")

# Scan if beam is blocked across all Arduinos
def ARDUINO_BLOCK_BEAM_SCAN(ADDRESSES):
    arduino_blocked = []
    for address in ADDRESSES:
        if read_response(address, CMD_BEAM_BLOCKED):
            arduino_blocked.append(address)
            print(" ARDUINO BLOCKED :", address)
    return arduino_blocked

# Read photodiode voltage from one Arduino
def READ_PD_VOLT(ADDRESS):
    value = read_response(ADDRESS, CMD_PD_VOLT)
    # print(f"PD VOLT :{value} V")
    return value  # Return the value instead of just printing it 

# Read laser current from one Arduino
def READ_LASER_CURRENT(ADDRESS):
    current = read_response(ADDRESS, CMD_READ_CURRENT)
    print(f"Current for {ADDRESS} Arduino is {current}mA")
    return current

# Read and decode laser color from one Arduino
def READ_LASER_COLOR(ADDRESS):
    Value = read_response(ADDRESS, CMD_READ_COLOR)
    if Value == 0x01:
        color = "blue"
    elif Value == 0x02:
        color = "green"
    elif Value == 0x04:
        color = "red"
    print(f"Color : {color}")
    return color

# Game mode execution for all devices
# Starts countdown, sets thresholds, monitors beam interruptions
def GAME_MODE_ON(ADDRESSES):
    TURN_ALL_ON(ADDRESSES)
    print("GAME ON")
    for address in ADDRESSES:
        send_command(address, CMD_GAME)
    
#     try:
#         while True:
#             
#             READ_TIMER()
#             time.sleep(0.001)
#     except KeyboardInterrupt:
#         print("\nExiting Program")

# Monitor beam block signal via GPIO and read with arduino is block Arduinos and add penalty
def MONITOR_BLOCKED_BEAM(ADDRESSES):
    BLOCKED = gpio.input(21)
    if BLOCKED == 0:
        ASK_ARDUINO_BLOCKED_BEAM(ADDRESSES)

# Query each Arduino to check if their beam is blocked
# Adds penalty time if beam is broken
def ASK_ARDUINO_BLOCKED_BEAM(ADDRESSES):
    for address in ADDRESSES:
        if read_response(address, CMD_BEAM_BLOCKED):
            ADD_TIME_COUNTER(address)


# Increase penalty counter based on laser color
# blue = +20s, green = +5s, red = +10s
def ADD_TIME_COUNTER(ADDRESS):
    global penatly
    color = READ_LASER_COLOR(ADDRESS)
    if color == "blue":
        penatly += 20
    elif color == "green":
        penatly += 5
    elif color == "red":
        penatly += 10

# Starts countdown and initializes timer
def START_TIMER():
    global start
    global penatly
    penatly = 0
    start = time.time()

# Read and print total elapsed game time with penalties
def READ_TIMER():
    
    counter = (time.time() - start) + penatly
    #print(f"\nTimer :{counter} s       ",end="\r")
    print("Timer:{:.1f} s".format(counter),end="\r")
    return counter

def STOP_GAME_MODE():
    addrs = SCAN_I2C_BUS()
    TURN_ALL_OFF(addrs)
    print("GAME MODE STOPPED – all lasers off")
