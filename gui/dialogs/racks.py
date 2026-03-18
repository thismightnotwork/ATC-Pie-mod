
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

from PyQt5.QtWidgets import QDialog, QMessageBox
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex

from ui.editRackDialog import Ui_editRackDialog
from ui.rackVisibilityDialog import Ui_rackVisibilityDialog

from base.strip import rack_detail, recycled_detail

from gui.misc import RadioKeyEventFilter, signals
from gui.graphics.miscGraphics import coloured_square_icon

from session.config import settings
from session.env import env
from session.models.liveStrips import default_rack_name


# ---------- Constants ----------

# -------------------------------



class RackVisibilityDialog(QDialog, Ui_rackVisibilityDialog):
	def __init__(self, visible_racks, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.table_model = RackVisibilityTableModel(self, visible_racks)
		self.tableView.setModel(self.table_model)
		self.selectAll_button.clicked.connect(lambda: self.table_model.globalSelect(True))
		self.selectNone_button.clicked.connect(lambda: self.table_model.globalSelect(False))
		self.buttonBox.accepted.connect(self.accept)
		self.buttonBox.rejected.connect(self.reject)
	
	def getSelection(self):
		return self.table_model.getSelectedRacks()
		




class RackVisibilityTableModel(QAbstractTableModel):
	def __init__(self, parent, racks):
		QAbstractTableModel.__init__(self, parent)
		self.racks = racks
		self.ticked = len(racks) * [False]
	
	def getSelectedRacks(self):
		return [r for r, v in zip(self.racks, self.ticked) if v]
	
	def globalSelect(self, b):
		self.ticked = len(self.racks) * [b]
		self.dataChanged.emit(self.index(0, 0), self.index(0, len(self.racks)))
	
	# MODEL STUFF
	def rowCount(self, parent=QModelIndex()):
		return len(self.racks)

	def columnCount(self, parent=QModelIndex()):
		return 1
	
	def flags(self, index):
		return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
	
	def headerData(self, section, orientation, role):
		return None

	def data(self, index, role):
		if index.column() == 0:
			row = index.row()
			if role == Qt.DisplayRole:
				return self.racks[row]
			elif role == Qt.CheckStateRole:
				return Qt.Checked if self.ticked[row] else Qt.Unchecked
			elif role == Qt.DecorationRole:
				if self.racks[row] in settings.rack_colours:
					return coloured_square_icon(settings.rack_colours[self.racks[row]], width=24)
	
	def setData(self, index, value, role):
		if index.isValid() and index.column() == 0 and role == Qt.CheckStateRole:
			row = index.row()
			self.ticked[row] = value == Qt.Checked
			return True
		return False


class EditRackDialog(QDialog, Ui_editRackDialog):
	def __init__(self, parent, rack_name):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.deleteRack_info.clear()
		self.installEventFilter(RadioKeyEventFilter(self))
		self.initial_rack_name = rack_name
		self.flagged_for_deletion = False
		self.rackName_edit.setText(self.initial_rack_name)
		self.privateRack_tickBox.setChecked(self.initial_rack_name in settings.private_racks)
		self.pickColour_widget.setChoice(settings.rack_colours.get(rack_name, None))
		if rack_name == default_rack_name:
			self.rackName_edit.setEnabled(False)
			self.collectedStrips_box.setVisible(False)
			self.deleteRack_button.setEnabled(False)
			self.deleteRack_info.setText('Default rack cannot be deleted')
		else:
			self.collectsFrom_edit.setPlainText(
				'\n'.join(atc for atc, rack in settings.ATC_collecting_racks.items() if rack == rack_name))
			self.collectAutoPrintedStrips_tickBox.setChecked(
				settings.auto_print_collecting_rack == self.initial_rack_name)
			self.rackName_edit.selectAll()
			self.deleteRack_button.toggled.connect(self.flagRackForDeletion)
		self.buttonBox.rejected.connect(self.reject)
		self.buttonBox.accepted.connect(self.doOK)

	def flagRackForDeletion(self, toggle):
		if toggle:
			if env.strips.count(lambda s: s.lookup(rack_detail) == self.initial_rack_name) > 0:
				QMessageBox.warning(self, 'Non-empty rack deletion',
									'Rack not empty. Strips will be reracked if deletion confirmed.')
			self.deleteRack_info.setText('Flagged for deletion')
		else:
			self.deleteRack_info.clear()

	def doOK(self):
		if self.deleteRack_button.isChecked():
			for strip in env.strips.listAll():
				if strip.lookup(rack_detail) == self.initial_rack_name:
					strip.writeDetail(recycled_detail, True)
					env.strips.repositionStrip(strip, default_rack_name)
			for atc, rack in list(settings.ATC_collecting_racks.items()):
				if rack == self.initial_rack_name:
					del settings.ATC_collecting_racks[atc]
			if settings.auto_print_collecting_rack == self.initial_rack_name:
				settings.auto_print_collecting_rack = None
			env.strips.removeRack(self.initial_rack_name)
		else:  # rack NOT being deleted
			new_name = self.rackName_edit.text()
			# UPDATE SETTINGS
			if new_name != self.initial_rack_name:  # renaming
				if env.strips.validNewRackName(new_name):
					env.strips.renameRack(self.initial_rack_name, new_name)
				else:
					QMessageBox.critical(self, 'Rack name error', 'Name is reserved or already used.')
					return  # abort
			# private
			if self.initial_rack_name in settings.private_racks:
				settings.private_racks.remove(self.initial_rack_name)
			if self.privateRack_tickBox.isChecked():
				settings.private_racks.add(new_name)
			# colour
			new_colour = self.pickColour_widget.getChoice()
			if self.initial_rack_name in settings.rack_colours:
				del settings.rack_colours[self.initial_rack_name]
			if new_colour is not None:
				settings.rack_colours[new_name] = new_colour
			# collecting racks
			for atc, rack in list(settings.ATC_collecting_racks.items()):
				if rack == self.initial_rack_name:
					del settings.ATC_collecting_racks[atc]
			for atc in self.collectsFrom_edit.toPlainText().split('\n'):
				if atc != '':
					settings.ATC_collecting_racks[atc] = new_name
			if self.collectAutoPrintedStrips_tickBox.isChecked():  # should not be ticked if default rack
				settings.auto_print_collecting_rack = new_name
			elif settings.auto_print_collecting_rack == self.initial_rack_name:
				settings.auto_print_collecting_rack = None  # back to default if box has been unticked
			# DONE
			signals.rackEdited.emit(self.initial_rack_name, new_name)
		self.accept()
