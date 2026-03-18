
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

from datetime import timedelta, timezone

from PyQt5.QtWidgets import QWidget, QDialog, QMessageBox
from PyQt5.QtCore import Qt, QDateTime
from ui.radioWidget import Ui_radioWidget
from ui.radioPanel import Ui_radioPanel
from ui.atisDialog import Ui_atisDialog

from base.util import some
from base.utc import timestr
from base.radio import EMG_comm_freq
from base.text import replace_text_aliases

from gui.misc import signals, selection

from session.config import settings
from session.env import env
from session.manager import SessionType


# ---------- Constants ----------

soft_sound_level = .25
loud_sound_level = 1

# -------------------------------


class RadioBox(QWidget, Ui_radioWidget):
	next_ID = 0 # STATIC unique identifier for constructed radio boxes
	
	def __init__(self, parent, radio):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.box_ID = RadioBox.next_ID
		RadioBox.next_ID += 1
		self.RDF_tickBox.setVisible(settings.session_manager.session_type == SessionType.FLIGHTGEAR)
		self.PTT_button.setEnabled(False)
		self.radio = radio
		self.frequency_combo.addFrequencies((frq, descr) for frq, descr, t in env.frequencies())
		self.frequency_combo.addFrequencies([(EMG_comm_freq, 'EMG')])
		self.updateRdfButton()
		self.tuneRadio()
		self.onOff_button.clicked.connect(self.switchOnOff) # clicked manually (has toggle arg too)
		self.PTT_button.pressed.connect(lambda: self.doPTT(True))
		self.PTT_button.released.connect(lambda: self.doPTT(False))
		self.softVolume_tickBox.toggled.connect(self.setRadioVolume)
		self.frequency_combo.frequencyChanged.connect(self.tuneRadio)
		self.RDF_tickBox.toggled.connect(self.updateRdfMonitor)
		signals.locationSettingsChanged.connect(self.updateRdfButton)
	
	def isKbdPTT(self):
		return self.kbdPTT_checkBox.isChecked()
	
	def updateRdfButton(self):
		self.RDF_tickBox.setEnabled(settings.radio_direction_finding)
		if not settings.radio_direction_finding:
			self.RDF_tickBox.setChecked(False)
	
	def updateRdfMonitor(self):
		self.radio.setRdfMonitored(settings.radio_direction_finding and self.RDF_tickBox.isChecked())
	
	def switchOnOff(self, toggle):
		if not toggle:
			self.doPTT(False)
		self.radio.switchOnOff(toggle)
		on = self.radio.isOn()
		self.onOff_button.setChecked(on)
		self.PTT_button.setEnabled(on)
		self.removeBox_button.setEnabled(not on)
	
	def doPTT(self, toggle):
		if self.PTT_button.isEnabled():
			self.radio.setPTT(toggle)
			self.PTT_button.setChecked(toggle) # in case keyed with keyboard
		
	def tuneRadio(self):
		self.doPTT(False)
		self.radio.setFrequency(some(self.frequency_combo.getFrequency(), EMG_comm_freq)) # using EMG as fallback
	
	def setRadioVolume(self):
		if settings.radios_silenced:
			self.radio.setVolume(0)
		else:
			self.radio.setVolume(soft_sound_level if self.softVolume_tickBox.isChecked() else loud_sound_level)



