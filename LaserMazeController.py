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
        from opticamqfunclib import *
        import time  # Make sure time is imported
    except ImportError:
        TEST_MODE = True
        print("Hardware imports failed - running in test mode")
        


# ------------------- Laser Maze UI -------------------
class LaserMazeUI(tk.Tk):
    def __init__(self):
        global TEST_MODE  # Add this line to fix the variable scope issue
        super().__init__()
        self.title("Laser Maze Control")
        self.geometry("1024x1024")
        
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
        
#         self.start_game_pin ={11}
        # Set up finish button pins
        self.lane_finish_pins = {
            1: 7,   # Lane 1 finish button uses GPIO 7
            2: 8    # Lane 2 finish button uses GPIO 8
        }
        
        self.shutdown_pin = {
            1: 11,   # Shutdown Pin
        }
        
        # Lane finish state tracking
        self.lane_finished = {1: False, 2: False}
        self.lane_finish_times = {1: 0.0, 2: 0.0}
        self.winner_determined = False
        
        # Set up beam block detection pins
        # Each pin corresponds to a specific lane (RJ45 port)
        self.bus_to_gpio = {
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
            for pin in self.bus_to_gpio.values():
                GPIO.setup(pin, GPIO.IN)
                
            # Set up finish button pins with pull-up resistors (, pull_up_down=GPIO.PUD_UP
            for pin in self.lane_finish_pins.values():
                GPIO.setup(pin, GPIO.IN) 
            # Set up start button pins with pull-up resistors (, pull_up_down=GPIO.PUD_UP
            for pin in self.shutdown_pin.values():
                GPIO.setup(pin, GPIO.IN)
                
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
        self.lane_assignments = {}  # {addr: bus_number}
    
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
            text="OPTICA MQ - LASER MAZE CONTROL\nver. 1.1.0 (2025)",
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
        
        
        instructions = tk.Label(instruction_frame,
                                justify='left',
                                anchor='w',
                                text="Automatic Lane Detection:\n" +
                                  "• Modules are automatically assigned to lanes based on physical connections\n" +
                                  "• Lane 1 , Lane 2 \n" +
                                  "• Click on any module to see details or toggle its state")
        instructions.pack(pady=10, padx=10, fill='x')
        
        
        # ---------- Scan Modules ----------
        tk.Button(self.setup_frame, text="Scan All Modules", width=20,
                  command=self.scan_modules).pack(pady=(10,5))
        
        
        # ---------- Global Turn on and Turn off  ----------
        
        global_ctl = tk.Frame(self.setup_frame)
        global_ctl.pack(pady=10)
        

        tk.Button(global_ctl, text="Turn All Off", width=20,
                  command=self.turn_all_off).pack(side= 'left', padx=5)
        tk.Button(global_ctl, text="Turn All On", width=20,
                  command=self.turn_all_on).pack(side= 'left', padx=5)
        
        
        # ---------- Module Container  ----------
    # Create container for voltage readings that persists
        self.module_container = tk.Frame(self.setup_frame)
        self.module_container.pack(pady=5, padx=10, fill='x')
#
        # ---------- Lane Control Columns   ----------
        ctl = tk.Frame(self.setup_frame)
        ctl.pack(pady=10, fill='x')
        lane_container = tk.Frame(ctl)
        lane_container.pack(anchor='center')
        
        # ----- LANE 1 -----
        
        lane1_col =tk.Frame(lane_container)
        lane1_col.pack(side='left', padx=40, fill='y')
        tk.Label(lane1_col, text ="Lane 1 Controls", font = ("Arial", 12, "bold")).pack(pady=(0,5))
        
        
        tk.Button(lane1_col, text= "Toggle Lane 1", width=20, command= lambda:self.toggle_lane_modules(1)).pack(pady=5)
        tk.Button(lane1_col, text= "Align Lane 1", width=20, command= lambda:self.align_lane(1)).pack(pady=5)
        tk.Button(lane1_col, text= "Set Game Threshold Lane 1", width=20, command= lambda:self.prompt_and_set_lane_threshold(1)).pack(pady=5)
        tk.Button(lane1_col, text= "Read Game Threshold Lane 1", width=20, command= lambda:self.read_lane_game_threshold(1)).pack(pady=5)
        
        
        # ----- LANE 2 -----
        
        lane2_col =tk.Frame(lane_container)
        lane2_col.pack(side='left', padx=40, fill='y')
        tk.Label(lane2_col, text ="Lane 2 Controls", font = ("Arial", 12, "bold")).pack(pady=(0,5))
        
        
        tk.Button(lane2_col, text= "Toggle Lane 2", width=20, command= lambda:self.toggle_lane_modules(2)).pack(pady=5)
        tk.Button(lane2_col, text= "Align Lane 2", width=20, command= lambda:self.align_lane(2)).pack(pady=5)
        tk.Button(lane2_col, text= "Set Game Threshold Lane 2", width=20, command= lambda:self.prompt_and_set_lane_threshold(2)).pack(pady=5)
        tk.Button(lane2_col, text= "Read Game Threshold Lane 2", width=20, command= lambda:self.read_lane_game_threshold(2)).pack(pady=5)
        
        
        # ---------- Voltage Container  ----------
        #         # Create container for voltage readings that persists
        self.voltage_container = tk.Frame(self.setup_frame)
        self.voltage_container.pack(pady=5, fill='x')
        
        
#         # ---------- Continuous Monitoring Controls  ----------
#         self.monitoring_active = False
#         
#         # Create a frame for monitoring controls
#         monitor_controls = tk.Frame(self.setup_frame)
#         monitor_controls.pack(pady=5)
#         
#         # Monitor button
#         self.monitor_button = tk.Button(monitor_controls, text="Start PD Monitor", 
#                                       width=20, command=self.toggle_pd_monitoring)
#         self.monitor_button.pack(side='left', padx=5)
#         
#         # Clear button - initially disabled
#         self.clear_voltages_button = tk.Button(monitor_controls, text="Clear Voltages",
#                                              width=20, command=self.clear_voltage_display,
#                                              state='disabled')
#         self.clear_voltages_button.pack(side='left', padx=5)
        
        # ---------- Reset/Back  ----------
        tk.Button(self.setup_frame, text="Reset Modules", width=20,
                  command=self.reset_modules).pack(pady=5)
        tk.Button(self.setup_frame, text="Back", width=20,
                  command=self.show_main_menu).pack(pady=(0,10))


    def _get_bus_color(self, bus_num):
        """Get background color for bus assignment"""
        if bus_num == 1:
            return '#87CEEB'  # Light blue
        elif bus_num == 2:
            return '#98FB98'  # Light green
        elif bus_num == 3:
            return '#FFCC99'  # Light orange
        elif bus_num == 4:
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

#     def toggle_pd_monitoring(self):
#         """Toggle continuous PD voltage monitoring"""
#         self.monitoring_active = not self.monitoring_active
#     
#         if self.monitoring_active:
#             self.monitor_button.config(text="Stop PD Monitor", bg='red')
#             self.clear_voltages_button.config(state='normal')  # Enable clear button
#             
#             for widget in self.voltage_container.winfo_children():
#                 widget.destroy()
#                 
#             centered_container = tk.Frame(self.voltage_container)
#             centered_container.pack(expand=False)
#             
#             # Add header once
#             tk.Label(centered_container, 
#                     text="Live Detector Voltages", 
#                     font=('Arial', 14, 'bold')).pack(pady=(0,10))
#             
#             # Create grid container for voltage labels
#             grid_container = tk.Frame(centered_container)
#             grid_container.pack(pady=5)
#             
#             # Create dictionary to store labels
#             self.voltage_labels = {}
#             
#             # Create labels only once when starting monitoring
#             if not hasattr(self, 'bus_groups_by_lane') or not self.bus_groups_by_lane:
#                 tk.Label(gr=id_container,
#                          test="No modules detcted.\n Scan first",
#                          font = ("Arial", 12)).pack()
#                 return
#             
#             
#             
#             modules_with_lane =[]
#             for lane, bus_group in self.bus_groups_by_lane.items():
#                 for bus, modules in bus_group.items():
#                     for addr in modules:
#                         modules_with_lane.append((lane, bus, addr))
#                         
#                         
#                 
#                 # Calculate grid layout - max 5 rows, then add columns as needed
#             max_rows = 5
#             num_modules = len(modules_with_lane)
#             cols_needed = (num_modules + max_rows - 1) // max_rows  # Ceiling division
#             
#             # Create frames and labels for each module in a grid layout
#             for idx, (lane, bus, addr) in enumerate(modules_with_lane):
#                 row = idx % max_rows
#                 col = idx // max_rows
#                 
#                 label = tk.Label(
#                     grid_container,
#                     text="",  # Empty text initially
#                     font=('Arial', 11),
#                     width=20,  # Reduced width
#                     padx=5,
#                     pady=3,
#                     relief='ridge',
#                     borderwidth=1
#                 )
#                 label.grid(row=row, column=col, padx=3, pady=2, sticky='ew')
#                 self.voltage_labels[(lane, bus,addr)] = label
#         
#             self.update_pd_readings()
#         else:
#             self.monitor_button.config(text="Start PD Monitor", bg='#F0F0F0')
#             # Keep clear button enabled after stopping monitoring
# 
#     def update_pd_readings(self):
#         """Update PD voltage readings continuously"""
#         if not self.monitoring_active:
#             return
#          # Create labels only once when starting monitoring
#         if not hasattr(self, 'bus_groups_by_lane') or not self.bus_groups_by_lane:
#             self.monitoring_active = False
#             self.monitor_button.config(text="Start PD Monitor", bg='#F0F0F0')
#             return
# 
#         # Update only the text and colors of existing labels
#         for (lane, bus, addr), label in self.voltage_labels.items():
#             try: 
#                 self.set_i2c_route(bus)
#                 voltage = READ_PD_VOLT(addr)
#                     
#                 bg_color = '#90EE90' if voltage > 1.2 else '#FFB6C6'
#                 # Use proper address formatting function that shows decimal format
#                 label.config(
#                     text=f"Mod {addr} (L{lane}): {voltage:.2f}V",
#                     bg=bg_color)
#             except Exception as e:
#                 label.config(text= f"Mod {addr} (L{lane}):ERR" , bg= "FFA07A")
#                 print("errror failed to read PD voltage") 
# 
#         # Schedule next update
#         if self.monitoring_active:
#             self.after(200, self.update_pd_readings)
#             
            
    def align_lane(self,lane):
        """ Open pop up window for aligning a single lane and reading PD voltages """
        
#         print(f"[DEBUG] Align_lane called with lane = {lane}") 
        
        
        
        # Create labels only once when starting monitoring
        if not hasattr(self, 'bus_groups_by_lane') or not self.bus_groups_by_lane:
            messagebox.showwarning( "No modules detcted.\n Scan first")
            return
            
        lane_group= self.bus_groups_by_lane[lane]
        
        for bus, modules in lane_group.items():
            self.set_i2c_route(bus)
            time.sleep(0.05)
            for addr in modules:
                try:
                    self.bus.write_byte(addr, 0x03)
#                     print(f"[Debug] Turned on modules {addr} on bus{bus}")
                except Exception as e:
                    print(f"[DEBUG] Failed to tunr on module {addr}: {e}")
                    
        win = tk.Toplevel()
        win.title(f"Align Lane {lane}") 
        
        win.geometry("420x400")
        
        tk.Label(win, text= f"Align Lane {lane} - all laser ON" , font = ("Arial", 14, "bold")).pack(pady=(10,5))                                                                                   
        container = tk.Frame(win)
        container.pack(fill='both' , expand = True, padx=10, pady=10)
        voltage_labels={}
        
        def read_pd_voltages():
#             print(f"[DEBUG] Reading PD VOltages for lane{lane}")
            for widget in container.winfo_children():
                    widget.destroy()
                
            for bus, modules in lane_group.items():
                self.set_i2c_route(bus)
                time.sleep(0.05)
                for addr in modules:
                    try:
                        voltage = READ_PD_VOLT(addr)
#                         print(f"[DEBUG] Lane {lane} Bus {bus} Module {addr: 02X} Voltage {voltage: .3f}V")
                        row= tk.Frame(container)
                        row.pack(fill ='x', pady=2)
                        tk.Label(row, text =f"Mod {addr} bus({bus})",
                                 width=14, anchor ='w').pack(side='left')
                        lbl = tk.Label(row, text =f"{voltage:.3f}V",
                                 width=10, anchor ='e', bg='#EEE' )
                        lbl.pack(side='right') 
                        voltage_labels[(bus, addr)] =lbl
                    except Exception as e:
                        print(f"[Debug] error Failed to read PD from {addr}:{e}")
                                    
        def refresh_readings():
            """ refresh exisiting labels without rebuilding the whole UI."""
            for (bus, addr) , lbl in voltage_labels.items():
                try:
                    self.set_i2c_route(bus)
                    voltage =READ_PD_VOLT(addr)
                    lbl.config(text = f"{voltage:.3f} V")
                    print("refreshed") 
                except Exception:
                    lbl.config(text="ERR", bg='#FFA07A')
                    
                    
        tk.Button(win, text ="Read PD Voltages", command = read_pd_voltages).pack(pady=5)
        tk.Button(win, text= "Refresh" , command= refresh_readings).pack(pady=5)
        
            
        def on_close():
#             for bus, modules in lane_group.items():
#                 self.set_i2c_route(bus)
#                 time.sleep(0.05)
#                 for addr in modules:
#                     try:
#                         self.write_byte(addr, 0x04)
#                         print(f"[DEBUG] Turnned off modules on bus {bus}")
            try:
                lane_group = self.bus_groups_by_lane.get(lane,{})
                for bus, modules in lane_group.items():
                    self.set_i2c_route(bus)
                    time.sleep(0.05)
                    for addr in modules:
                        try:
                            self.write_byte(addr, 0x04)
#                             print(f"[DEBUG] Turnned off modules on bus {bus}")
                
                        except Exception as e:
                            print("--")
                            #print(f"Failed to turn off modules")
            except Exception as e:
                print("--")
                #continue
    
            win.destroy()
            
        win.protocol("WM_DELETE_WINDOW", on_close) 
        read_pd_voltages()
            
            
            
    def scan_modules(self):
        for w in self.module_container.winfo_children():
            w.destroy()
        self.module_frames.clear()
        self.module_states.clear()


        
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
        self.bus_modules={}
        self.lane_assignments= {}
        self.bus_groups_by_lane={} 
        
            # Groups buses to lane *(RJ1 and 2 are lane 1 and RJ3 and 4 are lane 2)
        bus_to_lane_map = {
            1:1 ,
            2:1 ,
            3:2 ,
            4:2
        }
            # In real mode, scan only lanes 1 and 2 (J1, J2)
        for lane_idx, bus in enumerate(range(1, 5)):  # <--- changed: only J1 and J2
            progress_var.set(lane_idx * 25)  # 50% per lane
            progress.update()
                
                # Set I2C routing to this lane
            self.set_i2c_route(bus)
                
                # Direct scan without retries or slow scan options
            bus_addresses = SCAN_I2C_BUS()
                
            if bus_addresses:
                lane = bus_to_lane_map[bus]
                self.bus_modules.setdefault(bus,[]).extend(bus_addresses)
                self.bus_groups_by_lane.setdefault(lane, {}).setdefault(bus,[]).extend(bus_addresses)
                
                if lane not in lane_modules: 
                    lane_modules[lane] = []
                lane_modules[lane].extend(bus_addresses)
                    
                if bus not in self.bus_modules:
                    self.bus_modules[bus] =[]
                self.bus_modules[bus].extend(bus_addresses)
            
                    # Add lane information to addresses found
                for addr in bus_addresses:
                        if addr not in all_addresses:  # Avoid duplicates
                            all_addresses.append(addr)
                            # Assign module to the current lane
                            self.lane_assignments[addr] = {"lane": lane, "bus": bus}
                            print(lane, bus) 
        for addr, assign in self.lane_assignments.items():
            print(f"Module {addr:02X}:lane {assign['lane']} , bus{assign['bus']}")
            
        self.scanned_addresses = all_addresses
        
        # Close progress window
        progress.destroy()
                
        if not self.scanned_addresses:
            messagebox.showinfo("Scan Result", "No I²C devices found.")
            return
        
    
        # Create module display grouped by lane
        row = 0
        
        # Display lanes in order
        for lane in sorted(lane_modules.keys()):
            # Add lane header
            lane_header = tk.Frame(self.module_container, bg=self._get_bus_color(lane))
            lane_header.grid(row=row, column=0, columnspan=6, sticky='ew', padx=5, pady=5)
            
            # Lane header with lane name and actions
            header_content = tk.Frame(lane_header, bg=self._get_bus_color(lane))
            header_content.pack(fill='x', expand=True)
            
            lane_label = tk.Label(header_content, 
                                text=f"Lane {lane} ", 
                                font=('Arial', 12, 'bold'),
                                bg=self._get_bus_color(lane))
            lane_label.pack(side=tk.LEFT, pady=5, padx=10)
            
            # Add buttons for lane actions
            actions_frame = tk.Frame(header_content, bg=self._get_bus_color(lane))
            actions_frame.pack(side=tk.RIGHT, padx=10)
            
#             toggle_button = tk.Button(actions_frame, text="Toggle Lane", 
#                                     command=lambda l=lane: self.toggle_lane_modules(l))
#             toggle_button.pack(side=tk.LEFT, padx=5)
# #             
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
        
        if addr in self.lane_assignments:
            assignment = self.lane_assignments[addr]
            bus= assignment["bus"]
            self.set_i2c_route(bus)
            time.sleep(0.05)
            
            
            
        success= False
        
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
        bus_map = getattr(self, "bus_groups_by_lane", None)
        if not bus_map or not isinstance(bus_map, dict):
            messagebox.showing("No Devices", "Scan First")
            return
        
        for lane, bus_groups in self.bus_groups_by_lane.items():
            for bus, modules in bus_groups.items():
                
            
                self.set_i2c_route(bus)
                time.sleep(0.05)
                for addr in modules:
                    try:
                        self.bus.write_byte(addr, 0x04)
                        self.module_states[addr]= False
                        f, lbl = self.module_frames[addr]
                        f.config(bg='red')
                        lbl.config(bg='red')
                    except Exception as e:
                        print(f"I2C error with module {addr:02X}:{e}")
                        
        messagebox.showinfo("Action", "All lasers turned off") 


    def turn_all_on(self):
        bus_map = getattr(self, "bus_groups_by_lane", None)
        if not bus_map or not isinstance(bus_map, dict):
            messagebox.showing("No Devices", "Scan First")
            return
        
        for lane, bus_groups in self.bus_groups_by_lane.items():
            for bus, modules in bus_groups.items():
                
            
                self.set_i2c_route(bus)
                time.sleep(0.05)
                for addr in modules:
                    try:
                        self.bus.write_byte(addr, 0x03)
                        self.module_states[addr]= True
                        f, lbl = self.module_frames[addr]
                        f.config(bg='green')
                        lbl.config(bg='green')
                    except Exception as e:
                        print(f"I2C error with module {addr:02X}:{e}")
                        
        messagebox.showinfo("Action", "All lasers turned on") 
        
    def toggle_lane_modules(self, bus_num):
        """Toggle all modules in a specific lane"""
        if bus_num not in self.bus_groups_by_lane:
             mesagebox.showwarning("No Devices", f"No Modules found in Lane {lane_num}.")
             return 
    
    
        
        bus_groups= self.bus_groups_by_lane[bus_num] 
            
        for bus, modules in bus_groups.items():
            self.set_i2c_route(bus)
            time.sleep(0.05)
            
            for addr in modules:
                
                try:
                # Toggle modules based on current state
                    if self.module_states[addr]:
                        self.bus.write_byte(addr,0x04)
                        self.module_states[addr]= False
                        col ='green'
                    else:
                        self.bus.write_byte(addr, 0x03)
                        self.module_states[addr] = True
                        col='red' 
                        

                except Exception as e:
                    print(f"I2C Error with module {addr:02X}: {e}")
                    
                    
                f, lbl =self.module_frames[addr]
                col = 'green' if self.module_states[addr] else 'red'
                f.config(bg=col)
                lbl.config(bg=col)
        messagebox.showinfo("Action" , f"All laser in Lane {bus_num} toggled.") 

                
    def set_module_game_threshold(self, addr, voltage):
        try:
            raw_10bit = int((voltage/2.5)*1023)
            
            raw_8bit= int(raw_10bit *255/1023)
            
            self.bus.write_byte_data(addr, 0x10, raw_8bit)
            
#             print(f"[Debug] Set game threshold {voltage:.2f}V to {raw_8bit} (1byte) on module {addr}")
        except Exception as e:
            print(f"threshold failed to send error= {e}")
            
    def set_lane_game_threshold(self, lane, voltage):
        if lane not in self.bus_groups_by_lane:
            messagebox.showwarning("No devices", f"No Modules found on lane {lane}. Scan first")
            return
        
        lane_group = self.bus_groups_by_lane[lane]
        for bus, modules in lane_group.items():
            self.set_i2c_route(bus)
            time.sleep(0.05)
            print(f"{bus}")
            for addr in modules:
                self.set_module_game_threshold(addr, voltage)
                print(f"{addr}") 
                
                
    def prompt_and_set_lane_threshold(self, lane):
        
        voltage_str = tk.simpledialog.askstring(
            f" Set Game threshold Lane{lane}",
            f"Enter voltage for lane {lane}(0-2.5V):")
        if voltage_str is None:
            return
        try:
            voltage = float(voltage_str)
            if not (0 <= voltage<=2.51):
                raise ValueError("Voltage is out of Range")
            self.set_lane_game_threshold(lane, voltage)
            messagebox.showinfo("Success", f"Lane{lane} threhsold is set to {voltage:.2f} V" )
            
        except ValueError:
            messagebox.showerror("Invalid Input" , "Please eneter a valid number between 0 and 2.5V") 
        
            
    def read_module_game_threshold(self, addr):
        
        try:
            raw_byte = self.bus.read_byte_data(addr, 0x12)
            voltage = (raw_byte /255)*2.5
#             print(f"[DEBUG] Module {addr} game Threshold = {voltage:.2f} V")
            return voltage
        except Exception as e:
            print(f"[Error] Failed to read the threshold for module {addr}: {e}")
            return None
        
    def read_lane_game_threshold(self, lane):
        
        if lane not in self.bus_groups_by_lane:
            messagebox.showwarning("No Devices", f"No modules found on lane {lane}. Scan first")
            return
        
        lane_groups = self.bus_groups_by_lane[lane]
        results= []
        
        for bus, modules in lane_groups.items():
            self.set_i2c_route(bus)
            time.sleep(0.05)
            for addr in modules:
                voltage = self.read_module_game_threshold(addr)
                
                if voltage is not None:
                    results.append(f"Module {addr} (Bus {bus}): {voltage:.2f} V")
                else:
                    results.append(f"Module {addr} (Bus {bus}): ERROR")
                    
        popup = tk.Toplevel()
        popup.title(f"Lane{lane} Game Thresholds")
        tk.Label(popup, text= f"Lane{lane} Game Thresholds", font=("Arial", 14, 'bold')).pack(pady=10)

        container = tk.Frame(popup)
        container.pack(padx=10, pady=10)
        
        for line in results:
            tk.Label(container, text=line, font = ("Arial", 11)).pack(anchor ='w')
            
        tk.Button(popup, text= "Close", command=popup.destroy).pack(pady=10)
        
        
        
    def reset_modules(self):
        self.module_frames.clear()
        self.module_states.clear()
        for w in self.module_container.winfo_children():
            w.destroy()
        messagebox.showinfo("Reset Complete", "Scanned data cleared.")

#     def beam_block_scan(self):
#         """Check detector voltages for all modules"""
#         if not self.scanned_addresses:
#             messagebox.showwarning("No Modules", "Please scan for modules first")
#             return
# 
#         # Create popup window
#         popup = tk.Toplevel(self)
#         popup.title("Detector Voltages")
#         popup.geometry("300x400")
# 
#         # Create scrollable frame
#         container = tk.Frame(popup)
#         container.pack(fill='both', expand=True, padx=10, pady=10)
#         
#         # Add header
#         tk.Label(container, text="Module Detector Voltages", font=('Arial', 14, 'bold')).pack(pady=(0,10))
# 
#         # Check each module
#         for addr in self.scanned_addresses:
#             frame = tk.Frame(container)
#             frame.pack(fill='x', pady=2)
#             
#             # Get voltage reading
#             voltage = READ_PD_VOLT(addr)
#             
#             # Determine color based on threshold
#             bg_color = '#90EE90' if voltage > 1.2 else '#FFB6C6'  # Light green or light red
#             
#             # Create label with colored background
#             label = tk.Label(
#                 frame, 
#                 text=f"Module {addr:02X}: {voltage:.2f}V",
#                 font=('Arial', 12),
#                 bg=bg_color,
#                 width=25,
#                 pady=5
#             )
#             label.pack(fill='x')
# 
#         # Add close button
#         tk.Button(
#             container,
#             text="Close",
#             command=popup.destroy,
#             width=10
#         ).pack(pady=10)
    
                        
                        
                        
                        
    
    
    # ---------- Game Mode ----------
    def _build_game_mode(self):
        self.game_frame = tk.Frame(self)
        
        # Control buttons only in main window
        tk.Button(self.game_frame, text="Start Game", width=20,
                  command=self.start_game).pack(pady=5)
        tk.Button(self.game_frame, text="Stop Game", width=20,
                  command=self.stop_game).pack(pady=5)
                       
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
#         self.cleanup_game_ui()
        
        if not getattr(self, "scanned_addresses", None):
            messagebox.showwarning("No Modules:" , "Please scan for modules" )
            return
        
        # Clean up any UI elements from previous games
        # (kept for compatibility; _reset_for_new_game already handles cleanu
        for lane, bus_groups in self.bus_groups_by_lane.items():
            for bus, modules in bus_groups.items():
                self.set_i2c_route(bus)
                time.sleep(0.005)
                GAME_MODE_ON(modules)
                
#         time.sleep(0.05)
        print("checking modules") 
        blocked_modules = self.check_and_get_blocked_beam()
        print(blocked_modules)
        if blocked_modules:
            msg_lines = []
            for item in blocked_modules:
                if len(item) ==4:
                    addr, lane, bus, penalty =item
                    msg_lines.append(f"Module 0x{addr} (Lane {lane} , Bus {bus})")
                else:
                    msg_lines.append(str(item)) 
               
            messagebox.showerror("Cannot Start Game- Misalignment",
                                 "The following modules are blocked:\n" + "\n".join(msg_lines) +
                                 "\n\nPlease realign before starting the game")
            return
            

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
                                  width=10)  # Fixed width to prevent jumping
            self.lane1_timer.pack()
            
            self.lane2_timer = tk.Label(timer2_container, text="0.00",
                                  font=('Arial', 120, 'bold'),
                                  fg='white', bg='black',
                                  width=10)  # Fixed width to prevent jumping
            self.lane2_timer.pack()

        
          
          
        
        # Reset timers and tracking variables
        self._last_elapsed = 0.0
        self._lane1_timer = 0.0
        self._lane2_timer = 0.0
        
  # Play countdown sound if available
        if self.audio_available:
            try:
                pygame.mixer.music.load("countdown.mp3")
                print("Countdown Audio")
                pygame.mixer.music.play()
            except Exception as e:
                print("Could not play countdown.mp3:", e)
                 
                 
        
        self.countdown(3)

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
            
        # Ensure lane is valid
        if lane not in self.bus_to_gpio:
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
        blocked =[] 
            
        gpio_to_bus_map= {
            16:1,
            19:2,
            20:3,
            21:4 }
        
        for pin, bus in gpio_to_bus_map.items():
            lane = 1 if bus in (1,2) else 2
            lane_signal =GPIO.input(pin)
