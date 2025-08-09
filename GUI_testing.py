import tkinter as tk
from tkinter import messagebox, simpledialog
import time
import sys
import pygame

# ------------------- TEST MODE / HARDWARE IMPORTS -------------------
TEST_MODE = "--test" in sys.argv

if not TEST_MODE:
    try:
        import smbus
        import RPi.GPIO as GPIO
        from i2cfunction_AO_Test import *
    except ImportError:
        TEST_MODE = True
        print("Hardware imports failed - running in test mode")

if TEST_MODE:
    # Stub implementations
    class smbus:
        class SMBus:
            def __init__(self, bus): pass

    class GPIO:
        BCM = OUT = IN = LOW = HIGH = None
        @staticmethod
        def setmode(mode): pass
        @staticmethod
        def setup(pin, mode, initial=None): pass
        @staticmethod
        def cleanup(): pass

    def set_bus(bus): pass
    
    # Test mode variables
    _game_timer = 0
    _game_active = False
    _last_time = 0
    
    # Simulated I2C functions
    def SCAN_I2C_BUS(): 
        return [0x10, 0x11, 0x12, 0x13]  # Simulated addresses
        
    def TURN_ALL_OFF(addrs): pass
    def TURN_ALL_ON(addrs): pass
    def TURN_ONLY_ONE_ON(addr): pass
    def TURN_ONLY_ONE_OFF(addr): pass
    
    def READ_PD_VOLT(addr):
        import random
        return random.uniform(1.5, 2.5)  # Random voltage for testing
        
    def START_TIMER():
        global _game_timer, _game_active, _last_time
        _game_timer = 0
        _game_active = True
        _last_time = time.time()
        
    def READ_TIMER():
        global _game_timer, _game_active, _last_time
        if _game_active:
            now = time.time()
            _game_timer += now - _last_time
            _last_time = now
        return _game_timer
        
    def GAME_MODE_ON(addrs): pass
    def STOP_GAME_MODE(): 
        global _game_active
        _game_active = False
        
    def MONITOR_BLOCKED_BEAM(addrs):
        import random
        if random.random() < 0.9:  # 90% chance of beam break
            return random.choice(addrs)
        return None

