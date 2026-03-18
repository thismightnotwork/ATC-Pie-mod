
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

from base.utc import realTime


# ---------- Constants ----------

teacher_callsign = 'Teacher'
student_callsign = 'Student'
missing_client_type_str = '!!type'

# -------------------------------


class SessionType:
	enum = SOLO, FLIGHTGEAR, FSD, TEACHER, STUDENT, PLAYBACK = range(6)



class TextMsgBlocked(Exception):
	def __init__(self, msg):
		Exception.__init__(self, msg)


class HandoverBlocked(Exception):
	def __init__(self, msg):
		Exception.__init__(self, msg)


class CpdlcOperationBlocked(Exception):
	def __init__(self, msg):
		Exception.__init__(self, msg)


class OnlineFplActionBlocked(Exception):
	def __init__(self, msg):
		Exception.__init__(self, msg)



class SessionManager:
	"""
	Subclasses should redefine the following silent methods:
		- start
		- stop
		- pause
		- resume
		- isRunning
		- clockTime
		- getAircraft
		- postTextRadioMsg          (raises TextMsgBlocked)
		- postAtcChatMsg            (raises TextMsgBlocked)
		- instructAircraftByCallsign
		- sendStrip                 (raises HandoverBlocked)
		- sendCpdlcMsg              (raises CpdlcOperationBlocked)
		- sendCpdlcTransferRequest  (raises CpdlcOperationBlocked)
		- sendCpdlcTransferResponse (raises CpdlcOperationBlocked)
		- sendCpdlcDisconnect           (raises CpdlcOperationBlocked)
		- sendWhoHas
		- createRadio
		- recordAtis
		- phoneLineManager
		- weatherLookUpRequest (should "register_weather_information" if any is retrieved)
		- pushFplOnline             (raises OnlineFplActionBlocked)
		- changeFplStatus           (raises OnlineFplActionBlocked)
		- syncOnlineFPLs            (raises OnlineFplActionBlocked)
	"""
	def __init__(self, gui, session_type):
		self.gui = gui
		self.session_type = session_type
	
	## Methods to override below ##
	
	def start(self):
		pass
	
	def stop(self):
		pass
	
	def pause(self):
		pass
	
	def resume(self):
		pass

	def isRunning(self):
		return False

	def clockTime(self):
		return realTime()
	
	def getAircraft(self):
		return []
	
	# ACFT/ATC interaction
	def instructAircraftByCallsign(self, callsign, instr):
		pass
	
	def postTextRadioMsg(self, msg):
		pass
	
	def postAtcChatMsg(self, msg):
		pass
	
	def sendStrip(self, strip, atc):
		pass
	
	def sendWhoHas(self, callsign):
		pass
	
	def sendCpdlcMsg(self, callsign, msg):
		pass
	
	def sendCpdlcTransferRequest(self, acft_callsign, atc_callsign, proposing):
		pass
	
	def sendCpdlcTransferResponse(self, acft_callsign, atc_callsign, accept):
		pass
	
	def sendCpdlcDisconnect(self, acft_callsign):
		pass
	
	# Voice communications
	def createRadio(self):
		return None

	def recordAtis(self, parent_dialog):
		pass
	
	def phoneLineManager(self):
		return None
	
	# Online systems
	def weatherLookUpRequest(self, station):
		pass
	
	def pushFplOnline(self, fpl):
		pass
	
	def changeFplStatus(self, fpl, new_status):
		pass
	
	def syncOnlineFPLs(self):
		pass
