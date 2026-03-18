
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

from PyQt5.QtWidgets import QWidget
from ui.notepadPanel import Ui_notepadPanel
from session.config import settings


# ---------- Constants ----------

# -------------------------------

class NotepadPanel(QWidget, Ui_notepadPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.localNotes_textEdit.setPlainText(settings.local_notes)
		self.generalNotes_textEdit.setPlainText(settings.general_notes)
		self.localNotes_textEdit.textChanged.connect(self.saveLocalNotes)
		self.generalNotes_textEdit.textChanged.connect(self.saveGeneralNotes)
	
	def saveGeneralNotes(self):
		settings.general_notes = self.generalNotes_textEdit.toPlainText()
	
	def saveLocalNotes(self):
		settings.local_notes = self.localNotes_textEdit.toPlainText()
