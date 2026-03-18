
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

from datetime import datetime

from PyQt5.QtCore import Qt, QObject, QEvent, pyqtSignal, QStringListModel

from base.acft import Aircraft
from base.coords import EarthCoords
from base.cpdlc import CpdlcMessage
from base.fpl import FPL
from base.nav import Navpoint
from base.params import Heading
from base.strip import Strip
from base.text import TextMessage
from base.weather import Weather

from session.config import settings
from session.env import env


# ---------- Constants ----------

PTT_key = Qt.Key_Control

recognisedValue_lineEdit_styleSheet = 'QLineEdit { color: black; background-color: rgb(200, 255, 200) }' # pale green
unrecognisedValue_lineEdit_styleSheet = 'QLineEdit { color: black; background-color: rgb(255, 200, 200) }' # pale red

# -------------------------------



class SimpleStringListModel(QStringListModel):
	"""
	CAUTION: set views' "dragDropMode" to "InternalMove" if allowing reordering here
	"""
	
	def __init__(self, parent, allow_reordering):
		QStringListModel.__init__(self, parent)
		self.allow_reordering = allow_reordering
	
	def flags(self, index):
		if self.allow_reordering:  # suppress drop replacement
			flags = QStringListModel.flags(self, index)
			if index.isValid():
				flags &= ~Qt.ItemIsDropEnabled
			return flags
		else:  # display only
			return Qt.ItemIsEnabled
	
	def appendString(self, s):
		self.setStringList(self.stringList() + [s])
	
	def clearList(self):
		self.setStringList([])





class RadioKeyEventFilter(QObject):
	"""
	install on major QDialogs and widgets that can be flagged with Qt.Window without a parent,
	not to block PTT while the window has focus
	"""
	def eventFilter(self, receiver, event):
		t = event.type()
		if t == QEvent.KeyPress or t == QEvent.KeyRelease:
			#DEBUG('EVENT key=%s, nvk=%s, nsc=%s' % (event.key(), event.nativeVirtualKey(), event.nativeScanCode()))
			if event.key() == PTT_key:
				signals.kbdPTT.emit(t == QEvent.KeyPress)
				return True
			else:
				return False
		else:
			return QObject.eventFilter(self, receiver, event)




class IconFile:
	action_generalSettings = 'resources/pixmap/tools.png'
	action_sessionSettings = 'resources/pixmap/tools-play.png'
	action_locationSettings = 'resources/pixmap/tools-loc.png'
	action_adSfcUse = 'resources/pixmap/adSfcUse.png'
	action_newStrip = 'resources/pixmap/newStrip.png'
	action_newLinkedStrip = 'resources/pixmap/newLinkedStrip.png'
	action_newFPL = 'resources/pixmap/newFPL.png'
	action_newLinkedFPL = 'resources/pixmap/newLinkedFPL.png'
	action_newRack = 'resources/pixmap/newRack.png'
	action_newRackPanel = 'resources/pixmap/newRackPanel.png'
	action_newRadarScreen = 'resources/pixmap/newRadarScreen.png'
	action_newLooseStripBay = 'resources/pixmap/newLooseStripBay.png'
	
	option_primaryRadar = 'resources/pixmap/primary-radar.png'
	option_approachSpacingHints = 'resources/pixmap/spacing-hints.png'
	option_runwayOccupationMonitor = 'resources/pixmap/runway-incursion.png'
	option_routeConflictWarnings = 'resources/pixmap/routeConflict.png'
	option_identificationAssistant = 'resources/pixmap/radar-identification.png'
	option_recordSession = 'resources/pixmap/rec-play.png'

	panel_locInfo = 'resources/pixmap/info.png'
	panel_atis = 'resources/pixmap/atis.png'
	panel_unitConv = 'resources/pixmap/calculator.png'
	panel_airportList = 'resources/pixmap/AD.png'
	panel_teaching = 'resources/pixmap/teaching.png'
	panel_ATCs = 'resources/pixmap/handshake.png'
	panel_CPDLC = 'resources/pixmap/cpdlc.png'
	panel_atcChat = 'resources/pixmap/ATC-chat.png'
	panel_FPLs = 'resources/pixmap/FPL.png'
	panel_instructions = 'resources/pixmap/instruction.png'
	panel_looseBay = 'resources/pixmap/looseStrips.png'
	panel_navigator = 'resources/pixmap/compass.png'
	panel_notepads = 'resources/pixmap/notepad.png'
	panel_notifications = 'resources/pixmap/light-bulb.png'
	panel_playbackCtrl = 'resources/pixmap/play-pause-timeline.png'
	panel_radarScreen = 'resources/pixmap/radar.png'
	panel_radios = 'resources/pixmap/radio.png'
	panel_runwayBox = 'resources/pixmap/strip-on-rwy.png'
	panel_selInfo = 'resources/pixmap/plane-radar.png'
	panel_racks = 'resources/pixmap/rack.png'
	panel_txtRadio = 'resources/pixmap/text-radio.png'
	panel_twrView = 'resources/pixmap/control-TWR.png'
	panel_weather = 'resources/pixmap/weather.png'

	button_view = 'resources/pixmap/eye.png'
	button_clear = 'resources/pixmap/sweep.png'
	button_search = 'resources/pixmap/magnifying-glass.png'
	button_save = 'resources/pixmap/floppy-save.png'
	button_recall = 'resources/pixmap/floppy-recall.png'
	button_suggest = 'resources/pixmap/light-bulb.png'
	button_bin = 'resources/pixmap/bin.png'
	button_shelf = 'resources/pixmap/shelf.png'

	pixmap_alarmClock = 'resources/pixmap/stopwatch.png'
	pixmap_lock = 'resources/pixmap/lock.png'
	pixmap_strip = 'resources/pixmap/strip.png'
	pixmap_recycle = 'resources/pixmap/recycle.png'
	pixmap_printer = 'resources/pixmap/printer.png'
	pixmap_telephone_idle = 'resources/pixmap/telephone-idle.png'
	pixmap_telephone_placedCall = 'resources/pixmap/telephone-outgoing.png'
	pixmap_telephone_incomingCall = 'resources/pixmap/telephone-incoming.png'
	pixmap_telephone_inCall = 'resources/pixmap/telephone-active.png'








