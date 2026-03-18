
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

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtGui import QTransform


# ---------- Constants ----------

# -------------------------------


class RadarScopeView(QGraphicsView):
	zoom_signal = pyqtSignal(bool)
	
	def __init__(self, parent):
		QGraphicsView.__init__(self, parent)
		self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
		self._pan_from = None
	
	def setScaleFactor(self, sc):
		tm = QTransform.fromScale(sc, sc)
		tm.rotate(self.scene().currentRotation())
		self.setTransform(tm)
	
	
	## MOUSE

	def wheelEvent(self, event):
		if not self.scene().lock_pan_zoom:
			self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
			self.zoom_signal.emit(event.angleDelta().y() > 0)
	
	def mousePressEvent(self, event):
		QGraphicsView.mousePressEvent(self, event)
		if not event.isAccepted() and not self.scene().lock_pan_zoom \
				and event.button() == Qt.LeftButton and not event.modifiers() & Qt.ShiftModifier: # Shift key handled in scene
			self._pan_from = event.pos()
			event.accept()

	def mouseMoveEvent(self, event):
		if self._pan_from is None:
			QGraphicsView.mouseMoveEvent(self, event)
		else:
			if not self.scene().prevent_mouse_release_deselect: # yet
				self.setCursor(Qt.ClosedHandCursor)
				self.scene().prevent_mouse_release_deselect = True
			self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - event.x() + self._pan_from.x())
			self.verticalScrollBar().setValue(self.verticalScrollBar().value() - event.y() + self._pan_from.y())
			self._pan_from = event.pos()
			event.accept()

	def mouseReleaseEvent(self, event):
		self._pan_from = None
		self.setCursor(Qt.ArrowCursor)
		QGraphicsView.mouseReleaseEvent(self, event)

	def moveToShow(self, coords):
		#OPTION: self.ensureVisible(rect, xmargin, ymargin)
		#OPTION: self.​fitInView(rect)
		self.centerOn(coords.toQPointF())


