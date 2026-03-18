
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

from datetime import timedelta

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QWidget, QMessageBox
from ui.playbackCtrlPanel import Ui_playbackCtrlPanel

from gui.misc import signals, IconFile

from session.config import settings
from session.manager import SessionType


# ---------- Constants ----------

# -------------------------------

class PlaybackCtrlPanel(QWidget, Ui_playbackCtrlPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.timeSpeedFactorReset_button.setIcon(QIcon(IconFile.button_clear))
		self.setEnabled(False)
		self.memory_slots = [] # CAUTION: list extended with button signal connections
		self.custom_step_unit = 'min'
		self.customStep_edit.setSuffix(' ' + self.custom_step_unit)
		for fwdbtn, tdelta in \
				(self.stepBack1h_button, -timedelta(hours=1)), (self.stepBack10min_button, -timedelta(minutes=10)), \
				(self.stepBack1min_button, -timedelta(minutes=1)), (self.stepBack10s_button, -timedelta(seconds=10)), \
				(self.stepFwd10s_button, timedelta(seconds=10)), (self.stepFwd1min_button, timedelta(minutes=1)), \
				(self.stepFwd10min_button, timedelta(minutes=10)), (self.stepFwd1h_button, timedelta(hours=1)):
			fwdbtn.clicked.connect(lambda ignore_arg, td=tdelta: settings.session_manager.offsetSessionTime(td))
		self.clock_slider.valueChanged.connect(self.clockSliderValueChanged)
		self.stepBackCustom_button.clicked.connect(lambda: settings.session_manager.offsetSessionTime(-self.customTimeStep()))
		self.stepFwdCustom_button.clicked.connect(lambda: settings.session_manager.offsetSessionTime(self.customTimeStep()))
		self.changeCustomStepUnit_button.clicked.connect(self.changeCustomStepUnit)
		for mem_button in self.memory1_button, self.memory2_button, self.memory3_button:
			mem_button.clicked.connect(lambda ignore_arg, memIdx=len(self.memory_slots): self.memButtonClicked(memIdx))
			self.memory_slots.append(None)
		self.playFwd_toggle.toggled.connect(lambda b: settings.session_manager.resume() if b else settings.session_manager.pause())
		self.playFwd_toggle.toggled.connect(self.clock_slider.setDisabled)
		self.timeSpeedFactor_edit.valueChanged.connect(lambda b: settings.session_manager.setTimeSpeedFactor(b))
		self.timeSpeedFactorReset_button.clicked.connect(lambda: self.timeSpeedFactor_edit.setValue(1))
		self.auto_slider_value_change = False
		signals.sessionPaused.connect(lambda: self.playFwd_toggle.setChecked(False))
		signals.sessionResumed.connect(lambda: self.playFwd_toggle.setChecked(True))
		signals.playbackClockChanged.connect(self.updateClockSliderPosition)
		signals.sessionStarted.connect(self.sessionHasStarted)
		signals.sessionEnded.connect(self.sessionHasEnded)

	def sessionHasStarted(self, session_type):
		if session_type == SessionType.PLAYBACK:
			dur = settings.session_manager.timeline.duration().total_seconds()
			self.clock_slider.setMaximum(int(dur) if int(dur) == dur else int(dur) + 1)
			self.clock_slider.setValue(0)
			self.setEnabled(True)

	def sessionHasEnded(self, session_type):
		if session_type == SessionType.PLAYBACK:
			self.setEnabled(False)
		for i in range(len(self.memory_slots)):
			self.memory_slots[i] = None

	def changeCustomStepUnit(self):
		self.custom_step_unit = {'s': 'min', 'min': 'h', 'h': 's'}[self.custom_step_unit]
		self.customStep_edit.setSuffix(' ' + self.custom_step_unit)

	def customTimeStep(self):
		if self.custom_step_unit == 's':
			return timedelta(seconds=self.customStep_edit.value())
		elif self.custom_step_unit == 'min':
			return timedelta(minutes=self.customStep_edit.value())
		elif self.custom_step_unit == 'h':
			return timedelta(hours=self.customStep_edit.value())

	def updateClockSliderPosition(self, session_time):
		if settings.session_manager.timeline.lastEventTime() - session_time < timedelta(milliseconds=1):
			new_value = self.clock_slider.maximum()
		else:
			new_value = int(settings.session_manager.timeline.timeAfterStart(session_time).total_seconds())
		if new_value != self.clock_slider.value():
			self.auto_slider_value_change = True
			self.clock_slider.setValue(new_value)

	def clockSliderValueChanged(self, value):
		if self.auto_slider_value_change: # automatic change from session time update; do not set session time
			self.auto_slider_value_change = False
		elif value == self.clock_slider.maximum(): # manual change to last notch
			settings.session_manager.setSessionTime(settings.session_manager.timeline.lastEventTime())
		else: # manual change anywhere else
			settings.session_manager.setSessionTime(settings.session_manager.timeline.startTime() + timedelta(seconds=value))

	def memButtonClicked(self, mem_idx):
		if self.setMemory_toggle.isChecked():
			self.memory_slots[mem_idx] = settings.session_manager.clockTime()
			signals.statusBarMsg.emit('Current timeline position saved to memory slot.')
			self.setMemory_toggle.setChecked(False)
		elif self.memory_slots[mem_idx] is None:
			QMessageBox.critical(self, 'Recall time memory', 'Memory slot not set.')
		else:
			settings.session_manager.setSessionTime(self.memory_slots[mem_idx])
