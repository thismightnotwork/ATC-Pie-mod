
#
# This file is part of the ATC-pie project,
# an air traffic control simulation program.
# 
# Copyright (C) 2015  Michael Filhol <mickybadia@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA
#

try:
	from pyaudio import PyAudio, paInt16
	pyaudio_available = True
except ImportError:
	pyaudio_available = False

from PyQt5.QtCore import QThread


# ---------- Constants ----------

default_pyaudio_chunk_size = 1024
default_pyaudio_sample_rate = 16000

# -------------------------------

class InOutAudioStreamer(QThread):
	"""
	Subclasses should define a method processMicAudioChunk(bytes) automatically called when mic audio is being processed
	"""
	def __init__(self, parent, audioChunkSize=default_pyaudio_chunk_size, audioSampleRate=default_pyaudio_sample_rate):
		QThread.__init__(self, parent)
		self.py_audio = PyAudio()
		self.audio_chunk_size = audioChunkSize
		self.audio_sample_rate = audioSampleRate
		self.audio_in = None
		self.audio_out = None
		self.running = False
		self.process_audio_in = False

	def run(self):
		self.audio_in = self.py_audio.open(format=paInt16, channels=1, rate=self.audio_sample_rate,
				frames_per_buffer=self.audio_chunk_size, input=True, output=True, start=False)
		self.audio_out = self.py_audio.open(format=paInt16, channels=1, rate=self.audio_sample_rate,
				frames_per_buffer=self.audio_chunk_size, output=True)
		self.running = True
		while self.running:
			if self.processingMicAudio(): # sound must be picked up and processed
				if self.audio_in.is_stopped():
					self.audio_in.start_stream()
				self.processMicAudioChunk(self.audio_in.read(self.audio_chunk_size, exception_on_overflow=False))
			else: # no reason to keep recording
				if not self.audio_in.is_stopped():
					self.audio_in.stop_stream()
				self.msleep(100)
		self.audio_in.close()
		self.audio_out.close()

	def stopAndWait(self, allowRestart=False):
		self.process_audio_in = False
		self.running = False
		self.wait()
		if not allowRestart:
			self.py_audio.terminate()

	def receiveAudioData(self, data):
		if self.running:
			self.audio_out.write(data)

	def startProcessingMicAudio(self):
		self.process_audio_in = True

	def stopProcessingMicAudio(self):
		self.process_audio_in = False

	def processingMicAudio(self):
		return self.process_audio_in

	## Methods to implement in subclasses below
	def processMicAudioChunk(self, audio_data):
		raise NotImplementedError()
