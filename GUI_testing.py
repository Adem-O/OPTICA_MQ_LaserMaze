import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import time
import sys
import os

# Hide the pygame welcome message
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame
import random

# Move TEST_MODE definition to the top, before any function or class definitions
TEST_MODE = "--test" in sys.argv

# ------------------- TEST MODE / HARDWARE IMPORTS -------------------
if not TEST_MODE:
    try:
        import smbus
        import RPi.GPIO as GPIO
        from i2cfunction_AO_Test import *
        import time  # Make sure time is imported
    except ImportError:
        TEST_MODE = True
        print("Hardware imports failed - running in test mode")
        
if TEST_MODE:
    # Stub implementations
    class smbus:
        class SMBus:
            def __init__(self, bus): pass

    class GPIO:
        BCM = OUT = IN = LOW = HIGH = PUD_DOWN = None
        @staticmethod
        def setmode(mode): pass
        @staticmethod
        def setup(pin, mode, initial=None, pull_up_down=None): pass
        @staticmethod
        def output(pin, value): pass
        @staticmethod
        def input(pin): return 0
        @staticmethod
        def cleanup(): pass

    def set_bus(bus): pass
    
    # Test mode variables
    _game_timer = 0
    _game_active = False
    _last_time = 0
    
    # Simulated I2C functions
    def SCAN_I2C_BUS(): 
        return [0x10, 0x11, 0x12, 0x13, 0x15,0x03]  # Simulated addresses
        
    def TURN_ALL_OFF(addrs): pass
    def TURN_ALL_ON(addrs): pass
    def TURN_ONLY_ONE_ON(addr): pass
    def TURN_ONLY_ONE_OFF(addr): pass
    
    class TestVoltageGenerator:
        def __init__(self):
            self.base_voltages = {}
            self.noise_factor = 0.1
            
        def set_base_voltage(self, addr, voltage):
            self.base_voltages[addr] = voltage
            
        def get_voltage(self, addr):
            base = self.base_voltages.get(addr, 2.0)  # default 2.0V if not set
            noise = (random.random() - 0.5) * self.noise_factor
            return max(0, min(3.3, base + noise))  # Keep voltage between 0-3.3V

    # Create global test voltage generator
    test_voltage_gen = TestVoltageGenerator()

    # Override READ_PD_VOLT to use test generator
    def READ_PD_VOLT(addr):
        return test_voltage_gen.get_voltage(addr)
    
    # Add test function to simulate voltage changes
    def simulate_voltage_change(addr, new_voltage):
        """Test function to change the base voltage for a module"""
        test_voltage_gen.set_base_voltage(addr, new_voltage)
    
    def START_TIMER():
        global _game_timer, _game_active, _last_time
        _game_timer = 0
        _game_active = True
        _last_time = time.time()
        
    def READ_TIMER():
        """Return larger of two lane timers for compatibility"""
        return max(app._lane1_timer, app._lane2_timer)
        
    def GAME_MODE_ON(addrs): pass
    def STOP_GAME_MODE(): 
        global _game_active
        _game_active = False
        
    def MONITOR_BLOCKED_BEAM(addrs):
        """Simulate random beam breaks for testing"""
        if random.random() < 0.1:  # 10% chance of beam break
            return random.choice(addrs)
        return None