class SignalCentre(QObject):
	selectionChanged = pyqtSignal()
	stripInfoChanged = pyqtSignal()
	statusBarMsg = pyqtSignal(str) # message to display
	sessionStarted = pyqtSignal(int) # session type
	sessionEnded = pyqtSignal(int) # session type
	sessionPaused = pyqtSignal()
	sessionResumed = pyqtSignal()
	sessionRecorderStarted = pyqtSignal()
	sessionRecorderStopped = pyqtSignal()
	playbackClockChanged = pyqtSignal(datetime)
	fastClockTick = pyqtSignal()
	slowClockTick = pyqtSignal()
	alarmClockTimedOut = pyqtSignal(str) # timeout message (empty string if none set)
	towerViewToggled = pyqtSignal(bool) # True=started; False=finished
	soloRuntimeSettingsChanged = pyqtSignal()
	generalSettingsChanged = pyqtSignal()
	locationSettingsChanged = pyqtSignal()
	closeNonDockableWindows = pyqtSignal()
	adSfcUseChanged = pyqtSignal()
	stripDeleted = pyqtSignal(Strip)
	rackEdited = pyqtSignal(str, str) # old name, new name
	hdgDistMeasured = pyqtSignal(Heading, float) # heading, distance measured with RMB tool
	measuringLogEntry = pyqtSignal(str)
	rackVisibilityTaken = pyqtSignal(list) # racks made visible in the signalling rack panel
	rackVisibilityLost = pyqtSignal(list) # racks in closed view
	backgroundImagesReloaded = pyqtSignal()
	colourConfigReloaded = pyqtSignal()
	mainStylesheetApplied = pyqtSignal()
	mainWindowClosing = pyqtSignal()
	kbdPTT = pyqtSignal(bool) # mic PTT
	appendCpdlcMsgElement = pyqtSignal(str, str) # callsign, message element
	
	indicatePoint = pyqtSignal(EarthCoords)
	toggleMachNumbers = pyqtSignal()
	navpointClick = pyqtSignal(Navpoint)
	pkPosClick = pyqtSignal(str)
	specialTool = pyqtSignal(EarthCoords, Heading)
	voiceMsgRecognised = pyqtSignal(list, list) # callsign tokens used, recognised instructions
	voiceMsgNotRecognised = pyqtSignal()
	wilco = pyqtSignal()
	
	newATC = pyqtSignal(str) # callsign
	newFPL = pyqtSignal(FPL)
	stripAutoPrinted = pyqtSignal(Strip, str) # str is DEP/ARR + time reason for auto-print
	linkedContactLost = pyqtSignal(Strip, EarthCoords)
	emergencySquawk = pyqtSignal(Aircraft)
	aircraftIdentification = pyqtSignal(Strip, Aircraft, bool) # bool True if mode S identification
	runwayIncursion = pyqtSignal(int, Aircraft)
	pathConflict = pyqtSignal()
	nearMiss = pyqtSignal()
	newWeather = pyqtSignal(str, Weather) # str = the station with new weather
	voiceMsg = pyqtSignal(Aircraft, str)
	textInstructionSuggestion = pyqtSignal(str, str) # dest callsign, instr message
	incomingTextRadioMsg = pyqtSignal(TextMessage)
	incomingAtcTextMsg = pyqtSignal(TextMessage)
	incomingContactClaim = pyqtSignal(str, str) # sender, ACFT callsign
	cpdlcInitLink = pyqtSignal(str) # ACFT callsign
	cpdlcStatusChanged = pyqtSignal(str) # data link callsign
	cpdlcMessageReceived = pyqtSignal(str, CpdlcMessage) # ACFT callsign, message
	cpdlcTransferRequest = pyqtSignal(str, str, bool) # ACFT callsign, ATC callsign, proposed else cancelled
	cpdlcTransferResponse = pyqtSignal(str, str, bool) # ACFT callsign, ATC callsign, accepted else rejected
	cpdlcProblem = pyqtSignal(str, str) # ACFT callsign, problem description
	cpdlcDialogueRequest = pyqtSignal(str, bool) # ACFT callsign, must be live or pending (otherwise take any latest, incl. terminated)
	phoneManagerAvailabilityChange = pyqtSignal()
	phoneLineStatusChanged = pyqtSignal(str) # ATC callsign
	incomingPhoneCall = pyqtSignal(str) # ATC callsign
	phoneCallAnswered = pyqtSignal(str) # ATC callsign
	phoneCallDropped = pyqtSignal(str) # ATC callsign
	
	privateAtcChatRequest = pyqtSignal(str)
	weatherDockRaiseRequest = pyqtSignal()
	openShelfRequest = pyqtSignal()
	stripRecall = pyqtSignal(Strip)
	stripEditRequest = pyqtSignal(Strip)
	fplEditRequest = pyqtSignal(FPL)
	atisDialogRequest = pyqtSignal()
	depClearanceDispRequest = pyqtSignal(Strip)
	receiveStrip = pyqtSignal(Strip)
	handoverFailure = pyqtSignal(Strip, str)
	
	def __init__(self):
		QObject.__init__(self)