class AtisDialog(QDialog, Ui_atisDialog):
	def __init__(self, parent):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.newFrequency_edit.addFrequencies([(f, d) for f, d, t in env.frequencies() if t == 'recorded'])
		if settings.last_recorded_ATIS is None:
			self.tabs.setTabEnabled(0, False)
			self.tabs.setCurrentIndex(1)
			next_info_letter = 'A'
		else:
			self._updateLastInfo()
			next_info_letter = chr((ord(settings.last_recorded_ATIS[0]) - ord('A') + 1) % 26 + ord('A'))
		self.newInfo_text.setPlainText(env.suggestedATIS(next_info_letter, appendix=replace_text_aliases(settings.ATIS_custom_appendix, selection, False)))
		self.newLetter_edit.setLetter(next_info_letter)
		self.nextAtisReminder_tickBox.setChecked(settings.record_ATIS_reminder is not None)
		if settings.session_manager.session_type == SessionType.PLAYBACK:
			self.record_button.setEnabled(False)
			self.nextAtisReminder_tickBox.setEnabled(False)
		else: # non-playback session type
			if settings.record_ATIS_reminder is None:
				self.suggestNextAtisReminderTime()
			else:
				self.nextAtisReminder_edit.setDateTime(QDateTime(settings.record_ATIS_reminder.year, settings.record_ATIS_reminder.month,
						settings.record_ATIS_reminder.day, settings.record_ATIS_reminder.hour, settings.record_ATIS_reminder.minute, timeSpec=Qt.UTC))
			self.record_button.clicked.connect(self.record)
			self.nextAtisReminder_tickBox.toggled.connect(self.nextAtisReminder_edit.setFocus)
		self.close_button.clicked.connect(self.closeMe)

	def _updateLastInfo(self):
		self.tabs.setTabText(0, 'View last recorded (%s)' % settings.last_recorded_ATIS[0])
		self.tabs.setTabEnabled(0, True)
		self.lastLetter_info.setText(settings.last_recorded_ATIS[0])
		self.lastTime_info.setText(timestr(settings.last_recorded_ATIS[1]))
		self.lastFrequency_info.setText(str(settings.last_recorded_ATIS[2]))
		self.lastInfo_text.setPlainText(settings.last_recorded_ATIS[3])
	
	def record(self):
		frq = self.newFrequency_edit.getFrequency()
		letter = self.newLetter_edit.currentLetter()
		if frq is None:
			QMessageBox.critical(self, 'Record ATIS', 'Invalid frequency')
		else:
			ok = QMessageBox.question(self, 'Record ATIS', 'Save present notepad as information %s, and start voice recording if applicable to current session?' % letter) == QMessageBox.Yes
			if settings.last_recorded_ATIS is not None:
				ok &= ord(letter) == ord(settings.last_recorded_ATIS[0]) + 1 \
						or QMessageBox.question(self, 'Record ATIS', 'The letter you are saving as is not the letter after last. Confirm?') == QMessageBox.Yes
				ok &= frq.inTune(settings.last_recorded_ATIS[2]) \
					or QMessageBox.question(self, 'Record ATIS', 'The frequency you are recording to is not in tune with the last. Confirm?') == QMessageBox.Yes
			if ok:
				settings.last_recorded_ATIS = letter, settings.session_manager.clockTime(), frq, self.newInfo_text.toPlainText()
				self._updateLastInfo()
				settings.session_manager.recordAtis(self)
				self.tabs.setCurrentIndex(0)
				settings.session_recorder.proposeNewAtis(settings.last_recorded_ATIS[1], letter, frq, settings.last_recorded_ATIS[3])
		self.suggestNextAtisReminderTime()
	
	def closeMe(self):
		if self.nextAtisReminder_tickBox.isChecked():
			settings.record_ATIS_reminder = self.nextAtisReminder_edit.dateTime().toPyDateTime().replace(tzinfo=timezone.utc)
		else:
			settings.record_ATIS_reminder = None
		self.accept()
	
	def suggestNextAtisReminderTime(self):
		t = settings.session_manager.clockTime() + timedelta(minutes=35)
		self.nextAtisReminder_edit.setDateTime(QDateTime(t.year, t.month, t.day, t.hour, (0 if t.minute // 30 == 0 else 30), timeSpec=Qt.UTC))



class RadioPanel(QWidget, Ui_radioPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.atis_button.setVisible(env.airport_data is not None)
		self.setEnabled(False)
		self.pubFreq_tickBox.setText(settings.location_code + ':')
		self.pubFreq_edit.addFrequencies([(f, d) for f, d, t in env.frequencies() if t != 'recorded'])
		# connections
		self.addBox_button.clicked.connect(self.addRadioBox)
		self.atis_button.clicked.connect(signals.atisDialogRequest.emit)
		self.muteAllRadios_tickBox.toggled.connect(self.toggleSilenceRadios)
		self.pubFreq_tickBox.toggled.connect(self.pubFreqToggled)
		self.pubFreq_edit.frequencyChanged.connect(self.setPubFreq)
		signals.kbdPTT.connect(self.generalKeyboardPTT)
		signals.sessionStarted.connect(self.sessionHasStarted)
		signals.sessionEnded.connect(self.sessionHasEnded)
	
	def sessionHasStarted(self, session_type):
		self.setEnabled(session_type != SessionType.PLAYBACK)
		self.pubFreq_tickBox.setText(settings.my_callsign + ':')
	
	def sessionHasEnded(self):
		while self.radios_table.rowCount() > 0:
			self.removeRadioBox(tblRow=0)
		self.muteAllRadios_tickBox.setChecked(False)
		self.pubFreq_tickBox.setChecked(False)
		self.setEnabled(False)
	
	def pubFreqToggled(self, toggle):
		if toggle:
			self.pubFreq_tickBox.setText(settings.my_callsign + ':')
			self.pubFreq_edit.lineEdit().selectAll()
		else:
			settings.publicised_frequency = None
	
	def setPubFreq(self):
		settings.publicised_frequency = self.pubFreq_edit.getFrequency()
	
	def radioBox(self, row):
		return self.radios_table.cellWidget(row, 0)
		
	def addRadioBox(self):
		new_radio = settings.session_manager.createRadio()
		if new_radio is not None:
			settings.radios.append(new_radio)
			box = RadioBox(self, new_radio)
			row = self.radios_table.rowCount()
			box.kbdPTT_checkBox.setChecked(row == 0)
			box.removeBox_button.clicked.connect(lambda ignore_arg, rid=box.box_ID: self.removeRadioBox(boxID=rid))
			self.radios_table.insertRow(row)
			self.radios_table.setCellWidget(row, 0, box)
			self.radios_table.scrollToBottom()
			self.radios_table.resizeColumnToContents(0)
			self.radios_table.resizeRowToContents(row)
	
	def removeRadioBox(self, boxID=None, tblRow=None):
		if tblRow is None: # radio identified by ID on manual removal; get row from ID
			try:
				tblRow = next(row for row in range(self.radios_table.rowCount()) if self.radioBox(row).box_ID == boxID)
			except StopIteration:
				return # abort
		self.radioBox(tblRow).switchOnOff(False)
		self.radios_table.removeRow(tblRow)
		try:
			del settings.radios[tblRow]
		except IndexError:
			pass
	
	def generalKeyboardPTT(self, toggle):
		for i in range(self.radios_table.rowCount()):
			box = self.radioBox(i)
			if box.isKbdPTT():
				box.doPTT(toggle)
	
	def toggleSilenceRadios(self, toggle):
		settings.radios_silenced = toggle
		for i in range(self.radios_table.rowCount()):
			self.radioBox(i).setRadioVolume() # takes care of zero volume if silenced here
