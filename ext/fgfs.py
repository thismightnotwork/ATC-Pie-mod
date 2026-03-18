
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

from socket import socket, AF_INET, SOCK_STREAM
from sys import stderr

from PyQt5.QtCore import QProcess, QThread

from base.coords import pitchLookAt
from base.util import m2NM, INET_addr_str

from gui.misc import signals
from gui.widgets.basicWidgets import Ticker

from session.config import settings
from session.env import env


# ---------- Constants ----------

fgfs_viewing_acft_model = 'ufo'
dummy_viewer_callsign = 'ATC-pie'
tracker_cmd_repeat_interval = 35 # ms
initial_FOV = 55 # degrees of horizontal angle covered

ATCpie_model_string = 'ATC-pie'

# -------------------------------

FGFS_ACFT_recogniser = []
FGFS_ATC_recogniser = []

FGFS_model_chooser = {}  # str type dez -> (float height, float lat offset, float fwd offset)
FGFS_model_liveries = {} # str type dez -> (str airline -> str livery file)


def is_ATC_model(fgfs_model):
	return fgfs_model == ATCpie_model_string or any(regexp.match(fgfs_model) for regexp in FGFS_ATC_recogniser)


# FGFS model -> ICAO type identification (used when reading FGMS packets)
def ICAO_aircraft_type(fgfs_model):
	return next((icao for regexp, icao in FGFS_ACFT_recogniser if regexp.match(fgfs_model)), fgfs_model)


def FGFS_model_position(icao_type_dez, coords, amsl, heading):
	try:
		model, (height, lat_offset, fwd_offset) = FGFS_model_chooser[icao_type_dez]
		lat_dir = heading + (90 if lat_offset >= 0 else 270)
		fwd_dir = heading if fwd_offset >= 0 else heading.opposite()
		return model, coords.moved(lat_dir, m2NM * abs(lat_offset)).moved(fwd_dir, m2NM * abs(fwd_offset)), amsl + height
	except KeyError:  # fallback on ICAO type designator itself
		return icao_type_dez, coords, amsl






def send_packet_to_views(udp_packet):
	if settings.controlled_tower_viewer.isRunning():
		tower_viewer_host = settings.external_tower_viewer_host if settings.external_tower_viewer_process else 'localhost'
		send_packet_to_view(udp_packet, (tower_viewer_host, settings.tower_viewer_UDP_port))
		#print('Sent packet to %s:%d' % (tower_viewer_host, settings.tower_viewer_UDP_port))
	for i in settings.activated_additional_viewers:
		send_packet_to_view(udp_packet, settings.additional_viewers[i])


def send_packet_to_view(packet, addr):
	try:
		settings.FGFS_views_send_socket.sendto(packet, addr)
	except OSError as err:
		print('Error sending data to FG viewer.', str(err), file=stderr)







def fgTwrCommonOptions():
	assert env.airport_data is not None
	pos, alt = env.viewpoint()
	return ['--lat=%s' % pos.lat, '--lon=%s' % pos.lon, '--altitude=%g' % alt, '--heading=360',
			'--aircraft=%s' % fgfs_viewing_acft_model, '--fdm=null']