# ------------------- Laser Maze UI -------------------
class LaserMazeUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Laser Maze Control")
        self.geometry("1024x768")
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
        GPIO.setup(21, GPIO.IN)
        for p in (5, 6):
            GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
        bus = smbus.SMBus(1)
        set_bus(bus)

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
            text="OPTICA MQ - LASER MAZE CONTROL\nver. 1.0.1 (2025)",
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

        tk.Button(self.setup_frame, text="Check PD Voltage", width=20,
                  command=self.beam_block_scan).pack(pady=(10,5))
        tk.Button(self.setup_frame, text="Reset Modules", width=20,
                  command=self.reset_modules).pack(pady=5)
        tk.Button(self.setup_frame, text="Back", width=20,
                  command=self.show_main_menu).pack(pady=(0,10))

    def scan_modules(self):
        for w in self.module_container.winfo_children():
            w.destroy()
        self.module_frames.clear()
        self.module_states.clear()

        self.scanned_addresses = SCAN_I2C_BUS()
        if not self.scanned_addresses:
            messagebox.showinfo("Scan Result", "No I²C devices found.")
            return

        for idx, addr in enumerate(self.scanned_addresses):
            r, c = divmod(idx, 4)
            f = tk.Frame(self.module_container, width=60, height=60,
                         bg='red', relief='raised', bd=2, cursor='hand2')
            f.grid(row=r, column=c, padx=5, pady=5)
            lbl = tk.Label(f, text=f"0x{addr:02X}", bg='red', fg='white')
            lbl.place(relx=0.5, rely=0.5, anchor='center')
            f.bind("<Button-1>", lambda e, a=addr: self.on_module_click(a))
            lbl.bind("<Button-1>", lambda e, a=addr: self.on_module_click(a))
            self.module_frames[addr] = (f, lbl)
            self.module_states[addr] = False

    def on_module_click(self, addr):
        if self.module_states[addr]:
            TURN_ONLY_ONE_OFF(addr)
            col, st = 'red', False
        else:
            TURN_ONLY_ONE_ON(addr)
            col, st = 'green', True
        f, lbl = self.module_frames[addr]
        f.config(bg=col); lbl.config(bg=col)
        self.module_states[addr] = st

    def turn_all_off(self):
        addrs = self.scanned_addresses
        if not addrs:
            messagebox.showwarning("No Devices", "Scan first.")
            return
        TURN_ALL_OFF(addrs)
        for addr, (f, lbl) in self.module_frames.items():
            f.config(bg='red'); lbl.config(bg='red')
            self.module_states[addr] = False
        messagebox.showinfo("Action", "All lasers off.")

    def turn_all_on(self):
        addrs = self.scanned_addresses
        if not addrs:
            messagebox.showwarning("No Devices", "Scan first.")
            return
        TURN_ALL_ON(addrs)
        for addr, (f, lbl) in self.module_frames.items():
            f.config(bg='green'); lbl.config(bg='green')
            self.module_states[addr] = True
        messagebox.showinfo("Action", "All lasers on.")

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
            bg_color = '#90EE90' if voltage > 1.8 else '#FFB6C6'  # Light green or light red
            
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
        tk.Button(self.game_frame, text="Begin Game", width=20,
                  command=self.start_game).pack(pady=(20,5))
        tk.Button(self.game_frame, text="Stop Game",  width=20,
                  command=self.stop_game).pack(pady=5)
        tk.Button(self.game_frame, text="Beam Block Scan", width=20,
                  command=self.beam_block_scan).pack(pady=5)
        tk.Button(self.game_frame, text="Back",        width=20,
                  command=self.show_main_menu).pack(pady=(20,10))


    def start_game(self):
        # Play countdown.mp3 when game starts
        if self.audio_available:
            try:
                pygame.mixer.music.load("countdown.mp3")
                
            except Exception as e:
                print("Could not play countdown.mp3:", e)

        if not self.timer_window or not tk.Toplevel.winfo_exists(self.timer_window):
            self.timer_window = tk.Toplevel(self); self.timer_window.title("Game Timer")
            self.timer_label = tk.Label(
                self.timer_window, text="",
                font=('Arial',200,'bold'),
                fg='white', bg='black',
                anchor='center', justify='center'
            )
            self.timer_label.pack(expand=True, fill='both')
            self.timer_window.config(bg='black')
        self._last_elapsed = 0.0
        GAME_MODE_ON(self.scanned_addresses)
        self.countdown(3)
        pygame.mixer.music.play()

    def countdown(self, n):
        cmap = {3:'red',2:'orange',1:'green'}
        if n>0:
            c = cmap[n]
            self.timer_label.config(text=str(n), fg='white', bg=c)
            self.timer_window.config(bg=c)
            self.timer_window.after(1000, lambda: self.countdown(n-1))
        else:
            self.timer_label.config(text="Go!", fg='white', bg='green')
            self.timer_window.config(bg='green')
            START_TIMER()
            self.timer_window.after(2000, self._update_timer)

    def _update_timer(self):
        """Poll READ_TIMER and update the label every poll_interval."""
        elapsed = READ_TIMER()

        # 1) First live update after countdown: just init and schedule next
        if self._last_elapsed <= 0.0:
            self.timer_label.config(
                text=f"{elapsed:.2f} s",
                font=('Arial', 64, 'bold'),
                fg='white', bg='black'
            )
            self.timer_window.config(bg='black')
            self._last_elapsed = elapsed
            self._timer_updater = self.timer_window.after(
                int(self._poll_interval * 1000),
                self._update_timer
            )
            return

        # 2) Compute jump
        delta = elapsed - self._last_elapsed

        # 3) Penalty detection: large jump beyond poll + tolerance
        if delta > self._poll_interval + 0.5:
            added = int(round(delta - self._poll_interval))
            self._show_penalty(added)
            return

        # 4) Normal update
        self.timer_label.config(
            text=f"{elapsed:.2f} s",
            font=('Arial', 64, 'bold'),
            fg='white', bg='black'
        )
        self.timer_window.config(bg='black')
        self._last_elapsed = elapsed
        self._timer_updater = self.timer_window.after(
            int(self._poll_interval * 1000),
            self._update_timer
        )
        MONITOR_BLOCKED_BEAM(self.scanned_addresses)

    def _show_penalty(self, sec):
        """Flash red + display +Xs for 0.5s, then resume the live timer."""
        # Play laser.mp3 sound when penalty occurs
        if self.audio_available and self.laser_sound:
            try:
                self.laser_sound.play()
            except Exception as e:
                print("Could not play laser.mp3:", e)

        # show penalty
        text = f"+{sec}s"
        self.timer_label.config(
            text=text,
            font=('Arial', 200, 'bold'),
            fg='white', bg='red'
        )
        self.timer_window.config(bg='red')

        # cancel any pending live update
        if getattr(self, '_timer_updater', None):
            try:
                self.timer_window.after_cancel(self._timer_updater)
            except Exception:
                pass

        # after 0.5 s, reset bg/font, re-init last_elapsed, and restart timer
        def resume():
            self.timer_label.config(font=('Arial', 64, 'bold'))
            self._last_elapsed = READ_TIMER()
            self._update_timer()

        self._penalty_flash_id = self.timer_window.after(500, resume)

    def _last_resume(self):
        self._last_elapsed = READ_TIMER()
        self._update_timer()

    def stop_game(self):
        STOP_GAME_MODE()
        if getattr(self, '_timer_updater', None):
            self.timer_window.after_cancel(self._timer_updater)
        if getattr(self, '_penalty_flash_id', None):
            self.timer_window.after_cancel(self._penalty_flash_id)
        self.timer_label.config(text="Stopped", font=('Arial',64,'bold'),
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
        tk.Button(btn, text="Read Colour",       width=16,
                  command=self.read_calib_color)\
          .grid(row=1, column=0, padx=5, pady=5)
        tk.Button(btn, text="Read Current",      width=16,
                  command=self.read_calib_current)\
          .grid(row=1, column=1, padx=5, pady=5)
        tk.Button(btn, text="Set Colour",        width=16,
                  command=self.set_calib_color)\
          .grid(row=2, column=0, padx=5, pady=5)
        tk.Button(btn, text="Set Current",       width=16,
                  command=self.set_calib_current)\
          .grid(row=2, column=1, padx=5, pady=5)

        tk.Button(self.calib_frame, text="Back", width=20,
                  command=self.show_main_menu).pack(pady=(0,10))

    def scan_calib_modules(self):
        for w in self.calib_container.winfo_children():
            w.destroy()
        self.calib_frames.clear()
        self.calib_on.clear()
        self.calib_color.clear()
        self.calib_current.clear()
        self.selected_calib_addr = None

        self.scanned_addresses = SCAN_I2C_BUS()
        if not self.scanned_addresses:
            messagebox.showinfo("Scan Result", "No I²C devices found.")
            return

        for idx, addr in enumerate(self.scanned_addresses):
            r, c = divmod(idx, 4)
            outer = tk.Frame(self.calib_container,
                             width=100, height=100,
                             relief='raised', bd=2, cursor='hand2')
            outer.grid(row=r, column=c, padx=5, pady=5)
            outer.pack_propagate(False)

            top = tk.Frame(outer, height=50, bg='red')
            top.pack(fill='x')
            lbl_addr = tk.Label(top, text=f"0x{addr:02X}", bg='red', fg='white')
            lbl_addr.place(relx=0.5, rely=0.5, anchor='center')

            bottom = tk.Frame(outer, height=50, bg='gray')
            bottom.pack(fill='x')
            lbl_color   = tk.Label(bottom, text="Colour:",  bg='gray')
            lbl_color.place(relx=0.5, rely=0.3, anchor='center')
            lbl_current = tk.Label(bottom, text="Current:", bg='gray')
            lbl_current.place(relx=0.5, rely=0.7, anchor='center')

            def mk(a): return lambda ev: self.select_calib_module(a)
            for wdg in (outer, top, bottom, lbl_addr, lbl_color, lbl_current):
                wdg.bind("<Button-1>", mk(addr))

            self.calib_frames[addr]   = (outer, top, bottom, lbl_addr, lbl_color, lbl_current)
            self.calib_on[addr]       = False
            self.calib_color[addr]    = None
            self.calib_current[addr]  = None

    def select_calib_module(self, addr):
        self.selected_calib_addr = addr
        for a, (fr, *_ ) in self.calib_frames.items():
            fr.config(relief='raised', bd=2)
        fr, *_ = self.calib_frames[addr]
        fr.config(relief='solid', bd=4)

    def read_calib_color(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        colour = READ_LASER_COLOR(addr)
        _, top, bottom, _, lbl_color, lbl_current = self.calib_frames[addr]
        bg = colour.lower() if colour else 'gray'
        bottom.config(bg=bg)
        lbl_color.config(text=f"Colour: {colour or ''}", bg=bg)
        lbl_current.config(bg=bg)
        self.calib_color[addr] = colour

    def read_calib_current(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        current = READ_LASER_CURRENT(addr)
        _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
        lbl_current.config(text=f"Current: {current:.2f} mA")
        self.calib_current[addr] = current

    def read_calib_all(self):
        addrs = list(self.calib_frames.keys())
        if not addrs:
            messagebox.showwarning("No Devices", "Scan modules first."); return
        for addr in addrs:
            colour = READ_LASER_COLOR(addr) or ""
            current = READ_LASER_CURRENT(addr) or 0.0
            _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
            bg = colour.lower() if colour else 'gray'
            bottom.config(bg=bg)
            lbl_color.config(text=f"Colour: {colour}", bg=bg)
            lbl_current.config(text=f"Current: {current:.2f} mA", bg=bg)
            self.calib_color[addr]   = colour
            self.calib_current[addr] = current
        messagebox.showinfo("Action", "Read colour and current for all modules.")

    def set_calib_color(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        popup = tk.Toplevel(self)
        popup.title(f"Set Colour for 0x{addr:02X}")
        tk.Label(popup, text="Select Colour:").pack(pady=(10,0))
        var = tk.StringVar(popup); var.set(self.calib_color.get(addr, 'RED') or 'RED')
        tk.OptionMenu(popup, var, 'RED','GREEN','BLUE').pack(pady=5)
        def apply():
            c = var.get().lower()
            SET_LASER_COLOR(addr, c)
            _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
            bottom.config(bg=c)
            lbl_color.config(text=f"Colour: {c.upper()}", bg=c)
            lbl_current.config(bg=c)
            self.calib_color[addr] = c.upper()
            messagebox.showinfo("Action", f"Set colour of 0x{addr:02X} to {c.upper()}.")
            popup.destroy()
        tk.Button(popup, text="OK", command=apply).pack(pady=(0,10))

    def set_calib_current(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        val = simpledialog.askinteger("Set Current", "Enter current (mA):", minvalue=1, maxvalue=119)
        if val is None: return
        SET_LASER_CURRENT(addr, val)
        _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
        lbl_current.config(text=f"Current: {val:.2f} mA")
        self.calib_current[addr] = val
        messagebox.showinfo("Action", f"Set current of 0x{addr:02X} to {val:.2f} mA.")

    def turn_calib_all_off(self):
        addrs = self.scanned_addresses
        if not addrs:
            messagebox.showwarning("No Devices", "Scan first."); return
        TURN_ALL_OFF(addrs)
        for addr, (outer, top, bottom, lbl_addr, lbl_color, lbl_current) in self.calib_frames.items():
            top.config(bg='red')
            lbl_addr.config(bg='red')
            self.calib_on[addr] = False
        messagebox.showinfo("Action", "All lasers turned off.")

    def turn_calib_selected_on(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        TURN_ONLY_ONE_ON(addr)
        _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
        top.config(bg='green'); lbl_addr.config(bg='green')
        self.calib_on[addr] = True
        messagebox.showinfo("Action", f"Laser at 0x{addr:02X} turned on.")

    def turn_calib_selected_off(self):
        addr = self.selected_calib_addr
        if addr is None:
            messagebox.showwarning("Select Module", "Click a module first."); return
        TURN_ONLY_ONE_OFF(addr)
        _, top, bottom, lbl_addr, lbl_color, lbl_current = self.calib_frames[addr]
        top.config(bg='red'); lbl_addr.config(bg='red')
        self.calib_on[addr] = False
        messagebox.showinfo("Action", f"Laser at 0x{addr:02X} turned off.")

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
        except Exception as e:
            print("GPIO.cleanup() failed:", e)
        self.destroy()    # close the Tk window
    

if __name__ == "__main__":
    app = LaserMazeUI()
    app.mainloop()

