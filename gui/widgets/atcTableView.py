
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
from PyQt5.QtWidgets import QTableView

from session.env import env


# ---------- Constants ----------

# -------------------------------

class AtcTableView(QTableView):
	def __init__(self, parent=None):
		QTableView.__init__(self, parent)
	
	def mouseDoubleClickEvent(self, event):
		index = self.indexAt(event.pos())
		if index.isValid() and event.button() == Qt.LeftButton:
			self.model().itemDoubleClicked(index, event.modifiers() & Qt.ShiftModifier)
			event.accept()
		else:
			QTableView.mouseDoubleClickEvent(self, event)
	
	def dropEvent(self, event):
		env.ATCs.mouse_drop_has_ALT = bool(event.keyboardModifiers() & Qt.AltModifier)
		QTableView.dropEvent(self, event)
		env.ATCs.mouse_drop_has_ALT = False

