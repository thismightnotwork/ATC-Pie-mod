
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
from PyQt5.QtWidgets import QWidget, QStackedWidget

from gui.misc import RadioKeyEventFilter, signals


# ---------- Constants ----------

# -------------------------------

class WorkspaceDockablePanel(QWidget):
	titleChanged = pyqtSignal(str)
	closing = pyqtSignal()

	def __init__(self, defaultTitle=None):
		"""
		Inherit from this class to make a panel dockable in the workspace area.
		Specifying a default title makes the panel renamable.
		"""
		QWidget.__init__(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.default_title = defaultTitle  # not renamable if None
		signals.mainWindowClosing.connect(self.close)

	def defaultTitle(self):
		return self.default_title

	def flashStyleSheet(self):
		return 'QWidget { background: yellow }'

	def stateSave(self):
		return {}

	def restoreState(self, saved_state):
		return None

	def setWindowTitle(self, title):
		QWidget.setWindowTitle(self, title)
		self.titleChanged.emit(title)

	def closeEvent(self, event):
		self.closing.emit()
		QWidget.closeEvent(self, event)



class WorkspaceArea(QStackedWidget):
	"""
	Actually not used as a stack; just as a placeholder to dock & remove a widget.
	Moreover, it hides when empty to allow free resizing around it.
	"""
	def __init__(self, parent):
		QStackedWidget.__init__(self, parent)
		self.saved_non_docked_geometry = None
		self.hide()

	def currentPanel(self):
		return self.currentWidget()

	def setCurrentPanel(self, panel):
		current = self.currentWidget()
		if current is not panel:
			if current is not None: # pop out current
				self.removeWidget(current)
				current.setParent(None)
				current.setGeometry(current.saved_non_docked_geometry)
				current.show()
			if panel is None:
				self.hide()
			else:
				self.show()
				panel.saved_non_docked_geometry = panel.geometry()
				panel.hide() # in case it was popped out
				self.addWidget(panel)
				self.setCurrentWidget(panel)
