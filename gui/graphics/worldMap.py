
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

from PyQt5.QtWidgets import QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem, QGraphicsView
from PyQt5.QtGui import QPixmap, QBrush, QPen, QTransform
from PyQt5.QtCore import Qt, QPointF, QRectF

from base.coords import breakUpLine

from gui.graphics.miscGraphics import new_pen


# ---------- Constants ----------

world_map_pixmap = 'resources/pixmap/worldMap-equirectProj.png'
world_map_wheel_zoom_factor = 1.25

route_colour_standard = Qt.green
route_colour_selected = Qt.magenta
route_colour_departure = Qt.yellow
route_colour_arrival = Qt.red
route_leg_breakUp_length = 20 # NM

# -------------------------------


def world_split(p1, p2):
	thdg = p1.headingTo(p2).trueAngle()
	return p2.lat < p1.lat and (thdg <= 90 or thdg >= 270) or p2.lat > p1.lat and 90 <= thdg <= 270 \
		or p2.lon < p1.lon and 0 <= thdg <= 180 or p2.lon > p1.lon and thdg >= 180


class RouteLegItem(QGraphicsItem):
	def __init__(self, p1, p2, parent=None):
		QGraphicsItem.__init__(self, parent)
		self.setAcceptedMouseButtons(Qt.NoButton) # is selectable but only by explicit flag setting; no mouseclick here
		self.setFlag(QGraphicsItem.ItemIsSelectable, True)
		self.segments = breakUpLine(p1, p2, segmentLength=route_leg_breakUp_length)
	
	def boundingRect(self):
		return self.scene().mapBoundingRect()

	def paint(self, painter, option, widget):
		colour = route_colour_selected if self.isSelected() else route_colour_standard
		painter.setPen(new_pen(colour))
		for p1, p2 in self.segments:
			if not world_split(p1, p2):
				painter.drawLine(self.scene().scenePoint(p1), self.scene().scenePoint(p2))



class RoutePointItem(QGraphicsItem):
	def __init__(self, parent=None):
		QGraphicsItem.__init__(self, parent)
		self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
		self.setAcceptedMouseButtons(Qt.NoButton) # is selectable but only by explicit flag setting; no mouseclick here
		self.setFlag(QGraphicsItem.ItemIsSelectable, True)
	
	def boundingRect(self):
		return QRectF(-5, -5, 10, 10)

	def paint(self, painter, option, widget):
		painter.setPen(QPen(Qt.NoPen))
		painter.setBrush(QBrush(route_colour_selected if self.isSelected() else route_colour_standard))
		painter.drawEllipse(QPointF(0, 0), 4, 4)




class PointCircleItem(QGraphicsItem):
	def __init__(self, radius, colour, parent=None):
		QGraphicsItem.__init__(self, parent)
		self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
		self.setAcceptedMouseButtons(Qt.NoButton) # is selectable but only by explicit flag setting; no mouseclick here
		self.setFlag(QGraphicsItem.ItemIsSelectable, True)
		self.radius = radius
		self.colour = colour
	
	def boundingRect(self):
		return QRectF(-self.radius - .5, -self.radius - .5, 2 * self.radius + 1, 2 * self.radius + 1)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(self.colour, width=2))
		painter.drawEllipse(QPointF(0, 0), self.radius, self.radius)





class WorldMapScene(QGraphicsScene):
	def __init__(self, parent):
		QGraphicsScene.__init__(self, parent)
		background_map_item = QGraphicsPixmapItem(QPixmap(world_map_pixmap))
		rect = background_map_item.boundingRect()
		self._lon_factor = rect.width() / 360
		self._lat_factor = -rect.height() / 180
		background_map_item.setOffset(-rect.width() / 2, -rect.height() / 2)
		self.map_bounding_rect = background_map_item.boundingRect()
		self.addItem(background_map_item)

	def mapBoundingRect(self):
		return self.map_bounding_rect

	def scenePoint(self, earthCoords):
		return QPointF(self._lon_factor * earthCoords.lon, self._lat_factor * earthCoords.lat)




class SingleWorldPointScene(WorldMapScene):
	def __init__(self, parent):
		WorldMapScene.__init__(self, parent)
		self.point_item = PointCircleItem(4, route_colour_selected)
		self.point_item.setVisible(False)
		self.addItem(self.point_item)

	def showPoint(self, world_coords):
		self.point_item.setPos(self.scenePoint(world_coords))
		self.point_item.setVisible(True)

	def clearPoint(self):
		self.point_item.setVisible(False)



class RouteScene(WorldMapScene):
	def __init__(self, route, parent):
		WorldMapScene.__init__(self, parent)
		self.route_coords = route.routePointCoords() # len == legCount + 1
		self.point_items = []
		for p in self.route_coords:
			item = RoutePointItem()
			item.setPos(self.scenePoint(p))
			self.point_items.append(item)
			self.addItem(item)
		item = PointCircleItem(3, route_colour_departure)
		item.setPos(self.scenePoint(self.route_coords[0]))
		self.addItem(item)
		item = PointCircleItem(5, route_colour_arrival)
		item.setPos(self.scenePoint(self.route_coords[-1]))
		self.addItem(item)
		self.leg_items = []
		for i in range(route.legCount()):
			item = RouteLegItem(self.route_coords[i], self.route_coords[i + 1])
			self.leg_items.append(item)
			self.addItem(item)
	
	def setSelectedLegs(self, lst):
		for i in range(len(self.leg_items)):
			self.leg_items[i].setSelected(i in lst)
			self.point_items[i + 1].setSelected(i in lst or i + 1 in lst)




class WorldMapView(QGraphicsView):
	def __init__(self, parent):
		QGraphicsView.__init__(self, parent)
		self.scale = .25
		self.setTransform(QTransform.fromScale(self.scale, self.scale))

	def wheelEvent(self, event):
		if event.angleDelta().y() > 0:
			self.scale *= world_map_wheel_zoom_factor
		else:
			self.scale /= world_map_wheel_zoom_factor
		self.setTransform(QTransform.fromScale(self.scale, self.scale))
