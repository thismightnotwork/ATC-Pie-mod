
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

from os import path

from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QUrl
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import QWidget, QMessageBox
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from ui.notifierPanel import Ui_notifierPanel

from base.fpl import FPL
from base.strip import received_from_detail, assigned_SQ_detail
from base.utc import rel_session_datetime_str

from gui.misc import signals, IconFile

from session.config import settings
from session.env import env
from session.manager import SessionType


# ---------- Constants ----------

sounds_directory = 'resources/sounds'
icons_directory = 'resources/pixmap'

# -------------------------------


class Notification:
	types = GUI_INFO, ALARM_CLOCK, WEATHER_UPDATE, FPL_FILED, STRIP_AUTO_PRINTED, \
			ATC_CONNECTED, ATC_CHAT_MSG, ATC_PHONE_CALL, ATC_PHONE_CALL_ANSWERED, ATC_PHONE_CALL_DROPPED, \
			STRIP_RECEIVED, TXT_RADIO_MSG, CPDLC_TRANSMISSION, CPDLC_PROBLEM, \
			RADAR_IDENTIFICATION, EMG_SQUAWK, LOST_LINKED_CONTACT, \
			CONFLICT_WARNING, SEPARATION_INCIDENT, RWY_INCURSION, UNRECOGNISED_VOICE_INSTR = range(21)
	
	def __init__(self, notification_type, time, msg, action):
		self.t = notification_type
		self.time = time
		self.msg = msg
		self.double_click_function = action

	@staticmethod
	def tstr(t):
		return {
			Notification.GUI_INFO: 'GUI message',
			Notification.ALARM_CLOCK: 'Alarm clock timed out',
			Notification.WEATHER_UPDATE: 'Primary weather update',
			Notification.FPL_FILED: 'FPL filed for location',
			Notification.STRIP_AUTO_PRINTED: 'Strip auto-printed',
			Notification.ATC_CONNECTED: 'New ATC service in range',
			Notification.ATC_CHAT_MSG: 'Incoming ATC text message',
			Notification.ATC_PHONE_CALL: 'Incoming ATC phone call',
			Notification.ATC_PHONE_CALL_ANSWERED: 'Phone call answered',
			Notification.ATC_PHONE_CALL_DROPPED: 'Phone line dropped',
			Notification.STRIP_RECEIVED: 'Strip received',
			Notification.TXT_RADIO_MSG: 'Text radio message',
			Notification.CPDLC_TRANSMISSION: 'CPDLC connection or request',
			Notification.CPDLC_PROBLEM: 'CPDLC dialogue problem',
			Notification.RADAR_IDENTIFICATION: 'Radar identification',
			Notification.EMG_SQUAWK: 'Emergency squawk',
			Notification.LOST_LINKED_CONTACT: 'Linked radar contact lost',
			Notification.CONFLICT_WARNING: 'Route conflict',
			Notification.SEPARATION_INCIDENT: 'Separation incident',
			Notification.RWY_INCURSION: 'Runway incursion',
			Notification.UNRECOGNISED_VOICE_INSTR: 'Unrecognised voice instruction'
		}[t]


icon_files = { # If given, the messages will be logged in the notification table.
	Notification.GUI_INFO: 'info.png',
	Notification.ALARM_CLOCK: 'stopwatch.png',
	Notification.WEATHER_UPDATE: 'weather.png',
	Notification.FPL_FILED: 'FPLicon.png',
	Notification.STRIP_AUTO_PRINTED: 'printer.png',
	Notification.ATC_CONNECTED: 'control-TWR.png',
	Notification.ATC_PHONE_CALL: 'telephone-incoming.png',
	Notification.STRIP_RECEIVED: 'handshake.png',
	Notification.CPDLC_TRANSMISSION: 'cpdlc.png',
	Notification.CPDLC_PROBLEM: 'cpdlc.png',
	Notification.RADAR_IDENTIFICATION: 'radar.png',
	Notification.EMG_SQUAWK: 'planeEMG.png',
	Notification.LOST_LINKED_CONTACT: 'contactLost.png',
	Notification.CONFLICT_WARNING: 'routeConflict.png',
	Notification.SEPARATION_INCIDENT: 'nearMiss.png',
	Notification.RWY_INCURSION: 'runway-incursion.png'
} # No log for: ATC_CHAT_MSG, ATC_PHONE_CALL_ANSWERED, ATC_PHONE_CALL_DROPPED, TXT_RADIO_MSG, UNRECOGNISED_VOICE_INSTR


