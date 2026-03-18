
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

import re
from sys import stderr
from os import path

from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QDialog, QMessageBox, QLabel, QPushButton, QVBoxLayout

from base.radio import CommFrequency, EMG_comm_freq, AbstractRadio
from base.nav import Navpoint, world_navpoint_db
from base.params import Heading

from gui.widgets.basicWidgets import Ticker

from session.config import settings
from session.env import env
from session.manager import SessionType


# ---------- Constants ----------

radio_signal_strength = 11 # W
FGCom_tick_interval = 100 # ms
echo_test_freq_str = '910.00'
mumble_plugin_str_encoding = 'utf8'
mumble_plugin_special_freq_stop_packet_count = 3

legacy_FGCom_executable = 'fgcom'
legacy_FGCom_server = 'fgcom.flightgear.org'
legacy_FGCom_standard_port = 16661
legacy_FGCom_reserved_port = 16665

# -------------------------------


class FGComRadio(AbstractRadio):
	def __init__(self):
		AbstractRadio.__init__(self)
		self._on = False
		self._frq = EMG_comm_freq
		self._ptt = False
		self._vol = 1 # float: 0=muted; 1=loudest
	
	## Defining AbstractRadio methods below
	def isOn(self):
		return self._on
	
	def frequency(self):
		return self._frq
	
	def isTransmitting(self):
		return self._on and self._ptt
	
	def volume(self):
		return self._vol if self._on else 0
	
	def switchOnOff(self, toggle):
		self._on = toggle
	
	def setFrequency(self, new_frq):
		self._frq = new_frq
	
	def setPTT(self, ptt):
		self._ptt = ptt
	
	def setVolume(self, volume):
		self._vol = volume




###  FGCom-mumble  ###

# Two global variables that affect what is sent to Mumble client
FGCom_Mumble_testing_counter = 0
FGCom_Mumble_recording_counter = 0


def escape_str_field(s):
	return s.replace('\\', '\\\\').replace(',', '\\,').replace('=', '\\=')

def unescape_str_field(s):
	return re.sub(r'\\(.)', r'\1', s)


def send_FGCom_mumble_control_packet(socket, host, port, sfx):
	global FGCom_Mumble_testing_counter, FGCom_Mumble_recording_counter
	if FGCom_Mumble_testing_counter == 0 and FGCom_Mumble_recording_counter == 0 and len(settings.radios) == 0:
		return # no point sending anything
	coords, alt = env.rdf.antennaPos()
	data = 'CALLSIGN=%s' % escape_str_field(settings.my_callsign)
	data += ',LAT=%f,LON=%f' % (coords.lat, coords.lon)
	data += ',ALT=%f,HGT=%f' % (alt, alt - env.elevation(coords))
	data += ',AUDIO_FX_RADIO=%d' % sfx
	for i, radio in enumerate(settings.radios, 1): # start at 1 (no "COM0" radio)
		# unsent fields: COMn_VLT (electrical power; default=12) and COMn_SRV (failed vs. serviceable; default=1)
		data += ',COM%d_PBT=%d' % (i, radio.isOn() or radio.isRdfMonitored())
		data += ',COM%d_FRQ=%.4f' % (i, radio.frequency().MHz()) # .4 precision to prevent confusion with channel name by plug-in
		data += ',COM%d_CWKHZ=8.33' % i
		data += ',COM%d_PTT=%d' % (i, radio.isTransmitting())
		data += ',COM%d_PWR=%f' % (i, radio_signal_strength)
		data += ',COM%d_VOL=%f' % (i, radio.volume()) # zero if radio is off
		if settings.radio_direction_finding:
			data += ',COM%d_RDF=%d' % (i, radio.isRdfMonitored())
	isupp = len(settings.radios) + 1
	if FGCom_Mumble_testing_counter != 0:
		data += ',COM%d_PBT=1' % isupp
		data += ',COM%d_FRQ=%s' % (isupp, echo_test_freq_str)
		data += ',COM%d_PTT=%d' % (isupp, FGCom_Mumble_testing_counter > 0)
		data += ',COM%d_VOL=1' % isupp
		if FGCom_Mumble_testing_counter < 0: # stopping
			FGCom_Mumble_testing_counter += 1
	elif FGCom_Mumble_recording_counter != 0 and settings.last_recorded_ATIS is not None:
		data += ',COM%d_PBT=1' % isupp
		data += ',COM%d_FRQ=RECORD_%.4f' % (isupp, settings.last_recorded_ATIS[2].MHz()) # .4 precision to prevent confusion with channel name by plug-in
		data += ',COM%d_PTT=%d' % (isupp, FGCom_Mumble_recording_counter > 0)
		if FGCom_Mumble_recording_counter < 0: # stopping
			FGCom_Mumble_recording_counter += 1
	#DEBUGprint('FGCom-M packet:', data)
	socket.sendto(bytes(data, 'utf8'), (host, port))



