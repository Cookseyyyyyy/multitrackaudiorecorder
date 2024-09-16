import tkinter as tk
from tkinter import filedialog
import pyaudio
import wave
import threading
import os
import struct
import re
import time
import json
from pythonosc import dispatcher
from pythonosc import osc_server
from pythonosc import udp_client

class AudioRecorderGUI:
    def __init__(self, master):
        self.master = master
        master.title("Multi-Track Audio Recorder")
        master.configure(bg='#2e2e2e')  # Dark background color

        # Initialize variables
        self.save_directory = ""
        self.is_recording = False
        self.frames = []
        self.take_number = 1
        self.device_indices = []
        self.channels = 0
        self.recording_indicator_state = True  # For flashing indicator
        self.levels = []
        self.level_bars = []
        self.track_checkboxes = []
        self.track_vars = []
        self.custom_name = "Recording"
        self.monitoring = False
        self.monitoring_thread = None
        self.audio_interface = pyaudio.PyAudio()
        self.monitor_stream = None
        self.monitor_lock = threading.Lock()
        self.osc_server_thread = None
        self.osc_client = None
        self.osc_ip = "192.168.1.72"  # Replace with your computer's IP address
        self.osc_port = 4565
        self.config_file = 'config.json'

        # Get audio devices
        self.audio_devices = self.get_audio_devices()

        # Initialize device_var before load_config
        self.device_var = tk.StringVar(master)

        # Load configuration
        self.load_config()

        # Audio device selection
        self.device_label = tk.Label(master, text="Select Audio Device:", bg='#2e2e2e', fg='white')
        self.device_label.pack()

        self.device_menu = tk.OptionMenu(master, self.device_var, *self.audio_devices, command=self.update_device)
        self.device_menu.config(bg='#444444', fg='white', activebackground='#555555', activeforeground='white', highlightthickness=0)
        self.device_menu["menu"].config(bg='#444444', fg='white')
        self.device_menu.pack()

        # Levels Frame
        self.levels_frame = tk.Frame(master, bg='#2e2e2e')
        self.levels_frame.pack()

        # Update device to reflect the loaded configuration
        self.update_device()

        # Custom name input
        self.name_label = tk.Label(master, text="Enter Custom Name:", bg='#2e2e2e', fg='white')
        self.name_label.pack()
        self.name_entry = tk.Entry(master, bg='#3e3e3e', fg='white', insertbackground='white')
        self.name_entry.pack()
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, self.custom_name)

        # Save directory selection
        self.save_button = tk.Button(master, text="Select Save Directory", command=self.select_save_directory, bg='#444444', fg='white', activebackground='#555555', activeforeground='white', highlightthickness=0)
        self.save_button.pack()

        # Save directory label
        self.save_directory_label = tk.Label(master, text=f"Save Directory: {self.save_directory}", bg='#2e2e2e', fg='white')
        self.save_directory_label.pack()

        # Update save directory label
        self.save_directory_label.config(text=f"Save Directory: {self.save_directory}")

        # Last take number indicator
        self.take_label = tk.Label(master, text="Next Take Number: 0001", bg='#2e2e2e', fg='white')
        self.take_label.pack()

        # Start and Stop buttons
        self.start_button = tk.Button(master, text="Start Recording", command=self.start_recording, bg='#444444', fg='white', activebackground='#555555', activeforeground='white', highlightthickness=0)
        self.start_button.pack()

        self.stop_button = tk.Button(master, text="Stop Recording", command=self.stop_recording, bg='#444444', fg='white', activebackground='#555555', activeforeground='white', highlightthickness=0)
        self.stop_button.pack()
        self.stop_button.config(state='disabled')

        # Recording indicator
        self.indicator_canvas = tk.Canvas(master, width=20, height=20, highlightthickness=0, bg='#2e2e2e')
        self.indicator_canvas.pack()
        self.indicator_light = self.indicator_canvas.create_oval(2, 2, 18, 18, fill='green')

        # Status Label
        self.status_label = tk.Label(master, text="Status: Idle", bg='#2e2e2e', fg='white')
        self.status_label.pack()

        

        # Start OSC server
        self.start_osc_server()

    def get_audio_devices(self):
        device_list = []
        self.device_indices = []

        for i in range(self.audio_interface.get_device_count()):
            device_info = self.audio_interface.get_device_info_by_index(i)
            # Only include devices with input channels
            if device_info['maxInputChannels'] > 0:
                device_list.append(device_info.get('name'))
                self.device_indices.append(i)
        return device_list

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                self.save_directory = config.get('save_directory', '')
                last_device_name = config.get('last_device_name', '')
                if last_device_name in self.audio_devices:
                    self.device_var = tk.StringVar(self.master, value=last_device_name)
                else:
                    self.device_var = tk.StringVar(self.master, value=self.audio_devices[0] if self.audio_devices else '')
        else:
            self.device_var = tk.StringVar(self.master, value=self.audio_devices[0] if self.audio_devices else '')

    def save_config(self):
        config = {
            'save_directory': self.save_directory,
            'last_device_name': self.device_var.get(),
        }
        with open(self.config_file, 'w') as f:
            json.dump(config, f)

    def select_save_directory(self):
        initial_dir = self.save_directory if self.save_directory else os.getcwd()
        self.save_directory = filedialog.askdirectory(initialdir=initial_dir)
        self.update_take_number()

    def get_selected_device_index(self):
        selected_device_name = self.device_var.get()
        if selected_device_name in self.audio_devices:
            index = self.audio_devices.index(selected_device_name)
            return self.device_indices[index]
        else:
            return None

    def update_device(self, *args):
        self.stop_monitoring()
        self.update_tracks()
        self.start_monitoring()

    def update_tracks(self):
        # Clear existing widgets
        for widget in self.levels_frame.winfo_children():
            widget.destroy()
        self.levels = []
        self.level_bars = []
        self.track_checkboxes = []
        self.track_vars = []

        # Get the selected device channels
        device_index = self.get_selected_device_index()
        if device_index is None:
            return

        device_info = self.audio_interface.get_device_info_by_index(device_index)
        self.channels = device_info['maxInputChannels']

        # Create level meters and checkboxes
        for i in range(self.channels):
            frame = tk.Frame(self.levels_frame, bg='#2e2e2e')
            frame.pack(side=tk.LEFT, padx=5)

            # Track checkbox
            var = tk.IntVar(value=1)
            chk = tk.Checkbutton(frame, text=f"Track {i+1}", variable=var, bg='#2e2e2e', fg='white', selectcolor='#3e3e3e', activebackground='#2e2e2e', activeforeground='white')
            chk.pack()
            self.track_vars.append(var)
            self.track_checkboxes.append(chk)

            # Level meter
            canvas = tk.Canvas(frame, width=20, height=100, bg='#3e3e3e', highlightthickness=0)
            canvas.pack()
            bar = canvas.create_rectangle(2, 2, 18, 98, fill='green')
            self.levels.append((canvas, bar))

    def update_take_number(self):
        if not self.save_directory or not self.custom_name:
            self.take_label.config(text="Next Take Number: 0001")
            self.take_number = 1
            return

        pattern = re.compile(rf"{re.escape(self.custom_name)}_(\d{{4}})_\d+\.wav")
        max_take = 0
        for filename in os.listdir(self.save_directory):
            match = pattern.match(filename)
            if match:
                take_num = int(match.group(1))
                if take_num > max_take:
                    max_take = take_num
        self.take_number = max_take + 1
        formatted_take_number = f"{self.take_number:04d}"
        self.take_label.config(text=f"Next Take Number: {formatted_take_number}")

    def start_recording(self):
        if self.is_recording:
            return  # Already recording

        if not self.save_directory:
            tk.messagebox.showwarning("No Save Directory", "Please select a save directory before recording.")
            return

        self.custom_name = self.name_entry.get().strip()
        if not self.custom_name:
            tk.messagebox.showwarning("No Custom Name", "Please enter a custom name for the recordings.")
            return

        self.update_take_number()

        # Get selected tracks
        self.selected_tracks = [i for i, var in enumerate(self.track_vars) if var.get() == 1]
        if not self.selected_tracks:
            tk.messagebox.showwarning("No Tracks Selected", "Please select at least one track to record.")
            return

        self.is_recording = True
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.status_label.config(text="Status: Recording...")
        self.frames = []

        # Start flashing indicator
        self.indicator_canvas.itemconfig(self.indicator_light, fill='red')
        self.flash_indicator()

        # Stop monitoring
        self.stop_monitoring()

        # Start recording thread
        self.recording_thread = threading.Thread(target=self.record)
        self.recording_thread.start()

        # Send OSC message: recording started
        self.send_osc_status()

    def flash_indicator(self):
        if self.is_recording:
            current_color = self.indicator_canvas.itemcget(self.indicator_light, 'fill')
            next_color = 'red' if current_color == 'white' else 'white'
            self.indicator_canvas.itemconfig(self.indicator_light, fill=next_color)
            self.master.after(500, self.flash_indicator)
        else:
            self.indicator_canvas.itemconfig(self.indicator_light, fill='green')

    def record(self):
        device_index = self.get_selected_device_index()

        if device_index is None:
            tk.messagebox.showerror("Error", "Selected audio device not found.")
            self.is_recording = False
            self.master.after(0, self.update_ui_after_recording)
            return

        device_info = self.audio_interface.get_device_info_by_index(device_index)
        self.channels = device_info['maxInputChannels']
        sample_rate = int(device_info['defaultSampleRate'])

        # Open recording stream
        try:
            self.record_stream = self.audio_interface.open(format=pyaudio.paInt16,
                                                           channels=self.channels,
                                                           rate=sample_rate,
                                                           input=True,
                                                           input_device_index=device_index,
                                                           frames_per_buffer=1024)
        except Exception as e:
            tk.messagebox.showerror("Error", f"Failed to open recording stream: {e}")
            self.is_recording = False
            self.master.after(0, self.update_ui_after_recording)
            return

        while self.is_recording:
            try:
                data = self.record_stream.read(1024, exception_on_overflow=False)
                self.frames.append(data)
                # Update level meters
                self.update_levels(data)
            except Exception as e:
                print(f"Recording error: {e}")
                break

        # Close recording stream
        self.record_stream.stop_stream()
        self.record_stream.close()

        self.save_recording(sample_rate)

        self.master.after(0, self.update_ui_after_recording)

    def update_ui_after_recording(self):
        self.is_recording = False
        self.start_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.status_label.config(text="Status: Idle")
        self.indicator_canvas.itemconfig(self.indicator_light, fill='green')
        self.take_number += 1
        self.update_take_number()
        # Send OSC message: recording stopped
        self.send_osc_status()

        # Restart monitoring
        self.start_monitoring()

    def stop_recording(self):
        if self.is_recording:
            self.is_recording = False

    def save_recording(self, sample_rate):
        # Split the frames into separate channels
        channel_data = self.extract_channel_data()

        formatted_take_number = f"{self.take_number:04d}"
        for i in self.selected_tracks:
            track_number = i + 1
            filename = f"{self.custom_name}_{formatted_take_number}_{track_number}.wav"
            filepath = os.path.join(self.save_directory, filename)
            wf = wave.open(filepath, 'wb')
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 2 bytes for paInt16
            wf.setframerate(sample_rate)
            wf.writeframes(b''.join(channel_data[i]))
            wf.close()

    def extract_channel_data(self):
        # Split interleaved data into separate channels
        channel_data = [[] for _ in range(self.channels)]
        for frame in self.frames:
            # Unpack the frame into samples
            samples = struct.unpack('<' + ('h' * (len(frame) // 2)), frame)
            for i in range(0, len(samples), self.channels):
                for ch in range(self.channels):
                    if i + ch < len(samples):
                        sample = samples[i + ch]
                        channel_data[ch].append(struct.pack('<h', sample))
        return channel_data

    def update_levels(self, data):
        # Unpack the data
        samples = struct.unpack('<' + ('h' * (len(data) // 2)), data)
        num_samples = len(samples) // self.channels

        levels = []
        for ch in range(self.channels):
            # Get samples for this channel
            channel_samples = samples[ch::self.channels]
            # Calculate RMS
            rms = (sum([s**2 for s in channel_samples]) / num_samples) ** 0.5 if num_samples > 0 else 0
            # Normalize and scale to meter height
            level = min(rms / 32768, 1)  # Normalize to 0-1
            levels.append(level)

        # Update GUI in the main thread
        self.master.after(0, self.update_level_meters, levels)

    def update_level_meters(self, levels):
        for ch, level in enumerate(levels):
            if ch >= len(self.levels):
                continue
            meter_height = int(level * 96)  # 96 pixels max height
            canvas, bar = self.levels[ch]
            canvas.coords(bar, 2, 98 - meter_height, 18, 98)
            # Change color if track is selected or not
            color = 'green' if self.track_vars[ch].get() == 1 else 'grey'
            canvas.itemconfig(bar, fill=color)

    def start_monitoring(self):
        # Get device info in main thread
        device_index = self.get_selected_device_index()
        if device_index is None:
            return

        device_info = self.audio_interface.get_device_info_by_index(device_index)
        channels = device_info['maxInputChannels']
        sample_rate = int(device_info['defaultSampleRate'])

        self.monitoring = True
        self.monitoring_thread = threading.Thread(target=self.monitor_levels, args=(device_index, channels, sample_rate))
        self.monitoring_thread.start()

    def stop_monitoring(self):
        if self.monitoring:
            self.monitoring = False
            if self.monitor_thread_is_alive():
                self.monitoring_thread.join()
            with self.monitor_lock:
                if self.monitor_stream is not None:
                    self.monitor_stream.stop_stream()
                    self.monitor_stream.close()
                    self.monitor_stream = None

    def monitor_thread_is_alive(self):
        return self.monitoring_thread is not None and self.monitoring_thread.is_alive()

    def monitor_levels(self, device_index, channels, sample_rate):
        try:
            with self.monitor_lock:
                self.monitor_stream = self.audio_interface.open(format=pyaudio.paInt16,
                                                                channels=channels,
                                                                rate=sample_rate,
                                                                input=True,
                                                                input_device_index=device_index,
                                                                frames_per_buffer=1024)
            while self.monitoring:
                try:
                    data = self.monitor_stream.read(1024, exception_on_overflow=False)
                    self.update_levels(data)
                    time.sleep(0.05)  # Slight delay to reduce CPU usage
                except Exception as e:
                    # Handle exceptions (e.g., device disconnection)
                    print(f"Monitoring error: {e}")
                    break
        finally:
            with self.monitor_lock:
                if self.monitor_stream is not None:
                    self.monitor_stream.stop_stream()
                    self.monitor_stream.close()
                    self.monitor_stream = None

    # OSC Integration
    def start_osc_server(self):
        # Set up dispatcher
        self.dispatcher = dispatcher.Dispatcher()
        self.dispatcher.map("/start_recording", self.osc_start_recording)
        self.dispatcher.map("/stop_recording", self.osc_stop_recording)
        # Create OSC server
        self.server = osc_server.ThreadingOSCUDPServer((self.osc_ip, self.osc_port), self.dispatcher)
        print(f"Serving OSC on {self.server.server_address}")
        # Start server thread
        self.osc_server_thread = threading.Thread(target=self.server.serve_forever)
        self.osc_server_thread.daemon = True
        self.osc_server_thread.start()
        # Set up OSC client for broadcasting status
        self.osc_client = udp_client.SimpleUDPClient(self.osc_ip, self.osc_port)

        # Broadcast initial status
        self.send_osc_status()

    def osc_start_recording(self, addr, *args):
        print("OSC command received: Start Recording")
        self.master.after(0, self.start_recording)

    def osc_stop_recording(self, addr, *args):
        print("OSC command received: Stop Recording")
        self.master.after(0, self.stop_recording)

    def send_osc_status(self):
        status = "recording" if self.is_recording else "idle"
        self.osc_client.send_message("/recorder_status", status)
        print(f"OSC status broadcasted: {status}")

    def on_closing(self):
        try:
            self.save_config()
            self.stop_monitoring()
            if hasattr(self, 'monitor_stream') and self.monitor_stream is not None:
                self.monitor_stream.close()
            if hasattr(self, 'audio_interface') and self.audio_interface is not None:
                self.audio_interface.terminate()
            if hasattr(self, 'server') and self.server:
                self.server.shutdown()
                self.server.server_close()
            self.master.destroy()
        except Exception as e:
            print(f"Exception in on_closing: {e}")
            self.master.destroy()

def main():
    root = tk.Tk()
    app = AudioRecorderGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