sound_files = { # If given, a sound can be toggled for this type of notification.
	Notification.ALARM_CLOCK: 'timeout.mp3',
	Notification.WEATHER_UPDATE: 'chime.mp3',
	Notification.STRIP_AUTO_PRINTED: 'printer.mp3',
	Notification.ATC_CONNECTED: 'aeroplaneDing.mp3',
	Notification.ATC_CHAT_MSG: 'hiClick.mp3',
	Notification.ATC_PHONE_CALL: 'phoneRing.mp3',
	Notification.ATC_PHONE_CALL_ANSWERED: 'notesUp.mp3',
	Notification.ATC_PHONE_CALL_DROPPED: 'notesDown.mp3',
	Notification.STRIP_RECEIVED: 'loClick.mp3',
	Notification.TXT_RADIO_MSG: 'typeWriter.mp3',
	Notification.CPDLC_TRANSMISSION: 'phoneDial.mp3',
	Notification.CPDLC_PROBLEM: 'phoneTone.mp3',
	Notification.RADAR_IDENTIFICATION: 'detectorBeep.mp3',
	Notification.EMG_SQUAWK: 'sq-buzz.mp3',
	Notification.LOST_LINKED_CONTACT: 'turnedOff.mp3',
	Notification.CONFLICT_WARNING: 'alarmHalf.mp3',
	Notification.SEPARATION_INCIDENT: 'alarm.mp3',
	Notification.RWY_INCURSION: 'alarm.mp3',
	Notification.UNRECOGNISED_VOICE_INSTR: 'loBuzz.mp3'
} # No sound notification for: GUI_INFO, FPL_FILED


def mkSound(file_base_name):
	return QMediaContent(QUrl.fromLocalFile(path.abspath(path.join(sounds_directory, file_base_name))))

wilco_beep = mkSound('hiBuzz.mp3')

notification_sound_base = {t: mkSound(f) for t, f in sound_files.items()}




default_sound_notifications = {
	Notification.ALARM_CLOCK, Notification.WEATHER_UPDATE, Notification.STRIP_AUTO_PRINTED,
	Notification.ATC_CHAT_MSG, Notification.ATC_PHONE_CALL, Notification.STRIP_RECEIVED,
	Notification.CPDLC_TRANSMISSION, Notification.CPDLC_PROBLEM, Notification.EMG_SQUAWK,
	Notification.LOST_LINKED_CONTACT, Notification.CONFLICT_WARNING, Notification.SEPARATION_INCIDENT,
	Notification.RWY_INCURSION,	Notification.UNRECOGNISED_VOICE_INSTR
}




class NotificationHistoryModel(QAbstractTableModel):
	columns = ['Time', 'Message']

	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.history = []

	def rowCount(self, parent=None):
		return len(self.history)

	def columnCount(self, parent):
		return len(NotificationHistoryModel.columns)

	def data(self, index, role):
		col = index.column()
		notification = self.history[index.row()]
		if role == Qt.DisplayRole:
			if col == 0:
				return rel_session_datetime_str(notification.time, seconds=True)
			if col == 1:
				return notification.msg
		elif role == Qt.DecorationRole:
			if col == 0:
				try:
					pixmap = QPixmap(path.join(icons_directory, icon_files[notification.t]))
					return QIcon(pixmap)
				except KeyError:
					pass # No decoration for this notification type

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return NotificationHistoryModel.columns[section]
	
	def addNotification(self, t, msg, dbl_click_function):
		position = self.rowCount()
		self.beginInsertRows(QModelIndex(), position, position)
		self.history.insert(position, Notification(t, settings.session_manager.clockTime(), msg, dbl_click_function))
		self.endInsertRows()
		return True

	def clearNotifications(self):
		self.beginRemoveRows(QModelIndex(), 0, self.rowCount() - 1)
		self.history.clear()
		self.endRemoveRows()
		return True