# ------------------- Laser Maze UI -------------------
class LaserMazeUI(tk.Tk):
    def __init__(self):
        global TEST_MODE  # Add this line to fix the variable scope issue
        super().__init__()
        self.title("Laser Maze Control")
        self.geometry("1024x768")
        
        # Set window icon based on platform
        try:
            if sys.platform.startswith('win'):
                self.iconbitmap('icon.ico')
            else:
                icon = tk.PhotoImage(file='icon.png')  
                self.iconphoto(True, icon)
        except Exception as e:
            print(f"Could not load window icon: {e}")

        # central address list
        self.scanned_addresses = []

        # Initialize pygame mixer for sound with error handling
        try:
            pygame.mixer.init()
            self.audio_available = True
            # Load sound effect once
            try:
                self.laser_sound = pygame.mixer.Sound("laser.mp3")
            except Exception as e:
                print("Could not load laser.mp3:", e)
                self.laser_sound = None
        except Exception as e:
            print("Audio initialization failed:", e)
            self.audio_available = False
            self.laser_sound = None

        # hardware init
        GPIO.setmode(GPIO.BCM)
        
        # Set up finish button pins
        self.lane_finish_pins = {
            1: 7,   # Lane 1 finish button uses GPIO 7
            2: 8    # Lane 2 finish button uses GPIO 8
        }
        
        # Lane finish state tracking
        self.lane_finished = {1: False, 2: False}
        self.lane_finish_times = {1: 0.0, 2: 0.0}
        self.winner_determined = False
        
        # Set up beam block detection pins
        # Each pin corresponds to a specific lane (RJ45 port)
        self.lane_to_gpio = {
            1: 16,  # Lane 1 (J1) uses GPIO 16 for beam block detection
            2: 19,  # Lane 2 (J2) uses GPIO 19 for beam block detection
            3: 20,  # Lane 3 (J3) uses GPIO 20 for beam block detection
            4: 21   # Lane 4 (J4) uses GPIO 21 for beam block detection
        }
        
        # Set up i2c routing pins
        self.i2c_routing_pins = (5, 6)
        
        # Only set up GPIO pins in real mode
        if not TEST_MODE:
            GPIO.setmode(GPIO.BCM)
            
            # Set up all GPIO pins
            for pin in self.lane_to_gpio.values():
                GPIO.setup(pin, GPIO.IN)
                
            # Set up finish button pins with pull-down resistors
            for pin in self.lane_finish_pins.values():
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                
            for p in self.i2c_routing_pins:
                GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
                
            # Default to Lane 1 (J1)
            self.set_i2c_route(1)
    
        # Initialize I2C bus normally without custom clock speed
        try:
            self.bus = smbus.SMBus(1)  # Use default I2C bus
            set_bus(self.bus)
        except Exception as e:
            print(f"I2C initialization failed: {e}")
            if not TEST_MODE:
                TEST_MODE = True
                print("Falling back to test mode")

        # setup module state storage
        self.module_frames = {}
        self.module_states = {}

        # power calibration storage
        self.calib_frames        = {}
        self.calib_on            = {}
        self.calib_color         = {}
        self.calib_current       = {}
        self.selected_calib_addr = None

        # game timer storage
        self.timer_window    = None
        self.timer_label     = None
        self._timer_updater  = None
        self._last_elapsed   = 0.0
        self._poll_interval  = 0.2
        self._penalty_flash_id = None

        # Add lane assignments dictionary
        self.lane_assignments = {}  # {addr: lane_number}
    
        # Add separate timers for each lane
        self._lane1_timer = 0.0
        self._lane2_timer = 0.0

        # Add a list to store dynamically created UI elements
        self.dynamic_ui_elements = []

        # build UI
        self._build_main_menu()
        self._build_setup_mode()
        self._build_game_mode()
        self._build_power_calibration_mode()
        self.show_main_menu()

    # ---------- Main Menu ----------
    def _build_main_menu(self):
        self.main_menu = tk.Frame(self)

        tk.Label(
            self.main_menu,
            text="OPTICA MQ - LASER MAZE CONTROL\nver. 1.3.5 (2025)",
            font=('Arial', 34, 'bold'),
            fg='#333'
        ).pack(pady=(20,10))

        try:
            logo = tk.PhotoImage(file="logo.png").subsample(25, 25)
            lbl_logo = tk.Label(self.main_menu, image=logo, bg='white')
            lbl_logo.image = logo
            lbl_logo.pack(pady=(0,20))
        except Exception:
            pass

        btn_font = ('Arial', 16)
        tk.Button(self.main_menu, text="Setup Mode", width=60,
                  font=btn_font, command=self.show_setup_mode).pack(pady=10)
        tk.Button(self.main_menu, text="Game Mode", width=60,
                  font=btn_font, command=self.show_game_mode).pack(pady=10)
        tk.Button(self.main_menu, text="Power Calib.", width=60,
                  font=btn_font, command=self.show_power_calibration_mode).pack(pady=10)
        tk.Button(self.main_menu,text="Exit",width=60,font=('Arial', 16),
                  bg='firebrick',fg='white',command=self.exit_app).pack(pady=10)
        
    # ---------- Setup Mode ----------
    def _build_setup_mode(self):
        self.setup_frame = tk.Frame(self)
        
        # Add instruction label for automatic lane detection
        instruction_frame = tk.Frame(self.setup_frame, bd=1, relief=tk.GROOVE)
        instruction_frame.pack(pady=10, padx=10, fill='x')
        
        instructions = tk.Label(instruction_frame, justify='left', anchor='w',
                             text="Automatic Lane Detection:\n" +
                                  "• Modules are automatically assigned to lanes based on physical connections\n" +
                                  "• Lane 1 = RJ45 Port J1, Lane 2 = J2, Lane 3 = J3, Lane 4 = J4\n" +
                                  "• Click on any module to see details or toggle its state")
        instructions.pack(pady=10, padx=10, fill='x')

        tk.Button(self.setup_frame, text="Scan All Modules", width=20,
                  command=self.scan_modules).pack(pady=(10,5))

        self.module_container = tk.Frame(self.setup_frame)
        self.module_container.pack(pady=5, padx=10, fill='x')

        ctl = tk.Frame(self.setup_frame)
        tk.Button(ctl, text="Turn All Off", width=16,
                  command=self.turn_all_off).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(ctl, text="Turn All On", width=16,
                  command=self.turn_all_on).grid(row=0, column=1, padx=5, pady=5)
        ctl.pack(pady=10)

        # Create container for voltage readings that persists
        self.voltage_container = tk.Frame(self.setup_frame)
        self.voltage_container.pack(pady=5, fill='x')
        
        # Track if continuous monitoring is active
        self.monitoring_active = False
        
        # Create a frame for monitoring controls
        monitor_controls = tk.Frame(self.setup_frame)
        monitor_controls.pack(pady=5)
        
        # Monitor button
        self.monitor_button = tk.Button(monitor_controls, text="Start PD Monitor", 
                                      width=20, command=self.toggle_pd_monitoring)
        self.monitor_button.pack(side='left', padx=5)
        
        # Clear button - initially disabled
        self.clear_voltages_button = tk.Button(monitor_controls, text="Clear Voltages",
                                             width=20, command=self.clear_voltage_display,
                                             state='disabled')
        self.clear_voltages_button.pack(side='left', padx=5)
        
        tk.Button(self.setup_frame, text="Reset Modules", width=20,
                  command=self.reset_modules).pack(pady=5)
        tk.Button(self.setup_frame, text="Back", width=20,
                  command=self.show_main_menu).pack(pady=(0,10))

    def _get_lane_color(self, lane_num):
        """Get background color for lane assignment"""
        if lane_num == 1:
            return '#87CEEB'  # Light blue
        elif lane_num == 2:
            return '#98FB98'  # Light green
        elif lane_num == 3:
            return '#FFCC99'  # Light orange
        elif lane_num == 4:
            return '#FFB6C1'  # Light pink
        return 'gray'  # Unassigned
        
    def _format_module_address(self, addr):
        """Format a module address for display, showing decimal format"""
        return f"{addr:d}"

    def clear_voltage_display(self):
        """Clear the voltage display area"""
        # Stop monitoring if active
        if self.monitoring_active:
            self.monitoring_active = False
            self.monitor_button.config(text="Start PD Monitor", bg='#F0F0F0')

        if hasattr(self, 'voltage_labels'):
            # Clear all labels
            for label in self.voltage_labels.values():
                label.destroy()
            self.voltage_labels.clear()
            
            # Clear any header labels
            for widget in self.voltage_container.winfo_children():
                widget.destroy()
                
            # Remove voltage_labels attribute
            delattr(self, 'voltage_labels')
            
        # Disable clear button until monitoring is started again
        self.clear_voltages_button.config(state='disabled')

    def toggle_pd_monitoring(self):
        """Toggle continuous PD voltage monitoring"""
        self.monitoring_active = not self.monitoring_active
    
        if self.monitoring_active:
            self.monitor_button.config(text="Stop PD Monitor", bg='red')
            self.clear_voltages_button.config(state='normal')  # Enable clear button
            
            # Create labels only once when starting monitoring
            if not hasattr(self, 'voltage_labels'):
                # Clear existing widgets
                for widget in self.voltage_container.winfo_children():
                    widget.destroy()
                    
                # Create centered container
                centered_container = tk.Frame(self.voltage_container)
                centered_container.pack(expand=False)
                
                # Add header once
                tk.Label(centered_container, 
                        text="Live Detector Voltages", 
                        font=('Arial', 14, 'bold')).pack(pady=(0,10))
                
                # Create grid container for voltage labels
                grid_container = tk.Frame(centered_container)
                grid_container.pack(pady=5)
                
                # Create dictionary to store labels
                self.voltage_labels = {}
                
                # Calculate grid layout - max 5 rows, then add columns as needed
                max_rows = 5
                num_modules = len(self.scanned_addresses)
                cols_needed = (num_modules + max_rows - 1) // max_rows  # Ceiling division
                
                # Create frames and labels for each module in a grid layout
                for idx, addr in enumerate(self.scanned_addresses):
                    row = idx % max_rows
                    col = idx // max_rows
                    
                    label = tk.Label(
                        grid_container,
                        text="",  # Empty text initially
                        font=('Arial', 11),
                        width=18,  # Reduced width
                        padx=5,
                        pady=3,
                        relief='ridge',
                        borderwidth=1
                    )
                    label.grid(row=row, column=col, padx=3, pady=2, sticky='ew')
                    self.voltage_labels[addr] = label
        
            self.update_pd_readings()
        else:
            self.monitor_button.config(text="Start PD Monitor", bg='#F0F0F0')
            # Keep clear button enabled after stopping monitoring

    def update_pd_readings(self):
        """Update PD voltage readings continuously"""
        if not self.monitoring_active:
            return
            
        if not self.scanned_addresses:
            self.monitoring_active = False
            self.monitor_button.config(text="Start PD Monitor", bg='#F0F0F0')
            return

        # Update only the text and colors of existing labels
        if TEST_MODE:
            for addr in self.scanned_addresses:
                voltage = READ_PD_VOLT(addr)
                bg_color = '#90EE90' if voltage > 1.2 else '#FFB6C6'
                
                label = self.voltage_labels[addr]
                # Use proper address formatting function that shows decimal format
                addr_display = self._format_module_address(addr)
                label.config(
                    text=f"Module {addr_display}: {voltage:.2f}V",
                    bg=bg_color
                )
        else:
            # Group modules by lane
            lane_modules = {}
            for addr in self.scanned_addresses:
                lane = self.lane_assignments.get(addr, 1)  # Default to lane 1 if not assigned
                if lane not in lane_modules:
                    lane_modules[lane] = []
                lane_modules[lane].append(addr)
            
            # Process each lane
            for lane, modules in lane_modules.items():
                # Set I2C routing to this lane
                self.set_i2c_route(lane)
                
                # Read voltages for all modules in this lane
                for addr in modules:
                    voltage = READ_PD_VOLT(addr)
                    bg_color = '#90EE90' if voltage > 1.2 else '#FFB6C6'
                    
                    label = self.voltage_labels[addr]
                    # Use proper address formatting function that shows decimal format
                    addr_display = self._format_module_address(addr)
                    label.config(
                        text=f"Mod {addr_display} (L{lane}): {voltage:.2f}V",
                        bg=bg_color
                    )

        # Schedule next update
        if self.monitoring_active:
            self.after(100, self.update_pd_readings)

    def scan_modules(self):
        for w in self.module_container.winfo_children():
            w.destroy()
        self.module_frames.clear()
        self.module_states.clear()

        # Reset lane assignments
        self.lane_assignments = {}
        
        # Show scanning progress
        progress = tk.Toplevel(self)
        progress.title("Scanning Modules")
        progress.geometry("300x100")
        tk.Label(progress, text="Scanning for modules...", font=('Arial', 12)).pack(pady=10)
        progress_var = tk.IntVar()
        progress_bar = tk.ttk.Progressbar(progress, variable=progress_var, maximum=100)
        progress_bar.pack(fill='x', padx=20)
        progress.update()
        
        # Scan modules directly without retries or extra delays
        all_addresses = []
        lane_modules = {}  # Dictionary to group modules by lane
        
        if TEST_MODE:
            # In test mode, simulate modules on different lanes
            # Assign first half of addresses to lane 1, second half to lane 2
            simulated_addresses = SCAN_I2C_BUS()
            
            # Split addresses between lanes
            middle = len(simulated_addresses) // 2
            lane1_addresses = simulated_addresses[:middle]
            lane2_addresses = simulated_addresses[middle:]
            
            # Assign lanes
            for addr in lane1_addresses:
                self.lane_assignments[addr] = 1
                if 1 not in lane_modules:
                    lane_modules[1] = []
                lane_modules[1].append(addr)
                
            for addr in lane2_addresses:
                self.lane_assignments[addr] = 2
                if 2 not in lane_modules:
                    lane_modules[2] = []
                lane_modules[2].append(addr)
                
            all_addresses = simulated_addresses
            progress_var.set(100)  # Complete progress bar
            
        else:
            # In real mode, scan only lanes 1 and 2 (J1, J2)
            for lane_idx, lane in enumerate(range(1, 3)):  # <--- changed: only J1 and J2
                progress_var.set(lane_idx * 50)  # 50% per lane
                progress.update()
                
                # Set I2C routing to this lane
                self.set_i2c_route(lane)
                
                # Direct scan without retries or slow scan options
                lane_addresses = SCAN_I2C_BUS()
                
                if lane_addresses:
                    lane_modules[lane] = lane_addresses
                    
                    # Add lane information to addresses found
                    for addr in lane_addresses:
                        if addr not in all_addresses:  # Avoid duplicates
                            all_addresses.append(addr)
                            # Assign module to the current lane
                            self.lane_assignments[addr] = lane
    
        self.scanned_addresses = all_addresses
        
        # Close progress window
        progress.destroy()
                
        if not self.scanned_addresses:
            messagebox.showinfo("Scan Result", "No I²C devices found.")
            return
        
        # Initialize test voltages for scanned addresses in test mode
        if TEST_MODE:
            for addr in self.scanned_addresses:
                test_voltage_gen.set_base_voltage(addr, 2.0)
    
        # Create module display grouped by lane
        row = 0
        
        # Display lanes in order
        for lane in sorted(lane_modules.keys()):
            # Add lane header
            lane_header = tk.Frame(self.module_container, bg=self._get_lane_color(lane))
            lane_header.grid(row=row, column=0, columnspan=6, sticky='ew', padx=5, pady=5)
            
            # Lane header with lane name and actions
            header_content = tk.Frame(lane_header, bg=self._get_lane_color(lane))
            header_content.pack(fill='x', expand=True)
            
            lane_label = tk.Label(header_content, 
                                text=f"Lane {lane} (J{lane})", 
                                font=('Arial', 12, 'bold'),
                                bg=self._get_lane_color(lane))
            lane_label.pack(side=tk.LEFT, pady=5, padx=10)
            
            # Add buttons for lane actions
            actions_frame = tk.Frame(header_content, bg=self._get_lane_color(lane))
            actions_frame.pack(side=tk.RIGHT, padx=10)
            
            toggle_button = tk.Button(actions_frame, text="Toggle Lane", 
                                    command=lambda l=lane: self.toggle_lane_modules(l))
            toggle_button.pack(side=tk.LEFT, padx=5)
            
            row += 1
            
            # Add modules for this lane
            module_addrs = lane_modules[lane]
            for idx, addr in enumerate(module_addrs):
                r, c = divmod(idx, 6)  # Changed from 4 to 6 columns
                f = tk.Frame(self.module_container, width=60, height=60,
                             bg='red', relief='raised', bd=2, cursor='hand2')
                f.grid(row=row + r, column=c, padx=5, pady=5)
                lbl = tk.Label(f, text=f"{self._format_module_address(addr)}", bg='red', fg='white')
                lbl.place(relx=0.5, rely=0.5, anchor='center')
                f.bind("<Button-1>", lambda e, a=addr: self.on_module_click(a))
                lbl.bind("<Button-1>", lambda e, a=addr: self.on_module_click(a))
                self.module_frames[addr] = (f, lbl)
                self.module_states[addr] = False
            
            # Update row counter for next lane
            row += r + 1
            
            # Add a separator between lanes
            if lane < max(lane_modules.keys()):
                separator = tk.Frame(self.module_container, height=2, bg='black')
                separator.grid(row=row, column=0, columnspan=6, sticky='ew', padx=5, pady=5)
                row += 1
                
        # Show summary message
        lane_summary = ", ".join([f"Lane {lane}: {len(modules)} modules" for lane, modules in lane_modules.items()])
        messagebox.showinfo("Scan Complete", f"Found {len(self.scanned_addresses)} modules\n{lane_summary}")

    def on_module_click(self, addr):
        # Ensure I2C is routed to the correct lane if this module has a lane assignment
        if not TEST_MODE and addr in self.lane_assignments:
            lane = self.lane_assignments[addr]
            self.set_i2c_route(lane)
            time.sleep(0.05)  # Short delay after routing
        
        success = False
        
        # Toggle the module state
        if TEST_MODE:
            # In test mode, use the original functions
            if self.module_states[addr]:
                TURN_ONLY_ONE_OFF(addr)
                success = True
            else:
                TURN_ONLY_ONE_ON(addr)
                success = True
        else:
            # In real mode, use direct I2C commands with correct command codes
            try:
                if self.module_states[addr]:
                    # Turn off - use CMD_TURN_OFF (0x04)
                    self.bus.write_byte(addr, 0x04)  # Correct OFF command
                    success = True
                else:
                    # Turn on - use CMD_TURN_ON (0x03)
                    self.bus.write_byte(addr, 0x03)  # Correct ON command
                    success = True
            except Exception as e:
                print(f"I2C error with module {addr:02X}: {e}")
                success = False
    
        # Only update UI if the command was successful
        if success:
            col, st = ('red', False) if self.module_states[addr] else ('green', True)
            f, lbl = self.module_frames[addr]
            f.config(bg=col); lbl.config(bg=col)
            self.module_states[addr] = st
        else:
            messagebox.showerror("Communication Error", f"Failed to communicate with module {addr:02X}")

    def turn_all_off(self):
        addrs = self.scanned_addresses
        if not addrs:
            messagebox.showwarning("No Devices", "Scan first.")
            return
            
        if TEST_MODE:
            TURN_ALL_OFF(addrs)
        else:
            # Turn off modules lane by lane
            lane_modules = {}
            
            # Group modules by lane
            for addr in addrs:
                lane = self.lane_assignments.get(addr, 1)  # Default to lane 1 if not assigned
                if lane not in lane_modules:
                    lane_modules[lane] = []
                lane_modules[lane].append(addr)
            
            # Process each lane
            for lane, modules in lane_modules.items():
                # Set I2C routing to this lane
                self.set_i2c_route(lane)
                time.sleep(0.1)  # Add delay after switching lanes
                
                # Use the proper function from i2cfunction_AO_Test.py to turn off modules
                TURN_ALL_OFF(modules)
    
        # Update UI
        for addr, (f, lbl) in self.module_frames.items():
            f.config(bg='red'); lbl.config(bg='red')
            self.module_states[addr] = False
        
        messagebox.showinfo("Action", "All lasers off.")

    def turn_all_on(self):
        addrs = self.scanned_addresses
        if not addrs:
            messagebox.showwarning("No Devices", "Scan first.")
            return
            
        if TEST_MODE:
            TURN_ALL_ON(addrs)
        else:
            # Turn on modules lane by lane
            lane_modules = {}
            
            # Group modules by lane
            for addr in addrs:
                lane = self.lane_assignments.get(addr, 1)  # Default to lane 1 if not assigned
                if lane not in lane_modules:
                    lane_modules[lane] = []
                lane_modules[lane].append(addr)
            
            # Process each lane
            for lane, modules in lane_modules.items():
                # Set I2C routing to this lane
                self.set_i2c_route(lane)
                time.sleep(0.1)  # Add delay after switching lanes
                
                # Use the proper function from i2cfunction_AO_Test.py to turn on modules
                TURN_ALL_ON(modules)
    
        # Update UI
        for addr, (f, lbl) in self.module_frames.items():
            f.config(bg='green'); lbl.config(bg='green')
            self.module_states[addr] = True
            
        messagebox.showinfo("Action", "All lasers on.")
        
    def toggle_lane_modules(self, lane_num):
        """Toggle all modules in a specific lane"""
        # Get all addresses for this lane
        lane_addrs = [addr for addr, lane in self.lane_assignments.items() if lane == lane_num]
        
        if not lane_addrs:
            messagebox.showwarning("No Devices", f"No modules found in Lane {lane_num}.")
            return
            
        # Check if all modules in this lane are on
        all_on = all(self.module_states.get(addr, False) for addr in lane_addrs)
        
        # Set I2C routing to this lane
        if not TEST_MODE:
            self.set_i2c_route(lane_num)
        
        # Toggle modules based on current state
        if all_on:
            # Turn all off
            if TEST_MODE:
                for addr in lane_addrs:
                    TURN_ONLY_ONE_OFF(addr)
            else:
                TURN_ALL_OFF(lane_addrs)
                
            # Update UI
            for addr in lane_addrs:
                f, lbl = self.module_frames[addr]
                f.config(bg='red'); lbl.config(bg='red')
                self.module_states[addr] = False
                
            messagebox.showinfo("Action", f"All lasers in Lane {lane_num} turned off.")
        else:
            # Turn all on
            if TEST_MODE:
                for addr in lane_addrs:
                    TURN_ONLY_ONE_ON(addr)
            else:
                TURN_ALL_ON(lane_addrs)
                
            # Update UI
            for addr in lane_addrs:
                f, lbl = self.module_frames[addr]
                f.config(bg='green'); lbl.config(bg='green')
                self.module_states[addr] = True
                
            messagebox.showinfo("Action", f"All lasers in Lane {lane_num} turned on.")

    def reset_modules(self):
        self.module_frames.clear()
        self.module_states.clear()
        for w in self.module_container.winfo_children():
            w.destroy()
        messagebox.showinfo("Reset Complete", "Scanned data cleared.")

    def beam_block_scan(self):
        """Check detector voltages for all modules"""
        if not self.scanned_addresses:
            messagebox.showwarning("No Modules", "Please scan for modules first")
            return

        # Create popup window
        popup = tk.Toplevel(self)
        popup.title("Detector Voltages")
        popup.geometry("300x400")

        # Create scrollable frame
        container = tk.Frame(popup)
        container.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Add header
        tk.Label(container, text="Module Detector Voltages", font=('Arial', 14, 'bold')).pack(pady=(0,10))

        # Check each module
        for addr in self.scanned_addresses:
            frame = tk.Frame(container)
            frame.pack(fill='x', pady=2)
            
            # Get voltage reading
            voltage = READ_PD_VOLT(addr)
            
            # Determine color based on threshold
            bg_color = '#90EE90' if voltage > 1.2 else '#FFB6C6'  # Light green or light red
            
            # Create label with colored background
            label = tk.Label(
                frame, 
                text=f"Module {addr:02X}: {voltage:.2f}V",
                font=('Arial', 12),
                bg=bg_color,
                width=25,
                pady=5
            )
            label.pack(fill='x')

        # Add close button
        tk.Button(
            container,
            text="Close",
            command=popup.destroy,
            width=10
        ).pack(pady=10)

    # ---------- Game Mode ----------
    def _build_game_mode(self):
        self.game_frame = tk.Frame(self)
        
        # Control buttons only in main window
        tk.Button(self.game_frame, text="Start Game", width=20,
                  command=self.start_game).pack(pady=5)
        tk.Button(self.game_frame, text="Stop Game", width=20,
                  command=self.stop_game).pack(pady=5)
                  
        # Add test mode buttons container frame
        if TEST_MODE:
            test_buttons_frame = tk.Frame(self.game_frame)
            test_buttons_frame.pack(pady=10)
            
            # Add label
            tk.Label(test_buttons_frame, text="Test Mode Finish Buttons:", 
                    font=('Arial', 10, 'bold')).pack(pady=(5,10))
            
            # Add buttons for each lane
            btn_frame = tk.Frame(test_buttons_frame)
            btn_frame.pack()
            
            tk.Button(btn_frame, text="Lane 1 Finish", width=15, bg='#87CEEB',
                     command=lambda: self.handle_lane_finish(1)).grid(row=0, column=0, padx=10)
            tk.Button(btn_frame, text="Lane 2 Finish", width=15, bg='#98FB98',
                     command=lambda: self.handle_lane_finish(2)).grid(row=0, column=1, padx=10)
            
            # Add reset button
            tk.Button(test_buttons_frame, text="Reset Finish Status", width=20,
                     command=self.reset_finish_status).pack(pady=10)
        
        tk.Button(self.game_frame, text="Back", width=20,
                  command=self.show_main_menu).pack(pady=(20,10))

    def reset_finish_status(self):
        """Reset the lane finish status for testing"""
        self.lane_finished = {1: False, 2: False}
        self.lane_finish_times = {1: 0.0, 2: 0.0}
        self.winner_determined = False
        
        # Clean up any UI elements from previous games
        self._cleanup_game_ui()
        
        # If timer window exists, update the displays with current timer values
        if hasattr(self, 'lane1_timer') and hasattr(self, 'lane2_timer'):
            self.lane1_timer.config(text=f"{self._lane1_timer:.2f} s")
            self.lane2_timer.config(text=f"{self._lane2_timer:.2f} s")
            
        messagebox.showinfo("Reset", "Lane finish status has been reset")

    def start_game(self):
        """Start game with countdown timer window"""
        # Reset any leftover state from previous game so we always start fresh
        self._reset_for_new_game()

        # Reset finish status and flags (again, for clarity)
        self.lane_finished = {1: False, 2: False}
        self.lane_finish_times = {1: 0.0, 2: 0.0}
        self.winner_determined = False

        # Clean up any UI elements from previous games
        # (kept for compatibility; _reset_for_new_game already handles cleanup)
        self._cleanup_game_ui()

        if not self.scanned_addresses:
            messagebox.showwarning("No Modules", "Please scan for modules first")
            return

        # Turn on all lasers per-lane and check alignment
        if TEST_MODE:
            TURN_ALL_ON(self.scanned_addresses)
            time.sleep(1)
        else:
            # Group modules by lane and turn on per-lane (ensure routing selected)
            lane_modules = {}
            for addr in self.scanned_addresses:
                lane = self.lane_assignments.get(addr, 1)
                lane_modules.setdefault(lane, []).append(addr)
            for lane, modules in lane_modules.items():
                self.set_i2c_route(lane)
                TURN_ALL_ON(modules)
            time.sleep(1)  # Give time for lasers to stabilize

        # Check each module's PD voltage by lane
        misaligned_modules = []
        
        if TEST_MODE:
            for addr in self.scanned_addresses:
                voltage = READ_PD_VOLT(addr)
                if voltage < 1.2:
                    lane_info = f" (Lane {self.lane_assignments.get(addr, '?')})" if addr in self.lane_assignments else ""
                    misaligned_modules.append(f"Module {self._format_module_address(addr)}{lane_info}")
        else:
            # Group modules by lane
            lane_modules = {}
            for addr in self.scanned_addresses:
                lane = self.lane_assignments.get(addr, 1)  # Default to lane 1 if not assigned
                if lane not in lane_modules:
                    lane_modules[lane] = []
                lane_modules[lane].append(addr)
            
            # Check alignment lane by lane
            for lane, modules in lane_modules.items():
                # Set I2C routing to this lane
                self.set_i2c_route(lane)
                
                # Check each module in this lane
                for addr in modules:
                    voltage = READ_PD_VOLT(addr)
                    if voltage < 1.2:
                        misaligned_modules.append(f"Module {self._format_module_address(addr)} (Lane {lane})")
        
        # If any modules are misaligned, show error and abort
        if misaligned_modules:
            # Turn all off per-lane (routing per-lane)
            if TEST_MODE:
                TURN_ALL_OFF(self.scanned_addresses)
            else:
                lane_modules2 = {}
                for addr in self.scanned_addresses:
                    lane = self.lane_assignments.get(addr, 1)
                    lane_modules2.setdefault(lane, []).append(addr)
                for lane, modules in lane_modules2.items():
                    self.set_i2c_route(lane)
                    TURN_ALL_OFF(modules)

            messagebox.showerror(
                "Cannot Start Game - Alignment Error",
                f"The following lasers are misaligned:\n{', '.join(misaligned_modules)}\n\n"
                "Please realign these modules before starting the game."
            )
            return

        # All modules aligned - proceed with game start
        if not self.timer_window or not tk.Toplevel.winfo_exists(self.timer_window):
            self.timer_window = tk.Toplevel(self)
            self.timer_window.title("Race Timers")
            self.timer_window.geometry("1200x600")
            
            # Store frame references
            self.left_frame = tk.Frame(self.timer_window, bg='black')
            self.left_frame.pack(side=tk.LEFT, expand=True, fill='both')
            
            self.right_frame = tk.Frame(self.timer_window, bg='black')
            self.right_frame.pack(side=tk.RIGHT, expand=True, fill='both')
            
            # Store header references
            self.lane1_header = tk.Label(self.left_frame, text="LANE 1", 
                                   font=('Arial', 48, 'bold'),
                                   fg='white', bg='black')
            self.lane1_header.pack(pady=20)
            
            self.lane2_header = tk.Label(self.right_frame, text="LANE 2", 
                                   font=('Arial', 48, 'bold'),
                                   fg='white', bg='black')
            self.lane2_header.pack(pady=20)
            
            # Create container frames for timers to maintain centering
            timer1_container = tk.Frame(self.left_frame, bg='black')
            timer1_container.pack(expand=True)
            
            timer2_container = tk.Frame(self.right_frame, bg='black')
            timer2_container.pack(expand=True)
            
            # Timer labels in containers
            self.lane1_timer = tk.Label(timer1_container, text="0.00",
                                  font=('Arial', 120, 'bold'),
                                  fg='white', bg='black',
                                  width=6)  # Fixed width to prevent jumping
            self.lane1_timer.pack()
            
            self.lane2_timer = tk.Label(timer2_container, text="0.00",
                                  font=('Arial', 120, 'bold'),
                                  fg='white', bg='black',
                                  width=6)  # Fixed width to prevent jumping
            self.lane2_timer.pack()

        # Play countdown sound if available
        if self.audio_available:
            try:
                pygame.mixer.music.load("countdown.mp3")
            except Exception as e:
                print("Could not play countdown.mp3:", e)

        # Reset timers and tracking variables
        self._last_elapsed = 0.0
        self._lane1_timer = 0.0
        self._lane2_timer = 0.0
        if TEST_MODE:
            GAME_MODE_ON(self.scanned_addresses)
        else:
            # Activate game mode for each lane
            lane_modules = {}
            for addr in self.scanned_addresses:
                lane = self.lane_assignments.get(addr, 1)  # Default to lane 1 if not assigned
                if lane not in lane_modules:
                    lane_modules[lane] = []
                lane_modules[lane].append(addr)
            
            # Process each lane
            for lane, modules in lane_modules.items():
                self.set_i2c_route(lane)
                GAME_MODE_ON(modules)
                
        self.countdown(3)
        if self.audio_available:
            pygame.mixer.music.play()

    def countdown(self, n):
        """Countdown on both lane displays"""
        cmap = {3:'red', 2:'orange', 1:'green'}
        if n > 0:
            c = cmap[n]
            # Change entire frames and labels
            self.left_frame.config(bg=c)
            self.right_frame.config(bg=c)
            self.lane1_timer.config(text=str(n), fg='white', bg=c)
            self.lane2_timer.config(text=str(n), fg='white', bg=c)
            self.lane1_header.config(bg=c)  # Change header backgrounds too
            self.lane2_header.config(bg=c)
            self.timer_window.after(1000, lambda: self.countdown(n-1))
        else:
            self.left_frame.config(bg='green')
            self.right_frame.config(bg='green')
            self.lane1_timer.config(text="Go!", fg='white', bg='green')
            self.lane2_timer.config(text="Go!", fg='white', bg='green')
            self.lane1_header.config(bg='green')
            self.lane2_header.config(bg='green')
            START_TIMER()
            self.timer_window.after(2000, self._update_timer)
            # Reset backgrounds after "Go!"
            self.timer_window.after(2500, self._reset_timer_backgrounds)

    def _reset_timer_backgrounds(self):
        """Reset timer window backgrounds to black"""
        self.left_frame.config(bg='black')
        self.right_frame.config(bg='black')
        self.lane1_timer.config(bg='black')
        self.lane2_timer.config(bg='black')
        self.lane1_header.config(bg='black')
        self.lane2_header.config(bg='black')
        
    def set_i2c_route(self, lane):
        """Set GPIO pins 5 and 6 to route I2C to the specified lane/RJ45 port
        
        Lane 1 (J1): Pin 5 Low, Pin 6 Low
        Lane 2 (J2): Pin 5 High, Pin 6 Low
        Lane 3 (J3): Pin 5 Low, Pin 6 High
        Lane 4 (J4): Pin 5 High, Pin 6 High
        """
        if TEST_MODE:
            return
            
        # Ensure lane is valid
        if lane not in self.lane_to_gpio:
            print(f"Invalid lane: {lane}")
            return
            
        # Set routing pins based on lane
        if lane == 1:  # J1
            GPIO.output(self.i2c_routing_pins[0], GPIO.LOW)
            GPIO.output(self.i2c_routing_pins[1], GPIO.LOW)
        elif lane == 2:  # J2
            GPIO.output(self.i2c_routing_pins[0], GPIO.HIGH)
            GPIO.output(self.i2c_routing_pins[1], GPIO.LOW)
        elif lane == 3:  # J3
            GPIO.output(self.i2c_routing_pins[0], GPIO.LOW)
            GPIO.output(self.i2c_routing_pins[1], GPIO.HIGH)
        elif lane == 4:  # J4
            GPIO.output(self.i2c_routing_pins[0], GPIO.HIGH)
            GPIO.output(self.i2c_routing_pins[1], GPIO.HIGH)
        
        # Small delay to ensure routing is established
        time.sleep(0.005)
        
    def check_and_get_blocked_beam(self):
        """Check if any beam is blocked and return the address and penalty seconds.

        This function checks lane GPIO pins (J1/J2). If the lane input indicates a block,
        it routes the I2C to that lane and queries each Arduino using CMD_BEAM_BLOCKED.
        The Arduino's response is interpreted as: 1 = blocked, 0 = clear.
        """
        if not TEST_MODE:
            
            for lane, pin in self.lane_to_gpio.items():
                if lane > 3:
                    continue

                # Only check the GPIO pin for this lane
                lane_signal = GPIO.input(pin)
                
                
                time.sleep(0.002)
                if lane_signal == 0:
                    print(lane_signal)
                    print(pin)
                    self.set_i2c_route(lane)
                    print(f"lane ass items: {self.lane_assignments.items()}")
                    
                    lane_modules = [addr for addr, a_lane in self.lane_assignments.items() if a_lane == lane]
                    
                    print(lane_modules)
                    if not lane_modules:
                        continue

                    for addr in lane_modules:
                        try:
                            print(f"address {addr}")
                            self.set_i2c_route(lane)
                            time.sleep(0.01)
                            self.bus.write_byte(addr, 0xFE)  # CMD_BEAM_BLOCKED
                            time.sleep(0.001)
                            is_blocked = self.bus.read_byte(addr)
                        except Exception:
                            continue

                        # Arduino convention: 1 = blocked, 0 = clear (typical for digitalRead HIGH/LOW)
                        if is_blocked == 1:
                            # Debug: print which lane/module tripped
                            print(f"Beam blocked detected: addr=0x{addr:02X} lane={lane}")
                            penalty_seconds = 3
