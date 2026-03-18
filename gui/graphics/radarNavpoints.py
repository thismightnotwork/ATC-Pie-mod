
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

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtWidgets import QGraphicsItem
from PyQt5.QtGui import QPen, QBrush, QPolygonF, QTransform

from base.instr import Instruction

from session.config import settings

from gui.actions import mouse_vector_tool_released
from gui.misc import signals
from gui.graphics.miscGraphics import new_pen


# ---------- Constants ----------

# -------------------------------



## Common superclass

class NavpointItem(QGraphicsItem):
	"""
	VIRTUAL. Subclasses must reimplement: boudingRect and paint methods for the icon.
	"""
	def __init__(self, navpoint):
		QGraphicsItem.__init__(self, parent=None)
		self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
		self.setAcceptedMouseButtons(Qt.LeftButton)
		self.navpoint = navpoint
	
	def mousePressEvent(self, event):
		QGraphicsItem.mousePressEvent(self, event)
		if event.button() == Qt.LeftButton:
			self.scene().prevent_mouse_release_deselect = True
			signals.navpointClick.emit(self.navpoint)
			if event.modifiers() & Qt.ShiftModifier: # route modification request
				if not event.modifiers() & Qt.AltModifier: # do not get actions mixed up; add/remove might pop up a dialog
					self.scene().addRemoveRouteNavpoint.emit(self.navpoint)
				event.accept()
			elif event.modifiers() & Qt.AltModifier: # CPDLC "proceed/request direct"
				mouse_vector_tool_released(Instruction(Instruction.VECTOR_DCT, arg=self.navpoint.code), True)
				event.accept()




## Subclasses to use

class NavVORItem(NavpointItem):
	def __init__(self, vor):
		NavpointItem.__init__(self, vor)
	
	def boundingRect(self):
		return QRectF(-10, -8, 20, 16)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['nav_aid']))
		painter.drawEllipse(QPointF(0, 0), .33, .33)
		painter.drawPolygon(QPolygonF([QPointF(-8, 0), QPointF(-3, -6), QPointF(3, -6), QPointF(8, 0), QPointF(3, 6), QPointF(-3, 6)]))
		if self.navpoint.tacan:
			painter.setBrush(QBrush(settings.colours['nav_aid']))
			poly = QPolygonF([QPointF(-3, 6), QPointF(3, 6), QPointF(3, 8), QPointF(-3, 8)])
			rot = QTransform()
			painter.drawPolygon(poly)
			rot.rotate(120)
			painter.drawPolygon(rot.map(poly))
			rot.rotate(120)
			painter.drawPolygon(rot.map(poly))
		elif self.navpoint.dme:
			painter.drawRect(QRectF(-8, -6, 16, 12))


class NavNDBItem(NavpointItem):
	def __init__(self, ndb):
		NavpointItem.__init__(self, ndb)
	
	def boundingRect(self):
		return QRectF(-8, -8, 16, 16)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['nav_aid']))
		painter.drawEllipse(QPointF(0, 0), .33, .33)
		brush = QBrush(Qt.Dense6Pattern)
		brush.setColor(settings.colours['nav_aid'])
		painter.setPen(QPen(Qt.NoPen))
		painter.setBrush(brush)
		painter.drawEllipse(QPointF(0, 0), 7, 7)



class NavFixItem(NavpointItem):
	def __init__(self, fix):
		NavpointItem.__init__(self, fix)
	
	def boundingRect(self):
		return QRectF(-4, -4, 8, 6)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['nav_fix']))
		painter.drawPolygon(QPolygonF([QPointF(-3, 0), QPointF(0, -3), QPointF(3, 0)]))



class RnavItem(NavpointItem):
	def __init__(self, p):
		NavpointItem.__init__(self, p)
	
	def boundingRect(self):
		return QRectF(-3, -3, 6, 6)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['nav_RNAV']))
		painter.setBrush(QBrush(painter.pen().color()))
		painter.drawEllipse(QPointF(0, 0), .5, .5)		



class NavAirfieldItem(NavpointItem):
	def __init__(self, airfield):
		NavpointItem.__init__(self, airfield)
	
	def boundingRect(self):
		return QRectF(-6, -6, 12, 12)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['nav_airfield']))
		painter.drawEllipse(-4, -4, 8, 8)
	