class FlightGearTowerViewer:
	def __init__(self, gui):
		self.gui = gui
		self._running = False
		self.telnet_connection = None
		self.get_tracking_target = None # callback to generate live (EarthCoords, float real alt.) to look at while tracking
		self.tracker_ticker = Ticker(gui, lambda: self._turnToPoint(*self.get_tracking_target()))
		self.internal_process = QProcess(gui)
		self.internal_process.setStandardErrorFile(settings.outputFileName('fgfs', ext='stderr'))
		self.internal_process.stateChanged.connect(self._internalProcessStateChanged)

	def _internalProcessStateChanged(self, state):
		if state == QProcess.Running:
			self._notifyStartStop(True)
		elif state == QProcess.NotRunning:
			self._notifyStartStop(False)
		# NOTE: ignoring third case QProcess.Starting, not to signal anything on process state change

	def _notifyStartStop(self, b):
		self._running = b
		if b:
			tower_viewer_host = settings.external_tower_viewer_host if settings.external_tower_viewer_process else 'localhost'
			self.telnet_connection = ThreadedTelnetSession(self.gui, tower_viewer_host, settings.tower_viewer_telnet_port)
			self.telnet_connection.start()
		elif self.telnet_connection is not None:
			self.telnet_connection.stop() # destroys connection and terminates thread
			self.telnet_connection = None
		signals.towerViewToggled.emit(b)

	def _sendCmd(self, cmd):
		"""
		cmd can be a single command (str) or a command list
		"""
		if self.isRunning():
			self.telnet_connection.enqueueCommands(cmd if isinstance(cmd, list) else [cmd])

	def isRunning(self):
		return self._running

	def start(self):
		weather = env.primaryWeather()
		if settings.external_tower_viewer_process:
			self._notifyStartStop(True)
			if weather is not None:
				self.setWeather(weather)
		else:
			fgfs_options = fgTwrCommonOptions()
			fgfs_options.append('--roll=0')
			fgfs_options.append('--pitch=0')
			fgfs_options.append('--vc=0')
			fgfs_options.append('--fov=%g' % initial_FOV)
			# Env. options
			fgfs_options.append('--time-match-real')
			if weather is None:
				fgfs_options.append('--disable-real-weather-fetch')
			else:
				fgfs_options.append('--metar=%s' % weather.METAR()) # implies --disable-real-weather-fetch
			# Local directory options
			if settings.FGFS_root_dir != '':
				fgfs_options.append('--fg-root=%s' % settings.FGFS_root_dir)
			if settings.FGFS_aircraft_dir != '':
				fgfs_options.append('--fg-aircraft=%s' % settings.FGFS_aircraft_dir)
			if settings.FGFS_scenery_dir != '':
				fgfs_options.append('--fg-scenery=%s' % settings.FGFS_scenery_dir)
			# Connection options
			fgfs_options.append('--callsign=%s' % dummy_viewer_callsign)
			fgfs_options.append('--multiplay=out,100,localhost,%d' % settings.FGFS_views_send_port)
			fgfs_options.append('--multiplay=in,100,localhost,%d' % settings.tower_viewer_UDP_port)
			fgfs_options.append('--telnet=,,100,,%d,' % settings.tower_viewer_telnet_port)
			# Options for lightweight (interface and CPU load)
			fgfs_options.append('--disable-ai-traffic')
			fgfs_options.append('--disable-panel')
			fgfs_options.append('--disable-sound')
			fgfs_options.append('--disable-hud')
			fgfs_options.append('--disable-fullscreen')
			fgfs_options.append('--prop:/sim/menubar/visibility=false')
			# Now run
			self.internal_process.setProgram(settings.FGFS_executable)
			self.internal_process.setArguments(fgfs_options)
			#DEBUGprint('Running: %s %s' % (settings.FGFS_executable, ' '.join(fgfs_options)))
			self.internal_process.start()
		
	def stop(self, wait=False):
		self.stopTracking()
		if self.isRunning():
			if settings.external_tower_viewer_process:
				self._notifyStartStop(False)
			else:
				self.internal_process.terminate()
				if wait:
					self.internal_process.waitForFinished() # default time-out

	def startTracking(self, point_callback):
		if self.isRunning():
			self.get_tracking_target = point_callback
			self.tracker_ticker.startTicking(tracker_cmd_repeat_interval, immediate=True)

	def stopTracking(self):
		self.tracker_ticker.stop()
		self.get_tracking_target = None

	# Meaningful methods for sending FG telnet commands
	def _turnToPoint(self, earth_coords, target_alt):
		twr_pos, twr_alt = env.viewpoint()
		hdg = twr_pos.headingTo(earth_coords).trueAngle()
		pitch = pitchLookAt(twr_pos.distanceTo(earth_coords), target_alt - twr_alt)
		self._sendCmd(['set /sim/current-view/goal-heading-offset-deg %g' % -hdg,
				'set /sim/current-view/goal-pitch-offset-deg %g' % pitch])

	def lookAtPoint(self, earth_coords, target_alt):
		self.stopTracking()
		self._turnToPoint(earth_coords, target_alt)

	def lookInDirection(self, d):
		self.stopTracking()
		self._sendCmd(['set /sim/current-view/goal-heading-offset-deg %g' % -d.trueAngle(),
				'set /sim/current-view/goal-pitch-offset-deg 0'])

	def updateTowerPosition(self):
		twr_pos, twr_alt = env.viewpoint()
		self._sendCmd(['set /position/latitude-deg %g' % twr_pos.lat,
				'set /position/longitude-deg %g' % twr_pos.lon,
				'set /position/altitude-ft %g' % twr_alt])

	def setWeather(self, weather):
		self._sendCmd('set /environment/metar/data %s' % weather.METAR())

	def ensureDayLight(self):
		self._sendCmd('run timeofday noon')

	def setFOV(self, fov):
		self._sendCmd('set /sim/current-view/field-of-view %g' % fov)




class ThreadedTelnetSession(QThread):
	def __init__(self, gui, host, port):
		QThread.__init__(self, gui)
		try:
			self.socket = socket(AF_INET, SOCK_STREAM)
		except OSError as err:
			print('Failed to create socket; tower viewer control inoperative.', str(err), file=stderr)
			self.socket = None
		self.peer_host = host
		self.peer_port = port
		self.cmd_queue = []

	def enqueueCommands(self, cmdlst):
		self.cmd_queue.extend(cmdlst)
		self.start()

	def connected(self):
		if self.socket is not None:
			try:
				ignore = self.socket.getpeername()
				return True
			except OSError:
				pass
		return False
	
	def run(self):
		if self.socket is not None:
			while not self.connected():
				try:
					QThread.sleep(5)
					self.socket.connect((self.peer_host, self.peer_port))
					print('Connection established with tower viewer %s.' % INET_addr_str(self.peer_host, self.peer_port))
				except OSError as err:
					print('Connection to tower viewer failed (%s); retrying...' % err, file=stderr)
			try:
				while self.cmd_queue:
					#DEBUG print('Sending command:', self.cmd_queue[0])
					self.socket.sendall(bytes(self.cmd_queue.pop(0) + '\r\n', 'utf8'))
			except OSError as err:
				print(str(err), file=stderr)
				self.cmd_queue.clear()
	
	def stop(self):
		self.terminate()
		self.cmd_queue.clear()
		if self.connected():
			self.socket.close()