#                             try:
#                                 self.bus.write_byte(addr, 0xFB)  # CMD_READ_COLOR
#                                 time.sleep(0.001)
#                                 color_code = self.bus.read_byte(addr)
#                                 if color_code == 0x01:
#                                     penalty_seconds = 20
#                                 elif color_code == 0x02:
#                                     penalty_seconds = 5
#                                 elif color_code == 0x04:
#                                     penalty_seconds = 10
#                             except Exception:
#                                 pass
                            return addr, penalty_seconds

        return None

    def _update_timer(self):
        """Update both lane timers"""
        if TEST_MODE:
            # Simulate separate timers for test mode
            if not self.lane_finished[1]:
                self._lane1_timer += self._poll_interval
            if not self.lane_finished[2]:
                self._lane2_timer += self._poll_interval
        else:
            # Read hardware timer but track increments separately for each lane
            elapsed = READ_TIMER()
            # Calculate the time difference since last update
            time_diff = elapsed - self._last_elapsed
            self._last_elapsed = elapsed
            
            # Add the time difference to each lane's timer separately
            if not self.lane_finished[1]:
                self._lane1_timer += time_diff
            if not self.lane_finished[2]:
                self._lane2_timer += time_diff
        
        # Update display for both lanes
        self.lane1_timer.config(text=f"{self._lane1_timer:.2f} s")
        self.lane2_timer.config(text=f"{self._lane2_timer:.2f} s")
        
        # Check for button presses
        if not TEST_MODE:
            for lane, pin in self.lane_finish_pins.items():
                if not self.lane_finished[lane] and GPIO.input(pin) == GPIO.HIGH:
                    self.handle_lane_finish(lane)
        
        # Check for blocked beams
        if TEST_MODE:
            # In test mode, we directly get the blocked address
            blocked_addr = MONITOR_BLOCKED_BEAM(self.scanned_addresses)
            if blocked_addr:
                # Determine which lane was blocked
                if blocked_addr in self.lane_assignments:
                    lane = self.lane_assignments[blocked_addr]
                    self._show_penalty(3, lane)  # Add 3 second penalty to appropriate lane
        else:
            # In real mode, we need to check the GPIO pin and then query each Arduino
            # to find out which one was blocked, then apply penalty to the correct lane
            blocked = self.check_and_get_blocked_beam()
            if blocked:
                addr, penalty_seconds = blocked
                print(f"address: {addr}, pen: {penalty_seconds}")
                print(f"lane assignments: {self.lane_assignments}")
                
                if addr in self.lane_assignments:
                    lane = self.lane_assignments[addr]
                    
                    self._show_penalty(penalty_seconds, lane)
    
        # Schedule next update
        self._timer_updater = self.after(
            int(self._poll_interval * 1000),
            self._update_timer
        )

    def _show_penalty(self, sec, lane):
        """Show penalty for specific lane"""
        # Do not apply penalty flash to a lane that has already finished
        if self.lane_finished.get(lane, False):
            return

        # Add penalty time and prepare UI refs
        if lane == 1:
            self._lane1_timer += sec
            timer_label = self.lane1_timer
            frame = self.left_frame
            header = self.lane1_header
            current_text = f"{self._lane1_timer:.2f} s"
        else:
            self._lane2_timer += sec
            timer_label = self.lane2_timer
            frame = self.right_frame
            header = self.lane2_header
            current_text = f"{self._lane2_timer:.2f} s"

        # Save original header text/fg to restore later
        orig_header_text = header.cget('text')
        orig_header_fg = header.cget('fg')

        # Flash entire side red with temporary "+Ns" text
        frame.config(bg='red')
        timer_label.config(bg='red', text=f"+{sec}s")
        header.config(bg='red')

        # Play sound effect
        if self.audio_available and self.laser_sound:
            try:
                self.laser_sound.play()
            except Exception as e:
                print(f"Could not play laser sound: {e}")

        # Reset display after flash - restore correct timer text and header
        def reset_display():
            # If lane finished during timeout, preserve finished display; otherwise restore timer and header
            frame.config(bg='black')
            timer_label.config(bg='black', text=current_text)
            header.config(bg='black', fg=orig_header_fg, text=orig_header_text)

        self.after(500, reset_display)

    def handle_lane_finish(self, lane):
        """Handle a lane finish button press"""
        if self.lane_finished[lane]:
            return  # Already finished
            
        # Record finish time
        finish_time = self._lane1_timer if lane == 1 else self._lane2_timer
        self.lane_finish_times[lane] = finish_time
        self.lane_finished[lane] = True
        
        # Turn off all lasers for this lane
        # Get all modules assigned to this lane
        lane_modules = [addr for addr, assigned_lane in self.lane_assignments.items() 
                      if assigned_lane == lane]
    
        if lane_modules:
            if TEST_MODE:
                # In test mode, turn off each module individually
                for addr in lane_modules:
                    TURN_ONLY_ONE_OFF(addr)
            else:
                # In real mode, set the I2C route for this lane and turn off all modules
                self.set_i2c_route(lane)
                TURN_ALL_OFF(lane_modules)
                
            # Update UI for the modules if they're displayed in setup mode
            for addr in lane_modules:
                if addr in self.module_states:
                    self.module_states[addr] = False
                    if addr in self.module_frames:
                        f, lbl = self.module_frames[addr]
                        f.config(bg='red')
                        lbl.config(bg='red')
    
        # Update display for the finished lane
        frame = self.left_frame if lane == 1 else self.right_frame
        timer_label = self.lane1_timer if lane == 1 else self.lane2_timer
        header = self.lane1_header if lane == 1 else self.lane2_header
        
        # Change to orange finish display
        frame.config(bg='orange')
        timer_label.config(bg='orange', text=f"{finish_time:.2f} s")
        header.config(bg='orange', text=f"LANE {lane} FINISHED", fg='black')
        
        # Check if both lanes are finished to determine winner
        if all(self.lane_finished.values()) and not self.winner_determined:
            self.determine_winner()

    def determine_winner(self):
        """Determine the winner between lanes and update display"""
        self.winner_determined = True
        
        # Determine which lane has the lower time
        if self.lane_finish_times[1] < self.lane_finish_times[2]:
            winner_lane = 1
        else:
            winner_lane = 2
            
        # Get the corresponding UI elements
        winner_frame = self.left_frame if winner_lane == 1 else self.right_frame
        winner_timer = self.lane1_timer if winner_lane == 1 else self.lane2_timer
        winner_header = self.lane1_header if winner_lane == 1 else self.lane2_header
        
        # Calculate time difference for display
        time_diff = abs(self.lane_finish_times[1] - self.lane_finish_times[2])
        
        # Change winner's display
        winner_frame.config(bg='gold')
        winner_timer.config(bg='gold')
        winner_header.config(bg='gold', text=f"LANE {winner_lane} WINS!", fg='black')
        
        # Add win margin display under the timer
        margin_label = tk.Label(winner_frame, 
                       text=f"Win margin: {time_diff:.2f}s",
                       font=('Arial', 24, 'bold'),
                       fg='black', bg='gold')
        margin_label.pack(pady=10)
        
        # Add the label to our list of dynamic UI elements
        self.dynamic_ui_elements.append(margin_label)
        
        # Remove the popup message - instead rely on the visual display in the timer window
        # messagebox.showinfo("Race Complete", 
        #                   f"Lane {winner_lane} wins!\n"
        #                   f"Time: {self.lane_finish_times[winner_lane]:.2f}s\n"
        #                   f"Margin: {time_diff:.2f}s")

    def stop_game(self):
        # Reset finish status when stopping the game
        self.lane_finished = {1: False, 2: False}
        self.lane_finish_times = {1: 0.0, 2: 0.0}
        self.winner_determined = False
        
        # Stop the game mode for all lanes
        if TEST_MODE:
            STOP_GAME_MODE()
        else:
            # Handle each lane
            for lane in range(1, 3):  # Currently using lanes 1 and 2
                self.set_i2c_route(lane)
                STOP_GAME_MODE()
        
        # Cancel any timer updates
        if getattr(self, '_timer_updater', None):
            self.timer_window.after_cancel(self._timer_updater)
        if getattr(self, '_penalty_flash_id', None):
            self.timer_window.after_cancel(self._penalty_flash_id)
            
        # Update UI if timer window exists
        if hasattr(self, 'lane1_timer') and hasattr(self, 'lane2_timer'):
            self.lane1_timer.config(text="Stopped", font=('Arial',64,'bold'),
                                    fg='white', bg='black')
            self.lane2_timer.config(text="Stopped", font=('Arial',64,'bold'),
                                    fg='white', bg='black')
        self.timer_window.config(bg='black')

    # ---------- Power Calibration Mode ----------
    def _build_power_calibration_mode(self):
        self.calib_frame = tk.Frame(self)

        # top row
        top = tk.Frame(self.calib_frame)
        tk.Button(top, text="Scan Modules",   width=20,
                  command=self.scan_calib_modules).grid(row=0,column=0,padx=5,pady=(10,5))
        tk.Button(top, text="Turn All Off",   width=20,
                  command=self.turn_calib_all_off).grid(row=0,column=1,padx=5,pady=(10,5))
        top.pack()

        # Read All
        tk.Button(self.calib_frame, text="Read All", width=20,
                  command=self.read_calib_all).pack(pady=5)

        # module grid
        self.calib_container = tk.Frame(self.calib_frame)
        self.calib_container.pack(pady=5, padx=10, fill='x')

        # action grid
        btn = tk.Frame(self.calib_frame)
        btn.pack(pady=10)
        tk.Button(btn, text="Turn Selected On",  width=16,
                  command=self.turn_calib_selected_on)\
          .grid(row=0, column=0, padx=5, pady=5)
        tk.Button(btn, text="Turn Selected Off", width=16,
                  command=self.turn_calib_selected_off)\
          .grid(row=0, column=1, padx=5, pady=5)
