
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

from PyQt5.QtCore import Qt, QRect, QRectF, QPoint, QPointF
from PyQt5.QtGui import QFontMetrics, QDrag, QPixmap, QPainter
from PyQt5.QtWidgets import QGraphicsItem, QMessageBox

from base.radar import XPDR_emergency_codes
from base.strip import parsed_route_detail, assigned_altitude_detail, assigned_SQ_detail
from base.util import some
from base.fpl import FPL
from base.nav import world_navpoint_db, NavpointError

from session.config import settings
from session.env import env
from session.manager import SessionType
from session.models.dataLinks import ConnectionStatus

from gui.actions import new_strip_dialog, default_rack_name
from gui.graphics.flightStrips import FlightStripItem, paint_strip_box
from gui.graphics.miscGraphics import new_pen, ACFT_pen_colour
from gui.misc import signals, selection


# ---------- Constants ----------

vertical_speed_sensitivity = 100 # feet per minute

# -------------------------------

def info_text_lines(radar_contact, compact_display, mach_disp):
	strip = env.linkedStrip(radar_contact)
	wtc = None if strip is None else strip.lookup(FPL.WTC, fpl=True)
	
	# FL/ALT. & SPEED LINE
	if settings.SSR_mode_capability in '0A':
		fl_speed_line = ''
	else: # we may hope for altitude values from XPDR
		if radar_contact.xpdrGND():
			fl_speed_line = 'GND '
		else:
			xpdr_alt = radar_contact.xpdrAlt()
			if xpdr_alt is None:
				fl_speed_line = 'alt? '
			else:
				if settings.radar_tag_interpret_XPDR_FL:
					alt_str = env.specifyAltFl(xpdr_alt).toStr(unit=False)
				else:
					alt_str = '%03d' % xpdr_alt.FL()
				vs = radar_contact.verticalSpeed()
				if vs is None:
					comp_char = '-'
				elif abs(vs) < vertical_speed_sensitivity:
					comp_char = '='
				elif vs > 0:
					comp_char = '↗'
				else:
					comp_char = '↘'
				fl_speed_line = '%s %c ' % (alt_str, comp_char)
	ass_alt = None if strip is None else strip.lookup(assigned_altitude_detail)
	if ass_alt is not None:
		fl_speed_line += ass_alt.toStr(unit=False)
	if fl_speed_line == '': # radar modes 0/A without assigned alt.
		fl_speed_line = '-'
	fl_speed_line += '  '
	if mach_disp:
		mach_num = radar_contact.xpdrMachNumber()
		if mach_num is not None:
			fl_speed_line += ('%.2f' % mach_num).lstrip('0')
	else: # speed in knots
		speed = radar_contact.groundSpeed()
		if speed is not None:
			if settings.radar_tag_speed_tens:
				fl_speed_line += '%02d' % (int(speed.kt() + 5) // 10)
			else:
				fl_speed_line += '%03d' % speed.kt()
	if settings.radar_tag_WTC_position == 2 and wtc is not None:
		fl_speed_line += '/' + wtc
	
	# XPDR CODE || WAYPOINT/DEST LINE
	xpdr_code = radar_contact.xpdrCode()
	emg = False if xpdr_code is None else xpdr_code in XPDR_emergency_codes
	if emg or strip is None or assigned_SQ_detail in strip.xpdrConflicts(): # Show XPDR code
		sq_wp_line = '' if xpdr_code is None else '%04o' % xpdr_code
		if emg:
			sq_wp_line += '  !!EMG'
	else:
		parsed_route = strip.lookup(parsed_route_detail)
		if parsed_route is None:
			dest = some(strip.lookup(FPL.ICAO_ARR, fpl=True), '')
			try:
				ad = world_navpoint_db.findAirfield(dest)
				sq_wp_line = '%s  %s°' % (ad.code, radar_contact.coords().headingTo(ad.coordinates).read())
			except NavpointError: # not an airport
				sq_wp_line = dest
		else: # got parsed route
			leg = parsed_route.currentLegIndex(radar_contact.coords())
			if leg == 0 and parsed_route.SID() is not None:
				sq_wp_line = 'SID %s' % parsed_route.SID()
			elif leg == parsed_route.legCount() - 1 and parsed_route.STAR() is not None:
				sq_wp_line = 'STAR %s' % parsed_route.STAR()
			else:
				wp = parsed_route.waypoint(leg)
				sq_wp_line = '%s  %s°' % (wp.code, radar_contact.coords().headingTo(wp.coordinates).read())
	
	result_lines = [sq_wp_line, fl_speed_line] if settings.radar_tag_FL_at_bottom else [fl_speed_line, sq_wp_line]
	
	# CALLSIGN & ACFT TYPE LINE (top line, only if NOT compact display)
	if not compact_display:
		line1 = ''
		if radar_contact.flagged:
			line1 += '# '
		cs = radar_contact.xpdrCallsign()
		if cs is None and strip is not None:
			cs = strip.callsign()
		if settings.session_manager.session_type == SessionType.TEACHER:
			dl = env.cpdlc.lastDataLink(radar_contact.identifier)
		else:
			dl = None if cs is None else env.cpdlc.lastDataLink(cs)
		if dl is not None and not dl.isTerminated():
			line1 += {ConnectionStatus.OK: '⚡ ', ConnectionStatus.EXPECTING: '[⚡] ', ConnectionStatus.PROBLEM: '!![⚡] '}[dl.statusColour()]
		line1 += some(cs, '?')
		if radar_contact.xpdrIdent():
			line1 += '  !!ident'
		t = radar_contact.xpdrAcftType()
		if t is None and strip is not None:
			t = strip.lookup(FPL.ACFT_TYPE, fpl=True)
		line1 += '  '
		if t is not None:
			line1 += '%s' % t
		if settings.radar_tag_WTC_position == 1 and wtc is not None:
			line1 += '/%s' % wtc
		result_lines.insert(0, line1)
	
	return '\n'.join(result_lines)




class RadarTagItem(QGraphicsItem):
	def __init__(self, acft_item):
		QGraphicsItem.__init__(self, acft_item)
		self.setVisible(False)
		self.radar_contact = acft_item.radar_contact
		self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
		self.text_box_item = TextBoxItem(self)
		self.callout_line_start = QPointF(0, 0)
		self.callout_line_end = self.text_box_item.pos() + self.text_box_item.calloutConnectingPoint()
	
	def updateInfoText(self):
		self.text_box_item.updateContents()
		self.textBoxChanged()
	
	def textBoxChanged(self):
		self.prepareGeometryChange()
		self.callout_line_end = self.text_box_item.pos() + self.text_box_item.calloutConnectingPoint()
		self.update(self.boundingRect())
		
	def paint(self, painter, option, widget):
		# Draw callout line; child text box draws itself
		pen = new_pen(settings.colours['radar_tag_line'])
		painter.setPen(pen)
		painter.drawLine(self.callout_line_start, self.callout_line_end)
		
	def boundingRect(self):
		return QRectF(self.callout_line_start, self.callout_line_end).normalized() | self.childrenBoundingRect()




class TextBoxItem(QGraphicsItem):
	max_rect = QRect(-56, -20, 112, 40)
	init_offset = QPointF(66, -34)
	dummy_contents = '# X-ABCDE  ####/#\n##### ###\n10000 = 10000  ####X'
	dummy_contents_compact = '####\n10000  ####'
	txt_rect_2lines = QRectF()
	txt_rect_3lines = QRectF()

	@staticmethod
	def setBoxSizesFromTextFont(font):
		fm = QFontMetrics(font)
		TextBoxItem.txt_rect_2lines = QRectF(fm.boundingRect(TextBoxItem.max_rect, Qt.AlignLeft, TextBoxItem.dummy_contents_compact))
		TextBoxItem.txt_rect_3lines = QRectF(fm.boundingRect(TextBoxItem.max_rect, Qt.AlignLeft, TextBoxItem.dummy_contents))
	
	def __init__(self, parent_item):
		QGraphicsItem.__init__(self, parent_item)
		self.radar_contact = parent_item.radar_contact
		self.info_text = ''
		self.rectangle = QRectF()
		self.setCursor(Qt.PointingHandCursor)
		self.setPos(TextBoxItem.init_offset)
		self.mouse_hovering = False
		self.paint_border = True
		self.setFlag(QGraphicsItem.ItemIsMovable, True)
		self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
		self.setAcceptHoverEvents(True)
		self.updateContents()
	
	def updateContents(self):
		self.prepareGeometryChange()
		extended_disp = self.mouse_hovering or self.radar_contact is selection.acft or env.linkedStrip(self.radar_contact) is not None
		mach_disp = self.scene() is not None and self.scene().show_mach_numbers #STYLE ugly test for scene?
		self.paint_border = extended_disp
		self.info_text = info_text_lines(self.radar_contact, not extended_disp, mach_disp)
		self.rectangle = TextBoxItem.txt_rect_3lines if extended_disp else TextBoxItem.txt_rect_2lines
	
	def positionQuadrant(self):
		return (1 if self.pos().x() > 0 else -1), (1 if self.pos().y() > 0 else -1)
	
	def calloutConnectingPoint(self):
		q = self.positionQuadrant()
		if q == (-1, -1):
			return self.rectangle.bottomRight()
		elif q == (-1, 1):
			return self.rectangle.topRight()
		elif q == (1, -1):
			return self.rectangle.bottomLeft()
		elif q == (1, 1):
			return self.rectangle.topLeft()
	
	def paint(self, painter, option, widget):
		coloured_pen = new_pen(ACFT_pen_colour(self.radar_contact))
		# 1. Write info text
		painter.setPen(coloured_pen)
		painter.drawText(self.rectangle, Qt.AlignLeft | Qt.AlignVCenter, self.info_text)
		# 2. Draw container box?
		if self.paint_border:
			pen = coloured_pen if self.radar_contact is selection.acft else new_pen(settings.colours['radar_tag_line'])
			if self.radar_contact.individual_cheat:
				pen.setStyle(Qt.DashLine)
			painter.setPen(pen)
			painter.drawRect(self.rectangle)
		
	def boundingRect(self):
		return self.rectangle
	

	# EVENTS
	
	def itemChange(self, change, value):
		if change == QGraphicsItem.ItemPositionChange:
			self.parentItem().textBoxChanged()
		return QGraphicsItem.itemChange(self, change, value)
	
	def hoverEnterEvent(self, event):
		self.mouse_hovering = True
		self.updateContents()
		self.parentItem().textBoxChanged()
		QGraphicsItem.hoverEnterEvent(self, event)
	
	def hoverLeaveEvent(self, event):
		self.mouse_hovering = False
		self.updateContents()
		self.parentItem().textBoxChanged()
		QGraphicsItem.hoverLeaveEvent(self, event)

	def mousePressEvent(self, event):
		if event.button() == Qt.LeftButton:
			selection.selectAircraft(self.radar_contact)
		elif event.button() == Qt.MiddleButton:
			if event.modifiers() & Qt.ShiftModifier:
				selection.unlinkAircraft(self.radar_contact)
			else:
				selection.linkAircraft(self.radar_contact)
			event.accept()
		QGraphicsItem.mousePressEvent(self, event)

	def mouseMoveEvent(self, event):
		if event.modifiers() & Qt.ShiftModifier:
			QGraphicsItem.mouseMoveEvent(self, event)
		else:
			strip = env.linkedStrip(self.radar_contact)
			if strip is not None:
				drag = QDrag(event.widget())
				drag.setMimeData(env.strips.mkMimeDez(strip))
				pixmap = QPixmap(FlightStripItem.strip_box_full_size)
				paint_strip_box(event.widget(), QPainter(pixmap), strip, QRect(QPoint(0, 0), FlightStripItem.strip_box_full_size))
				#painter = QPainter()
				#painter.begin(pixmap)
				#assert painter.isActive(), 'Painter NOT active after "begin"'
				#paint_strip_box(event.widget(), painter, strip, QRect(QPoint(0, 0), FlightStripItem.strip_box_full_size))
				#painter.end()
				drag.setPixmap(pixmap)
				drag.setHotSpot(pixmap.rect().center())
				drag.exec()

	def mouseDoubleClickEvent(self, event):
		if event.button() == Qt.LeftButton:
			if event.modifiers() & Qt.ShiftModifier: # reset box position
				self.setPos(TextBoxItem.init_offset)
				self.parentItem().textBoxChanged()
			elif event.modifiers() & Qt.AltModifier: # open CPDLC dialogue
				cs = selection.selectedCallsign()
				if cs is not None:
					signals.cpdlcDialogueRequest.emit(cs, False)
			elif selection.strip is not None:
				signals.stripEditRequest.emit(selection.strip)
			elif QMessageBox.question(settings.session_manager.gui, 'Linked strip', 'No strip linked to contact. Create and link one?') == QMessageBox.Yes:
				new_strip_dialog(settings.session_manager.gui, default_rack_name, linkToSelection=True)
			event.accept()
		else:
			QGraphicsItem.mouseDoubleClickEvent(self, event)
