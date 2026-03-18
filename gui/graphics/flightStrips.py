
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

from datetime import timedelta

from PyQt5.QtCore import Qt, QPoint, QRect, QRectF, QSize
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem
from PyQt5.QtGui import QPolygon, QTextDocument, QPen, QBrush, QDrag, QPixmap, QPainter, QFontMetrics

from base.util import some
from base.fpl import FPL
from base.nav import world_navpoint_db, NavpointError
from base.params import time_to_fly
from base.strip import strip_mime_type, student_ok_detail, received_from_detail, sent_to_detail, \
		assigned_SQ_detail, departure_clearance_detail, parsed_route_detail, soft_link_detail, \
		recycled_detail, auto_printed_detail, duplicate_callsign_detail

from session.config import settings
from session.env import env
from session.manager import SessionType, student_callsign
from session.models.dataLinks import ConnectionStatus

from gui.actions import new_strip_dialog
from gui.misc import signals, selection
from gui.graphics.miscGraphics import new_pen, EmptyGraphicsItem


# ---------- Constants ----------

strip_text_bottom_margin = 11 # under bottom of text; includes IFR/VFR lower stripe width
flight_rules_stripe_width = 3
corner_triangle_width = 8
strip_text_max_rect = QRect(0, 0, 500, 200)
dummy_strip_contents = '# XX-ABCDE  ####/#  !!####\n[##:##] dummy route dummy route'
loose_strip_margin = 2 # between selection indicator and strip border
spacing_hint_threshold = timedelta(minutes=30) # threshold above which not to display (useless) hint
spacing_hint_speed_var_thr = 5 # kt (minimum speed difference between the two aircraft to show a variability)

# -------------------------------



def acknowledge_strip(strip):
	strip.writeDetail(received_from_detail, None)
	strip.writeDetail(sent_to_detail, None)
	strip.writeDetail(recycled_detail, None)
	strip.writeDetail(auto_printed_detail, None)


def strip_mouse_press(strip, event):
	if event.button() == Qt.LeftButton:
		acknowledge_strip(strip)
		selection.selectStrip(strip)
	elif event.button() == Qt.MiddleButton:
		if event.modifiers() & Qt.ShiftModifier: # STRIP UNLINK REQUEST
			if strip is selection.strip:
				if selection.fpl is not None and selection.acft is not None: # both are linked
					signals.statusBarMsg.emit('Ambiguous action. Use SHIFT+MMB on FPL or radar contact to unlink.')
				elif selection.fpl is None and selection.acft is not None: # XPDR link only
					strip.linkAircraft(None)
					signals.stripInfoChanged.emit()
					selection.selectAircraft(selection.acft)
				elif selection.fpl is not None and selection.acft is None: # FPL link only
					strip.linkFPL(None)
					signals.stripInfoChanged.emit()
					selection.selectFPL(selection.fpl)
		else: # STRIP LINK REQUEST
			if selection.fpl is not None and env.linkedStrip(selection.fpl) is None and strip.linkedFPL() is None:
				strip.linkFPL(selection.fpl)
				signals.stripInfoChanged.emit()
				selection.selectStrip(strip)
			elif selection.acft is not None and env.linkedStrip(selection.acft) is None and strip.linkedAircraft() is None:
				strip.linkAircraft(selection.acft)
				if settings.strip_autofill_on_ACFT_link:
					strip.fillFromXPDR()
				signals.stripInfoChanged.emit()
				selection.selectStrip(strip)
			if strip is selection.strip:
				acknowledge_strip(strip)



