
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

from math import radians, tan, atan2

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsItemGroup, QGraphicsRectItem
from PyQt5.QtGui import QPen, QBrush, QConicalGradient, QPixmap, QVector2D, QTransform, QPolygonF, QPainterPath

from base.strip import runway_box_detail
from base.util import pop_one, m2NM, m2ft

from session.config import settings
from session.env import env

from ext.xplane import is_paved_surface

from gui.misc import signals
from gui.graphics.miscGraphics import new_pen, MouseOverLabelledItem


# ---------- Constants ----------

slope_tick_amsl_step = 1000 # ft
slope_tick_spacing = .06 # NM
LOC_line_RWY_sep_dist = .1 # NM
intercept_cone_half_angle = 10 # degrees
tower_pixmap = 'resources/pixmap/control-TWR.png'
tower_width = .03
windsock_pixmap = 'resources/pixmap/windsock.png'
windsock_width = .03
TWY_line_margin = .0125

# -------------------------------



# ================================================ #

#                     RUNWAYS                      #

# ================================================ #


runway_border_colours = {
	0: 'AD_runway',
	1: 'RWY_reserved',
	2: 'RWY_incursion'
}


class RunwayItem(QGraphicsItem):
	"""
	Draws a bidir runway from a base runway, with both RWY numbers at threshold
	"""
	def __init__(self, ad_data, physical_index):
		QGraphicsItem.__init__(self, parent=None)
		self.physical_location = ad_data.navpoint.code
		self.physical_runway_index = physical_index
		self.base_rwy, self.opposite_runway = ad_data.physicalRunway(physical_index)
		width_metres, surface = ad_data.physicalRunwayData(physical_index)
		self.width = m2NM * width_metres
		self.paved = is_paved_surface(surface)
		self.occupation_indication = 0
		thr = self.base_rwy.threshold().toRadarCoords()
		self.length = thr.distanceTo(self.opposite_runway.threshold().toRadarCoords())
		self.label1 = RunwayNameItem(self.base_rwy.name, self)
		self.label1.setPos(0, 0)
		self.label2 = RunwayNameItem(self.opposite_runway.name, self)
		self.label2.setPos(0, -self.length)
		self.appGuide_item1 = FinalApproachGuideItem(self.base_rwy, self) # CAUTION: accessed from outside of class
		self.appGuide_item2 = FinalApproachGuideItem(self.opposite_runway, self) # CAUTION: accessed from outside of class
		self.appGuide_item2.setPos(0, -self.length)
		item_rot = self.base_rwy.orientation().trueAngle()
		if self.base_rwy.LOC_bearing is not None:
			self.appGuide_item1.setRotation(self.base_rwy.LOC_bearing.trueAngle() - item_rot)
		if self.opposite_runway.LOC_bearing is None:
			self.appGuide_item2.setRotation(180)
		else:
			self.appGuide_item2.setRotation(self.opposite_runway.LOC_bearing.trueAngle() - item_rot)
		self.label1.setRotation(item_rot)
		self.label2.setRotation(item_rot + 180)
		self.rect = QRectF(-self.width / 2, -self.length, self.width, self.length)
		self.setPos(thr.toQPointF())
		self.setRotation(item_rot)
		self.setAcceptHoverEvents(True)

	def updateBorders(self):
		self.occupation_indication = 0
		if self.physical_location == settings.location_code:
			try:
				boxed_strip = env.strips.findStrip(lambda strip: strip.lookup(runway_box_detail) == self.physical_runway_index)
				self.occupation_indication = 1
			except StopIteration: # no strip boxed on this runway
				boxed_strip = None
			if settings.monitor_runway_occupation:
				occ = env.radar.runwayOccupation(self.physical_runway_index)
				if len(occ) >= 2 or len(occ) == 1 and boxed_strip is None:
					self.occupation_indication = 2
				elif len(occ) == 1: # one traffic on RWY and runway is reserved
					acft = occ[0]
					boxed_link = boxed_strip.linkedAircraft() # NB: can be None
					if not (boxed_link is None and env.linkedStrip(acft) is None or boxed_link is acft):
						self.occupation_indication = 2
		self.setZValue(self.occupation_indication)
		self.update(self.rect)
	
	def updateNumbersVisibility(self):
		forced = self.scene().runway_names_always_visible
		self.label1.setVisible(forced or self.base_rwy.inUse())
		self.label2.setVisible(forced or self.opposite_runway.inUse())

	def updateNumbersRotation(self):
		rot = self.base_rwy.orientation().trueAngle() + self.scene().currentRotation()
		self.label1.setRotation(rot)
		self.label2.setRotation(rot + 180)
	
	def rwyAppGuideItem(self, rwy):
		if self.base_rwy.name == rwy:
			return self.appGuide_item1
		elif self.opposite_runway.name == rwy:
			return self.appGuide_item2
		else:
			return None
	
	def boundingRect(self):
		return self.rect

	def paint(self, painter, option, widget):
		# 0,0 is threshold of first DirRunway
		col = runway_border_colours[self.occupation_indication]
		w = 0 if self.occupation_indication == 0 else 3
		painter.setPen(new_pen(settings.colours[col], width=w))
		if self.paved:
			painter.setBrush(QBrush(settings.colours['AD_runway']))
		painter.drawRect(self.rect)
	
	## MOUSE HOVER
	
	def hoverEnterEvent(self, event):
		self.label1.setVisible(True)
		self.label2.setVisible(True)
	
	def hoverLeaveEvent(self, event):
		self.updateNumbersVisibility()





