
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

from math import degrees, atan

from PyQt5.QtWidgets import QWidget, QDialog
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QIcon, QColor

from ui.adSfcUseDialog import Ui_adSfcUseDialog
from ui.rwyParamsWidget import Ui_rwyParamsWidget
from ui.helipadParamsWidget import Ui_helipadParamsWidget

from base.params import Heading

from session.env import env

from gui.misc import signals, IconFile, RadioKeyEventFilter
from gui.graphics.miscGraphics import coloured_square_icon


# ---------- Constants ----------

# -------------------------------



# ******* SAVED PARAMETERS (location settings) *******

class RunwayParametersWidget(QWidget, Ui_rwyParamsWidget):
	def __init__(self, parent, rwy):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.runway = rwy
		title = 'Runway %s' % self.runway.name
		if self.runway.ILS_cat is not None:
			title += ' (%s)' % self.runway.ILS_cat
		self.rwyName_info.setText(title)
		self.FPA_edit.setValue(self.runway.param_FPA)
		self.updateFpaDegInfo()
		self.appLineLength_edit.setValue(self.runway.param_disp_line_length)
		self.acftCat_props_tickBox.setChecked(self.runway.param_acceptProps)
		self.acftCat_turboprops_tickBox.setChecked(self.runway.param_acceptTurboprops)
		self.acftCat_jets_tickBox.setChecked(self.runway.param_acceptJets)
		self.acftCat_heavy_tickBox.setChecked(self.runway.param_acceptHeavy)
		if self.runway.hasILS():
			self.FPA_edit.setEnabled(False)
			self.FPA_edit.setToolTip('Fixed by ILS glide slope')
		else:
			self.FPA_edit.valueChanged.connect(self.updateFpaDegInfo)
	
	def updateFpaDegInfo(self):
		self.FPA_deg_info.setText(' = %.1f°' % degrees(atan(self.FPA_edit.value() / 100)))
	
	def applyParams(self):
		self.runway.param_FPA = self.FPA_edit.value()
		self.runway.param_disp_line_length = self.appLineLength_edit.value()
		self.runway.param_acceptProps = self.acftCat_props_tickBox.isChecked()
		self.runway.param_acceptTurboprops = self.acftCat_turboprops_tickBox.isChecked()
		self.runway.param_acceptJets = self.acftCat_jets_tickBox.isChecked()
		self.runway.param_acceptHeavy = self.acftCat_heavy_tickBox.isChecked()



class HelipadParametersWidget(QWidget, Ui_helipadParamsWidget):
	def __init__(self, parent, helipad):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.helipad = helipad
		self.helipadName_info.setText('Helipad %s' % self.helipad.name)
		self.preferredDepCourse_edit.setValue(self.helipad.param_preferred_DEP_course.magneticAngle())

	def applyParams(self):
		self.helipad.param_preferred_DEP_course = Heading(self.preferredDepCourse_edit.value(), False)





# ******* RUNWAY/HELIPAD USE *******

