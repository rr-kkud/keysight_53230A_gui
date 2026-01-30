import tkinter as tk
import tkinter.ttk as ttk

from matplotlib.backends.backend_tkagg import (
	FigureCanvasTkAgg, NavigationToolbar2Tk)
from matplotlib.backend_bases import key_press_handler
from matplotlib.figure import Figure

import seaborn as sns
sns.set_palette('colorblind')

import os
import allantools as at
import numpy as np
import zmq
from scipy import signal

import time
import threading
from counter import Counter

class MyApp(tk.Tk):

	def __init__(self, data_name, virtual=False, *args, **kwargs):

		tk.Tk.__init__(self, *args, **kwargs)
		
		# Set window size and title
		self.geometry('1400x900')
		self.title('Keysight 53230A Counter - Data Analysis')

		thetime = time.strftime('%H%M%S')
		if data_name[-1] != '_':
			data_name += '_'
		# Placeholder filenames - will be updated when logging starts
		self.allan_file = 'ks_placeholder_allan.txt'
		self.time_series_file = 'ks_placeholder_timeseries.txt'
		
		# Create data folder if it doesn't exist
		if not os.path.exists('./data'):
			os.makedirs('./data')
		
		# Counter and connection setup
		self.counter = None
		self.virtual = virtual
		self.counter_thread = None
		self.connected = False
		self.gate_time = 1  # Default gate time
		self.time_between_reads = 3  # Default time between reads
		self.freq_mode = 'RCON'  # Frequency measurement mode (RCON or CONT)
		
		self.context = zmq.Context()
		self.socket = self.context.socket(zmq.SUB)
		self.socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1 second timeout
		self.socket.setsockopt_string(zmq.SUBSCRIBE, '')

		self.initialized = False
		self.allan_update_time = 10
		self.time_series_record_length = 250
		self.f0 = 193e12
		self.data_name = data_name  # Store base data name for later use
		self.f_start = np.array([])
		self.t_start = np.array([])
		self.log_start_index = 0  # Index where logging started
		self.plot_oadev = tk.BooleanVar(value=False)  # OADEV plotting enabled
		self.log_data = tk.BooleanVar(value=False)  # Data logging enabled
		self.plot_psd = tk.BooleanVar(value=False)  # PSD plotting enabled
		self.subtract_trend = tk.BooleanVar(value=False)  # Subtract linear trend from data
		self.psd_averaging = 10 # nperseg parameter for welch
		self.f_psd = np.array([])  # Data for PSD calculation

		self.t = np.array([])
		self.f = np.array([])

		self.time_series_fig = FigureFrame(self)
		self.allan_dev_fig = FigureFrame(self)
		self.psd_fig = FigureFrame(self)

		# Log scales will be set when data is first plotted
		self.allan_dev_fig.ax.set_xlabel('Averaging Time $\\tau$ (s)')
		self.allan_dev_fig.ax.set_ylabel('Overlapping Allan Deviation')
		self.allan_dev_fig.line.set_linestyle('-')
		self.allan_dev_fig.line.set_marker('o')
		self.allan_dev_fig.ax.grid(which='minor',alpha=0.5)
		self.allan_dev_fig.ax.grid()
		
		self.psd_fig.ax.set_xlabel('Frequency (Hz)')
		self.psd_fig.ax.set_ylabel('Power Spectral Density')
		self.psd_fig.ax.grid(which='minor',alpha=0.5)
		self.psd_fig.ax.grid()

		# Create top control frame for connection and buttons
		top_frame = tk.Frame(self)
		top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
		
		self.connect_button = tk.Button(top_frame, text='Connect', command=self.connect_to_counter, 
										width=12, bg='lightgray', font=('Arial', 10))
		self.connect_button.pack(side=tk.LEFT, padx=5, pady=5)
		
		quit_button = tk.Button(top_frame, text='Quit', command=self.quit_app, width=10, font=('Arial', 10))
		quit_button.pack(side=tk.LEFT, padx=5, pady=5)
		
		self.status_label = tk.Label(top_frame, text='Status: Disconnected', fg='red', font=('Arial', 10, 'bold'))
		self.status_label.pack(side=tk.LEFT, padx=20, pady=5)
		
		# Create main settings frame with two columns
		settings_main = tk.Frame(self)
		settings_main.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
		
		# Left column: Connection Settings
		settings_frame = tk.LabelFrame(settings_main, text='Connection Settings', font=('Arial', 9, 'bold'))
		settings_frame.pack(side=tk.LEFT, fill=tk.X, padx=5, pady=5, expand=False)
		
		# IP Address
		ip_label = tk.Label(settings_frame, text='IP:', font=('Arial', 8))
		ip_label.grid(row=0, column=0, padx=5, pady=3, sticky='w')
		self.ip_entry = tk.Entry(settings_frame, width=12, font=('Arial', 8))
		self.ip_entry.insert(0, '192.168.19.80')
		self.ip_entry.grid(row=0, column=1, padx=5, pady=3)
		
		# Port
		port_label = tk.Label(settings_frame, text='Port:', font=('Arial', 8))
		port_label.grid(row=0, column=2, padx=5, pady=3, sticky='w')
		self.port_entry = tk.Entry(settings_frame, width=8, font=('Arial', 8))
		self.port_entry.insert(0, '5555')
		self.port_entry.grid(row=0, column=3, padx=5, pady=3)
		
		# Gate Time
		gate_label = tk.Label(settings_frame, text='Gate (s):', font=('Arial', 8))
		gate_label.grid(row=0, column=4, padx=5, pady=3, sticky='w')
		self.gate_entry = tk.Entry(settings_frame, width=8, font=('Arial', 8))
		self.gate_entry.insert(0, '1')
		self.gate_entry.grid(row=0, column=5, padx=5, pady=3)
		
		# Time Between Reads
		tbr_label = tk.Label(settings_frame, text='TBR (s):', font=('Arial', 8))
		tbr_label.grid(row=0, column=6, padx=5, pady=3, sticky='w')
		self.tbr_entry = tk.Entry(settings_frame, width=8, font=('Arial', 8))
		self.tbr_entry.insert(0, '3')
		self.tbr_entry.grid(row=0, column=7, padx=5, pady=3)
		
		# Frequency Mode
		mode_label = tk.Label(settings_frame, text='Mode:', font=('Arial', 8))
		mode_label.grid(row=0, column=8, padx=5, pady=3, sticky='w')
		self.mode_var = tk.StringVar(value='RCON')
		self.mode_combo = tk.ttk.Combobox(settings_frame, textvariable=self.mode_var, 
										   values=['RCON (Pi)', 'CONT (Lambda)'], 
										   width=12, font=('Arial', 8), state='readonly')
		self.mode_combo.grid(row=0, column=9, padx=5, pady=3)
		
		# Right column: PSD Settings and Data Controls
		right_settings = tk.Frame(settings_main)
		right_settings.pack(side=tk.RIGHT, fill=tk.X, padx=5, pady=5, expand=True)
		
		# PSD settings frame
		psd_frame = tk.LabelFrame(right_settings, text='PSD Settings', font=('Arial', 9, 'bold'))
		psd_frame.pack(side=tk.LEFT, fill=tk.X, padx=5, pady=5, expand=False)
		
		# Averaging (nperseg)
		avg_label = tk.Label(psd_frame, text='Avg:', font=('Arial', 8))
		avg_label.grid(row=0, column=0, padx=5, pady=3, sticky='w')
		self.avg_entry = tk.Entry(psd_frame, width=8, font=('Arial', 8))
		self.avg_entry.insert(0, str(self.psd_averaging))
		self.avg_entry.grid(row=0, column=1, padx=5, pady=3)
		
		set_avg_button = tk.Button(psd_frame, text='Set', command=self.set_psd_averaging, font=('Arial', 8))
		set_avg_button.grid(row=0, column=2, padx=5, pady=3)
		
		# Data controls frame
		control_frame = tk.LabelFrame(right_settings, text='Data Controls', font=('Arial', 9, 'bold'))
		control_frame.pack(side=tk.LEFT, fill=tk.X, padx=5, pady=5, expand=True)
		
		# F0 setting controls
		f0_label = tk.Label(control_frame, text='F0:', font=('Arial', 8))
		f0_label.grid(row=0, column=0, padx=5, pady=3, sticky='w')
		
		self.f0_entry = tk.Entry(control_frame, width=12, font=('Arial', 8))
		self.f0_entry.insert(0, str(self.f0))
		self.f0_entry.grid(row=0, column=1, padx=5, pady=3)
		
		set_f0_button = tk.Button(control_frame, text='Set F0', 
								command=self.set_f0_and_recalc, font=('Arial', 8))
		set_f0_button.grid(row=0, column=2, padx=5, pady=3)
		
		oadev_check = tk.Checkbutton(control_frame, text='OADEV', variable=self.plot_oadev,
									   command=self.toggle_oadev_plotting, font=('Arial', 8))
		oadev_check.grid(row=0, column=3, padx=5, pady=3)
		
		log_check = tk.Checkbutton(control_frame, text='Log', variable=self.log_data, 
							   command=self.toggle_logging, font=('Arial', 8))
		log_check.grid(row=0, column=4, padx=5, pady=3)
		
		psd_check = tk.Checkbutton(control_frame, text='PSD', variable=self.plot_psd,
								   command=self.toggle_psd_plotting, font=('Arial', 8))
		psd_check.grid(row=0, column=5, padx=5, pady=3)
		
		trend_check = tk.Checkbutton(control_frame, text='Detrend', variable=self.subtract_trend,
								   font=('Arial', 8))
		trend_check.grid(row=0, column=6, padx=5, pady=3)
		
		self.trend_label = tk.Label(control_frame, text='Trend: --', font=('Arial', 8))
		self.trend_label.grid(row=0, column=7, padx=5, pady=3)
		
		# Create plots frame with better layout
		plots_frame = tk.Frame(self)
		plots_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)
		
		# Time series plot - smaller height
		ts_frame = tk.LabelFrame(plots_frame, text='Time Series Data', font=('Arial', 9, 'bold'))
		ts_frame.pack(fill=tk.BOTH, expand=False, side=tk.TOP, pady=5, ipady=2)
		ts_frame.configure(height=180)
		self.time_series_fig = FigureFrame(ts_frame, figsize=(12, 2.5))
		self.time_series_fig.pack(fill=tk.BOTH, expand=True)
		
		# Allan deviation and PSD side by side - smaller
		bottom_frame = tk.Frame(plots_frame)
		bottom_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=5)
		
		# Allan deviation plot
		allan_frame = tk.LabelFrame(bottom_frame, text='Allan Deviation', font=('Arial', 9, 'bold'))
		allan_frame.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=5, ipady=2)
		self.allan_dev_fig = FigureFrame(allan_frame, figsize=(5, 3.5))
		self.allan_dev_fig.pack(fill=tk.BOTH, expand=True)
		
		# PSD plot
		psd_plot_frame = tk.LabelFrame(bottom_frame, text='Power Spectral Density', font=('Arial', 9, 'bold'))
		psd_plot_frame.pack(fill=tk.BOTH, expand=True, side=tk.RIGHT, padx=5, ipady=2)
		self.psd_fig = FigureFrame(psd_plot_frame, figsize=(5, 3.5))
		self.psd_fig.pack(fill=tk.BOTH, expand=True)

		self.allan_dev_fig.ax.set_xlabel('Averaging Time $\\tau$ (s)', fontsize=8)
		self.allan_dev_fig.ax.set_ylabel('Overlapping Allan Deviation', fontsize=8)
		self.allan_dev_fig.line.set_linestyle('-')
		self.allan_dev_fig.line.set_marker('o')
		self.allan_dev_fig.ax.grid(which='minor',alpha=0.5)
		self.allan_dev_fig.ax.grid()
		
		self.psd_fig.ax.set_xlabel('Frequency (Hz)', fontsize=8)
		self.psd_fig.ax.set_ylabel('Power Spectral Density', fontsize=8)
		self.psd_fig.ax.grid(which='minor',alpha=0.5)
		self.psd_fig.ax.grid()
		self.psd_fig.ax.tick_params(labelsize=7)
		self.allan_dev_fig.ax.tick_params(labelsize=7)

	def connect_to_counter(self):
		"""Connect to counter and start streaming"""
		if self.connected:
			# Already connected, disconnect instead
			self.disconnect_counter()
			return
		
		# Validate and get settings
		try:
			ip = self.ip_entry.get().strip()
			port = self.port_entry.get().strip()
			gate_time = float(self.gate_entry.get().strip())
			time_between_reads = float(self.tbr_entry.get().strip())
			
			# Validate IP address format
			ip_parts = ip.split('.')
			if len(ip_parts) != 4 or not all(0 <= int(p) <= 255 for p in ip_parts):
				raise ValueError('Invalid IP address format. Use XXX.XXX.XXX.XXX')
			
			# Validate port
			port_int = int(port)
			if port_int < 1 or port_int > 65535:
				raise ValueError('Port must be between 1 and 65535')
			
			# Validate gate time
			if gate_time <= 0:
				raise ValueError('Gate time must be positive')
			
			# Validate time between reads
			if time_between_reads < 1 or time_between_reads > 10:
				raise ValueError('Time between reads must be between 1 and 10 seconds')
		
		except ValueError as e:
			self.status_label.config(text=f'Status: Invalid input - {str(e)[:40]}', fg='red')
			return
		
		self.connect_button.config(state=tk.DISABLED)
		self.status_label.config(text='Status: Connecting...', fg='orange')
		self.update()
		
		# Get frequency mode (extract first 4 characters: RCON or CONT)
		freq_mode = self.mode_var.get().split()[0]  # Get RCON or CONT from dropdown
		
		# Create counter instance with settings
		self.counter = Counter(
			ip=ip,
			port=port,
			gate_time=gate_time,
			time_between_reads=time_between_reads,
			freq_mode=freq_mode,
			virtual=self.virtual
		)
		
		# Connect to counter
		if not self.counter.connect():
			self.status_label.config(text='Status: Connection Failed', fg='red')
			self.connect_button.config(state=tk.NORMAL, text='Retry Connect')
			return
		
		# Store settings for later use
		self.gate_time = gate_time
		self.time_between_reads = time_between_reads
		self.freq_mode = freq_mode
		
		# Connect socket to counter
		try:
			self.socket.connect('tcp://localhost:'+port)
		except Exception as e:
			print(f'Error connecting socket: {e}')
			self.status_label.config(text='Status: Socket Error', fg='red')
			self.connect_button.config(state=tk.NORMAL, text='Retry Connect')
			return
		
		# Start counter stream in separate thread
		self.counter_thread = threading.Thread(target=self.counter.start_stream, daemon=True)
		self.counter_thread.start()
		
		self.connected = True
		self.status_label.config(text='Status: Connected', fg='green')
		self.connect_button.config(state=tk.NORMAL, text='Disconnect')
		
		# Disable settings during connection
		self.ip_entry.config(state=tk.DISABLED)
		self.port_entry.config(state=tk.DISABLED)
		self.gate_entry.config(state=tk.DISABLED)
		self.tbr_entry.config(state=tk.DISABLED)
		
		# Start reading data
		self.read_data_stream()
		# Don't auto-start OADEV - let user check the box

	def disconnect_counter(self):
		"""Disconnect from counter and stop streaming"""
		if not self.connected:
			return
		
		self.connected = False
		
		if self.counter:
			self.counter.stop_stream()
			self.counter.cleanup()  # Properly clean up socket
			self.counter = None
		
		# Disconnect socket
		try:
			self.socket.disconnect('tcp://localhost:'+self.port_entry.get().strip())
		except:
			pass
		
		self.status_label.config(text='Status: Disconnected', fg='red')
		self.connect_button.config(state=tk.NORMAL, text='Connect')
		
		# Re-enable settings
		self.ip_entry.config(state=tk.NORMAL)
		self.port_entry.config(state=tk.NORMAL)
		self.gate_entry.config(state=tk.NORMAL)
		self.tbr_entry.config(state=tk.NORMAL)

	def quit_app(self):
		"""Disconnect before quitting"""
		if self.connected:
			self.disconnect_counter()
		self.destroy()

	def read_data_stream(self):
		
		if not self.connected:
			return
		
		try:
			r = np.array([float(i) for i in self.socket.recv_string().split(',')])
		except zmq.error.Again:
			# Timeout occurred, reschedule and retry
			self.after(int(950 * self.time_between_reads), self.read_data_stream)
			return
		except Exception as e:
			print(f'Error receiving data: {e}')
			self.status_label.config(text=f'Status: Error - {str(e)[:30]}', fg='red')
			return

		if self.initialized:
			self.t = np.concatenate((self.t, np.arange(1,len(r)+1)*self.gate_time + self.t[-1]))
		else:
			self.t = np.concatenate((self.t, np.arange(len(r))*self.gate_time))
			self.initialized = True

		self.f = np.concatenate((self.f, r))

		if len(self.t) > self.time_series_record_length:
			self.time_series_fig.redraw(x=self.t[-self.time_series_record_length:],
			 							y=self.f[-self.time_series_record_length:])
		else:
			self.time_series_fig.redraw(x=self.t,y=self.f)
		
		# Save data only if logging is enabled and we have data after logging started
		if self.log_data.get() and len(self.t) > self.log_start_index:
			# Only save data from logging start point onwards
			np.savetxt('./data/'+self.time_series_file, np.array([self.t[self.log_start_index:],self.f[self.log_start_index:]]).T)
		
		# Append to f_start if OADEV plotting is enabled
		if self.plot_oadev.get():
			self.t_start = np.concatenate((self.t_start, self.t[-len(r):]))
			self.f_start = np.concatenate((self.f_start, r))
		
		# Append to f_psd if PSD plotting is enabled
		if self.plot_psd.get():
			self.f_psd = np.concatenate((self.f_psd, r))
		
		self.after(int(950 * self.time_between_reads), self.read_data_stream)

	def toggle_oadev_plotting(self):
		"""Toggle OADEV plotting on/off"""
		if self.plot_oadev.get():
			# Checkbox is checked - clear starting data and start plotting from scratch
			self.f_start = np.array([])
			self.t_start = np.array([])
			print(f'OADEV plotting started')
			# Schedule update to start collecting data
			self.after(self.allan_update_time * 1000, self.update_allan_dev)
		else:
			# Checkbox is unchecked - keep last plot but stop updating
			print('OADEV plotting stopped')

	def toggle_logging(self):
		"""Toggle logging on/off and generate new filename when enabled"""
		if self.log_data.get():
			# Generate new filenames with current timestamp
			self.generate_log_filenames()
			# Set start index to only log data from this point onwards
			self.log_start_index = len(self.f)
			print(f'Logging started - saving to {self.time_series_file}')
		else:
			print('Logging stopped')

	def update_allan_dev(self):
		# Only update if OADEV plotting is enabled
		if not self.plot_oadev.get():
			return
		
		t = time.time()
		data_f = self.f_start
		
		if len(data_f) > 2:
			try:
				# Detrend data if enabled
				detrended_f, trend_slope = self.get_detrended_data(data_f)
				
				# Update trend label (scaled by gate time to show trend per second)
				if trend_slope is not None:
					scaled_trend = trend_slope / self.gate_time
					self.trend_label.config(text=f'Trend: {scaled_trend:.3e}/s')
				else:
					self.trend_label.config(text='Trend: --')
				
				taus, ad, ade, ns = at.oadev(detrended_f/self.f0, rate=1/self.gate_time, data_type='freq')
				self.allan_dev_fig.redraw(x=taus, y=ad, set_xlog=True, set_ylog=True)
			except ValueError as e:
				# Handle case where data has no positive values
				print(f'OADEV plotting error: {e}')
		print(time.time()-t)
		
		# Schedule next update only if plotting is still enabled
		if self.plot_oadev.get():
			self.after(self.allan_update_time * 1000, self.update_allan_dev)
	
	def set_f0_and_recalc(self):
		try:
			new_f0 = float(self.f0_entry.get())
			self.f0 = new_f0
			if self.plot_oadev.get():
				self.update_allan_dev()
		except ValueError:
			print('Invalid F0 value entered')

	def generate_log_filenames(self):
		"""Generate new log filenames with current timestamp in format: ks_YYYYMMDD_HHMMSS_timeseries_mode_gatetime"""
		date_str = time.strftime('%Y%m%d')
		time_str = time.strftime('%H%M%S')
		mode = self.freq_mode  # RCON or CONT
		gate_time = int(self.gate_time) if self.gate_time == int(self.gate_time) else self.gate_time
		
		# Format: ks_YYYYMMDD_HHMMSS_timeseries_mode_gatetime
		self.time_series_file = f'ks_{date_str}_{time_str}_timeseries_{mode}_{gate_time}.txt'
		self.allan_file = f'ks_{date_str}_{time_str}_allan_{mode}_{gate_time}.txt'

	def get_detrended_data(self, data):
		"""Subtract linear trend from data if enabled, return detrended data and trend slope"""
		if not self.subtract_trend.get() or len(data) < 2:
			return data, None
		
		# Fit polynomial (line) to the data using indices as x-axis
		x = np.arange(len(data))
		coeffs = np.polyfit(x, data, 1)
		trend_line = np.polyval(coeffs, x)
		detrended = data - trend_line
		
		# Return slope (trend value per sample)
		return detrended, coeffs[0]

	def toggle_psd_plotting(self):
		"""Toggle PSD plotting on/off"""
		if self.plot_psd.get():
			# Checkbox is checked - clear PSD data and start plotting from scratch
			self.f_psd = np.array([])
			print(f'PSD plotting started')
			# Schedule update to start collecting data
			self.after(self.allan_update_time * 1000, self.update_psd)
		else:
			# Checkbox is unchecked - keep last plot but stop updating
			print('PSD plotting stopped')

	def set_psd_averaging(self):
		"""Set the averaging (nperseg) parameter for Welch"""
		try:
			new_avg = int(self.avg_entry.get().strip())
			if new_avg < 2:
				raise ValueError('Averaging must be at least 2')
			self.psd_averaging = new_avg
			print(f'PSD averaging set to {self.psd_averaging}')
		except ValueError as e:
			print(f'Invalid averaging value: {e}')

	def update_psd(self):
		"""Calculate and update Power Spectral Density using Welch method"""
		# Only update if PSD plotting is enabled
		if not self.plot_psd.get():
			return
		
		t = time.time()
		data_f = self.f_psd
		
		if len(data_f) > self.psd_averaging:
			try:
				# Detrend data if enabled
				detrended_f, trend_slope = self.get_detrended_data(data_f)
				
				# Calculate PSD using Welch method
				freqs, pxx = signal.welch(detrended_f, fs=1/self.gate_time, nperseg=self.psd_averaging)
				# Scale PSD to rad^2/Hz by dividing by frequency squared
				pxx = pxx / (freqs ** 2)
				self.psd_fig.ax.clear()
				self.psd_fig.ax.loglog(freqs, pxx)
				self.psd_fig.ax.set_xlabel('Frequency (Hz)')
				self.psd_fig.ax.set_ylabel('Power Spectral Density (rad$^2$/Hz)')
				self.psd_fig.ax.grid(which='minor',alpha=0.5)
				self.psd_fig.ax.grid()
				self.psd_fig.ax.tick_params(labelsize=8)
				self.psd_fig.fig.tight_layout()
				self.psd_fig.canvas.draw()
			except ValueError as e:
				# Handle case where data has no positive values
				print(f'PSD plotting error: {e}')
		print(time.time()-t)
		
		# Schedule next update only if plotting is still enabled
		if self.plot_psd.get():
			self.after(self.allan_update_time * 1000, self.update_psd)


