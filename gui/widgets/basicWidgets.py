
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

from PyQt5.QtCore import pyqtSignal, Qt, QEvent, QTimer, QRegExp
from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtWidgets import QCompleter, QComboBox, QToolButton, QSpinBox, QLineEdit, QLabel, QMessageBox

from base.radio import CommFrequency
from base.db import all_aircraft_types
from base.params import Heading, AltFlSpec, Speed

from session.env import env

from gui.misc import recognisedValue_lineEdit_styleSheet, unrecognisedValue_lineEdit_styleSheet


# ---------- Constants ----------

widget_flash_time = 800 # ms
default_alt_FL_spec = AltFlSpec(True, 100)
alt_FL_wheel_step = 5 # hundreds of feet

# -------------------------------


def flash_widget(w, stylesheet):
	w.setStyleSheet(stylesheet)
	QTimer.singleShot(widget_flash_time, lambda: w.setStyleSheet(None))



class AtisCodeEditWidget(QSpinBox):
	def __init__(self, parent=None):
		QSpinBox.__init__(self, parent)
		self.setWrapping(True)
		self.setMaximum(25) # 0:A ... 25:Z

	def textFromValue(self, v):  # override
		return chr(ord('A') + v)

	def valueFromText(self, txt):
		return ord(txt.upper()) - ord('A')

	def setLetter(self, txt):
		self.setValue(self.valueFromText(txt))

	def currentLetter(self):
		return self.textFromValue(self.value())



class ModClickButton(QToolButton):
	modClicked = pyqtSignal(Qt.KeyboardModifiers)

	def __init__(self, parent):
		QToolButton.__init__(self, parent)
		self.setToolTip('With ALT: send through CPDLC')

	def mouseReleaseEvent(self, event):
		self.modClicked.emit(event.modifiers())
		QToolButton.mouseReleaseEvent(self, event)



class DoubleClickLabel(QLabel):
	doubleClicked = pyqtSignal()

	def __init__(self, parent):
		QLabel.__init__(self, parent)

	def mouseDoubleClickEvent(self, event):
		event.accept()
		self.doubleClicked.emit()
		QLabel.mouseReleaseEvent(self, event)



class Ticker(QTimer):
	def __init__(self, parent, action_callback):
		QTimer.__init__(self, parent)
		self.action = action_callback
		self.timeout.connect(self.action)

	def startTicking(self, interval, immediate=True):
		tms = int(1000 * interval.total_seconds() if isinstance(interval, timedelta) else interval)
		if tms == 0:
			self.stop()
		else:
			if immediate:
				self.action()
			self.start(tms)




##-------------------------##
##                         ##
##    RADIO/FREQUENCIES    ##
##                         ##
##-------------------------##

class RdfStatusBarLabel(DoubleClickLabel):
	def __init__(self, parent):
		DoubleClickLabel.__init__(self, parent)
		self.setToolTip('Current signal / last QDM')
		self.lastest_signal = None
		self.updateDisp(None)
		self.doubleClicked.connect(self.showLastSignalInfo)

	def updateDisp(self, current_signal):
		if current_signal is None:
			s1 = ' - - - '
		else:
			s1 = current_signal.direction.read()
			self.lastest_signal = current_signal
		if self.lastest_signal is None:
			s2 = ' - - - '
		else:
			s2 = self.lastest_signal.direction.opposite().read()
		self.setText('RDF %s / %s' % (s1, s2))

	def showLastSignalInfo(self):
		if self.lastest_signal is not None:
			txt = 'Last signal detected from %s (%s)' % (self.lastest_signal.direction.read(), self.lastest_signal.direction.approxCardinal(False))
			if self.lastest_signal.frequency is not None:
				txt += ' on %s' % self.lastest_signal.frequency
			QMessageBox.information(self, 'RDF info', txt)