fgcom_mumble_RDF_signal_line_header = 'RDF:'
fgcom_mumble_field_regex = re.compile(r'\w+=([^,=\\]|\\.)*')

def receive_FGCom_mumble_packet(datagram):
	signal_freqs = set()
	for signal_line in datagram.decode(encoding=mumble_plugin_str_encoding).split('\n'):
		if signal_line.startswith(fgcom_mumble_RDF_signal_line_header):
			sig_dict = {}
			for match in fgcom_mumble_field_regex.finditer(signal_line[len(fgcom_mumble_RDF_signal_line_header):]):
				key, val = match.group().split('=', maxsplit=1)
				sig_dict[key] = unescape_str_field(val)
			try:
				frq = CommFrequency(float(sig_dict['FRQ'])) # float conversion for MHz value (not a channel name)
				hdg = Heading(float(sig_dict['DIR']), True) # radial from antenna
				qual = float(sig_dict.get('QLY', 1)) # given default value; OK if missing
				signal_freqs.add(frq)
				env.rdf.radioSignal(frq, hdg, quality=qual)
			except KeyError as err:
				print('ERROR in FGCom-mumble data: missing %s for RDF signal.' % err, file=stderr)
			except ValueError as err:
				print('ERROR in FGCom-mumble data: %s' % err, file=stderr)
	for radio in settings.radios:
		if radio.isRdfMonitored():
			sig = radio.rdfSignal()
			if sig is not None and not any(frq.inTune(sig.frequency) for frq in signal_freqs):
				env.rdf.endOfSignal(sig.frequency)


def test_FGCom_Mumble(parent_widget, host, port, sfx):
	global FGCom_Mumble_testing_counter
	if settings.session_manager.isRunning() and (settings.session_manager.session_type == SessionType.FLIGHTGEAR
			or settings.session_manager.session_type == SessionType.FSD) and settings.FGCom_enabled:
		ticker = None
	else: # no FGCom ticker currently running; ad hoc ticker needed to enable stream of UDP control packets to plug-in
		ticker = Ticker(parent_widget, lambda: send_FGCom_mumble_control_packet(settings.FGFS_views_send_socket, host, port, sfx)) # NOTE: hijacking a UDP socket
		ticker.startTicking(FGCom_tick_interval)
	FGCom_Mumble_testing_counter = 1
	QMessageBox.information(parent_widget, 'FGCom-mumble test', 'Testing FGCom-mumble... Hearing echo?')
	FGCom_Mumble_testing_counter = -mumble_plugin_special_freq_stop_packet_count
	if ticker is not None:
		ticker.stop()
		ticker.deleteLater()
		while FGCom_Mumble_testing_counter < 0:
			send_FGCom_mumble_control_packet(settings.FGFS_views_send_socket, host, port, sfx) # NOTE: hijacking a UDP socket

def record_FGCom_Mumble_ATIS(parent_widget):
	global FGCom_Mumble_recording_counter
	FGCom_Mumble_recording_counter = 1
	QMessageBox.information(parent_widget, 'Record ATIS', 'Now recording...\nClose dialog when finished.')
	FGCom_Mumble_recording_counter = -mumble_plugin_special_freq_stop_packet_count




###  Legacy FGCom (standalone executable)  ###

# INFO: 122.75 and 123.45 are special freq's in this FGCom variant for global A/A comm's