#         tk.Button(btn, text="Read Colour",       width=16,
#                   command=self.read_calib_color)\
#           .grid(row=1, column=0, padx=5, pady=5)
        tk.Button(btn, text="Read Current",      width=16,
                  command=self.read_calib_current)\
          .grid(row=1, column=1, padx=5, pady=5)
#         tk.Button(btn, text="Set Colour",        width=16,
#                   command=self.set_calib_color)\
#           .grid(row=2, column=0, padx=5, pady=5)
        tk.Button(btn, text="Set Current",       width=16,
                  command=self.set_calib_current)\
          .grid(row=2, column=1, padx=5, pady=5)

        tk.Button(self.calib_frame, text="Back", width=20,
                  command=self.show_main_menu).pack(pady=(0,10))

    def scan_calib_modules(self):
        """Scan only J1/J2, route per-lane, collect unique addresses and populate calibration grid grouped by lane."""
        for w in self.calib_container.winfo_children():
            w.destroy()
        self.calib_frames.clear()
        self.calib_on.clear()
        self.calib_color.clear()
        self.calib_current.clear()
        self.selected_calib_addr = None

        all_addresses = []
        lane_modules = {}

        if TEST_MODE:
            # In test mode, ask the test scanner once and split between lanes 1/2
            simulated = SCAN_I2C_BUS()
            middle = len(simulated) // 2
            lane1 = simulated[:middle]
            lane2 = simulated[middle:]
            for a in lane1:
                self.lane_assignments[a] = 1
                lane_modules.setdefault(1, []).append(a)
                all_addresses.append(a)
            for a in lane2:
                self.lane_assignments[a] = 2
                lane_modules.setdefault(2, []).append(a)
                all_addresses.append(a)
        else:
            # Real mode: scan lanes J1 and J2 only (route per-lane)
            for lane in (1, 2):
                self.set_i2c_route(lane)
                time.sleep(0.01)
                lane_addrs = SCAN_I2C_BUS() or []
                if lane_addrs:
                    for addr in lane_addrs:
                        if addr not in all_addresses:
                            all_addresses.append(addr)
                            self.lane_assignments[addr] = lane
                            lane_modules.setdefault(lane, []).append(addr)

        self.scanned_addresses = all_addresses

        if not self.scanned_addresses:
            messagebox.showinfo("Scan Result", "No I²C devices found.")
            return

        # Init test voltages if needed
        if TEST_MODE:
            for addr in self.scanned_addresses:
                test_voltage_gen.set_base_voltage(addr, 2.0)

        # Build UI grouped by lane (J1/J2)
        row = 0
        for lane in sorted(lane_modules.keys()):
            # Lane header
            lane_header = tk.Frame(self.calib_container, bg=self._get_lane_color(lane))
            lane_header.grid(row=row, column=0, columnspan=6, sticky='ew', padx=5, pady=5)
            header_content = tk.Frame(lane_header, bg=self._get_lane_color(lane))
            header_content.pack(fill='x', expand=True)
            lane_label = tk.Label(header_content, text=f"Lane {lane} (J{lane})", font=('Arial', 12, 'bold'),
                                  bg=self._get_lane_color(lane))
            lane_label.pack(side=tk.LEFT, pady=5, padx=10)
            actions_frame = tk.Frame(header_content, bg=self._get_lane_color(lane))
            actions_frame.pack(side=tk.RIGHT, padx=10)
            toggle_button = tk.Button(actions_frame, text="Toggle Lane",
                                  command=lambda l=lane: self.toggle_lane_modules(l))
            toggle_button.pack(side=tk.LEFT, padx=5)

            row += 1

            module_addrs = lane_modules[lane]
            for idx, addr in enumerate(module_addrs):
                r, c = divmod(idx, 6)
                f = tk.Frame(self.calib_container, width=100, height=100, bg='red', relief='raised', bd=2, cursor='hand2')
                f.grid(row=row + r, column=c, padx=5, pady=5)
                f.pack_propagate(False)
                top = tk.Frame(f, height=50, bg='red')
                top.pack(fill='x')
                lbl_addr = tk.Label(top, text=f"{self._format_module_address(addr)}", bg='red', fg='white')
                lbl_addr.place(relx=0.5, rely=0.5, anchor='center')
                bottom = tk.Frame(f, height=50, bg='gray')
                bottom.pack(fill='x')
