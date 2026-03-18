
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

from PyQt5.QtWidgets import QTableView
from PyQt5.QtCore import Qt

from session.env import env

from gui.misc import signals, selection


# ---------- Constants ----------

# -------------------------------



class FlightPlanTableView(QTableView):
	def __init__(self, parent=None):
		QTableView.__init__(self, parent)
		signals.selectionChanged.connect(self.updateSelection)
		self.doubleClicked.connect(self.editSelectedFPL)
	
	def updateSelection(self):
		if selection.fpl is None:
			self.clearSelection()
		else:
			try:
				src_index = env.FPLs.sourceIndex(selection.fpl)
				self.selectRow(self.model().mapFromSource(self.model().sourceModel().index(src_index, 0)).row())
			except StopIteration:
				self.clearSelection()
	
	def mousePressEvent(self, event):
		QTableView.mousePressEvent(self, event)
		try:
			proxy_index = self.selectedIndexes()[0]
		except IndexError:
			return
		fpl = env.FPLs.FPL(self.model().mapToSource(proxy_index).row())
		if event.button() == Qt.MiddleButton:
			if event.modifiers() & Qt.ShiftModifier: # Trying to unlink
				if selection.strip is not None and selection.strip.linkedFPL() is fpl:
					selection.strip.linkFPL(None)
					selection.selectStrip(selection.strip)
				else:
					signals.selectionChanged.emit() # revert selection
			else: # Trying to link
				if selection.strip is not None and selection.strip.linkedFPL() is None and env.linkedStrip(fpl) is None:
					selection.strip.linkFPL(fpl)
					selection.selectFPL(fpl)
				else:
					signals.selectionChanged.emit() # revert selection
		else:
			selection.selectFPL(fpl)
	
	def editSelectedFPL(self):
		signals.fplEditRequest.emit(selection.fpl)
		


