
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

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QInputDialog, QListView, QMessageBox

from ui.atcListPanel import Ui_atcListPanel

from base.phone import PhoneLineStatus
from base.utc import timestr, datestr

from gui.misc import signals, selection, SimpleStringListModel, RadioKeyEventFilter

from session.config import settings
from session.env import env
from session.manager import SessionType


# ---------- Constants ----------

left_icon_column_width = 50

# -------------------------------


class WhoHasWidget(QListView):
	def __init__(self, parent=None):
		QListView.__init__(self, parent)
		self.setModel(SimpleStringListModel(self, False))
		self.last_whohas_request = None
	
	def newRequest(self, acft_callsign):
		self.model().clearList()
		self.setWindowTitle('Claiming %s at %s (%s)' % (acft_callsign, timestr(settings.session_manager.clockTime(), seconds=True), datestr(settings.session_manager.clockTime())))
		self.last_whohas_request = acft_callsign.upper()
	
	def processClaim(self, atc_callsign, acft_callsign):
		if acft_callsign.upper() == self.last_whohas_request: # CAUTION last is None until being shown once; uppercase afterwards
			self.model().appendString(atc_callsign)






class AtcCoordinationPanel(QWidget, Ui_atcListPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.phoneSquelch_widget.setVisible(False) # toggles from system menu action
		self.phoneSquelch_edit.setValue(int(1000 * settings.phone_line_squelch))
		self.call_button.setEnabled(False)
		self.phoneSquelch_widget.setEnabled(False)
		self.whoHas_button.setEnabled(False)
		self.whoHas_window = WhoHasWidget(self)
		self.whoHas_window.setWindowFlags(Qt.Window)
		self.whoHas_window.installEventFilter(RadioKeyEventFilter(self))
		self.who_has_suggestion = None
		self.ATC_view.setModel(env.ATCs)
		self.whoHas_button.clicked.connect(self.whoHasRequest)
		self.call_button.clicked.connect(self.manualPhoneCall)
		self.phoneSquelch_edit.valueChanged.connect(self.setSquelchFromValue)
		signals.incomingContactClaim.connect(self.whoHas_window.processClaim)
		signals.selectionChanged.connect(self.updateSuggestionFromSelection)
		signals.sessionStarted.connect(self.sessionHasStarted)
		signals.sessionEnded.connect(self.sessionHasEnded)
		signals.phoneManagerAvailabilityChange.connect(self.showHidePhoneLines)
		signals.closeNonDockableWindows.connect(self.whoHas_window.close)
	
	def sessionHasStarted(self, session_type):
		self.who_has_suggestion = None
		self.whoHas_button.setEnabled(session_type != SessionType.PLAYBACK)
		self.showHidePhoneLines()
		signals.fastClockTick.connect(env.ATCs._flashRingingIcons)
		signals.phoneLineStatusChanged.connect(env.ATCs.updatePhoneLineStatus)
	
	def sessionHasEnded(self):
		signals.fastClockTick.disconnect(env.ATCs._flashRingingIcons)
		signals.phoneLineStatusChanged.disconnect(env.ATCs.updatePhoneLineStatus)
		env.ATCs.clear()
		self.call_button.setEnabled(False)
		self.phoneSquelch_widget.setEnabled(False)
		self.whoHas_button.setEnabled(False)

	def showHidePhoneLines(self):
		if settings.session_manager.phoneLineManager() is None:
			self.ATC_view.horizontalHeader().resizeSection(0, 0) # using setColumnHidden messes logical indices
			self.call_button.setEnabled(False)
			self.phoneSquelch_widget.setEnabled(False)
		else:
			self.ATC_view.horizontalHeader().resizeSection(0, left_icon_column_width)
			self.call_button.setEnabled(True)
			self.phoneSquelch_widget.setEnabled(True)

	def setSquelchFromValue(self, value):
		settings.phone_line_squelch = value / 1000

	def updateSuggestionFromSelection(self):
		cs = selection.selectedCallsign()
		if cs is not None:
			self.who_has_suggestion = cs
	
	def manualPhoneCall(self):
		if settings.session_manager.isRunning():
			llm = settings.session_manager.phoneLineManager()
			items = None if llm is None else llm.linesWithStatus(PhoneLineStatus.IDLE) # non-idle will be listed in table
			if items is None or len(items) == 0:
				QMessageBox.critical(self, 'ATC phone call error', 'No more idle lines available to call.')
			else:
				cs, ok = QInputDialog.getItem(self, 'ATC phone call', 'Callsign:', items, editable=False)
				if ok and llm.lineStatus(cs) is not None: # line might have become unreachable during dialog interaction
					llm.requestPhoneLine(cs)
	
	def whoHasRequest(self):
		if settings.session_manager.isRunning():
			sugg_items = [] if self.who_has_suggestion is None else [self.who_has_suggestion]
			sugg_items.extend(cs for cs in env.knownAcftCallsigns() if cs != self.who_has_suggestion)
			cs, ok = QInputDialog.getItem(self, 'Send a who-has request', 'Callsign:', sugg_items)
			if ok:
				if cs == '':
					QMessageBox.critical(self, 'Who-has', 'Callsign needed for who-has request.')
				else:
					self.whoHas_window.newRequest(cs)
					settings.session_manager.sendWhoHas(cs)
					self.whoHas_window.show()
					self.who_has_suggestion = cs
