
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
try:
	from irc.bot import SingleServerIRCBot
	IRC_available = True
except ImportError:
	IRC_available = False

from PyQt5.QtCore import QThread, pyqtSignal

from base.text import TextMessage
from base.strip import Strip, received_from_detail
from base.util import some, INET_addr_str, INET_addr_from_str

from gui.misc import signals

from session.config import settings
from session.env import env


# ---------- Constants ----------

FG_server_host = 'mpirc.flightgear.org'
FG_server_port = 6667
disconnect_part_message = 'Disconnecting.'

ATC_pie_cmd_prefix = '___ATC-pie___'
IRC_cmd_strip = 'STRIP'
IRC_cmd_whohas = 'WHO_HAS'
IRC_cmd_ihave = 'I_HAVE'
IRC_cmd_phone_number = 'PHONE_NUMBER'
IRC_cmd_phone_line_open = 'PHONE_OPEN'
IRC_cmd_phone_line_close = 'PHONE_CLOSE'
IRC_cmd_cpdlc_xfr_init = 'CPDLC_XFR_INIT' # str callsign arg (proposed transfer)
IRC_cmd_cpdlc_xfr_cancel = 'CPDLC_XFR_CANCEL' # str callsign arg (cancelled transfer proposal)
IRC_cmd_cpdlc_xfr_accept = 'CPDLC_XFR_ACCEPT' # str callsign arg (accepted transfer)
IRC_cmd_cpdlc_xfr_reject = 'CPDLC_XFR_REJECT' # str callsign arg (rejected transfer)

# -------------------------------


if IRC_available:
	class FgIrcBot(SingleServerIRCBot):
		def __init__(self, srv_host, srv_port, msg_received_callback, channel_joined_callback):
			# IRC_nickname is callsign checked against whitespace at session start.
			# MP_social_name is used here as IRC "real name".
			# Callback function should take arguments: str sender, str text line, bool is private
			SingleServerIRCBot.__init__(self, [(srv_host, srv_port)], settings.my_callsign, settings.MP_social_name)
			self.conn = None
			self.expect_disconnect = False
			self.msg_callback = msg_received_callback
			self.channel_joined_callback = channel_joined_callback
		
		def doDisconnect(self):
			if self.conn is not None:
				self.expect_disconnect = True
				self.conn.part(settings.FG_IRC_channel, message=disconnect_part_message)
				#self.conn.disconnect(message='Disconnecting.') # commented out: freezes for too long + doc says "will try to reconnect"
		
		## REACT TO IRC EVENTS
		def on_welcome(self, server, event):
			self.expect_disconnect = False
			print('IRC: connected to server; joining ATC channel...')
			server.join(settings.FG_IRC_channel)
		
		def on_disconnect(self, server, event):
			if not self.expect_disconnect:
				print('WARNING: IRC disconnected; retrying soon...', file=stderr)
		
		def on_nicknameinuse(self, server, event):
			print('WARNING: IRC nickname reported in use.', file=stderr)
			server.disconnect(message='Reconnecting later because of used nickname.')
		
		def on_join(self, server, event):
			if event.source.nick == settings.my_callsign and event.target.lower() == settings.FG_IRC_channel.lower():
				print('IRC: ATC channel joined.')
				self.conn = server
				self.channel_joined_callback()
		
		def on_pubmsg(self, server, event):
			#DEBUGprint('IRC: Channel msg received from %s' % event.source.nick, event.arguments[0])
			self.msg_callback(event.source.nick, event.arguments[0], False)
		
		def on_privmsg(self, server, event):
			#DEBUGprint('IRC: Private msg received from %s' % event.source.nick, event.arguments[0])
			self.msg_callback(event.source.nick, event.arguments[0], True)
		
		## SEND/RECEIVE MESSAGES
		def send_privmsg(self, target, text):
			if self.conn is None:
				raise ValueError('IRC connection lost or not yet available.')
			else:
				self.conn.privmsg(target, text) # should not be called if target unavailable





