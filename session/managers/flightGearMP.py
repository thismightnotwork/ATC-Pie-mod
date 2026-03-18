
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

from sys import stderr
from datetime import timedelta
from socket import socket, AF_INET, SOCK_DGRAM, SOL_SOCKET, SO_REUSEADDR

from PyQt5.QtCore import QMutex, QThread
from PyQt5.QtWidgets import QMessageBox

from base.cpdlc import CpdlcMessage
from base.phone import AbstractVoipPhoneManager
from base.strip import handover_details
from base.utc import realTime
from base.util import pop_all, INET_addr_str

from ext.audio import pyaudio_available
from ext.fgcom import FGCom_tick_interval, FGComRadio, send_FGCom_mumble_control_packet, receive_FGCom_mumble_packet, record_FGCom_Mumble_ATIS
from ext.fgfs import is_ATC_model, send_packet_to_views
from ext.fgms import FgmsSender, FgmsAircraft, update_FgmsAircraft_list
from ext.irc import FgIrcCommunicator, IRC_available, ATC_pie_cmd_prefix, IRC_cmd_strip, IRC_cmd_whohas, \
	IRC_cmd_phone_line_open, IRC_cmd_phone_line_close, \
	IRC_cmd_cpdlc_xfr_init, IRC_cmd_cpdlc_xfr_cancel, IRC_cmd_cpdlc_xfr_accept, IRC_cmd_cpdlc_xfr_reject
from ext.lenny64 import Lenny64Error, download_FPLs, file_new_FPL, upload_FPL_updates, set_FPL_status
from ext.noaa import RealWeatherChecker
from ext.orsx import WwStripExchanger

from gui.actions import register_weather_information
from gui.misc import signals
from gui.widgets.basicWidgets import Ticker

from session.config import settings
from session.env import env
from session.manager import SessionManager, SessionType, TextMsgBlocked, HandoverBlocked, OnlineFplActionBlocked, CpdlcOperationBlocked
from session.models.dataLinks import CpdlcDialogueModel


# ---------- Constants ----------

FG_session_tick_interval = 500 # ms
UDP_listen_timeout = 1 # seconds
UDP_max_packet_size = 2048

# CPDLC through IRC
FG_IRC_ACFT_callsign_prefix = 'MP_IRC_'
FG_IRC_cmd_CPDLC_connect = '___CPDLC_CONNECT___'
FG_IRC_cmd_CPDLC_message = '___CPDLC_MSG___' # str msg arg
FG_IRC_cmd_CPDLC_disconnect = '___CPDLC_DISCONNECT___'

# -------------------------------


class Lenny64FplChecker(QThread):
	def __init__(self, parent):
		QThread.__init__(self, parent)
		
	def run(self):
		day = settings.session_manager.clockTime().date()
		downloaded = []
		try:
			for i in range(-4, 5):
				downloaded.extend(download_FPLs(day + i * timedelta(days=1)))
		except Lenny64Error as err:
			print('Error while checking for online flight plans. %s' % err, file=stderr)
		else:
			online_IDs = set()
			for fpl in downloaded:
				online_IDs.add(fpl.online_id)
				env.FPLs.updateFromOnlineDownload(fpl)
			# Remove FPLs that have disappeared online:
			env.FPLs.clearFPLs(lambda fpl: fpl.isOnline() and fpl.online_id not in online_IDs)




class UdpSessionListener(QThread):
	def __init__(self, parent, recv_socket, callback):
		QThread.__init__(self, parent)
		self.socket = recv_socket
		self.process_packet = callback
		
	def run(self):
		self.socket.settimeout(UDP_listen_timeout)
		self.listening = True
		while self.listening:
			try:
				received_packet = self.socket.recv(UDP_max_packet_size)
				#DEBUG('Received packet from %s (%d bytes).' % (received_packet[24:32].decode('utf8'), len(received_packet)))
			except OSError: # this includes the timeout exception from socket.recv
				pass
			else:
				self.process_packet(received_packet)
		self.socket.settimeout(None)
	
	def stop(self):
		self.listening = False