class AdSfcUseDialog(QDialog, Ui_adSfcUseDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.setWindowIcon(QIcon(IconFile.action_adSfcUse))
		self.rwy_table_model = RunwayUseTableModel(self, ([] if env.airport_data is None else env.airport_data.directionalRunways()))
		self.hpad_table_model = HelipadUseTableModel(self, ([] if env.airport_data is None else env.airport_data.helipads()))
		self.rwyUse_tableView.setModel(self.rwy_table_model)
		self.helipadUse_tableView.setModel(self.hpad_table_model)
		self.rwyUse_box.setVisible(self.rwy_table_model.columnCount() != 0)
		self.helipadUse_box.setVisible(self.hpad_table_model.columnCount() != 0)
		for i in range(self.rwy_table_model.columnCount()):
			self.rwyUse_tableView.resizeColumnToContents(i)
		for i in range(self.hpad_table_model.columnCount()):
			self.helipadUse_tableView.resizeColumnToContents(i)
		self.avoidOppositeRunways_tickBox.toggled.connect(self.rwy_table_model.setAvoidOppositeRunwayUse)
		self.buttonBox.accepted.connect(self.ok)
		self.buttonBox.rejected.connect(self.reject)
	
	def ok(self):
		self.rwy_table_model.applyChoices()
		self.hpad_table_model.applyChoices()
		signals.adSfcUseChanged.emit()
		self.accept()





class RunwayUseTableModel(QAbstractTableModel):
	column_headers = ['RWY', 'DEP', 'LDG', 'Wind']

	def __init__(self, parent, runways):
		QAbstractTableModel.__init__(self, parent)
		self.runways = runways
		self.deplst = [rwy.use_for_departures for rwy in runways]
		self.arrlst = [rwy.use_for_arrivals for rwy in runways]
		self.unselect_opposite_runways = True
	
	def setAvoidOppositeRunwayUse(self, b):
		self.unselect_opposite_runways = b
		if b:
			for row in range(self.rowCount()):
				if self.deplst[row] or self.arrlst[row]:
					self._unselectOppositeRow(row)
	
	def _unselectOppositeRow(self, row):
		opprwy = self.runways[row].opposite().name
		opprow = next(i for i, r in enumerate(self.runways) if r.name == opprwy)
		self.deplst[opprow] = self.arrlst[opprow] = False
		self.dataChanged.emit(self.index(opprow, 1), self.index(opprow, 2))
	
	def applyChoices(self):
		for i, rwy in enumerate(self.runways):
			rwy.use_for_departures = self.deplst[i]
			rwy.use_for_arrivals = self.arrlst[i]
	
	# MODEL STUFF
	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.runways)

	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(RunwayUseTableModel.column_headers)
	
	def flags(self, index):
		flags = Qt.ItemIsEnabled
		if index.isValid() and index.column() in [1, 2]:
			flags |= Qt.ItemIsUserCheckable
		return flags
	
	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return RunwayUseTableModel.column_headers[section]

	def data(self, index, role):
		row = index.row()
		col = index.column()
		if col == 0: # RWY name
			if role == Qt.DisplayRole:
				return self.runways[row].name
		elif col == 1: # DEP tick box
			if role == Qt.CheckStateRole:
				return Qt.Checked if self.deplst[row] else Qt.Unchecked
		elif col == 2: # LDG tick box
			if role == Qt.CheckStateRole:
				return Qt.Checked if self.arrlst[row] else Qt.Unchecked
		elif col == 3: # Wind stuff
			rwy = self.runways[row]
			wind_diff = env.RWD(rwy.orientation().opposite())
			if role == Qt.DisplayRole:
				return '' if wind_diff is None else '%+d°' % wind_diff
			elif role == Qt.DecorationRole:
				w = env.primaryWeather()
				if wind_diff is None and w is not None and w.mainWind() is not None:
					wind_diff = 0 # allows a green icon for VRB wind
				if wind_diff is not None:
					k = int(255/90 * abs(wind_diff))
					red = min(221, k)
					green = min(221, 510 - k)
					return coloured_square_icon(QColor(red, green, 0), width=24)
	
	def setData(self, index, value, role):
		col = index.column()
		if index.isValid() and (col == 1 or col == 2) and role == Qt.CheckStateRole:
			row = index.row()
			lst = self.deplst if col == 1 else self.arrlst
			lst[row] = value == Qt.Checked
			if self.unselect_opposite_runways and lst[row]:
				self._unselectOppositeRow(row)
			return True
		return False



class HelipadUseTableModel(QAbstractTableModel):
	def __init__(self, parent, helipads):
		QAbstractTableModel.__init__(self, parent)
		self.helipads = helipads
		self.ticklst = [hpad.use_for_departures or hpad.use_for_arrivals for hpad in helipads]

	def applyChoices(self):
		for i, hpad in enumerate(self.helipads):
			hpad.use_for_departures = hpad.use_for_arrivals = self.ticklst[i]

	# MODEL STUFF
	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else 1

	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.helipads)

	def flags(self, index):
		return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable

	def data(self, index, role):
		if index.isValid() and index.row() == 0: # only row
			idx = index.column()
			if role == Qt.DisplayRole:
				return self.helipads[idx].name
			elif role == Qt.CheckStateRole:
				return Qt.Checked if self.ticklst[idx] else Qt.Unchecked

	def setData(self, index, value, role):
		if index.isValid() and index.row() == 0 and role == Qt.CheckStateRole:
			self.ticklst[index.column()] = value == Qt.Checked
			return True
		return False