#                 lbl_color = tk.Label(bottom, text="Colour:", bg='gray')
#                 lbl_color.place(relx=0.5, rely=0.3, anchor='center')
                lbl_current = tk.Label(bottom, text="Current:", bg='gray')
                lbl_current.place(relx=0.5, rely=1.2, anchor='center')

                def mk(a): return lambda ev: self.select_calib_module(a)
                for wdg in (f, top, bottom, lbl_addr, lbl_current):
                    wdg.bind("<Button-1>", mk(addr))

                self.calib_frames[addr] = (f, top, bottom, lbl_addr, lbl_current)
                self.calib_on[addr] = False
                self.calib_color[addr] = None
                self.calib_current[addr] = None

            # advance row
            row += (len(module_addrs) + 5) // 6 or 1

        lane_summary = ", ".join([f"Lane {lane}: {len(mods)} modules" for lane, mods in lane_modules.items()])
        messagebox.showinfo("Scan Complete", f"Found {len(self.scanned_addresses)} modules\n{lane_summary}")

    def select_calib_module(self, addr):
        self.selected_calib_addr = addr
        for a, (fr, *_ ) in self.calib_frames.items():
            fr.config(relief='raised', bd=2)
        fr, *_ = self.calib_frames[addr]
        fr.config(relief='solid', bd=4)

