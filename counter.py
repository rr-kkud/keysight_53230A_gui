import pyvisa
import zmq
import config
from time import sleep
from numpy.random import default_rng
import argparse


class Counter(object):

	def __init__(self, ip='192.168.19.80', port='5555', gate_time=1, time_between_reads=3, freq_mode='RCON', virtual=False):
		# define the counter parameters and the socket
		self.virtual = virtual
		self.ip = ip
		self.port = port
		self.gate_time = gate_time
		self.time_between_reads = time_between_reads
		self.freq_mode = freq_mode
		self.inst = None
		self.socket = None
		self.is_running = False

		try:
			self.context = zmq.Context()		
			self.socket = self.context.socket(zmq.PUB)
			self.socket.setsockopt(zmq.LINGER, 0)  # Don't linger on close
			self.socket.bind('tcp://*:'+port)
		except Exception as e:
			print(f'Error setting up ZMQ socket: {e}')
			self.socket = None

	def connect(self):
		"""Initialize connection to counter device"""
		try:
			if not self.virtual:
				rm = pyvisa.ResourceManager()
				usb_id = f'TCPIP::{self.ip}::INSTR'
				self.inst = rm.open_resource(usb_id)
				self.inst.write('*RST')
				self.inst.write(f'SENS:FREQ:MODE {self.freq_mode};')
				self.inst.write(f'SENS:FREQ:GATE:TIME {self.gate_time};')
				#self.inst.write('TRIG:SOUR IMM; COUN MAX;')
				self.inst.write('SAMP:COUN MAX')
			return True
		except Exception as e:
			print(f'Error connecting to counter: {e}')
			return False		

	def cleanup(self):
		"""Cleanup socket and context"""
		try:
			if self.socket:
				self.socket.close(linger=0)
				self.socket = None
			if hasattr(self, 'context') and self.context:
				self.context.term()
				self.context = None
		except Exception as e:
			print(f'Error cleaning up socket: {e}')

	def start_stream(self):
		"""Start streaming data from counter"""
		if not self.socket:
			print('Error: Socket not initialized')
			return
		
		if not self.virtual and not self.inst:
			print('Error: Counter not connected')
			return

		self.is_running = True

		if self.virtual:
			rng = default_rng()
			f0 = 79.860e6
			sigma = 100
			while self.is_running:
				num = int(self.time_between_reads/self.gate_time + rng.integers(-2,2))
				freqs = f0 + sigma*rng.standard_normal(num)
				r = ','.join(['%+.15e'%i for i in freqs])+'\n'
				print(r)
				self.socket.send_string(r)
				sleep(1)
		else:
			self.inst.write('INIT')
			sleep(self.gate_time)

			while self.is_running:
				r = self.inst.query('R?')
				if r != '#10\n':
					while r[0] != '+':
						r = r[1:]
					self.socket.send_string(r)

				sleep(self.time_between_reads)

	def stop_stream(self):
		"""Stop streaming data"""
		self.is_running = False

class CounterParser(argparse.ArgumentParser):
	def __init__(self):
		argparse.ArgumentParser.__init__(self)
		self.add_argument('-v', '--virtual', help='Virtual counter mode.',
					action='store_true')



if __name__ == '__main__':

	parser = CounterParser()
	args = parser.parse_args()
	
	if args.virtual:
		print('Using Virtual Counter')
		myCounter = Counter(virtual=True)
	else:
		myCounter = Counter()
	
	# Connect first, then start streaming
	if myCounter.connect():
		print('Connected to counter successfully')
		myCounter.start_stream()
	else:
		print('Failed to connect to counter')