class NotifierFrame(QWidget, Ui_notifierPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.cleanUp_button.setIcon(QIcon(IconFile.button_clear))
		self.table_model = NotificationHistoryModel(self)
		self.notification_table.setModel(self.table_model)
		# In case no settings were loaded:
		if settings.sound_notifications is None:
			settings.sound_notifications = default_sound_notifications
		# In case loading the settings inserted bad values:
		settings.sound_notifications = {t for t in settings.sound_notifications if t in notification_sound_base}
		self.media_player = QMediaPlayer()
		self.notification_table.doubleClicked.connect(self.notificationDoubleClicked)
		self.cleanUp_button.clicked.connect(self.table_model.clearNotifications)
		# Notification signals
		signals.emergencySquawk.connect(self.catchEmergencySquawk)
		signals.pathConflict.connect(lambda: self.notify(Notification.CONFLICT_WARNING, 'Anticipated conflict'))
		signals.nearMiss.connect(lambda: self.notify(Notification.SEPARATION_INCIDENT, 'Loss of separation!'))
		signals.runwayIncursion.connect(self.catchRwyIncursion)
		signals.cpdlcInitLink.connect(self.catchCpdlcInit)
		signals.cpdlcMessageReceived.connect(self.catchCpdlcMessage)
		signals.cpdlcProblem.connect(self.catchCpdlcProblem)
		signals.sessionStarted.connect(self.catchSessionStarted)
		signals.sessionEnded.connect(lambda: self.notify(Notification.GUI_INFO, 'Session ended'))
		signals.sessionRecorderStarted.connect(lambda: self.notify(Notification.GUI_INFO, 'Session recorder started'))
		signals.sessionRecorderStopped.connect(lambda: self.notify(Notification.GUI_INFO, 'Session recorder stopped'))
		signals.alarmClockTimedOut.connect(self.alarmClockTimeOut)
		signals.newWeather.connect(self.catchNewWeather)
		signals.voiceMsgNotRecognised.connect(lambda: self.notify(Notification.UNRECOGNISED_VOICE_INSTR, 'Voice instruction not recognised'))
		signals.newATC.connect(self.catchNewATC)
		signals.newFPL.connect(self.catchNewFlightPlan)
		signals.stripAutoPrinted.connect(self.catchStripAutoPrinted)
		signals.linkedContactLost.connect(self.catchLostLinkedContact)
		signals.incomingTextRadioMsg.connect(self.catchIncomingTextRadioMsg)
		signals.incomingAtcTextMsg.connect(self.catchIncomingAtcTextMsg)
		signals.incomingPhoneCall.connect(lambda caller: self.notify(Notification.ATC_PHONE_CALL, 'Incoming phone call from ' + caller))
		signals.phoneCallAnswered.connect(lambda atc: self.notify(Notification.ATC_PHONE_CALL_ANSWERED, 'Phone call answered by ' + atc))
		signals.phoneCallDropped.connect(lambda atc: self.notify(Notification.ATC_PHONE_CALL_DROPPED, 'Phone line dropped by ' + atc))
		signals.aircraftIdentification.connect(self.catchAircraftIdentification)
		signals.receiveStrip.connect(self.catchStripReceived)
		signals.wilco.connect(lambda: self.playSound(wilco_beep))

	def alarmClockTimeOut(self, msg):
		def popup(txt=msg):
			QMessageBox.information(self, 'Alarm clock message', txt)
		self.notify(Notification.ALARM_CLOCK, 'Alarm clock timed out.', dblClick=(popup if msg else None))
		if msg:
			popup()

	def playSound(self, sound):
		self.media_player.setMedia(sound)
		self.media_player.play()
	
	def notify(self, t, msg, dblClick=None):
		if settings.session_manager.session_type == SessionType.PLAYBACK and t not in {Notification.GUI_INFO, Notification.ALARM_CLOCK}:
			return
		if msg is not None:
			signals.statusBarMsg.emit(msg)
			if t in icon_files:
				self.table_model.addNotification(t, msg, dblClick)
				self.notification_table.scrollToBottom()
		if t in settings.sound_notifications and not settings.mute_notifications and not settings.session_start_temp_lock and \
				not (settings.PTT_mutes_notifications and (settings.keyboard_PTT_pressed or any(r.isTransmitting() for r in settings.radios))):
			self.playSound(notification_sound_base[t])

	def notifyTimeForAtis(self):
		self.notify(Notification.ALARM_CLOCK, 'Reminder: record ATIS', dblClick=signals.atisDialogRequest.emit)
	
	def notificationDoubleClicked(self):
		try:
			notification = self.table_model.history[self.notification_table.selectedIndexes()[0].row()]
		except IndexError:
			return
		if notification.double_click_function is not None:
			notification.double_click_function()
	
	## REACTING TO GUI SIGNALS
	
	def catchNewATC(self, callsign):
		if not settings.session_start_temp_lock:
			self.notify(Notification.ATC_CONNECTED, '%s connected' % callsign)
	
	def catchIncomingTextRadioMsg(self, msg):
		if msg.sender() not in settings.text_radio_senders_blacklist:
			self.notify(Notification.TXT_RADIO_MSG, None)
	
	def catchIncomingAtcTextMsg(self, msg):
		if msg.isPrivate() or settings.session_manager.session_type in (SessionType.TEACHER, SessionType.STUDENT):
			self.notify(Notification.ATC_CHAT_MSG, '%s: "%s"' % (msg.sender(), msg.txtOnly()))
		elif settings.ATC_chatroom_msg_notifications:
			self.notify(Notification.ATC_CHAT_MSG, 'Public ATC channel message')
	
	def catchCpdlcInit(self, callsign):
		if settings.session_start_temp_lock:
			return
		link = env.cpdlc.lastDataLink(callsign)
		if link is not None:
			f = lambda cs=callsign: signals.cpdlcDialogueRequest.emit(cs, True)
			if settings.session_manager.session_type == SessionType.TEACHER:
				if link.isLive() and link.pendingTransferTo() is not None:
					txt = 'Data link transfer from student'
				else: # manual ACFT log-on or XFR proposal to student
					return
			else: # not teaching
				xfr = link.pendingTransferFrom()
				txt = 'Data link established with ' + callsign if xfr is None else 'Data link transfer from ' + xfr
			self.notify(Notification.CPDLC_TRANSMISSION, txt, dblClick=f)
	
	def catchCpdlcMessage(self, callsign, msg):
		if not msg.isAcknowledgement() and not msg.isStandby():
			tofrom = 'to' if msg.isUplink() else 'from' # receiving an uplink means we are teaching
			f = lambda cs=callsign: signals.cpdlcDialogueRequest.emit(cs, True)
			self.notify(Notification.CPDLC_TRANSMISSION, 'CPDLC message %s %s' % (tofrom, callsign), dblClick=f)
	
	def catchCpdlcProblem(self, callsign, pb):
		f = lambda cs=callsign: signals.cpdlcDialogueRequest.emit(cs, True)
		self.notify(Notification.CPDLC_PROBLEM, 'CPDLC problem with %s' % callsign, dblClick=f)
	
	def catchLostLinkedContact(self, strip, pos):
		cs = strip.callsign()
		msg = 'Radar contact lost'
		if cs is not None:
			msg += ' for ' + cs
		msg += ' ' + env.mapLocStr(pos)
		f = lambda coords=pos: signals.indicatePoint.emit(coords)
		self.notify(Notification.LOST_LINKED_CONTACT, msg, dblClick=f)
	
	def catchAircraftIdentification(self, strip, acft, modeS):
		if strip.linkedAircraft() is not acft: # could already be hard linked if XPDR was turned off and back on (avoid too many signals)
			if modeS:
				msg = 'Callsign %s identified (mode S)' % strip.lookup(FPL.CALLSIGN)
			else:
				msg = 'XPDR code %04o identified' % strip.lookup(assigned_SQ_detail)
			f = lambda coords=acft.coords(): signals.indicatePoint.emit(coords)
			self.notify(Notification.RADAR_IDENTIFICATION, msg, dblClick=f)
	
	def catchStripReceived(self, strip):
		fromATC = strip.lookup(received_from_detail)
		if fromATC is not None:
			self.notify(Notification.STRIP_RECEIVED, 'Strip received from %s' % fromATC)
	
	def catchStripAutoPrinted(self, strip, reason):
		msg = 'Strip printed'
		cs = strip.callsign()
		if cs is not None:
			msg += ' for ' + cs
		if reason is not None:
			msg += '; ' + reason
		f = lambda s=strip: signals.stripEditRequest.emit(s)
		self.notify(Notification.STRIP_AUTO_PRINTED, msg, dblClick=f)
	
	def catchSessionStarted(self, session_type):
		self.notify(Notification.GUI_INFO, {
				SessionType.SOLO: 'Solo simulation started',
				SessionType.FLIGHTGEAR: 'FlightGear network joined',
				SessionType.FSD: 'FSD connection established',
				SessionType.STUDENT: 'Student session beginning',
				SessionType.TEACHER: 'Teacher session beginning',
				SessionType.PLAYBACK: 'Playback session opened'
			}[session_type]
		)
	
	def catchNewWeather(self, station, weather):
		if not settings.session_start_temp_lock and station == settings.primary_METAR_station:
			self.notify(Notification.WEATHER_UPDATE, 'Weather update: %s' % weather.METAR(), dblClick=signals.weatherDockRaiseRequest.emit)
	
	def catchNewFlightPlan(self, new_fpl):
		if not settings.session_start_temp_lock and (new_fpl[FPL.ICAO_DEP] == settings.location_code or new_fpl[FPL.ICAO_ARR] == settings.location_code):
			f = lambda fpl=new_fpl: signals.fplEditRequest.emit(fpl)
			self.notify(Notification.FPL_FILED, 'FPL filed for %s' % settings.location_code, dblClick=f)
	
	def catchEmergencySquawk(self, acft):
		f = lambda coords=acft.coords(): signals.indicatePoint.emit(coords)
		self.notify(Notification.EMG_SQUAWK, 'Aircraft squawking emergency', dblClick=f)
	
	def catchRwyIncursion(self, phyrwy, acft):
		rwy = env.airport_data.physicalRunwayNameFromUse(phyrwy)
		f = lambda coords=acft.coords(): signals.indicatePoint.emit(coords)
		self.notify(Notification.RWY_INCURSION, 'Runway %s incursion!' % rwy, dblClick=f)