#     def read_calib_color(self):
#         addr = self.selected_calib_addr
#         if addr is None:
#             messagebox.showwarning("Select Module", "Click a module first."); return
# 
#         # Route I2C to the correct lane for this module (if known)
#         if not TEST_MODE and addr in self.lane_assignments:
#             self.set_i2c_route(self.lane_assignments[addr])
# 
#         # Defensive read: READ_LASER_COLOR may return None or raise
#         try:
#             colour = READ_LASER_COLOR(addr)
#         except Exception as e:
#             print(f"Error reading colour from 0x{addr:02X}: {e}")
#             colour = None
# 
#         _, top, bottom, _, lbl_color, lbl_current = self.calib_frames[addr]
#         if colour:
#             bg = colour.lower()
#             lbl_color_text = f"Colour: {colour}"
#         else:
#             bg = 'gray'
#             lbl_color_text = "Colour: "
#         bottom.config(bg=bg)
#         lbl_color.config(text=lbl_color_text, bg=bg)
#         lbl_current.config(bg=bg)
#         self.calib_color[addr] = colour

    def read_calib_current(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
            
        # Route I2C to the correct lane for this module
        if not TEST_MODE and addr in self.lane_assignments:
            self.set_i2c_route(self.lane_assignments[addr])
            
        current = READ_LASER_CURRENT(addr)
        _, top, bottom, lbl_addr, lbl_current = self.calib_frames[addr]
        lbl_current.config(text=f"Current: {current:.2f} mA")
        self.calib_current[addr] = current

    def read_calib_all(self):
        addrs = list(self.calib_frames.keys())
        if not addrs:
            messagebox.showwarning("No Devices", "Scan modules first."); return
            
        if TEST_MODE:
            for addr in addrs:
#                 colour = READ_LASER_COLOR(addr) or ""
                current = READ_LASER_CURRENT(addr) or 0.0
                _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
#                 bg = colour.lower() if colour else 'gray'
                bottom.config(bg=bg)
#                 lbl_color.config(text=f"Colour: {colour}", bg=bg)
                lbl_current.config(text=f"Current: {current:.2f} mA", bg=bg)
#                 self.calib_color[addr]   = colour
                self.calib_current[addr] = current
        else:
            # Group modules by lane
            lane_modules = {}
            for addr in addrs:
                lane = self.lane_assignments.get(addr, 1)  # Default to lane 1 if not assigned
                if lane not in lane_modules:
                    lane_modules[lane] = []
                lane_modules[lane].append(addr)
            
            # Process each lane
            for lane, modules in lane_modules.items():
                self.set_i2c_route(lane)
                
                # Read info for all modules in this lane
                for addr in modules:
#                     colour = READ_LASER_COLOR(addr) or ""
#                     time.sleep(1)
                    current = READ_LASER_CURRENT(addr) or 0.0
                    time.sleep(1)
                    _, top, bottom, lbl_addr, lbl_current = self.calib_frames[addr]
                    bg = 'gray'
                    bottom.config(bg=bg)
#                     lbl_color.config(text=f"Colour: {colour}", bg=bg)
                    lbl_current.config(text=f"Current: {current:.2f} mA", bg=bg)
#                     self.calib_color[addr]   = colour
                    self.calib_current[addr] = current
                    
        messagebox.showinfo("Action", "Read current for all modules.")

#     def set_calib_color(self):
#         addr = self.selected_calib_addr
#         if addr is None:
#             messagebox.showwarning("Select Module", "Click a module first."); return
#         popup = tk.Toplevel(self)
#         popup.title(f"Set Colour for Module {self._format_module_address(addr)}")
#         tk.Label(popup, text="Select Colour:").pack(pady=(10,0))
#         var = tk.StringVar(popup); var.set(self.calib_color.get(addr, 'RED') or 'RED')
#         tk.OptionMenu(popup, var, 'RED','GREEN','BLUE').pack(pady=5)
#         def apply():
#             c = var.get().lower()
#             
#             # Route I2C to the correct lane for this module
#             if not TEST_MODE and addr in self.lane_assignments:
#                 self.set_i2c_route(self.lane_assignments[addr])
#                 
#             SET_LASER_COLOR(addr, c)
#             _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
#             bottom.config(bg=c)
#             lbl_color.config(text=f"Colour: {c.upper()}", bg=c)
#             lbl_current.config(bg=c)
#             self.calib_color[addr] = c.upper()
#             messagebox.showinfo("Action", f"Set colour of Module {self._format_module_address(addr)} to {c.upper()}.")
#             popup.destroy()
#         tk.Button(popup, text="OK", command=apply).pack(pady=(0,10))

    def set_calib_current(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        val = simpledialog.askinteger("Set Current", "Enter current (mA):", minvalue=1, maxvalue=119)
        if val is None: return
        
        # Route I2C to the correct lane for this module
        if not TEST_MODE and addr in self.lane_assignments:
            self.set_i2c_route(self.lane_assignments[addr])
            
        SET_LASER_CURRENT(addr, val)
        _, top, bottom, lbl_addr, lbl_current = self.calib_frames[addr]
        lbl_current.config(text=f"Current: {val:.2f} mA")
        self.calib_current[addr] = val
        messagebox.showinfo("Action", f"Set current of Module {self._format_module_address(addr)} to {val:.2f} mA.")

    def turn_calib_all_off(self):
        addrs = self.scanned_addresses
        if not addrs:
            messagebox.showwarning("No Devices", "Scan first."); return
            
        if TEST_MODE:
            TURN_ALL_OFF(addrs)
        else:
            # Group modules by lane
            lane_modules = {}
            for addr in addrs:
                lane = self.lane_assignments.get(addr, 1)  # Default to lane 1 if not assigned
                if lane not in lane_modules:
                    lane_modules[lane] = []
                lane_modules[lane].append(addr)
            
            # Process each lane
            for lane, modules in lane_modules.items():
                self.set_i2c_route(lane)
                TURN_ALL_OFF(modules)
                
        for addr, (outer, top, bottom, lbl_addr, lbl_color, lbl_current) in self.calib_frames.items():
            top.config(bg='red')
            lbl_addr.config(bg='red')
            self.calib_on[addr] = False
        messagebox.showinfo("Action", "All lasers turned off.")

    def turn_calib_selected_on(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
            
        # Route I2C to the correct lane for this module
        if not TEST_MODE and addr in self.lane_assignments:
            self.set_i2c_route(self.lane_assignments[addr])
            
        TURN_ONLY_ONE_ON(addr)
        _, top, bottom, lbl_addr, lbl_current = self.calib_frames[addr]
        top.config(bg='green'); lbl_addr.config(bg='green')
        self.calib_on[addr] = True
        messagebox.showinfo("Action", f"Laser at Module {self._format_module_address(addr)} turned on.")

    def turn_calib_selected_off(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
            
        # Route I2C to the correct lane for this module
        if not TEST_MODE and addr in self.lane_assignments:
            self.set_i2c_route(self.lane_assignments[addr])
            
        TURN_ONLY_ONE_OFF(addr)
        _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
        top.config(bg='red'); lbl_addr.config(bg='red')
        self.calib_on[addr] = False
        messagebox.showinfo("Action", f"Laser at Module {self._format_module_address(addr)} turned off.")

    def _reset_for_new_game(self):
        """Fully reset timers, UI and scheduled tasks so a fresh game can start."""
        # Cancel scheduled callbacks safely
        try:
            if getattr(self, '_timer_updater', None):
                try:
                    self.after_cancel(self._timer_updater)
                except Exception:
                    try:
                        self.timer_window.after_cancel(self._timer_updater)
                    except Exception:
                        pass
                self._timer_updater = None
        except Exception:
            pass

        try:
            if getattr(self, '_penalty_flash_id', None):
                try:
                    self.after_cancel(self._penalty_flash_id)
                except Exception:
                    try:
                        self.timer_window.after_cancel(self._penalty_flash_id)
                    except Exception:
                        pass
                self._penalty_flash_id = None
        except Exception:
            pass

        # Remove dynamic UI elements created during the previous game
        for element in list(self.dynamic_ui_elements):
            try:
                if element and getattr(element, 'winfo_exists', lambda: False)():
                    element.destroy()
            except Exception:
                pass
        self.dynamic_ui_elements = []

        # Reset lane headers and timer labels if they exist
        if hasattr(self, 'lane1_header') and getattr(self.lane1_header, 'winfo_exists', lambda: False)():
            self.lane1_header.config(text="LANE 1", fg='white', bg='black')
        if hasattr(self, 'lane2_header') and getattr(self.lane2_header, 'winfo_exists', lambda: False)():
            self.lane2_header.config(text="LANE 2", fg='white', bg='black')

        if hasattr(self, 'left_frame') and getattr(self.left_frame, 'winfo_exists', lambda: False)():
            self.left_frame.config(bg='black')
        if hasattr(self, 'right_frame') and getattr(self.right_frame, 'winfo_exists', lambda: False)():
            self.right_frame.config(bg='black')

        if hasattr(self, 'lane1_timer') and getattr(self.lane1_timer, 'winfo_exists', lambda: False)():
            self.lane1_timer.config(text="0.00", bg='black', fg='white', font=('Arial', 120, 'bold'))
        if hasattr(self, 'lane2_timer') and getattr(self.lane2_timer, 'winfo_exists', lambda: False)():
            self.lane2_timer.config(text="0.00", bg='black', fg='white', font=('Arial', 120, 'bold'))

        # Reset internal timers and flags
        self._last_elapsed = 0.0
        self._lane1_timer = 0.0
        self._lane2_timer = 0.0
        self.lane_finished = {1: False, 2: False}
        self.lane_finish_times = {1: 0.0, 2: 0.0}
        self.winner_determined = False

        # Ensure all lasers are off before starting (route per-lane then call TURN_ALL_OFF)
        try:
            if self.scanned_addresses:
                # Group modules by lane
                lane_modules = {}
                for addr in self.scanned_addresses:
                    lane = self.lane_assignments.get(addr, 1)
                    lane_modules.setdefault(lane, []).append(addr)
                for lane, modules in lane_modules.items():
                    if not TEST_MODE:
                        self.set_i2c_route(lane)
                        time.sleep(0.02)
                    try:
                        TURN_ALL_OFF(modules)
                    except Exception:
                        # best-effort: ignore hardware errors while resetting
                        pass
        except Exception:
            pass

    def _cleanup_game_ui(self):
        """Remove dynamic UI elements and restore timer/header frames to default state."""
        # Cancel scheduled callbacks safely
        try:
            if getattr(self, '_timer_updater', None):
                try:
                    self.after_cancel(self._timer_updater)
                except Exception:
                    try:
                        if getattr(self, 'timer_window', None):
                            self.timer_window.after_cancel(self._timer_updater)
                    except Exception:
                        pass
                self._timer_updater = None
        except Exception:
            pass

        try:
            if getattr(self, '_penalty_flash_id', None):
                try:
                    self.after_cancel(self._penalty_flash_id)
                except Exception:
                    try:
                        if getattr(self, 'timer_window', None):
                            self.timer_window.after_cancel(self._penalty_flash_id)
                    except Exception:
                        pass
                self._penalty_flash_id = None
        except Exception:
            pass

        # Destroy any dynamic UI elements created during the game (e.g. margin_label)
        for element in list(getattr(self, 'dynamic_ui_elements', [])):
            try:
                if element and getattr(element, 'winfo_exists', lambda: False)():
                    element.destroy()
            except Exception:
                pass
        self.dynamic_ui_elements = []

        # Restore headers and frames if they exist
        try:
            if hasattr(self, 'lane1_header') and getattr(self.lane1_header, 'winfo_exists', lambda: False)():
                self.lane1_header.config(text="LANE 1", fg='white', bg='black')
            if hasattr(self, 'lane2_header') and getattr(self.lane2_header, 'winfo_exists', lambda: False)():
                self.lane2_header.config(text="LANE 2", fg='white', bg='black')
        except Exception:
            pass

        try:
            if hasattr(self, 'left_frame') and getattr(self.left_frame, 'winfo_exists', lambda: False)():
                self.left_frame.config(bg='black')
            if hasattr(self, 'right_frame') and getattr(self.right_frame, 'winfo_exists', lambda: False)():
                self.right_frame.config(bg='black')
        except Exception:
            pass

        # Restore timer labels appearance but do not change the stored timer values here
        try:
            if hasattr(self, 'lane1_timer') and getattr(self.lane1_timer, 'winfo_exists', lambda: False)():
                self.lane1_timer.config(bg='black', fg='white', font=('Arial', 120, 'bold'))
            if hasattr(self, 'lane2_timer') and getattr(self.lane2_timer, 'winfo_exists', lambda: False)():
                self.lane2_timer.config(bg='black', fg='white', font=('Arial', 120, 'bold'))
        except Exception:
            pass

        # Ensure winner flag is cleared so new games can start cleanly
        self.winner_determined = False

    # ---------- Frame navigation ----------
    def show_main_menu(self):
        for f in (self.setup_frame, self.game_frame, self.calib_frame):
            f.pack_forget()
        self.main_menu.pack(expand=True)

    def show_setup_mode(self):
        self.main_menu.pack_forget()
        for f in (self.game_frame, self.calib_frame):
            f.pack_forget()
        self.setup_frame.pack(expand=True, fill='both')

    def show_game_mode(self):
        self.main_menu.pack_forget()
        for f in (self.setup_frame, self.calib_frame):
            f.pack_forget()
        self.game_frame.pack(expand=True, fill='both')

    def show_power_calibration_mode(self):
        self.main_menu.pack_forget()
        for f in (self.setup_frame, self.game_frame):
            f.pack_forget()
        self.calib_frame.pack(expand=True, fill='both')

    def exit_app(self):
        """Clean up GPIO and close the app."""
        try:
            GPIO.cleanup()
            TURN_ALL_OFF(self.scanned_addresses)
        except Exception as e:
            print("GPIO.cleanup() failed:", e)
        self.destroy()    # close the Tk window


if __name__ == "__main__":
    app = LaserMazeUI()
    app.mainloop()


