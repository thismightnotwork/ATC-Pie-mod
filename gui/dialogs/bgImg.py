
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
from PyQt5.QtGui import QTransform

from ui.positionDrawingDialog import Ui_positionDrawingDialog

from base.util import m2NM


# ---------- Constants ----------

# -------------------------------

class PositionBgImgDialog(QDialog, Ui_positionDrawingDialog):
	def __init__(self, graphics_items, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.items = graphics_items
		self.updateDisplay()
		self.moveUp_button.clicked.connect(lambda: self.moveImages(0, -1))
		self.moveDown_button.clicked.connect(lambda: self.moveImages(0, 1))
		self.moveLeft_button.clicked.connect(lambda: self.moveImages(-1, 0))
		self.moveRight_button.clicked.connect(lambda: self.moveImages(1, 0))
		self.increaseWidth_button.clicked.connect(lambda: self.scaleImages(1, 0))
		self.reduceWidth_button.clicked.connect(lambda: self.scaleImages(-1, 0))
		self.increaseHeight_button.clicked.connect(lambda: self.scaleImages(0, 1))
		self.reduceHeight_button.clicked.connect(lambda: self.scaleImages(0, -1))
		self.tuningStep_edit.valueChanged.connect(self.updateNM)
		self.tuningStep_edit.setValue(5000) # in metres
	
	def updateDisplay(self):
		if len(self.items) == 0:
			txt = 'Make at least one image visible!'
		else:
			txt = ''
			for item in self.items:
				nw = item.NWcoords()
				se = item.SEcoords()
				txt += '\n%s\n' % item.title
				txt += 'NW: %s\n' % nw.toString()
				txt += 'SE: %s\n' % se.toString()
		self.central_text_area.setPlainText(txt)

	def updateNM(self):
		self.stepNM_info.setText('%.2f NM' % (m2NM * self.tuningStep_edit.value()))
	
	def moveImages(self, kx, ky):
		for item in self.items:
			item.moveBy(kx * m2NM * self.tuningStep_edit.value(), ky * m2NM * self.tuningStep_edit.value())
		self.updateDisplay()
	
	def scaleImages(self, kx, ky):
		for item in self.items:
			rect = item.boundingRect()
			scale = QTransform.fromScale(1 + kx * m2NM * self.tuningStep_edit.value() / rect.width(),
										1 + ky * m2NM * self.tuningStep_edit.value() / rect.height())
			item.setTransform(scale, combine=True)
		self.updateDisplay()