class HelipadItem(QGraphicsItem):
	def __init__(self, helipad):
		QGraphicsItem.__init__(self, parent=None)
		self.helipad = helipad
		self.l = m2NM * self.helipad.length
		self.w = m2NM * self.helipad.width
		self.paved = is_paved_surface(self.helipad.surface)
		self.label = RunwayNameItem(self.helipad.name, self)
		self.rect = QRectF(-self.w / 2, -self.l / 2, self.w, self.l)
		self.setRotation(self.helipad.orientation.trueAngle())
		self.setPos(self.helipad.centre.toQPointF())
		self.label.setPos(0, self.l / 2)
		self.label.setRotation(self.helipad.orientation.trueAngle())
		self.setAcceptHoverEvents(True)
	
	def boundingRect(self):
		return self.rect

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['AD_runway']))
		if self.paved:
			painter.setBrush(QBrush(settings.colours['AD_runway']))
		painter.drawRect(self.rect)
	
	def updateNumbersVisibility(self):
		self.label.setVisible(self.scene().runway_names_always_visible)

	def updateNumbersRotation(self):
		self.label.setRotation(self.helipad.orientation.trueAngle() + self.scene().currentRotation())
	
	## MOUSE HOVER
	
	def hoverEnterEvent(self, event):
		self.label.setVisible(True)
	
	def hoverLeaveEvent(self, event):
		self.updateNumbersVisibility()






class RunwayNameItem(QGraphicsItem):
	brect = QRectF(-15, 0, 30, 20) #STYLE programmatic text bounding rect
	
	# also used to label helipads
	# 0,0 is middle of top of text
	def __init__(self, text, parentItem):
		QGraphicsItem.__init__(self, parentItem)
		self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
		self.text = text
	
	def boundingRect(self):
		return RunwayNameItem.brect

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['AD_runway']))
		painter.drawText(RunwayNameItem.brect, Qt.AlignHCenter | Qt.AlignTop, self.text)