def min_sec_hint_str(td):
	seconds = td.total_seconds()
	return '%d:%02d' % (seconds // 60, seconds % 60)



def spacing_hint(strip, prev_strip):
	me = strip.linkedAircraft()
	if me is None or me.considerOnGround():
		return None
	dest_icao = strip.lookup(FPL.ICAO_ARR, fpl=True)
	if dest_icao is None:
		return None
	try:
		dest = world_navpoint_db.findAirfield(dest_icao)
	except NavpointError:
		return None
	my_speed = me.groundSpeed()
	if my_speed is not None and prev_strip.lookup(FPL.ICAO_ARR, fpl=True) == dest.code:
		prev_acft = prev_strip.linkedAircraft()
		if prev_acft is not None and not prev_acft.considerOnGround(): # ACFT and previous are both identified and inbound
			prev_speed = prev_acft.groundSpeed()
			if prev_speed is not None:
				dist_to_prev = me.coords().distanceTo(prev_acft.coords())
				dist_prev_to_dest = prev_acft.coords().distanceTo(dest.coordinates)
				try:
					my_ttf_inseq = time_to_fly(dist_to_prev, my_speed) + time_to_fly(dist_prev_to_dest, my_speed)
					their_ttf_dct = time_to_fly(dist_prev_to_dest, prev_speed)
					if my_ttf_inseq <= their_ttf_dct: # diff_seconds < 0
						hint = '-' + min_sec_hint_str(their_ttf_dct - my_ttf_inseq)
						wrnsuff = ' !!seq'
					else: # if my_ttf_dct <= their_ttf_dct: sequence is fine; but check for "opt", and if time hint not too large to show
						wrnsuff = ''
						dist_to_dest = me.coords().distanceTo(dest.coordinates)
						my_ttf_dct = time_to_fly(dist_to_dest, my_speed)
						their_ttf_revseq = time_to_fly(dist_to_prev, prev_speed) + time_to_fly(dist_to_dest, prev_speed)
						if my_ttf_dct <= their_ttf_dct <= their_ttf_revseq <= my_ttf_inseq:
							# overtaking traffic ahead will get both down sooner but delay them
							combined_gain = my_ttf_inseq - their_ttf_revseq
							loss_for_prev = their_ttf_revseq - their_ttf_dct
							if combined_gain >= settings.seq_opt_min_combo_gain and loss_for_prev <= settings.seq_opt_max_acft_loss:
								wrnsuff = ' opt. %s/%s' % (min_sec_hint_str(combined_gain), min_sec_hint_str(loss_for_prev))
						if wrnsuff == '' and my_ttf_inseq - their_ttf_dct >= spacing_hint_threshold:
							return None
						hint = min_sec_hint_str(my_ttf_inseq - their_ttf_dct)
					diff_speed = my_speed.diff(prev_speed, tolerance=spacing_hint_speed_var_thr)
					if diff_speed != 0:
						hint += '&darr;' if diff_speed < 0 else '&uarr;'
					return '[%s%s]' % (hint, wrnsuff)
				except ValueError: # raised by time_to_fly if speed too low
					pass
	return None




def strip_size_hint(text_font):
	txt_rect = QFontMetrics(text_font).boundingRect(strip_text_max_rect, Qt.AlignLeft, dummy_strip_contents)
	return QSize(txt_rect.width(), txt_rect.height() + strip_text_bottom_margin)



def paint_strip_box(parent_widget, painter, strip, rect):
	acft = strip.linkedAircraft()
	xpdr_conflicts = strip.xpdrConflicts()
	
	### LINE 1
	cs = strip.callsign() # displayed callsign; may still be None
	if settings.strip_CPDLC_integration and cs is not None and FPL.CALLSIGN not in xpdr_conflicts:
		sdl = env.cpdlc.lastDataLink(cs)
	else:
		sdl = None
	## Decorated callsign section
	callsign_section = ''
	if settings.session_manager.session_type == SessionType.TEACHER and not strip.lookup(student_ok_detail):
		callsign_section += '+ '
	if sdl is not None and not sdl.isTerminated():
		if sdl.statusColour() == ConnectionStatus.OK:
			callsign_section += '⚡ '
		else: # includes problems and pending transfers
			if settings.session_manager.session_type == SessionType.TEACHER:
				xfr_to = None if sdl.pendingTransferFrom() is None else student_callsign
			else:
				xfr_to = sdl.pendingTransferTo()
			if xfr_to is None:
				callsign_section += '[⚡] '
			else: # data link proposed for data authority transfer
				callsign_section += '[⚡ >> %s] ' % xfr_to
	# handover from
	fromATC = strip.lookup(received_from_detail)
	if fromATC is not None:
		callsign_section += fromATC + ' &gt;&gt; '
	# callsign(s)
	callsign_section += '<strong>%s</strong>' % some(cs, '?')
	if strip.lookup(FPL.COMMENTS) is not None:
		callsign_section += '*'
	# handover to
	toATC = strip.lookup(sent_to_detail)
	if toATC is not None:
		callsign_section += ' &gt;&gt; ' + toATC
	if strip.lookup(duplicate_callsign_detail): # duplicate callsign warning
		callsign_section += ' !!dup'
	line1_sections = [callsign_section]
	## Wake turb. cat. / aircraft type
	atyp = None if acft is None else acft.xpdrAcftType()
	typesec = some(strip.lookup(FPL.ACFT_TYPE, fpl=True), some(atyp, ''))
	wtc = strip.lookup(FPL.WTC, fpl=True)
	if wtc is not None:
		typesec += '/%s' % wtc
	line1_sections.append(typesec)
	## Optional sections
	# transponder code
	sq = strip.lookup(assigned_SQ_detail)
	if sq is not None:
		if acft is None or assigned_SQ_detail in xpdr_conflicts:
			line1_sections.append('sq=%04o' % sq)
	# conflicts
	conflicts = []
	alert_lvl_hi = alert_lvl_lo = False
	if len(xpdr_conflicts) > 0:
		conflicts.append('!!XPDR')
		alert_lvl_hi = True
	if sdl is not None and sdl.statusColour() != ConnectionStatus.OK:
		if sdl.statusColour() == ConnectionStatus.PROBLEM:
			conflicts.append('!!CPDLC')
			alert_lvl_hi = True
		else:
			alert_lvl_lo = True
	if settings.strip_route_vect_warnings:
		if len(strip.vectoringConflicts(env.QNH())) != 0:
			conflicts.append('!!vect')
			alert_lvl_lo = True
		elif strip.routeConflict():
			conflicts.append('!!route')
			alert_lvl_lo = True
	if len(conflicts) > 0:
		line1_sections.append(' '.join(conflicts))
	
	### LINE 2
	line2_sections = []
	if settings.APP_spacing_hints:
		prev = env.strips.previousInSequence(strip)
		if prev is not None:
			hint = spacing_hint(strip, prev)
			if hint is not None:
				line2_sections.append('%s&nbsp;' % hint)
	parsed_route = strip.lookup(parsed_route_detail)
	if parsed_route is None:
		arr = strip.lookup(FPL.ICAO_ARR, fpl=True)
		if arr is not None:
			line2_sections.append(arr)
	elif acft is None:
		line2_sections.append(str(parsed_route))
	else:
		line2_sections.append('... ' + parsed_route.toGoStr(acft.coords()))
	
	## MAKE DOCUMENT
	html_line1 = ' &nbsp; '.join(line1_sections)
	html_line2 = ' '.join(line2_sections)
	doc = QTextDocument(parent_widget)
	doc.setHtml('<html><body><p>%s<br>&nbsp;&nbsp; %s</p></body></html>' % (html_line1, html_line2))
	
	## PAINT
	painter.save()
	## Background and borders
	if acft is None:
		if strip.lookup(soft_link_detail) is None:
			bgcol = 'strip_unlinked'
		else:
			bgcol = 'strip_unlinked_identified'
	else: # an aircraft is linked
		if alert_lvl_hi:
			bgcol = 'strip_linked_alert'
		elif alert_lvl_lo:
			bgcol = 'strip_linked_warning'
		else:
			bgcol = 'strip_linked_OK'
	if strip is selection.strip:
		painter.setPen(new_pen(Qt.black, width=2))
	else:
		painter.setPen(new_pen(Qt.darkGray))
	painter.setBrush(QBrush(settings.colours[bgcol]))
	painter.drawRect(rect)
	painter.translate(rect.topLeft())
	painter.setPen(Qt.NoPen)
	rules = strip.lookup(FPL.FLIGHT_RULES, fpl=True)
	if rules is not None: # add a border along bottom edge of strip
		painter.setBrush(QBrush(Qt.black, style={'IFR': Qt.SolidPattern, 'VFR': Qt.BDiagPattern}.get(rules, Qt.NoBrush)))
		painter.drawRect(QRectF(0, rect.height() - flight_rules_stripe_width, rect.width(), flight_rules_stripe_width))
	## Corner decorations
	painter.setBrush(QBrush(Qt.black, Qt.SolidPattern))
	if strip.linkedFPL() is not None: # add top triangular corner mark
		painter.drawPolygon(QPolygon([QPoint(rect.width() - corner_triangle_width, 0),
				QPoint(rect.width(), 0), QPoint(rect.width(), corner_triangle_width)]))
	if strip.lookup(departure_clearance_detail) is not None: # add bottom triangular corner mark
		painter.drawPolygon(QPolygon([QPoint(rect.width(), rect.height() - corner_triangle_width),
				QPoint(rect.width(), rect.height()), QPoint(rect.width() - corner_triangle_width, rect.height())]))
	## Text contents
	doc.drawContents(painter, QRectF(0, 0, rect.width(), rect.height() - flight_rules_stripe_width))
	painter.restore()








class FlightStripItem(QGraphicsItem):
	strip_box_full_size = QSize() # initially invalid

	@staticmethod
	def setSizeFromTextFont(font):
		FlightStripItem.strip_box_full_size = strip_size_hint(font)
	
	def __init__(self, strip, compact, parent=None):
		QGraphicsItem.__init__(self, parent)
		self.setFlag(QGraphicsItem.ItemIsMovable, True)
		self.strip = strip
		self.compact_display = compact
	
	def setCompact(self, toggle):
		self.compact_display = toggle
		self.prepareGeometryChange()
	
	def stripBoxRect(self):
		w = FlightStripItem.strip_box_full_size.width()
		h = FlightStripItem.strip_box_full_size.height()
		if self.compact_display:
			w //= 2
			h = (h + strip_text_bottom_margin) // 2 # avoid dividing margin
		return QRect(-w // 2, -h // 2, w, h)
	
	def boundingRect(self):
		m = loose_strip_margin + 2
		return QRectF(self.stripBoxRect().adjusted(-m, -m, m, m))
	
	def paint(self, painter, option, widget):
		if self.strip is selection.strip:
			painter.setPen(new_pen(settings.colours['selection_indicator'], width=2))
			painter.drawRect(QRectF(self.stripBoxRect().adjusted(-loose_strip_margin, -loose_strip_margin, loose_strip_margin, loose_strip_margin)))
		paint_strip_box(widget, painter, self.strip, self.stripBoxRect())
	
	def toPixmap(self):
		rect = self.stripBoxRect()
		pixmap = QPixmap(rect.width(), rect.height())
		pixmap.fill(Qt.darkRed)
		painter = QPainter(pixmap)
		b = loose_strip_margin + 2
		self.scene().render(painter, QRectF(), self.sceneBoundingRect().adjusted(b, b, -b, -b))
		painter.end()
		return pixmap
	
	def mousePressEvent(self, event):
		self._pos_at_mouse_press = self.pos()
		strip_mouse_press(self.strip, event)
		QGraphicsItem.mousePressEvent(self, event)
		
	def mouseMoveEvent(self, event):
		if event.modifiers() & Qt.ShiftModifier:
			QGraphicsItem.mouseMoveEvent(self, event)
		else:
			drag = QDrag(event.widget())
			drag.setMimeData(env.strips.mkMimeDez(self.strip))
			pixmap = self.toPixmap()
			drag.setPixmap(pixmap)
			drag.setHotSpot(pixmap.rect().center())
			self.setVisible(False)
			if drag.exec() != Qt.MoveAction:
				self.setVisible(True)

	def mouseDoubleClickEvent(self, event):
		if event.button() == Qt.LeftButton:
			event.accept()
			if event.modifiers() & Qt.ShiftModifier: # indicate radar link or identification
				acft = self.strip.linkedAircraft()
				if acft is None:
					acft = self.strip.lookup(soft_link_detail)
				if acft is not None:
					signals.indicatePoint.emit(acft.coords())
			elif event.modifiers() & Qt.AltModifier: # open CPDLC dialogue
				cs = selection.selectedCallsign()
				if cs is not None:
					signals.cpdlcDialogueRequest.emit(cs, False)
			else: # request strip edit
				signals.stripEditRequest.emit(self.strip)
		QGraphicsItem.mouseDoubleClickEvent(self, event)








class LooseStripBayScene(QGraphicsScene):
	dummy_init_rect = QRectF(-500, -400, 1000, 800)
	
	def __init__(self, parent):
		QGraphicsScene.__init__(self, parent)
		self.gui = parent
		self.bg_item = None
		self.compact_strips = False
		self.fillBackground()
		self.addRect(LooseStripBayScene.dummy_init_rect, pen=QPen(Qt.NoPen)) # avoid empty scene
		self.strip_items = EmptyGraphicsItem()
		self.addItem(self.strip_items)
		self.strip_items.setZValue(1) # gets strips on top of bg_item
		# External signal connections below. CAUTION: these must all be disconnected on widget deletion
		signals.selectionChanged.connect(self.updateSelection)
		signals.colourConfigReloaded.connect(self.fillBackground)
		env.strips.stripMoved.connect(self.removeInvisibleStripItems)
	
	def disconnectAllSignals(self):
		signals.selectionChanged.disconnect(self.updateSelection)
		signals.colourConfigReloaded.disconnect(self.fillBackground)
		env.strips.stripMoved.disconnect(self.removeInvisibleStripItems)
	
	def getStrips(self):
		return [item.strip for item in self.strip_items.childItems()]
	
	def fillBackground(self):
		self.setBackgroundBrush(settings.colours['loose_strip_bay_background'])
	
	def clearBgImg(self):
		if self.bg_item is not None:
			self.removeItem(self.bg_item)
			self.bg_item = None
	
	def setBgImg(self, pixmap, scale): # pixmap None to clear background
		self.clearBgImg()
		self.bg_item = QGraphicsPixmapItem(pixmap, None)
		rect = self.bg_item.boundingRect()
		self.bg_item.setScale(scale * FlightStripItem.strip_box_full_size.width() / rect.width())
		self.bg_item.setOffset(-rect.center())
		self.addItem(self.bg_item)
	
	def setCompactStrips(self, b):
		self.compact_strips = b
		for item in self.strip_items.childItems():
			item.setCompact(b)
	
	def updateSelection(self):
		for item in self.strip_items.childItems():
			item.setZValue(1 if item.strip is selection.strip else 0)
			item.update()
	
	def placeNewStripItem(self, strip, pos):
		item = FlightStripItem(strip, self.compact_strips)
		item.setPos(pos)
		self.addStripItem(item)
	
	def deleteStripItem(self, strip):
		self.removeItem(next(item for item in self.strip_items.childItems() if item.strip is strip))
	
	def removeInvisibleStripItems(self, strip):
		for item in self.strip_items.childItems():
			if not item.isVisible():
				self.removeItem(item)
	
	def deleteAllStripItems(self):
		for item in self.strip_items.childItems():
			self.removeItem(item)
	
	def addStripItem(self, item):
		item.setParentItem(self.strip_items)
	
	def dropEvent(self, event):
		if event.mimeData().hasFormat(strip_mime_type):
			strip = env.strips.fromMimeDez(event.mimeData())
			try: # maybe it was already inside this bay
				item = next(item for item in self.strip_items.childItems() if item.strip is strip)
				item.setPos(event.scenePos())
				item.setVisible(True)
			except StopIteration:
				env.strips.repositionStrip(strip, None)
				self.placeNewStripItem(strip, event.scenePos())
			signals.selectionChanged.emit()
			event.acceptProposedAction()
	
	def mousePressEvent(self, event):
		QGraphicsScene.mousePressEvent(self, event)
		if not event.isAccepted():
			selection.deselect()
			event.accept()
	
	def mouseDoubleClickEvent(self, event):
		QGraphicsScene.mouseDoubleClickEvent(self, event)
		if not event.isAccepted(): # avoid creating when double clicking on a strip item
			event.accept()
			strip = new_strip_dialog(self.gui, None)
			if strip is not None:
				self.placeNewStripItem(strip, event.scenePos())
				selection.selectStrip(strip)
	
	def dragMoveEvent(self, event):
		pass # Scene's default impl. ignores the event when no item is under mouse (this enables mouse drop on scene)