class FgIrcCommunicator(QThread):
	cmdMsgReceived = pyqtSignal(str, str, str) # sender, cmd, argstr
	
	def __init__(self, parent, command_prefixes):
		QThread.__init__(self, parent)
		self.bot = FgIrcBot(FG_server_host, FG_server_port, self.processMsg, self.onJoin)
		self.session_mgr_cmd_prefixes = command_prefixes
		
	def run(self):
		#DEBUG print('Connecting to IRC server.')
		self.bot.start()
	
	def stopAndWait(self):
		self.bot.doDisconnect()
		self.msleep(100)
		self.terminate()
		self.wait()
	
	def isConnected(self, atc_callsign):
		try:
			return self.bot.channels[settings.FG_IRC_channel].has_user(atc_callsign)
		except KeyError:
			return False
	
	def sendChatMsg(self, msg):
		if any(msg.txtOnly().startswith(cmd) for cmd in self.session_mgr_cmd_prefixes):
			raise ValueError('This message cannot be sent in this session type.')
		if msg.isPrivate():
			self.bot.send_privmsg(msg.recipient(), msg.txtOnly()) # may raise ValueError
		else:
			self.bot.send_privmsg(settings.FG_IRC_channel, msg.txtMsg()) # may raise ValueError
	
	def sendCmdMsg(self, cmd, argstr, privateTo=None):
		if cmd in self.session_mgr_cmd_prefixes:
			text_to_send = '%s %s' % (cmd, argstr)
		else: # add ATC-pie command escape prefix
			text_to_send = '%s %s %s' % (ATC_pie_cmd_prefix, cmd, argstr)
		try:
			self.bot.send_privmsg(some(privateTo, settings.FG_IRC_channel), text_to_send)
		except ValueError as err:
			print('IRC communication error: %s' % err, file=stderr)

	def onJoin(self):
		if settings.session_manager.phoneLineManager() is not None: # publicise my number (each with one will answer with theirs privately)
			self.sendCmdMsg(IRC_cmd_phone_number, INET_addr_str(settings.reachable_phone_IP, settings.FGMS_client_port)) # public msg

	def processMsg(self, sender, txt, is_private):
		txt_split = txt.split(' ', maxsplit=1)
		if len(txt_split) == 1:
			txt_split.append('')
		# txt_split now has length 2
		if txt_split[0].startswith(ATC_pie_cmd_prefix): # a number used to be stuck after the prefix
			cmd_split = txt_split[1].split(' ', maxsplit=1)
			cmd = cmd_split[0]
			argstr = '' if len(cmd_split) == 1 else cmd_split[1]
			
			# Receive a strip
			if cmd == IRC_cmd_strip:
				strip = Strip.fromEncodedDetails(argstr) # may raise ValueError
				strip.writeDetail(received_from_detail, sender)
				signals.receiveStrip.emit(strip)
			
			# Who-has question
			elif cmd == IRC_cmd_whohas:
				if env.shouldAnswerWhoHas(argstr):
					self.sendCmdMsg(IRC_cmd_ihave, argstr, privateTo=sender)
			
			# Traffic claim
			elif cmd == IRC_cmd_ihave:
				signals.incomingContactClaim.emit(sender, argstr)

			# Phone number
			elif cmd == IRC_cmd_phone_number:
				if settings.session_manager.phoneLineManager() is not None:
					try:
						settings.session_manager.phoneLineManager().updatePhoneBook(sender, INET_addr_from_str(argstr))
						if not is_private: # answer with mine privately
							self.sendCmdMsg(IRC_cmd_phone_number, INET_addr_str(settings.reachable_phone_IP, settings.FGMS_client_port), privateTo=sender)
					except ValueError:
						pass # ignore invalid phone number string

			# Phone line request
			elif cmd == IRC_cmd_phone_line_open:
				if settings.session_manager.phoneLineManager() is not None:
					settings.session_manager.phoneLineManager().incomingLineRequest(sender)

			# Phone line drop
			elif cmd == IRC_cmd_phone_line_close:
				if settings.session_manager.phoneLineManager() is not None:
					settings.session_manager.phoneLineManager().incomingLineDrop(sender)
			
			# Data link transfer proposal
			elif cmd == IRC_cmd_cpdlc_xfr_init:
				signals.cpdlcTransferRequest.emit(argstr, sender, True)
			
			# Data link transfer cancellation
			elif cmd == IRC_cmd_cpdlc_xfr_cancel:
				signals.cpdlcTransferRequest.emit(argstr, sender, False)
			
			# Transfer accepted by ATC
			elif cmd == IRC_cmd_cpdlc_xfr_accept:
				signals.cpdlcTransferResponse.emit(argstr, sender, True)
			
			# Data link disconnection or rejection
			elif cmd == IRC_cmd_cpdlc_xfr_reject:
				signals.cpdlcTransferResponse.emit(argstr, sender, False)
		
		else: # Not an ATC-pie command
			try: # Check for a session-manager-specific command
				self.cmdMsgReceived.emit(sender, next(cmd for cmd in self.session_mgr_cmd_prefixes if txt_split[0] == cmd), txt_split[1])
			except StopIteration: # Regular text message (no command prefix triggered)
				if is_private:
					msg = TextMessage(sender, txt, recipient=settings.my_callsign, private=True)
				else:
					msg = TextMessage(sender, txt, private=False)
				signals.incomingAtcTextMsg.emit(msg)