class FinalApproachGuideItem(QGraphicsItem):
	"""
	Draws the final approach guide (centre line, LOC cone, GS altitude marks)
	"""
	def __init__(self, runway, parentItem):
		QGraphicsItem.__init__(self, parentItem)
		self.runway = runway
		self.updateFromSettings() # CAUTION: creates a few attributes
		self.draw_OM = None if runway.OM_pos is None else runway.threshold().distanceTo(runway.OM_pos)
		self.draw_MM = None if runway.MM_pos is None else runway.threshold().distanceTo(runway.MM_pos)
		self.draw_IM = None if runway.IM_pos is None else runway.threshold().distanceTo(runway.IM_pos)
		self.setVisible(False)
	
	def updateFromSettings(self):
		self.prepareGeometryChange()
		self.slope_fact = m2ft * self.runway.param_FPA / 100 / m2NM
		self.dthr_NM = m2NM * self.runway.dthr
		dthr_elev = env.elevation(self.runway.touchDownPoint())
		tick_min_alt = dthr_elev + self.slope_fact * (self.dthr_NM + 2 * LOC_line_RWY_sep_dist)
		self.GS_init_step = int(tick_min_alt / slope_tick_amsl_step) + 1
		self.GS_init_dist = (self.GS_init_step * slope_tick_amsl_step - dthr_elev) / self.slope_fact
		self.GS_step_dist = slope_tick_amsl_step / self.slope_fact
		if self.runway.LOC_range is None:
			self.item_ymax = self.runway.param_disp_line_length
			self.draw_cone_half_width = self.draw_GS_up_to = 0
		else: # RWY has a LOC
			self.item_ymax = max(self.runway.LOC_range, self.runway.param_disp_line_length)
			self.draw_cone_half_width = self.runway.LOC_range * tan(radians(intercept_cone_half_angle))
			self.draw_GS_up_to = 0 if self.runway.GS_range is None else min(self.runway.LOC_range, self.runway.GS_range)
	
	def boundingRect(self):
		hw = max(5, self.draw_cone_half_width)
		return QRectF(-hw, -1, 2 * hw, self.item_ymax + 2)
	
	def paint(self, painter, option, widget):
		# 0,0 is RWY THR and drawing down
		ILS_colour = settings.colours['LDG_guide_ILS']
		noILS_colour = settings.colours['LDG_guide_noILS']
		ILS_pen = new_pen(ILS_colour)
		noILS_pen = new_pen(noILS_colour)
		ILS_brush = QBrush(ILS_colour)
		noILS_brush = QBrush(noILS_colour)
		## Centre line
		painter.setPen(noILS_pen if self.runway.LOC_range is None else ILS_pen)
		painter.drawLine(QPointF(0, LOC_line_RWY_sep_dist), QPointF(0, self.runway.param_disp_line_length))
		## GS altitude marks
		if self.scene().show_slope_altitudes:
			alt_step = self.GS_init_step
			dthr_dist = self.GS_init_dist
			while dthr_dist <= self.runway.param_disp_line_length:
				if dthr_dist < self.draw_GS_up_to:
					painter.setPen(ILS_pen)
					painter.setBrush(ILS_brush)
				else:
					painter.setPen(noILS_pen)
					painter.setBrush(noILS_brush)
				y = dthr_dist - self.dthr_NM
				for i in range(alt_step % 5):
					painter.drawLine(QPointF(-.12, y), QPointF(.12, y))
					y += slope_tick_spacing
				hw = .6 * slope_tick_spacing # slope diamond half width
				for i in range(alt_step // 5):
					painter.drawPolygon(QPolygonF([QPointF(-.15, y), QPointF(0, y - hw), QPointF(.15, y), QPointF(0, y + hw)]))
					y += slope_tick_spacing
				alt_step += 1
				dthr_dist += self.GS_step_dist
		## Interception cone
		if self.runway.LOC_range is not None and self.scene().show_interception_cones:
			cone_gradient = QConicalGradient(QPointF(0, 0), 270 - 2 * intercept_cone_half_angle)
			r = intercept_cone_half_angle / 180
			cone_gradient.setColorAt(0, ILS_colour)
			cone_gradient.setColorAt(.9 * r, Qt.transparent)
			cone_gradient.setColorAt(1.1 * r, Qt.transparent)
			cone_gradient.setColorAt(2 * r, ILS_colour)
			cone_brush = QBrush(cone_gradient)
			painter.setPen(Qt.NoPen)
			painter.setBrush(cone_brush)
			p1 = QPointF(-self.draw_cone_half_width, self.runway.LOC_range)
			p2 = QPointF(self.draw_cone_half_width, self.runway.LOC_range)
			painter.drawPolygon(QPolygonF([p1, QPointF(0, 0), p2]))
		## Marker beacons
		for md, ls, hl in (self.draw_OM, Qt.DashLine, .4), (self.draw_MM, Qt.DashDotLine, .25), (self.draw_IM, Qt.DotLine, .1):
			if md is not None:
				painter.setPen(new_pen(ILS_colour, width=2, style=ls))
				painter.drawLine(QPointF(-hl, md), QPointF(hl, md))
















# ================================================ #

#         GROUND NETS, PARKING, TAXIWAYS           #

# ================================================ #


class TarmacSectionItem(QGraphicsItem):
	"""
	Airport movement or non movement area: taxiway, ramp, etc.
	"""
	def __init__(self, path, surface_type, parent=None):
		QGraphicsItem.__init__(self, parent)
		self.paved = is_paved_surface(surface_type)
		self.path = path
	
	def boundingRect(self):
		return self.path.boundingRect()

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['AD_tarmac']))
		painter.setBrush(QBrush(settings.colours['AD_tarmac']) if self.paved else QBrush())
		painter.drawPath(self.path)