signals = SignalCentre()






class Selection:
	def __init__(self):
		self.acft = None
		self.strip = None
		self.fpl = None
	
	def deselect(self):
		self.acft = self.strip = self.fpl = None
		signals.selectionChanged.emit()
		
	def selectStrip(self, select):
		self.strip = select
		self.fpl = self.strip.linkedFPL()
		self.acft = self.strip.linkedAircraft()
		signals.selectionChanged.emit()
		
	def selectAircraft(self, select):
		self.acft = select
		self.strip = env.linkedStrip(self.acft)
		if self.strip is None:
			self.fpl = None
		else:
			self.fpl = self.strip.linkedFPL()
		signals.selectionChanged.emit()
		
	def selectFPL(self, select):
		self.fpl = select
		self.strip = env.linkedStrip(self.fpl)
		if self.strip is None:
			self.acft = None
		else:
			self.acft = self.strip.linkedAircraft()
		signals.selectionChanged.emit()
	
	def selectedCallsign(self):
		if self.strip is None: # selection is *either* ACFT, FPL or neither
			if self.acft is None:
				return None if self.fpl is None else self.fpl[FPL.CALLSIGN]
			else: # selection is ACFT or nothing
				return self.acft.xpdrCallsign()
		else: # strip display callsign is the one selected
			return self.strip.callsign()
	
	def linkAircraft(self, acft):
		if self.strip is not None and self.strip.linkedAircraft() is None and env.linkedStrip(acft) is None:
			self.strip.linkAircraft(acft)
			if settings.strip_autofill_on_ACFT_link:
				self.strip.fillFromXPDR()
			signals.stripInfoChanged.emit()
			self.selectAircraft(acft)

	def unlinkAircraft(self, acft):
		if self.strip is not None and self.strip.linkedAircraft() is acft:
			self.strip.linkAircraft(None)
			signals.stripInfoChanged.emit()
			self.selectStrip(self.strip)
	
	def __str__(self):
		return '{strip:%s, fpl:%s, acft:%s}' % (self.strip, self.fpl, self.acft)



selection = Selection()
