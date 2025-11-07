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
CMD_GAME_THRESHOLD_SET = 0x10 # setting the game threhsold 

CMD_READ_COLOR = 0xFB       # Read stored laser color
CMD_READ_CURRENT = 0xFC     # Read current laser current
CMD_ADDRESS = 0xFD          # Request device address
CMD_BEAM_BLOCKED = 0xFE     # Check if beam is blocked
CMD_PD_VOLT = 0xFF          # Read photodiode voltage
CMD_GAME_THRESHOLD_READ = 0x12 # Read the game mode threshold

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
        value = struct.unpack('f', bytes(data))[0]
        time.sleep(0.3)# Read float
    else:
        value = bus.read_byte(address)  # Read byte
    return value

# Scan I2C bus for connected devices and return their addresses
def SCAN_I2C_BUS():
    print("Scanning I2C bus for devices...")
    found_devices = []
    for address in range(0x01, 0x78):
        try:
            # Use a simple probe; some devices may NACK - swallow exceptions
            bus.read_byte(address)
            found_devices.append(address)
        except Exception:
            pass
    found_devices = list(dict.fromkeys(found_devices))  # ensure unique/order
    if not found_devices:
        print("No I2C devices found")
    else:
        print(f"Total devices found: {len(found_devices)} -> {found_devices}")
    return found_devices

# Turn off all lasers with improved reliability
def TURN_ALL_OFF(ADDRESSES):
    for address in ADDRESSES:
        send_command(address, CMD_TURN_OFF)
        time.sleep(0.01)  # Small delay between commands to prevent bus overload
        
    # Try to verify all modules are actually off
    verify_attempts = 0
    while verify_attempts < 3:
        all_off = True
        for address in ADDRESSES:
            try:
                time.sleep(0.01)
                # Simple read to check if device is responsive
                bus.read_byte(address)
            except Exception as e:
                print(f"Warning: Module 0x{address:02X} may not have received OFF command: {e}")
                all_off = False
                # Try again for this specific module
                try:
                    time.sleep(0.02)
                    send_command(address, CMD_TURN_OFF)
                except:
                    pass
        
        if all_off:
            break
        verify_attempts += 1

# Turn off a single laser
def TURN_ONLY_ONE_OFF(ADDRESS):
    # Try up to 3 times
    for attempt in range(3):
        try:
            send_command(ADDRESS, CMD_TURN_OFF)
            return  # Success
        except OSError as e:
            if e.errno == 5:  # I/O error
                print(f"I/O error turning off module 0x{ADDRESS:02X}, retrying...")
                time.sleep(0.02 * (attempt + 1))  # Progressively longer delays
            else:
                print(f"Error {e.errno} turning off module 0x{ADDRESS:02X}")
                break
        except Exception as e:
            print(f"Error turning off module 0x{ADDRESS:02X}: {e}")
            break

# Turn on all lasers with improved reliability
def TURN_ALL_ON(ADDRESSES):
    for address in ADDRESSES:
        send_command(address, CMD_TURN_ON)
        time.sleep(0.01)  # Small delay between commands to prevent bus overload
    
    # Give lasers time to stabilize
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
# Read photodiode voltage from one Arduino
def READ_GAME_THRESHOLD(ADDRESS):
    value = read_response(ADDRESS, CMD_GAME_THRESHOLD_READ)
    print(f"threshold :{value} V")
    return value  # Return the value instead of just printing it 

def SET_GAME_THRESHOLD(ADDRESS, value):
    send_command(ADDRESS, CMD_GAME_THRESHOLD_SET, value)
    print(f"Game threshold set to :{value} V")
    return value  # Return the value instead of just printing it 
# Read laser current from one Arduino
def READ_LASER_CURRENT(ADDRESS):
    current = read_response(ADDRESS, CMD_READ_CURRENT)
    print(f"Current for {ADDRESS} Arduino is {current}mA")
    return current

# Read and decode laser color from one Arduino
def READ_LASER_COLOR(ADDRESS):
    """Read and decode laser color from one Arduino. Return 'blue'|'green'|'red' or None."""
    Value = read_response(ADDRESS, CMD_READ_COLOR)
    color = None
    if Value == 0x01:
        color = "blue"
    elif Value == 0x02:
        color = "green"
    elif Value == 0x04:
        color = "red"
    # Always safe to print even if unknown
    print(f"Color for 0x{ADDRESS:02X}: {color}")
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
    """Query each Arduino to check if their beam is blocked; add penalty when found."""
    for address in ADDRESSES:
        try:
            if read_response(address, CMD_BEAM_BLOCKED):
                ADD_TIME_COUNTER(address)
        except Exception as e:
            print(f"Error querying beam block for 0x{address:02X}: {e}")

# Increase penalty counter based on laser color
# blue = +20s, green = +5s, red = +10s
def ADD_TIME_COUNTER(ADDRESS):
    """Increase penalty counter based on laser color."""
    global penalty
    color = READ_LASER_COLOR(ADDRESS)
    if color == "blue":
        penalty += 20
    elif color == "green":
        penalty += 5
    elif color == "red":
        penalty += 10
    # If color is None, do nothing

# Starts countdown and initializes timer
def START_TIMER():
    global start, penalty
    penalty = 0
    start = time.time()

# Read and print total elapsed game time with penalties
def READ_TIMER():
    """Return elapsed time plus penalties."""
    global start, penalty
    if start == 0:
        return 0.0
    counter = (time.time() - start) + penalty
    # optional: print status quietly
    # print("Timer:{:.1f} s".format(counter), end="\r")
    return counter

def STOP_GAME_MODE():
    try:
        addrs = SCAN_I2C_BUS()
        TURN_ALL_OFF(addrs)
    except Exception as e:
        print(f"Error stopping game mode: {e}")
    print("GAME MODE STOPPED – all lasers off")
    for address in addrs:
        if read_response(address, CMD_BEAM_BLOCKED):
            ADD_TIME_COUNTER(address)