class ParkingPositionItem(QGraphicsItem):
	def __init__(self, ad, name, hdg):
		QGraphicsItem.__init__(self, parent=None)
		self.ad = ad
		self.name = name
		self.setRotation(hdg.trueAngle())
		self.setAcceptedMouseButtons(Qt.LeftButton)
	
	def boundingRect(self):
		return QRectF(-.02, -.02, .04, .04)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['AD_parking_position']))
		painter.drawLine(QPointF(-.01, -.01), QPointF(.01, -.01))
		painter.drawLine(QPointF(0, -.01), QPointF(0, .015))
	
	def mousePressEvent(self, event):
		if event.button() == Qt.LeftButton:
			signals.pkPosClick.emit(self.name)
		QGraphicsItem.mousePressEvent(self, event)






def is_TWY_through_node(gnd_net, twy_name, node):
	return len(gnd_net.neighbours(node, twy=twy_name)) == len(gnd_net.neighbours(node, ignoreApron=True)) == 2



class AirportGroundNetItem(QGraphicsItem):
	def __init__(self, gndnet):
		QGraphicsItem.__init__(self, parent=None)
		self.setAcceptedMouseButtons(Qt.NoButton)
		q = lambda n: gndnet.nodePosition(n).toQPointF() # node ID to QPointF
		apron_edges = [((q(n1), q(n2)), None) for n1, n2 in gndnet.apronEdges()]
		self.apron_item = TaxiRouteItem(self, apron_edges, 'GND_route_apron')
		self.twy_items = []
		for twy_name in gndnet.taxiways():
			twy_qedges = [] # holds ALL edges (possibly labelled) of same TWY name
			edges_left = list(gndnet.taxiwayEdges(twy_name))
			while len(edges_left) > 0:
				start_edge = a, b = edges_left.pop()
				connected_edges = [start_edge]
				while is_TWY_through_node(gndnet, twy_name, a): # stop at intersection or end of TWY name
					next_edge = n1, n2 = pop_one(edges_left, lambda edge: a in edge)
					connected_edges.append(next_edge) # to be reversed
					a = n1 if n2 == a else n2
				connected_edges.reverse()
				while is_TWY_through_node(gndnet, twy_name, b): # stop at intersection or end of TWY name
					next_edge = n1, n2 = pop_one(edges_left, lambda edge: b in edge)
					connected_edges.append(next_edge)
					b = n1 if n2 == b else n2
				# HERE: a--b is the start--end of a linear group of edges; connected_edges is the list of edges in sequence
				qedges = [(q(n1), q(n2)) for n1, n2 in connected_edges]
				distances = [QVector2D(q2 - q1).length() for q1, q2 in qedges]
				i_lbl = 0
				stripped_left = 0
				while len(distances) != 1:
					if distances[0] + stripped_left < distances[-1]: # unlabel on the left
						i_lbl += 1
						stripped_left += distances.pop(0) # take first
					else:
						stripped_left -= distances.pop() # take last
				# DONE, add the connected edges to the TWY set
				twy_qedges.extend((edge, (twy_name if i == i_lbl else None)) for i, edge in enumerate(qedges))
			twy_item = TaxiRouteItem(self, twy_qedges, 'GND_route_taxiway')
			twy_item.setAcceptHoverEvents(True)
			self.twy_items.append(twy_item)
		self.apron_item.prepareGeometryChange()
		for item in self.twy_items:
			item.prepareGeometryChange()
	
	def boundingRect(self):
		return QRectF()
	
	def paint(self, painter, option, widget):
		pass
	
	def updateLabelsVisibility(self):
		for item in self.twy_items:
			item.labels.setVisible(self.scene().show_taxiway_names)
	