class LegacyFGComProcess(QProcess):
	def __init__(self, parent, cmdexe, cmdopts, server, port):
		QProcess.__init__(self, parent)
		cmdopts.append('--server=%s' % server)
		cmdopts.append('--port=%d' % port)
		cmdopts.append('--callsign=%s' % settings.my_callsign)
		self.setWorkingDirectory(path.dirname(path.abspath(cmdexe)))
		self.setProgram(cmdexe)
		self.setArguments(cmdopts)
		self.setStandardErrorFile(settings.outputFileName('fgcom-%d' % port, windowID=False, ext='stderr'))
		# DEBUGprint('FGCom command: %s %s' % (FGCom_executable, ' '.join(cmdopts)))


class LegacyFGComDialog(QDialog):
	def __init__(self, parent_widget, window_title, prgm_exe, prgm_options, server, port, text_on_started):
		QDialog.__init__(self, parent_widget)
		self.setWindowTitle(window_title)
		self.info_label = QLabel('Starting FGCom...', self)
		self.close_button = QPushButton('Close', self)
		self.layout = QVBoxLayout(self)
		self.layout.addWidget(self.info_label)
		self.layout.addWidget(self.close_button)
		self.text_on_started = text_on_started
		self.instance = LegacyFGComProcess(self, prgm_exe, prgm_options, server, port)
		self.close_button.clicked.connect(self.closeMe)
		self.instance.started.connect(self.processHasStarted)
		self.instance.finished.connect(self.processHasStopped)
		self.instance.start()

	def processHasStopped(self):
		self.info_label.setText('FGCom process has stopped.')

	def processHasStarted(self):
		self.info_label.setText(self.text_on_started)

	def closeMe(self):
		if self.instance.state() == QProcess.Running:
			self.info_label.setText('Closing...')
			self.instance.kill()
			self.instance.waitForFinished()
		self.accept()


class LegacyFGComRadio(FGComRadio):
	def __init__(self, socket, port):
		FGComRadio.__init__(self)
		self.send_socket = socket
		self.client_port = port
		ad = world_navpoint_db.findClosest(env.radarPos(), types=[
			Navpoint.AD]).code if env.airport_data is None else settings.location_code
		self.instance = LegacyFGComProcess(settings.session_manager.gui, legacy_FGCom_executable, ['--airport=%s' % ad],
										   legacy_FGCom_server, port)
		self.instance.finished.connect(self.processHasStopped)

	def controlPort(self):
		return self.client_port

	# override method
	def switchOnOff(self, toggle):  # FGCom process to deal with
		if toggle:
			self.instance.start()
			self._on = self.instance.waitForStarted()
			if self._on:
				print('Standalone FGCom process started listening on port %d' % self.controlPort())
			else:  # no "finished" signal if process could not start here
				print('ERROR: Could not start FGCom; is provided command valid?', file=stderr)
		else:
			self._on = False
			self.instance.kill()
			self.instance.waitForFinished()
			print('Standalone FGCom process (using port %d) stopped.' % self.controlPort())

	def sendControlPacket(self):
		if self._on:
			coords, alt = env.rdf.antennaPos()
			packet_str = 'CALLSIGN=%s' % settings.my_callsign
			packet_str += ',LAT=%f,LON=%f,ALT=%f' % (coords.lat, coords.lon, alt)
			packet_str += ',PTT=%d' % self.isTransmitting()  # False if radio is off
			packet_str += ',COM1_FRQ=%.3f,COM2_FRQ=121.850' % self.frequency().MHz()
			packet_str += ',OUTPUT_VOL=%f,SILENCE_THD=-60' % self.volume()  # zero if radio is off
			# DEBUGprint('FGCom-S packet:', packet_str)
			self.send_socket.sendto(bytes(packet_str, 'utf8'), ('localhost', self.controlPort()))

	def processHasStopped(self):
		if self._on:
			print('WARNING: Standalone FGCom process (using port %d) stopped.' % self.controlPort(), file=stderr)
			self._on = False


def test_legacy_FGCom(parent_widget, command, server, port):
	LegacyFGComDialog(parent_widget, 'Standalone FGCom echo test',
			command, ['--frequency=%s' % echo_test_freq_str], server, port, 'Testing standalone FGCom... Hearing echo?').exec()

def record_legacy_FGCom_ATIS(parent_widget):
	LegacyFGComDialog(parent_widget, 'Record ATIS',
			legacy_FGCom_executable, ['--airport=%s' % settings.location_code, '--atis=%s' % settings.last_recorded_ATIS[2]],
			legacy_FGCom_server, legacy_FGCom_reserved_port, 'Speak after beep...').exec()