class FigureFrame(tk.Frame):

	def __init__(self, parent, figsize=(7, 5)):
		
		tk.Frame.__init__(self, parent)
		
		self.x = []
		self.y = []
		self.log_scales_set = False

		self.fig = Figure(figsize=figsize, dpi=100)
		self.ax = self.fig.add_subplot()
		self.line, = self.ax.plot(self.x,self.y)
		self.ax.set_xlabel('t')
		self.ax.set_ylabel('Frequency (Hz)')
		self.fig.tight_layout()

		self.canvas = FigureCanvasTkAgg(self.fig, master=self)
		self.canvas.draw()
		self.toolbar = NavigationToolbar2Tk(self.canvas, self, 
			pack_toolbar=False)

		self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)
		self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, 
			expand=True)

	def redraw(self, x=[], y=[], set_xlog=False, set_ylog=False):
		#print(x[0],y[0])
		self.line.set_data(x,y)
		# Set log scales on first data plot if requested
		if not self.log_scales_set and len(x) > 0:
			if set_xlog:
				self.ax.set_xscale('log')
			if set_ylog:
				self.ax.set_yscale('log')
			self.log_scales_set = True
		self.ax.relim()
		self.ax.autoscale_view()
		self.fig.tight_layout()
		self.canvas.draw()


if __name__ == '__main__':

	import sys

	virtual = False
	data_name = 'foo'
	
	if len(sys.argv) > 1:
		if sys.argv[1] == '-v' or sys.argv[1] == '--virtual':
			virtual = True
			if len(sys.argv) > 2:
				data_name = sys.argv[2]
		else:
			data_name = sys.argv[1]
			if len(sys.argv) > 2 and (sys.argv[2] == '-v' or sys.argv[2] == '--virtual'):
				virtual = True

	app = MyApp(data_name, virtual=virtual)
	app.mainloop()