class TaxiRouteItem(QGraphicsItem):
	"""
	Draws a set of edges that turn on/off together, each possibly labelled.
	Call prepareGeometryChange after building to initialise correctly.
	"""
	def __init__(self, parentItem, segments, colour):
		QGraphicsItem.__init__(self, parent=parentItem)
		self.colour_name = colour
		self.shape = QPainterPath()
		self.labels = QGraphicsItemGroup(self)
		self.bbox = QRectF(0, 0, 0, 0)
		for (p1, p2), label in segments:
			lvect = QVector2D(p2 - p1)
			lpath = QPainterPath()
			m = TWY_line_margin
			l = lvect.length()
			plst = [QPointF(-m, 0), QPointF(-m/3, -m), QPointF(l + m/3, -m), QPointF(l + m, 0), QPointF(l + m/3, m), QPointF(-m/3, m)]
			lpath.addPolygon(QPolygonF(plst))
			lrot = QTransform()
			lrot.rotateRadians(atan2(lvect.y(), lvect.x()))
			lpath = lrot.map(lpath)
			lpath.translate(p1)
			self.shape.addPath(lpath)
			rect = QRectF(p1, p2).normalized()
			if label is not None:
				self.labels.addToGroup(TaxiwayLabelItem(label, rect.center(), self))
			self.bbox |= rect
		self.shape.setFillRule(Qt.WindingFill)
		self.mouse_highlight = False
		self.labels.setVisible(False)
	
	def hoverEnterEvent(self, event):
		self.mouse_highlight = self.scene().mouseover_highlights_groundnet_edges
		if self.mouse_highlight and not self.labels.isVisible():
			self.labels.setVisible(True)
		self.setVisible(False)
		self.setVisible(True)
	
	def hoverLeaveEvent(self, event):
		self.mouse_highlight = False
		self.labels.setVisible(self.scene().show_taxiway_names)
		self.setVisible(False)
		self.setVisible(True)
	
	def boundingRect(self):
		return self.bbox.adjusted(-TWY_line_margin, -TWY_line_margin, TWY_line_margin, TWY_line_margin)
	
	def shape(self):
		return self.shape

	def paint(self, painter, option, widget):
		if self.mouse_highlight or self.scene().show_ground_networks:
			painter.setPen(QPen(Qt.NoPen))
			brushcol = settings.colours[self.colour_name]
			brushcol.setAlpha(96 if self.mouse_highlight else 48)
			painter.setBrush(QBrush(brushcol))
			painter.drawPath(self.shape)
			brushcol.setAlpha(255) # alpha seems to apply to child TWY labels otherwise





class TaxiwayLabelItem(QGraphicsItem):
	brect = QRectF(-15, -10, 30, 20) #STYLE programmatic text bounding rect
	text_offset = QPointF(0, -.001)
	
	def __init__(self, text, position, parentItem):
		QGraphicsItem.__init__(self, parentItem)
		self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
		self.setPos(position + TaxiwayLabelItem.text_offset)
		self.text = text
	
	def boundingRect(self):
		return TaxiwayLabelItem.brect

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['GND_route_apron' if self.text == '' else 'GND_route_taxiway']))
		painter.drawText(TaxiwayLabelItem.brect, Qt.AlignCenter, self.text)









# =============================================== #

#                      OTHER                      #

# =============================================== #



class AirportLinearObjectItem(QGraphicsItem):
	"""
	Linear object or boundary for airport, drawn with given colour.
	Line is thin except for holding lines made thicker.
	"""
	def __init__(self, path, colour_name):
		QGraphicsItem.__init__(self, parent=None)
		self.setAcceptedMouseButtons(Qt.NoButton)
		self.path = path
		self.colour_name = colour_name
		self.width = 2 if colour_name == 'AD_holding_lines' else 0
	
	def boundingRect(self):
		return QRectF() if self.path is None else self.path.boundingRect()

	def paint(self, painter, option, widget):
		if self.path is not None:
			painter.setPen(new_pen(settings.colours[self.colour_name], width=self.width))
			painter.drawPath(self.path)



class WindsockItem(QGraphicsPixmapItem):
	"""
	Places and sizes a windsock pixmap.
	"""
	def __init__(self, coords):
		QGraphicsPixmapItem.__init__(self, QPixmap(windsock_pixmap), None)
		rect = self.boundingRect()
		self.setScale(windsock_width / rect.width())
		self.setOffset(-rect.bottomRight())
		self.setPos(coords.toQPointF())
	



class TowerItem(QGraphicsPixmapItem):
	"""
	Resized control tower pixmap item.
	"""
	def __init__(self, viewpoint_name):
		QGraphicsPixmapItem.__init__(self, QPixmap(tower_pixmap), parent=None)
		rect = self.boundingRect()
		self.setScale(tower_width / rect.width())
		self.setOffset(-rect.width() / 2, -rect.height())
		vp_item = QGraphicsRectItem(-rect.width() / 2, -rect.width(), rect.width(), rect.width())
		item = MouseOverLabelledItem(vp_item, 'AD_viewpoint', None)
		item.setMouseOverText(viewpoint_name)
		item.setParentItem(self)

