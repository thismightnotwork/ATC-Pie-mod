
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

from PyQt5.QtWidgets import QDialog
from PyQt5.QtCore import Qt, QAbstractTableModel

from ui.routeDialog import Ui_routeDialog

from base.nav import Navpoint
from base.db import cruise_speed
from base.coords import dist_str
from base.params import TTF_str

from gui.graphics.worldMap import RouteScene
from gui.misc import RadioKeyEventFilter


# ---------- Constants ----------

# -------------------------------



class RouteTableModel(QAbstractTableModel):
	# STATIC:
	column_headers = ['Leg', 'Start', 'Leg spec', 'Waypoint', 'Initial hdg', 'Distance', 'Final hdg']

	def __init__(self, route, parent):
		QAbstractTableModel.__init__(self, parent)
		self.route = route
	
	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return RouteTableModel.column_headers[section]

	def rowCount(self, parent=None):
		return self.route.legCount()

	def columnCount(self, parent=None):
		return len(RouteTableModel.column_headers)

	def data(self, index, role):
		row = index.row()
		col = index.column()
		if role == Qt.DisplayRole:
			if col == 0:
				return str(row + 1)
			elif col == 1:
				if row == 0:
					if self.route.knownOriginNavpoint() is not None:
						return self.route.knownOriginNavpoint().code
				else:
					return self.route.waypoint(row - 1).code
			elif col == 2:
				return ' '.join(self.route.legSpec(row))
			elif col == 3:
				return self.route.waypoint(row).code
			else:
				wp = self.route.waypoint(row).coordinates
				prev = self.route.originCoords() if row == 0 else self.route.waypoint(row - 1).coordinates
				if col == 4:
					return prev.headingTo(wp).read() + '°'
				elif col == 5:
					return dist_str(prev.distanceTo(wp))
				elif col == 6:
					return wp.headingFrom(prev).read() + '°'
				
		elif role == Qt.ToolTipRole:
			if col == 1:
				if row == 0:
					if self.route.knownOriginNavpoint() is not None:
						return Navpoint.tstr(self.route.knownOriginNavpoint().type)
				else:
					return Navpoint.tstr(self.route.waypoint(row - 1).type)
			elif col == 3:
				return Navpoint.tstr(self.route.waypoint(row).type)
			elif col == 4 or col == 6:
				return 'True heading'





class RouteDialog(QDialog, Ui_routeDialog):
	def __init__(self, route, speedHint=None, acftHint=None, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		origin_navpoint = route.knownOriginNavpoint() # CAUTION: unlike destination, this may be None
		if origin_navpoint is None:
			self.depICAO_info.clear()
			self.depAD_info.setText(str(route.originCoords()))
		else:
			self.depICAO_info.setText(origin_navpoint.code)
			self.depAD_info.setText(origin_navpoint.long_name)
		self.arrICAO_info.setText(route.destinationNavpoint().code)
		self.arrAD_info.setText(route.destinationNavpoint().long_name)
		self.route_length = route.totalDistance()
		self.totalRouteDistance_info.setText(dist_str(self.route_length))
		self.route_scene = RouteScene(route, parent=self)
		self.route_view.setScene(self.route_scene)
		self.route_table.setModel(RouteTableModel(route, self))
		for col in [0, 1, 3, 4, 6]:
			self.route_table.resizeColumnToContents(col)
		speedHint_OK = speedHint is not None and self.speed_edit.minimum() <= speedHint.kt() <= self.speed_edit.maximum()
		if speedHint_OK:
			self.speed_edit.setSpeedValue(speedHint)
		if acftHint is not None:
			self.acftType_select.setEditText(acftHint)
			if not speedHint_OK:
				self.EETfromACFT_radioButton.setChecked(True)
		self.updateEET()
		self.route_table.selectionModel().selectionChanged.connect(self.legSelectionChanged)
		self.OK_button.clicked.connect(self.accept)
		self.EETfromSpeed_radioButton.toggled.connect(self.updateEET)
		self.EETfromACFT_radioButton.toggled.connect(self.updateEET)
		self.speed_edit.valueChanged.connect(self.updateEET)
		self.acftType_select.editTextChanged.connect(self.updateEET)
	
	def legSelectionChanged(self):
		self.route_scene.setSelectedLegs([index.row() for index in self.route_table.selectionModel().selectedRows()])
	
	def updateEET(self):
		if self.EETfromSpeed_radioButton.isChecked():
			self.EET_info.setText(TTF_str(self.route_length, self.speed_edit.speedValue()))
		elif self.EETfromACFT_radioButton.isChecked():
			crspd = cruise_speed(self.acftType_select.getAircraftType())
			if crspd is None:
				self.EET_info.setText('(unknown ACFT cruise speed)')
			else:
				try:
					self.EET_info.setText(TTF_str(self.route_length, crspd))
				except ValueError:
					self.EET_info.setText('(speed too low)')