class FrequencyPickCombo(QComboBox):
	frequencyChanged = pyqtSignal()
	
	def __init__(self, parent=None):
		QComboBox.__init__(self, parent)
		self.setEditable(True)
		self.setToolTip('Type+ENTER to tune manually')
		self.setInsertPolicy(QComboBox.NoInsert)
		self.last_accepted_entry = ''
		self.currentIndexChanged.connect(self.selectFrequency)
		self.currentTextChanged.connect(lambda: self.lineEdit().setStyleSheet(None))
		self.lineEdit().returnPressed.connect(self.manualEntry)
	
	#Overriding method
	def focusOutEvent(self, event): # QFocusEvent
		self.lineEdit().setStyleSheet(None)
		if self.isEnabled():
			self.setEditText(self.last_accepted_entry)
		QComboBox.focusOutEvent(self, event)
	
	#Overriding method
	def changeEvent(self, event): # QEvent
		if event.type() == QEvent.EnabledChange:
			if self.isEnabled():
				self.selectFrequency()
			else:
				self.lineEdit().setStyleSheet(None)
		QComboBox.changeEvent(self, event)
	
	def addFrequencies(self, frqlst):
		self.addItems(['%s  %s' % frq_descr_pair for frq_descr_pair in frqlst])
	
	def selectFrequency(self):
		self.lineEdit().setStyleSheet(None)
		split = self.currentText().split(maxsplit=1)
		if len(split) == 0:
			self.last_accepted_entry = ''
		else: # will produce colour
			try:
				frq = CommFrequency(split[0])
				self.last_accepted_entry = str(frq)
				if len(split) > 1:
					self.last_accepted_entry += '  ' + split[1]
				self.setEditText(self.last_accepted_entry)
				if self.hasFocus():
					flash_widget(self.lineEdit(), recognisedValue_lineEdit_styleSheet)
			except ValueError:
				if self.hasFocus():
					self.lineEdit().setStyleSheet(unrecognisedValue_lineEdit_styleSheet)
		self.frequencyChanged.emit()
	
	def manualEntry(self):
		self.selectFrequency()
		self.lineEdit().selectAll()
		
	def getFrequency(self):
		try:
			return CommFrequency(self.currentText().split(maxsplit=1)[0])
		except (IndexError, ValueError):
			return None




##-------------------------------------------##
##                                           ##
##        AIRCRAFT TYPE & TRANSPONDER        ##
##                                           ##
##-------------------------------------------##

class AircraftTypeCombo(QComboBox):
	def __init__(self, parent=None):
		QComboBox.__init__(self, parent)
		self.setEditable(True)
		items = all_aircraft_types() # set
		items.add('ZZZZ')
		self.addItems(sorted(items))
		self.completer().setCompletionMode(QCompleter.PopupCompletion)
		self.completer().setFilterMode(Qt.MatchContains)
	
	def setAircraftFilter(self, pred):
		new_entries = [t for t in all_aircraft_types() if pred(t)]
		new_entries.sort()
		self.clear()
		self.addItems(new_entries)
	
	def getAircraftType(self):
		value = self.currentText()
		return None if value == '' else value



class XpdrCodeSpinBox(QSpinBox):
	def __init__(self, parent=None):
		QSpinBox.__init__(self, parent)
		self.setDisplayIntegerBase(8)
		self.setMaximum(0o7777)
		self.setWrapping(True)
	
	def textFromValue(self, sq): # override
		return '%04o' % sq




##-------------------------------##
##                               ##
##       FLIGHT PARAMETERS       ##
##                               ##
##-------------------------------##

class HeadingEditWidget(QSpinBox):
	def __init__(self, parent=None):
		QSpinBox.__init__(self, parent)
		self.setWrapping(True)
		self.setMinimum(1)
		self.setMaximum(360)
		self.setSingleStep(5)
		self.setSuffix('°')
		self.setValue(360)
	
	def textFromValue(self, v): # override
		return '%03d' % v
	
	def headingValue(self, is_true):
		return Heading(self.value(), is_true)



class AltFlEditWidget(QLineEdit):
	def __init__(self, parent):
		QLineEdit.__init__(self, parent)
		self.setClearButtonEnabled(True)
		self.setValidator(QRegExpValidator(QRegExp('FL? ?\\d+|\\d+( ?ft)?', cs=Qt.CaseInsensitive)))
		self.sync_with_env = False
		self.last_valid_spec = None # overridden by initial value immediately
		self.setAltFlSpec(default_alt_FL_spec)
		self.editingFinished.connect(lambda: self.setAltFlSpec(AltFlSpec.fromStr(self.text()))) # text validated (no ValueError)
	
	def altFlSpec(self):
		return self.last_valid_spec
	
	def setAltFlSpec(self, spec):
		self.last_valid_spec = env.specifyAltFl(env.pressureAlt(spec)) if self.sync_with_env else spec
		self.setText(self.last_valid_spec.toStr())
	
	def syncWithEnv(self, sync):
		self.sync_with_env = sync
		self.setToolTip('Synchronised with TA and QNH' if sync else '')
		if sync:
			self.setAltFlSpec(self.last_valid_spec)
	
	def wheelEvent(self, event):
		new_spec = self.last_valid_spec.plusHundredsFt(alt_FL_wheel_step if event.angleDelta().y() > 0 else -alt_FL_wheel_step)
		if not new_spec.toStr().startswith('-'):
			self.setAltFlSpec(new_spec)



class SpeedEditWidget(QSpinBox):
	def __init__(self, parent=None):
		QSpinBox.__init__(self, parent)
		self.setMinimum(50)
		self.setMaximum(999)
		self.setSingleStep(10)
		self.setSuffix(' kt')
		self.setValue(150)
	
	def speedValue(self):
		return Speed(self.value())
	
	def setSpeedValue(self, spd):
		self.setValue(int(spd.kt()))
