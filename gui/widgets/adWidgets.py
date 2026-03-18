
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

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QDialog, QLineEdit, QPushButton, QToolButton, QDialogButtonBox

from base.util import some
from base.nav import Airfield, world_navpoint_db, NavpointError

from session.env import env
from session.config import settings

from gui.misc import signals, IconFile, recognisedValue_lineEdit_styleSheet, unrecognisedValue_lineEdit_styleSheet
from gui.panels.navigator import AirportNavigatorWidget


# ---------- Constants ----------

airportPicker_shortcutToHere = '.'

# -------------------------------


class AirportPicker(QWidget):
	# SIGNALS
	unrecognised = pyqtSignal(str) # Not emitted if an ICAO code is recognised
	recognised = pyqtSignal(Airfield) # Emitted when either set or recognised
	
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.airport_edit = QLineEdit(self)
		self.search_button = QToolButton(self)
		layout = QHBoxLayout(self)
		layout.setSpacing(0)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.addWidget(self.airport_edit)
		layout.addWidget(self.search_button)
		self.airport_edit.setClearButtonEnabled(True)
		self.search_button.setToolTip('Search...')
		self.search_button.setIcon(QIcon(IconFile.button_search))
		self.search_button.setFocusPolicy(Qt.ClickFocus)
		self.setFocusProxy(self.airport_edit)
		self.recognised_airfield = None
		self.search_button.clicked.connect(self.searchAirportByName)
		self.airport_edit.textEdited.connect(self.tryRecognising)
		self.recognised.connect(lambda ad: self.airport_edit.setToolTip(ad.long_name))
		self.unrecognised.connect(lambda: self.airport_edit.setToolTip(''))
	
	def currentText(self):
		return self.airport_edit.text()
	
	def recognisedAirfield(self):
		return self.recognised_airfield
	
	def setEditText(self, txt):
		self.airport_edit.setText(txt)
		self.tryRecognising(txt)
	
	def tryRecognising(self, txt):
		self.recognised_airfield = None
		if txt == airportPicker_shortcutToHere and env.airport_data is not None:
			txt = settings.location_code
		try:
			self.recognise(world_navpoint_db.findAirfield(txt))
		except NavpointError:
			self.airport_edit.setStyleSheet(None if txt == '' else unrecognisedValue_lineEdit_styleSheet)
			self.unrecognised.emit(txt)

	def searchAirportByName(self):
		init = self.currentText() if self.recognised_airfield is None else ''
		dialog = AirportListSearchDialog(self, world_navpoint_db, initNameFilter=init)
		dialog.exec()
		if dialog.result() > 0:
			self.recognise(dialog.selectedAirport())
		self.airport_edit.setFocus()
	
	def recognise(self, ad):
		self.airport_edit.setText(ad.code)
		self.airport_edit.setStyleSheet(recognisedValue_lineEdit_styleSheet)
		self.recognised_airfield = ad
		self.recognised.emit(ad)



class AirportListSearchDialog(QDialog):
	def __init__(self, parent, nav_db, initCodeFilter=None, initNameFilter=None):
		assert initCodeFilter is None or initNameFilter is None
		QDialog.__init__(self, parent)
		self.setWindowTitle('Airport search')
		self.setWindowIcon(QIcon(IconFile.panel_airportList))
		self.navigator = AirportNavigatorWidget(self, nav_db)
		self.button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok, self)
		layout = QVBoxLayout(self)
		layout.addWidget(self.navigator)
		layout.addWidget(self.button_box)
		self.selected_airport = None
		self.navigator.setAndUpdateFilter(initCodeFilter is not None, some(initCodeFilter, some(initNameFilter, '')))
		self.navigator.airportDoubleClicked.connect(self.selectAirport)
		self.button_box.accepted.connect(self.selectAirportFromSelection)
		self.button_box.rejected.connect(self.reject)
	
	def selectAirportFromSelection(self):
		self.selected_airport = self.navigator.selectedAirport()
		if self.selected_airport is not None:
			self.accept()
	
	def selectAirport(self, ad):
		self.selected_airport = ad
		self.accept()
	
	def selectedAirport(self):
		return self.selected_airport



class WorldAirportNavigator(QWidget):
	def __init__(self, parent):
		QWidget.__init__(self, parent)
		self.setWindowFlags(Qt.Window)
		self.setWindowTitle('World airports')
		self.setWindowIcon(QIcon(IconFile.panel_airportList))
		self.navigator = AirportNavigatorWidget(self, world_navpoint_db)
		self.close_button = QPushButton('Close', self)
		layout = QVBoxLayout(self)
		layout.addWidget(self.navigator)
		layout.addWidget(self.close_button)
		self.navigator.airportDoubleClicked.connect(lambda ad: signals.indicatePoint.emit(ad.coordinates))
		self.close_button.clicked.connect(self.hide)
		signals.closeNonDockableWindows.connect(self.close)
	
	def showEvent(self, event):
		self.navigator.setFocus()