#             print(f"[DEBUG] GPIO {pin} (Bus {bus}, Lane {lane}) = {lane_signal} ")
            

            if lane_signal == 0:
#                 print(f"[DEBUG] Block detected on GPIO pin {pin} checking modules...")
                
                
                modules= self. bus_modules.get(bus, [])
                if not modules:
                    continue
                
                self.set_i2c_route(bus)
                time.sleep(0.01)
                    
                for addr in modules:
                    try:
                        
                        self.bus.write_byte(addr, 0xFE)  # CMD_BEAM_BLOCKED
                        time.sleep(0.001)
                        is_blocked = self.bus.read_byte(addr)
                    except Exception:
                        continue

                        # Arduino convention: 1 = blocked, 0 = clear (typical for digitalRead HIGH/LOW)
                    if is_blocked == 1:
                            # Debug: print which lane/module tripped
#                         print(f"Beam blocked detected: addr=0x{addr:02X} lane={lane} bus= {bus}")
                        penalty_seconds = 3
                        
                        blocked.append((addr, lane, bus, penalty_seconds))
        return blocked if blocked else None


    def _update_timer(self):
        """Update both lane timers"""
     
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
  
        for lane, pin in self.lane_finish_pins.items():
            if not self.lane_finished[lane] and GPIO.input(pin) == GPIO.LOW:
                self.handle_lane_finish(lane)
        
        # check for shutdown button
        shutdown = False
        if GPIO.input(11) == GPIO.LOW:
            shutdown = True
            self.lane_finished = {1: False, 2: False}
            self.lane_finish_times = {1: 0.0, 2: 0.0}
            self.winner_determined = False
            
            # Stop the game mode for all lanes
            if TEST_MODE:
                STOP_GAME_MODE()
            else:
                # Handle each lane
                for lane in range(1, 5):  # Currently using lanes 1 and 2
                    self.set_i2c_route(lane)
                    time.sleep(0.001)
                    STOP_GAME_MODE()
            
                # Cancel any timer updates
                if getattr(self, '_timer_updater', None):
                    self.timer_window.after_cancel(self._timer_updater)
                if getattr(self, '_penalty_flash_id', None):
                    self.timer_window.after_cancel(self._penalty_flash_id)
                    
                # Update UI if timer window exists
                if hasattr(self, 'lane1_timer') and hasattr(self, 'lane2_timer'):
                    self.lane1_timer.config(text="Stopped", font=('Arial',180,'bold'),
                                            fg='white', bg='black')
                    self.lane2_timer.config(text="Stopped", font=('Arial',180,'bold'),
                                            fg='white', bg='black')
                self.timer_window.config(bg='black')
        
        # Check for blocked beams
            # In real mode, we need to check the GPIO pin and then query each Arduino
            # to find out which one was blocked, then apply penalty to the correct lane
        blocked_modules = self.check_and_get_blocked_beam()
        if blocked_modules:
            for addr,lane,bus, penalty_seconds  in blocked_modules:
                print(f"address: {addr}, pen: {penalty_seconds}")
                print(f"lane assignments: {lane}")
                self._show_penalty(penalty_seconds, lane)
    
        # Schedule next update
        if not shutdown:
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
        
        
        #Turn off lasers for this lane
        bus_groups = self.bus_groups_by_lane[lane]  #group modules by appropriate bus
        for bus, modules in bus_groups.items():
            self.set_i2c_route(bus) #Switch bus
            time.sleep(0.05)
            TURN_ALL_OFF(modules) # Send turn all off through the bus

        # Update display for the finished lane
        frame = self.left_frame if lane == 1 else self.right_frame
        timer_label = self.lane1_timer if lane == 1 else self.lane2_timer
        header = self.lane1_header if lane == 1 else self.lane2_header
        
        # Change to orange finish display
        frame.config(bg='orange')
        timer_label.config(bg='orange', text=f"{finish_time:.2f} s", font=('Arial', 200, 'bold'))
        header.config(bg='orange', text=f"LANE {lane} FINISHED", fg='black', font=('Arial', 140, 'bold'))
        
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
        winner_header.config(bg='gold', text=f"LANE {winner_lane} WINS!", fg='black', font=('Arial', 120, 'bold'))
        
        if self.audio_available:
            try:
                pygame.mixer.music.load("Winner.mp3")
                print("Winner Audio")
                pygame.mixer.music.play()
            except Exception as e:
                print("Could not play winner.mp3:", e)
        
        # Add win margin display under the timer
        margin_label = tk.Label(winner_frame, 
                       text=f"Win margin: {time_diff:.2f}s",
                       font=('Arial', 140, 'bold'), # Old size 24pt 
                       fg='black', bg='gold')
        margin_label.pack(pady=10)
        
        # Add the label to our list of dynamic UI elements
        self.dynamic_ui_elements.append(margin_label)
        


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
            for lane in range(1, 5):  # Currently using lanes 1 and 2
                self.set_i2c_route(lane)
                time.sleep(0.001)
                STOP_GAME_MODE()
        
        # Cancel any timer updates
        if getattr(self, '_timer_updater', None):
            self.timer_window.after_cancel(self._timer_updater)
        if getattr(self, '_penalty_flash_id', None):
            self.timer_window.after_cancel(self._penalty_flash_id)
            
        # Update UI if timer window exists
        if hasattr(self, 'lane1_timer') and hasattr(self, 'lane2_timer'):
            self.lane1_timer.config(text="Stopped", font=('Arial',180,'bold'),
                                    fg='white', bg='black')
            self.lane2_timer.config(text="Stopped", font=('Arial',180,'bold'),
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
#         tk.Button(self.calib_frame, text="Read All", width=20,
#                   command=self.read_calib_all).pack(pady=5)

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
        tk.Button(btn, text="Read Game Threshold",       width=16,
                command=self.read_calib_game_threshold)\
          .grid(row=1, column=0, padx=5, pady=5)
        tk.Button(btn, text="Read Current",      width=16,
                  command=self.read_calib_current)\
          .grid(row=1, column=1, padx=5, pady=5)
        tk.Button(btn, text="Set Game Threshold",        width=16,
                command=self.set_calib_game_threshold)\
         .grid(row=2, column=0, padx=5, pady=5)
        tk.Button(btn, text="Set Current",       width=16,
                  command=self.set_calib_current)\
          .grid(row=2, column=1, padx=5, pady=5)

        tk.Button(self.calib_frame, text="Back", width=20,
                  command=self.show_main_menu).pack(pady=(0,10))

    def scan_calib_modules(self):
        """Scan all RJ45, route per-bus, collect unique addresses and populate calibration grid grouped by bus."""
        for w in self.calib_container.winfo_children():
            w.destroy()
        self.calib_frames.clear()
        self.calib_on.clear()
        self.calib_color.clear()
        self.calib_current.clear()
        self.selected_calib_addr = None
        self.module_bus={} 
        all_addresses = []
        bus_modules = {}

            # Real mode: scan lanes J1 and J2 only (route per-lane)
        for bus in (1, 2, 3, 4):
            self.set_i2c_route(bus)
            time.sleep(0.01)
            bus_addrs = SCAN_I2C_BUS() or []
            for addr in bus_addrs:
                    
                    if addr not in all_addresses:
                        all_addresses.append(addr)
                            
                        bus_modules.setdefault(bus, []).append(addr)
                        self.module_bus[addr] = bus 
        self.scanned_addresses = all_addresses

        if not self.scanned_addresses:
            messagebox.showinfo("Scan Result", "No I²C devices found.")
            return

      

        # Build UI grouped by lane (J1/J2)
        row = 0
        for bus in sorted(bus_modules.keys()):
            # Lane header
            bus_header = tk.Frame(self.calib_container, bg=self._get_bus_color(bus))
            bus_header.grid(row=row, column=0, columnspan=6, sticky='ew', padx=5, pady=5)
            header_content = tk.Frame(bus_header, bg=self._get_bus_color(bus))
            header_content.pack(fill='x', expand=True)
            lane_label = tk.Label(header_content, text=f"Bus {bus} (J{bus})", font=('Arial', 12, 'bold'),
                                  bg=self._get_bus_color(bus))
            lane_label.pack(side=tk.LEFT, pady=5, padx=10)
            actions_frame = tk.Frame(header_content, bg=self._get_bus_color(bus))
            actions_frame.pack(side=tk.RIGHT, padx=10)
            toggle_button = tk.Button(actions_frame, text="Toggle Lane",
                                  command=lambda l=bus: self.toggle_lane_modules(l))
            toggle_button.pack(side=tk.LEFT, padx=5)

            row += 1

            module_addrs = bus_modules[bus]
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
#                 lbl_current = tk.Label(top, text="Current:", bg='gray')
#                 lbl_current.place(relx=0.5, rely=0.8, anchor='center')
                
                lbl_threshold = tk.Label(bottom, text="Thres:", bg='gray')
                lbl_threshold.place(relx=0.5, rely=0.8, anchor='center')
#                 
                def mk(a): return lambda ev: self.select_calib_module(a)
                for wdg in (f, top, bottom, lbl_addr, lbl_threshold):
                    wdg.bind("<Button-1>", mk(addr))

#                 self.calib_frames[addr] = (f, top, bottom, lbl_addr, lbl_current, lbl_threshold)
                self.calib_frames[addr] = (f, top, bottom, lbl_addr, lbl_threshold)
                self.calib_on[addr] = False
                self.calib_color[addr] = None
                self.calib_current[addr] = None

            # advance row
            row += (len(module_addrs) + 5) // 6 or 1

        bus_summary = ", ".join([f"Bus {bus}: {len(mods)} modules" for bus, mods in bus_modules.items()])
        messagebox.showinfo("Scan Complete", f"Found {len(self.scanned_addresses)} modules\n{bus_summary}")

    def select_calib_module(self, addr, bus=None):
        self.selected_calib_addr = addr
        for a, (fr, *_ ) in self.calib_frames.items():
            fr.config(relief='raised', bd=2)
            
        if addr in self.calib_frames:
            
            frame, *_ = self.calib_frames[addr]
            frame.config(relief='solid', bd=4)
            
        bus= self.module_bus.get(addr, None)
        if bus is not None:
            self.lane_assignments[addr] =bus
             
#         except Exception as e:
#             print(f"I2C ERROR", "Error ={e}")  
            
            

    def read_calib_game_threshold(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        if addr not in self.lane_assignments:
            messagebox.showerror("I2C Error", f"Module {self._format_module_address(addr)} has no lane assignment")
            return
        # Route I2C to the correct lane for this module
        if addr in self.lane_assignments:
            self.set_i2c_route(self.lane_assignments[addr])
        try:
#             self.bus.write_byte(addr, CMD_GAME_THRESHOLD_READ)
#             test= self.bus.read_byte(addr)
            self.bus.write_i2c_block_data(addr, CMD_GAME_THRESHOLD_READ, [])
            time.sleep(0.005)
            threshold= self.bus.read_byte(addr)
            
            voltage = (threshold /255.0)*2.5
            print(voltage)
            _, top, bottom, lbl_addr,  lbl_threshold = self.calib_frames[addr]
            bg= 'gray'
            bottom.config(bg=bg)
            lbl_threshold.config(text=f"Threshold: {voltage:.2f} V", bg=bg)
            self.calib_current[addr] = voltage
#             lbl_threshold.update_idletasks()
#             _, top, bottom, lbl_addr, lbl_current = self.calib_frames[addr]
#             bg = 'gray'
#             bottom.config(bg=bg)
# #                     lbl_color.config(text=f"Colour: {colour}", bg=bg)
#             lbl_current.config(text=f"Thres: {voltage:.2f} mA", bg=bg)
# #                     self.calib_color[addr]   = colour
#             self.calib_current[addr] = voltage
            
        except Exception as e:
             messagebox.showerror("I2C Error", f"Failed to read threshold:{e}") 
#         game_threshold= READ_GAME_THRESHOLD(addr)
#         print(f"threshold = {game_threshold}")
        
        
    def set_calib_game_threshold(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        val = simpledialog.askstring("Set Game threshold", "Enter Voltage (V) (between 0 and 2.5V):")
        if val is None: return
        
        # Route I2C to the correct lane for this module
        if addr in self.lane_assignments:
            self.set_i2c_route(self.lane_assignments[addr])
        try:
            val_float= float(val)
            voltage= int((val_float/2.5)*255)
            SET_GAME_THRESHOLD(addr, voltage)
            _, top, bottom, lbl_addr, lbl_threshold = self.calib_frames[addr]
            lbl_threshold.config(text=f"Threshold: {val_float:.2f} V")
            self.calib_current[addr] = val_float
            messagebox.showinfo("Action", f"Set Threshold of Module {self._format_module_address(addr)} to {val_float:.2f} V.")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid number") 
#          
    def read_calib_current(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        if addr not in self.lane_assignments:
            messagebox.showerror("I2C Error", f"Module {self._format_module_address(addr)} has no lane assignment")
            return
        # Route I2C to the correct lane for this module
        if addr in self.lane_assignments:
            self.set_i2c_route(self.lane_assignments[addr])
        try:
#             self.bus.write_byte(addr, CMD_GAME_THRESHOLD_READ)
#             test= self.bus.read_byte(addr)
            self.bus.write_i2c_block_data(addr, CMD_READ_CURRENT, [])
            time.sleep(0.005)
            current= self.bus.read_byte(addr)
            
            
            _, top, bottom, lbl_addr,  lbl_threshold = self.calib_frames[addr]
            bg= 'gray'
            bottom.config(bg=bg)
            lbl_threshold.config(text=f"Current: {current:.2f} mA", bg=bg)
            self.calib_current[addr] = current
#             lbl_threshold.update_idletasks()
#             _, top, bottom, lbl_addr, lbl_current = self.calib_frames[addr]
#             bg = 'gray'
#             bottom.config(bg=bg)
# #                     lbl_color.config(text=f"Colour: {colour}", bg=bg)
#             lbl_current.config(text=f"Thres: {voltage:.2f} mA", bg=bg)
# #                     self.calib_color[addr]   = colour
#             self.calib_current[addr] = voltage
            
        except Exception as e:
             messagebox.showerror("I2C Error", f"Failed to read current:{e}") 
        
        

    def set_calib_current(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        val = simpledialog.askinteger("Set Current", "Enter current (mA):", minvalue=1, maxvalue=119)
        if val is None: return
        
        # Route I2C to the correct lane for this module
        if addr in self.lane_assignments:
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
            self.lane1_timer.config(text="0.00", bg='black', fg='white', font=('Arial', 200, 'bold'))
        if hasattr(self, 'lane2_timer') and getattr(self.lane2_timer, 'winfo_exists', lambda: False)():
            self.lane2_timer.config(text="0.00", bg='black', fg='white', font=('Arial', 200, 'bold'))

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
            if self.scanned_addresses:
                bus_map = getattr(self, "bus_groups_by_lane", None)
                for lane, bus_groups in self.bus_groups_by_lane.items():
                    for bus, modules in bus_groups.items():
                        self.set_i2c_route(bus)
                        time.sleep(0.05)
                        TURN_ALL_OFF(modules)
                GPIO.cleanup()
                self.destroy()
                print("All lasers off. Goodbye!")# close the Tk window
            else:
                GPIO.cleanup()
                self.destroy()
        except Exception as e:
            print(f"Exit error {addr:02X}:{e}")
            print("Try exit again. If fails again turn off all lasers from setup and close window")
        
            
            

        
    
#     def exit_app(self):
#         """Clean up GPIO and close the app."""
#         try:
#             if self.scanned_addresses:
#                 # Group modules by lane
#                 lane_modules = {}
#                 for addr in self.scanned_addresses:
#                     lane = self.lane_assignments.get(addr, 1)
#                     lane_modules.setdefault(lane, []).append(addr)
#                 for lane, modules in lane_modules.items():
#                     if not TEST_MODE:
#                         self.set_i2c_route(lane)
#                         time.sleep(0.02)
#                     try:
#                         TURN_ALL_OFF(modules)
#                     except Exception as e:
#                         print("Exit failed:", e)
#                         print("Try exit again")
#                 print("All Lasers all off, Goodbye!")
#                 GPIO.cleanup()
#                 self.destroy()    # close the Tk window


if __name__ == "__main__":
    app = LaserMazeUI()
    app.mainloop()