class FgPhoneManager(AbstractVoipPhoneManager):
	def __init__(self, gui):
		AbstractVoipPhoneManager.__init__(self, gui)
		self.phone_socket = None
		self.irc_communicator = None

	def setupComms(self, udp_socket, irc_communicator):
		self.phone_socket = udp_socket
		self.irc_communicator = irc_communicator

	## Defining AbstractVoipPhoneManager methods below
	def sendPhoneData(self, data, inet_addr):
		self.phone_socket.sendto(b'ATCPIE' + data, inet_addr)

	def _sendRequest(self, atc):
		self.irc_communicator.sendCmdMsg(IRC_cmd_phone_line_open, atc)

	def _sendDrop(self, atc):
		self.irc_communicator.sendCmdMsg(IRC_cmd_phone_line_close, atc)




class FlightGearSessionManager(SessionManager):
	def __init__(self, gui):
		SessionManager.__init__(self, gui, SessionType.FLIGHTGEAR)
		self.socket = None # None here when simulation NOT running
		self.FGMS_connections = [] # FgmsAircraft list of "connected" FGMS callsigns
		self.connection_list_mutex = QMutex() # Critical: session ticker clearing zombies vs. UDP listener adding traffic
		self.FPL_checker = Lenny64FplChecker(gui)
		self.weather_checker = RealWeatherChecker(gui, register_weather_information)
		if IRC_available and settings.FG_IRC_enabled:
			self.IRC_communicator = FgIrcCommunicator(gui, [FG_IRC_cmd_CPDLC_connect, FG_IRC_cmd_CPDLC_message, FG_IRC_cmd_CPDLC_disconnect])
		else:
			self.IRC_communicator = None
		if pyaudio_available and settings.phone_lines_enabled and self.IRC_communicator is not None:
			self.phone_manager = FgPhoneManager(gui)
		else:
			self.phone_manager = None
		self.WW_strip_exchanger = WwStripExchanger(gui)
		# tickers and signal connections
		self.session_ticker = Ticker(gui, self.sessionTick)
		self.FGCom_ticker = Ticker(gui, self.sendFGComControlDatagrams) if settings.FGCom_enabled else None
		self.FPL_ticker = Ticker(gui, self.FPL_checker.start)
		self.weather_ticker = Ticker(gui, self.weather_checker.lookupSelectedStations)
		self.FPL_checker.finished.connect(env.FPLs.refreshViews)
	
	def start(self):
		try:
			self.socket = socket(AF_INET, SOCK_DGRAM)
			self.socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
			self.socket.bind(('', settings.FGMS_client_port))
			self.server_address = settings.FGMS_server_host, settings.FGMS_server_port
		except OSError as error:
			self.socket = None
			print('Connection error: %s' % error, file=stderr)
		else:
			self.FGMS_sender = FgmsSender(self.socket, self.server_address, settings.my_callsign) # creating attribute
			self.UDP_listener = UdpSessionListener(self.gui, self.socket, self.receiveUdpPacket) # creating attribute
			self.session_ticker.start(FG_session_tick_interval)
			self.UDP_listener.start()
			if self.FGCom_ticker is not None:
				self.FGCom_ticker.startTicking(FGCom_tick_interval)
			if settings.FG_FPL_update_interval is not None:
				self.FPL_ticker.startTicking(settings.FG_FPL_update_interval)
			if settings.FG_METAR_update_interval is not None:
				self.weather_ticker.startTicking(settings.FG_METAR_update_interval)
			if self.IRC_communicator is not None:
				self.IRC_communicator.cmdMsgReceived.connect(self.receiveCommandMsg)
				self.IRC_communicator.start()
			if self.phone_manager is not None:
				self.phone_manager.setupComms(self.socket, self.IRC_communicator)
				self.phone_manager.start()
			if settings.FG_ORSX_enabled:
				self.WW_strip_exchanger.start()
			signals.sessionStarted.emit(SessionType.FLIGHTGEAR)
			print('Connected local port %d to %s.' % (settings.FGMS_client_port,
					INET_addr_str(settings.FGMS_server_host, settings.FGMS_server_port)))
	
	def stop(self):
		for link in env.cpdlc.dataLinks(CpdlcDialogueModel.isLive): # Never mind the pending or terminated ones
			try:
				self.sendCpdlcDisconnect(link.acftCallsign())
			except CpdlcOperationBlocked:
				pass # Never mind; we were just being courteous
		if self.isRunning():
			# stop tickers and threads in a clean way
			self.UDP_listener.stop() # looping thread
			self.session_ticker.stop()
			if self.FGCom_ticker is not None:
				self.FGCom_ticker.stop()
			self.FPL_ticker.stop() # ticker triggering a one shot thread
			self.weather_ticker.stop() # ticker triggering a one shot thread
			if self.IRC_communicator is not None:
				self.IRC_communicator.cmdMsgReceived.disconnect(self.receiveCommandMsg)
				self.IRC_communicator.stopAndWait()
			if self.phone_manager is not None:
				self.phone_manager.stopAndWait()
			self.WW_strip_exchanger.stopAndWait()
			for thread in self.UDP_listener, self.FPL_checker, self.weather_checker:
				thread.wait()
			del self.FGMS_sender
			del self.UDP_listener
			# finish up
			self.socket = None
			self.FGMS_connections.clear()
			signals.sessionEnded.emit(SessionType.FLIGHTGEAR)
	
	def isRunning(self):
		return self.socket is not None

	def clockTime(self):
		return realTime()

	def getAircraft(self):
		self.connection_list_mutex.lock()
		result = [acft for acft in self.FGMS_connections if not is_ATC_model(acft.aircraft_type)]
		self.connection_list_mutex.unlock()
		return result
	
	
	## ACFT/ATC INTERACTION
	
	def instructAircraftByCallsign(self, callsign, instr):
		signals.textInstructionSuggestion.emit(callsign, instr.readOutStr(env.radarContactByCallsign(callsign)))
	
	def postTextRadioMsg(self, msg):
		try:
			self.FGMS_sender.enqueueTextMsg(msg.txtMsg()) # may raise ValueError
		except ValueError as err:
			raise TextMsgBlocked(str(err))
	
	def postAtcChatMsg(self, msg):
		if self.IRC_communicator is None:
			raise TextMsgBlocked('ATC text messaging disabled. Reconnect with IRC sub-system to enable.')
		elif msg.txtOnly().startswith(ATC_pie_cmd_prefix):
			raise TextMsgBlocked('ATC-pie cannot send messages starting with "%s"' % ATC_pie_cmd_prefix)
		elif msg.isPrivate() and not self.IRC_communicator.isConnected(msg.recipient()):
			raise TextMsgBlocked('User unreachable.')
		try:
			self.IRC_communicator.sendChatMsg(msg) # can raise ValueError
		except ValueError as err:
			raise TextMsgBlocked(str(err))
	
	def sendStrip(self, strip, atc_callsign):
		if self.IRC_communicator is not None and self.IRC_communicator.isConnected(atc_callsign):
			self.IRC_communicator.sendCmdMsg(IRC_cmd_strip, strip.encodeDetails(handover_details), privateTo=atc_callsign)
		elif self.WW_strip_exchanger.isConnected(atc_callsign): # implies isRunning()
			acft = strip.linkedAircraft()
			if acft is None:
				raise HandoverBlocked('Only strips linked to a radar contact can be sent to OpenRadar.')
			self.WW_strip_exchanger.performHandover(acft.identifier, atc_callsign, strip)
		else:
			raise HandoverBlocked('No common sub-system available for strip exchange with this user.')
	
	def sendWhoHas(self, callsign):
		if self.IRC_communicator is not None:
			self.IRC_communicator.sendCmdMsg(IRC_cmd_whohas, callsign)
		ww_claim = self.WW_strip_exchanger.claimingContact(callsign)
		if ww_claim is not None:
			signals.incomingContactClaim.emit(ww_claim, callsign)
	
	def sendCpdlcMsg(self, callsign, msg):
		if self.IRC_communicator is None:
			raise CpdlcOperationBlocked('IRC sub-system must be enabled for CPDLC in FlightGear sessions.')
		self.IRC_communicator.sendCmdMsg(FG_IRC_cmd_CPDLC_message, msg.toEncodedStr(), privateTo=(FG_IRC_ACFT_callsign_prefix + callsign))
	
	def sendCpdlcTransferRequest(self, acft_callsign, atc_callsign, proposing):
		if self.IRC_communicator is None:
			raise CpdlcOperationBlocked('IRC sub-system must be enabled for CPDLC in FlightGear sessions.')
		cmd = IRC_cmd_cpdlc_xfr_init if proposing else IRC_cmd_cpdlc_xfr_cancel
		self.IRC_communicator.sendCmdMsg(cmd, acft_callsign, privateTo=atc_callsign)
	
	def sendCpdlcTransferResponse(self, acft_callsign, atc_callsign, accepting):
		if self.IRC_communicator is None:
			raise CpdlcOperationBlocked('IRC sub-system must be enabled for CPDLC in FlightGear sessions.')
		if accepting:
			self.IRC_communicator.sendCmdMsg(FG_IRC_cmd_CPDLC_connect, '',
					privateTo=(FG_IRC_ACFT_callsign_prefix + acft_callsign)) # tell ACFT we are new authority
			self.IRC_communicator.sendCmdMsg(IRC_cmd_cpdlc_xfr_accept, acft_callsign, privateTo=atc_callsign) # confirm transfer to ATC
		else:
			self.IRC_communicator.sendCmdMsg(IRC_cmd_cpdlc_xfr_reject, acft_callsign, privateTo=atc_callsign)
	
	def sendCpdlcDisconnect(self, callsign):
		if self.IRC_communicator is None:
			raise CpdlcOperationBlocked('IRC sub-system must be enabled for CPDLC in FlightGear sessions.')
		self.IRC_communicator.sendCmdMsg(FG_IRC_cmd_CPDLC_disconnect, '', privateTo=(FG_IRC_ACFT_callsign_prefix + callsign))
	
	
	## VOICE COMM'S
	
	def createRadio(self):
		if settings.FGCom_enabled:
			return FGComRadio()
		else:
			QMessageBox.information(self.gui, 'Create radio', 'FGCom-mumble sub-system must be enabled for integrated radios.')
			return None
	
	def recordAtis(self, parent_dialog):
		if settings.FGCom_enabled:
			record_FGCom_Mumble_ATIS(parent_dialog)
	
	def phoneLineManager(self):
		return self.phone_manager # can be None
	
	
	## ONLINE SYSTEMS
	
	def weatherLookUpRequest(self, station):
		self.weather_checker.lookupStation(station)
	
	def pushFplOnline(self, fpl):
		if settings.lenny64_account_email == '':
			raise OnlineFplActionBlocked('No Lenny64 account provided.')
		try:
			if fpl.isOnline():
				upload_FPL_updates(fpl)
			else:
				file_new_FPL(fpl)
			env.FPLs.refreshViews()
		except Lenny64Error as err:
			msg = 'A problem occured while uploading FPL data. Are you missing mandatory details?'
			if err.srvResponse() is not None:
				msg += '\nCheck console output for full server response.'
				print('Lenny64 server response: %s' % err.srvResponse(), file=stderr)
			raise OnlineFplActionBlocked(msg)
	
	def changeFplStatus(self, fpl, new_status):
		if settings.lenny64_account_email == '':
			raise OnlineFplActionBlocked('No Lenny64 account provided.')
		try:
			set_FPL_status(fpl, new_status)
			env.FPLs.refreshViews()
		except Lenny64Error as err:
			msg = 'Error in setting FPL online status (ID = %s): %s' % (fpl.online_id, err)
			if err.srvResponse() is not None:
				msg += '\nCheck console output for full server response.'
				print('Lenny64 server response: %s' % err.srvResponse(), file=stderr)
			raise OnlineFplActionBlocked(msg)
	
	def syncOnlineFPLs(self):
		self.FPL_checker.start()
	
	
	## MANAGER-SPECIFIC
	
	def sessionTick(self):
		self.FGMS_sender.sendPositionPacket()
		self.connection_list_mutex.lock()
		for acft in pop_all(self.FGMS_connections, FgmsAircraft.isZombie):
			acft.resetPtt()
		# update ATC model before unlocking mutex
		old_register = env.ATCs.knownAtcCallsigns()
		updated = []
		for atc in self.WW_strip_exchanger.connectedATCs():
			env.ATCs.updateATC(atc.callsign, atc.position, atc.social_name, atc.frequency)
			updated.append(atc.callsign)
		for c in self.FGMS_connections:
			if is_ATC_model(c.aircraft_type) and c.identifier not in updated:
				env.ATCs.updateATC(c.identifier, c.liveCoords(), c.ATCpie_social_name, c.ATCpie_publicised_frequency)
				updated.append(c.identifier)
		for had_callsign in old_register:
			if had_callsign not in updated:
				if self.phoneLineManager() is not None:
					self.phoneLineManager().removePhoneBookEntry(had_callsign)
				env.ATCs.removeATC(had_callsign)
		self.connection_list_mutex.unlock()
	
	def sendFGComControlDatagrams(self):
		send_FGCom_mumble_control_packet(self.socket, settings.FGCom_mumble_host, settings.FGCom_mumble_port, settings.FGCom_mumble_sound_effects)
	
	def receiveUdpPacket(self, datagram):
		if datagram[:4] == b'FGFS': # FGMS datagram
			self.connection_list_mutex.lock()
			update_FgmsAircraft_list(self.FGMS_connections, datagram)
			self.connection_list_mutex.unlock()
			send_packet_to_views(datagram)
		elif datagram[:5] == b'FGCOM': # FGCom-mumble datagram
			receive_FGCom_mumble_packet(datagram)
		elif datagram[:6] == b'ATCPIE': # VoIP phone audio
			if self.phone_manager is not None:
				self.phone_manager.receivePhoneData(datagram[6:])
		else:
			print('Unrecognised or unexpected packet type received on port %d.' % settings.FGMS_client_port, file=stderr)
	
	def receiveCommandMsg(self, sender, cmd, argstr): # NOTE: self.IRC_communicator should not be None at this point
		if sender.startswith(FG_IRC_ACFT_callsign_prefix):
			sender = sender[len(FG_IRC_ACFT_callsign_prefix):]
		else:
			print('Processing a FlightGear IRC command from an unprefixed callsign sender "%s"' % sender, file=stderr)
		
		# Log-on from ACFT
		if cmd == FG_IRC_cmd_CPDLC_connect:
			if settings.controller_pilot_data_link: # accept log-on
				env.cpdlc.beginDataLink(sender)
				answer = FG_IRC_cmd_CPDLC_connect
			else: # inform aircraft that log-on is not accepted
				answer = FG_IRC_cmd_CPDLC_disconnect
			self.IRC_communicator.sendCmdMsg(answer, '', privateTo=(FG_IRC_ACFT_callsign_prefix + sender))
		
		# Incoming CPDLC message
		elif cmd == FG_IRC_cmd_CPDLC_message:
			link = env.cpdlc.liveDataLink(sender)
			if link is None:
				print('Ignored CPDLC message sent from %s while not connected.' % sender, file=stderr)
			else:
				link.appendMessage(CpdlcMessage.fromEncodedStr(argstr))
		
		# Disconnection by ACFT (should also be received when ACFT has established with new authority after XFR)
		elif cmd == FG_IRC_cmd_CPDLC_disconnect:
			link = env.cpdlc.liveDataLink(sender)
			if link is not None:
				link.terminate(False)
	