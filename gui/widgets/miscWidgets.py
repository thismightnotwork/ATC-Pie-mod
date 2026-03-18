
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

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QSizePolicy, QLabel, QToolButton, QColorDialog
from ui.alarmClocksPanel import Ui_alarmClocksPanel
from ui.quickReference import Ui_quickReference
from ui.weatherDispWidget import Ui_weatherDispWidget
from ui.xpdrCodeSelectorWidget import Ui_xpdrCodeSelectorWidget

from base.util import some
from base.weather import hPa2inHg

from gui.graphics.miscGraphics import coloured_square_icon
from gui.misc import signals, IconFile, RadioKeyEventFilter

from session.env import env
from session.config import settings


# ---------- Constants ----------

quick_ref_disp = 'resources/quick-ref/display-conventions.html'
quick_ref_kbd = 'resources/quick-ref/keyboard-input.html'
quick_ref_mouse = 'resources/quick-ref/mouse-gestures.html'
quick_ref_aliases = 'resources/quick-ref/text-aliases.html'
quick_ref_voice = 'resources/quick-ref/voice-instructions.html'

# -------------------------------

class RecordingIconWidget(QLabel):
	doubleClicked = pyqtSignal()

	def __init__(self, parent):
		QLabel.__init__(self, parent)
		self.setPixmap(QPixmap(IconFile.option_recordSession).scaledToHeight(self.height() - 15))
		self.setToolTip('Recording session')

	def mouseDoubleClickEvent(self, event):
		self.doubleClicked.emit()
		event.accept()


##------------------------------------##
##                                    ##
##            ALARM CLOCKS           ##
##                                    ##
##------------------------------------##

class AlarmClockInfoWidget(QWidget):
	doubleClicked = pyqtSignal()

	def __init__(self, parent):
		QWidget.__init__(self, parent)
		self.icon_label = QLabel(parent=self)
		self.icon_label.setPixmap(QPixmap(IconFile.pixmap_alarmClock).scaledToHeight(self.icon_label.height() - 12))
		self.info_label = QLabel(parent=self)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.addWidget(self.icon_label)
		layout.addWidget(self.info_label)
		signals.fastClockTick.connect(self.updateDisp)

	def updateDisp(self):
		count = env.alarm_clocks.rowCount()
		if count > 0:
			secs = int(env.alarm_clocks.timeUntilFirstTimeout().total_seconds())
			txt = '%d:%02d' % (secs // 60, secs % 60)
			if count > 1:
				txt += ' (+%i)' % (count - 1)
			self.info_label.setText(txt)
		else: # no running timers
			self.info_label.setText('--:--')

	def mouseDoubleClickEvent(self, event):
		self.doubleClicked.emit()
		event.accept()



class AlarmClocksPanel(QWidget, Ui_alarmClocksPanel):
	def __init__(self, parent):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.timers_view.setModel(env.alarm_clocks)
		self.setWindowFlags(Qt.Window)
		self.setWindowIcon(QIcon(IconFile.pixmap_alarmClock))
		self.installEventFilter(RadioKeyEventFilter(self))
		self.newTimerStart_button.clicked.connect(self.newAlarmClock)
		self.deleteSelectedTimer_button.clicked.connect(self.deleteSelectedAlarmClocks)
		env.alarm_clocks.rowsInserted.connect(lambda: self.timers_view.scrollToBottom()) # rowsInserted: always a single row at bottom
		signals.closeNonDockableWindows.connect(self.close)

	def newAlarmClock(self):
		env.alarm_clocks.startNewTimer(timedelta(minutes=self.newTimerDuration_edit.value()))

	def deleteSelectedAlarmClocks(self):
		for row in sorted((idx.row() for idx in self.timers_view.selectedIndexes() if idx.column() == 0), reverse=True):
			self.timers_view.model().removeTimer(row)




##--------------------------------##
##                                ##
##       XPDR CODE SELECTOR       ##
##                                ##
##--------------------------------##

class XpdrCodeSelectorWidget(QWidget, Ui_xpdrCodeSelectorWidget):
	codeChanged = pyqtSignal(int)
	
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.setFocusProxy(self.xpdrCode_edit)
		self.updateXPDRranges()
		self.xpdrRange_select.currentIndexChanged.connect(self.selectXpdrRange)
		self.xpdrCode_edit.valueChanged.connect(self.codeChanged.emit)
	
	def updateXPDRranges(self):
		self.xpdrRange_select.setCurrentIndex(0)
		while self.xpdrRange_select.count() > 1:
			self.xpdrRange_select.removeItem(1)
		self.xpdrRange_select.addItems([r.name for r in settings.XPDR_assignment_ranges if r is not None])
	
	def selectXpdrRange(self, row):
		if row != 0:
			name = self.xpdrRange_select.itemText(row)
			assignment_range = next(r for r in settings.XPDR_assignment_ranges if r is not None and r.name == name)
			self.xpdrCode_edit.setValue(env.strips.nextSquawkCodeAssignment(assignment_range))
			self.xpdrRange_select.setCurrentIndex(0)
			self.xpdrCode_edit.setFocus()
	
	def getSQ(self):
		return self.xpdrCode_edit.value()
	
	def setSQ(self, value):
		return self.xpdrCode_edit.setValue(value)




##-------------------------##
##                         ##
##         WEATHER         ##
##                         ##
##-------------------------##

class WeatherDispWidget(QWidget, Ui_weatherDispWidget):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
	
	def updateDisp(self, new_weather):
		if new_weather is None:
			self.METAR_info.setText('N/A')
			self.wind_info.setText('N/A')
			self.visibility_info.setText('N/A')
			self.QNH_info.setText('N/A')
		else:
			self.METAR_info.setText(new_weather.METAR())
			self.wind_info.setText(new_weather.readWind())
			self.visibility_info.setText(new_weather.readVisibility())
			qnh = new_weather.QNH()
			if qnh is None:
				self.QNH_info.setText('N/A')
			else:
				self.QNH_info.setText('%d hPa, %.2f inHg' % (qnh, hPa2inHg * qnh))




##-------------------------------------##
##                                     ##
##            COLOUR PICKER            ##
##                                     ##
##-------------------------------------##

class ColourPicker(QWidget):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.pick_button = QToolButton(self)
		self.pick_button.setText('Pick...')
		self.clear_button = QToolButton(self)
		self.clear_button.setText('Clear')
		self.clear_button.setAutoRaise(True)
		layout = QHBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.addWidget(self.pick_button)
		layout.addWidget(self.clear_button)
		self.setSizePolicy(QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed))
		self.colour_choice = None
		self.clear_button.clicked.connect(self.clearColour)
		self.pick_button.clicked.connect(self.pickNewColour)
		self.updateColourIcon()
	
	def updateColourIcon(self):
		if self.colour_choice is None:
			self.pick_button.setIcon(QIcon())
			self.clear_button.hide()
		else:
			self.pick_button.setIcon(coloured_square_icon(self.colour_choice))
			self.clear_button.show()
	
	def setChoice(self, colour):
		self.colour_choice = colour
		self.updateColourIcon()
	
	def getChoice(self):
		return self.colour_choice
	
	def pickNewColour(self):
		colour = QColorDialog.getColor(parent=self, title='Pick radar contact colour', initial=some(self.colour_choice, Qt.white))
		if colour.isValid():
			self.setChoice(colour)
	
	def clearColour(self):
		self.colour_choice = None
		self.updateColourIcon()




##------------------------------------##
##                                    ##
##           QUICK REFERENCE          ##
##                                    ##
##------------------------------------##

class QuickReference(QWidget, Ui_quickReference):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.setWindowFlags(Qt.Window)
		with open(quick_ref_disp) as f:
			self.disp_pane.setHtml(f.read())
		with open(quick_ref_kbd) as f:
			self.kbd_pane.setHtml(f.read())
		with open(quick_ref_mouse) as f:
			self.mouse_pane.setHtml(f.read())
		with open(quick_ref_aliases) as f:
			self.aliases_pane.setHtml(f.read())
		with open(quick_ref_voice) as f:
			self.voice_pane.setHtml(f.read())
		signals.closeNonDockableWindows.connect(self.close)
