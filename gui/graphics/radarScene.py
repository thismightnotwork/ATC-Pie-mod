
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

from sys import stderr

from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, pyqtSignal
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsScene, QInputDialog
from PyQt5.QtGui import QColor

from base.coords import RadarCoords, EarthCoords, dist_str
from base.params import TTF_str
from base.nav import Navpoint

from session.config import settings
from session.env import env
from session.manager import SessionType

from ext.xplane import get_airport_drawables

from gui.misc import signals, selection
from gui.graphics.airport import RunwayItem, HelipadItem, TarmacSectionItem, \
		ParkingPositionItem, AirportGroundNetItem, AirportLinearObjectItem, WindsockItem, TowerItem
from gui.graphics.radarNavpoints import NavVORItem, NavNDBItem, NavFixItem, NavAirfieldItem, RnavItem
from gui.graphics.radarContact import AircraftItem
from gui.graphics.miscGraphics import new_pen, EmptyGraphicsItem, \
		MeasuringHeadingInstrToolItem, CustomLabelItem, BgPixmapItem, BgTextDrawingItem, MouseOverLabelledItem


# ---------- Constants ----------

bg_radar_circle_step = 20
navpoint_indicator_timeout = 3000 # milliseconds
init_speed_mark_count = 2 # one minute of fly time each
minimum_RDF_line_alphaF = .2 # in [0, 1]

# -------------------------------


class Layer:
	radar_layer_names = RADAR_BACKGROUND, TARMAC, AD_BOUNDARY, BG_IMAGES, RUNWAYS, TAXIWAY_LINES, \
						HOLDING_LINES, GROUND_NET, PARKING_POSITIONS, OBJECT_ICONS, NAV_AIRFIELDS, \
						RNAV_POINTS, NAV_FIXES, NAV_AIDS, CUSTOM_LABELS, AIRCRAFT, RADAR_FOREGROUND = range(17)



navpoint_layers = {
	Navpoint.AD: Layer.NAV_AIRFIELDS, Navpoint.VOR: Layer.NAV_AIDS, Navpoint.NDB: Layer.NAV_AIDS,
	Navpoint.FIX: Layer.NAV_FIXES, Navpoint.RNAV: Layer.RNAV_POINTS
}

navpoint_colours = {
	Navpoint.AD: 'nav_airfield', Navpoint.VOR: 'nav_aid', Navpoint.NDB: 'nav_aid',
	Navpoint.FIX: 'nav_fix', Navpoint.RNAV: 'nav_RNAV'
}








class RadarCircleItem(QGraphicsItem):
	def __init__(self, init_radius, colour_name, pen_style):
		QGraphicsItem.__init__(self, parent=None)
		self.setAcceptedMouseButtons(Qt.NoButton)
		self.radius = init_radius
		self.colour_name = colour_name
		self.pen_style = pen_style
	
	def updateRadius(self):
		self.prepareGeometryChange()
		self.radius = settings.radar_range
	
	def boundingRect(self):
		return QRectF(-self.radius, -self.radius, 2 * self.radius, 2 * self.radius)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours[self.colour_name], style=self.pen_style))
		painter.drawEllipse(self.boundingRect())



class PointIndicatorItem(QGraphicsItem):
	def __init__(self):
		QGraphicsItem.__init__(self, None)
		self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
		self.setVisible(False)
		
	def boundingRect(self):
		return QRectF(-15, -15, 30, 30)

	def paint(self, painter, option, widget):
		painter.setPen(new_pen(settings.colours['point_indicator'], width=2))
		painter.drawEllipse(QPointF(0, 0), 12, 6)
		painter.drawEllipse(QPointF(0, 0), 6, 12)



class RdfLineItem(QGraphicsItem):
	def __init__(self):
		QGraphicsItem.__init__(self, parent=None)
		self.setAcceptedMouseButtons(Qt.NoButton)
		self.length = settings.radar_range
		self.alpha_level = 1
		self.setVisible(False)
	
	def updateLength(self):
		self.prepareGeometryChange()
		self.length = settings.radar_range
	
	def boundingRect(self):
		return QRectF(-.05, -self.length - .05, .1, self.length + .1)

	def paint(self, painter, option, widget):
		col = QColor(settings.colours['RDF_line'])
		col.setAlphaF(self.alpha_level)
		painter.setPen(new_pen(col, width=2))
		painter.drawLine(QPointF(0, 0), QPointF(0, -self.length))
	
	def showSignal(self, signal):
		self.alpha_level = signal.quality * (1 - minimum_RDF_line_alphaF) + minimum_RDF_line_alphaF
		self.setRotation(signal.direction.trueAngle())
		self.show()






class RadarScene(QGraphicsScene):
	mouseInfo = pyqtSignal(str)
	addRemoveRouteNavpoint = pyqtSignal(Navpoint)
	imagesRedrawn = pyqtSignal()
	
	def __init__(self, parent):
		QGraphicsScene.__init__(self, parent)
		self.prevent_mouse_release_deselect = False # CAUTION set by view on panning
		self.current_rotation = 0 # used by view, but useful here to rotate LDG surface numbers, windsocks and TWR icons
		self.show_unlinked_tags = True
		self.show_all_vectors = False
		self.show_all_routes = False
		self.show_separation_rings = False
		self.show_sequence_numbers = False
		self.show_selected_ACFT_full_history = False
		self.show_selected_ACFT_assignments = False
		self.show_slope_altitudes = True
		self.show_interception_cones = False
		self.show_ground_networks = False
		self.show_taxiway_names = False
		self.show_GND_modes = True
		self.show_mach_numbers = False
		self.show_RDF_line = True
		self.lock_pan_zoom = False
		self.runway_names_always_visible = False
		self.speed_mark_count = init_speed_mark_count
		self.mouseover_highlights_groundnet_edges = False
		self.rdf_line_item = RdfLineItem() # radio direction finding
		self.point_indicator = PointIndicatorItem()
		self.point_indicator_timer = QTimer(self)
		self.point_indicator_timer.setSingleShot(True)
		self.point_indicator_timer.timeout.connect(lambda: self.point_indicator.setVisible(False))
		self.measuring_tool = MeasuringHeadingInstrToolItem()
		self.using_special_tool = False # Makes the difference between normal measuring and "special" tool
		self.setBackgroundBrush(settings.colours['radar_background'])
		self.additional_AD_items = []
		# Create layers
		self.layers = {layer: EmptyGraphicsItem() for layer in Layer.radar_layer_names}
		for layer in self.layers.values():
			self.addItem(layer)
		self.pinned_navpoints_layer = EmptyGraphicsItem()
		self.addItem(self.pinned_navpoints_layer)
		self.pinned_pkpos_layer = EmptyGraphicsItem()
		self.addItem(self.pinned_pkpos_layer)
		self.replaced_AD_items_layer = EmptyGraphicsItem()
		self.addItem(self.replaced_AD_items_layer)
		self.replaced_AD_items_layer.setVisible(False)
		
		# Populate radar back- and fore-ground
		if env.airport_data is not None:
			for n in range(1, int(settings.map_range / bg_radar_circle_step) + 1):
				dist = n * bg_radar_circle_step
				self.addToLayer(Layer.RADAR_BACKGROUND, RadarCircleItem(dist, 'radar_circle', Qt.SolidLine))
		self.radar_range_item = RadarCircleItem(settings.radar_range, 'radar_range_limit', Qt.DotLine)
		self.addToLayer(Layer.RADAR_BACKGROUND, self.radar_range_item)
		self.addToLayer(Layer.RADAR_FOREGROUND, self.point_indicator)
		self.addToLayer(Layer.RADAR_FOREGROUND, self.measuring_tool)
		self.addToLayer(Layer.RADAR_FOREGROUND, self.rdf_line_item)
		
		# Populate background images
		self.redrawBackgroundImages()
		
		# Populate airport objects
		if env.airport_data is not None:
			self._drawAirportData(env.airport_data, False) # things that are drawn for additional airports, but these do not reset
		
		# Populate navpoints
		for p in env.navpoints.findAll(types=navpoint_layers.keys()):
			if p.type == Navpoint.AD and p.code == settings.location_code:
				continue # do not draw base airport navpoint
			if p.type == Navpoint.VOR:
				base_item = NavVORItem(p)
			elif p.type == Navpoint.NDB:
				base_item = NavNDBItem(p)
			elif p.type == Navpoint.FIX:
				base_item = NavFixItem(p)
			elif p.type == Navpoint.RNAV:
				base_item = RnavItem(p)
			elif p.type == Navpoint.AD:
				base_item = NavAirfieldItem(p)
			label = '%s\n%s' % (p.code, p.frequency) if p.type in [Navpoint.VOR, Navpoint.NDB] else p.code
			item = MouseOverLabelledItem(base_item, navpoint_colours[p.type], self.pinned_navpoints_layer)
			item.setMouseOverText(label)
			item.setPos(p.coordinates.toQPointF())
			self.addToLayer(navpoint_layers[p.type], item)
		
		# Populate aircraft already in contact
		for acft in env.radar.contacts():
			self.addAircraftItem(acft)
		
		# External signal connections below. CAUTION: these must all be disconnected on widget deletion
		env.radar.acftBlip.connect(self.updateAircraftItem)
		env.radar.newContact.connect(self.addAircraftItem)
		env.radar.lostContact.connect(self.removeAircraftItem)
		env.strips.rwyBoxFilled.connect(self.updateRunways)
		env.strips.rwyBoxFreed.connect(self.updateRunways)
		signals.fastClockTick.connect(self.updateRdfLine)
		signals.stripInfoChanged.connect(self.updateContacts)
		signals.selectionChanged.connect(self.updateContacts)
		signals.adSfcUseChanged.connect(self.updateRunwayNamesVisibility)
		signals.generalSettingsChanged.connect(self.updateAfterGeneralSettingsChanged) # in case e.g. interpret XPDR FL toggle
		signals.locationSettingsChanged.connect(self.updateAfterLocationSettingsChanged) # in case e.g. RWY param changed
		signals.backgroundImagesReloaded.connect(self.redrawBackgroundImages)
		signals.colourConfigReloaded.connect(self.coloursReloaded)
	
	## DELETING
	def prepareForDeletion(self):
		self.point_indicator_timer.stop()
		env.radar.acftBlip.disconnect(self.updateAircraftItem)
		env.radar.newContact.disconnect(self.addAircraftItem)
		env.radar.lostContact.disconnect(self.removeAircraftItem)
		env.strips.rwyBoxFilled.disconnect(self.updateRunways)
		env.strips.rwyBoxFreed.disconnect(self.updateRunways)
		signals.fastClockTick.disconnect(self.updateRdfLine)
		signals.stripInfoChanged.disconnect(self.updateContacts)
		signals.selectionChanged.disconnect(self.updateContacts)
		signals.adSfcUseChanged.disconnect(self.updateRunwayNamesVisibility)
		signals.generalSettingsChanged.disconnect(self.updateAfterGeneralSettingsChanged)
		signals.locationSettingsChanged.disconnect(self.updateAfterLocationSettingsChanged)
		signals.backgroundImagesReloaded.disconnect(self.redrawBackgroundImages)
		signals.colourConfigReloaded.disconnect(self.coloursReloaded)
	
	
	## MISC.
	def _drawAirportData(self, ad_data, resets):
		twy_apron_surfaces, twy_centre_lines, holding_lines, ad_boundaries = get_airport_drawables(ad_data.navpoint.code)
		for path, surface in twy_apron_surfaces:
			self.addToLayer(Layer.TARMAC, TarmacSectionItem(path, surface), resets)
		for qpath in twy_centre_lines:
			self.addToLayer(Layer.TAXIWAY_LINES, AirportLinearObjectItem(qpath, 'AD_taxiway_lines'), resets)
		for qpath in holding_lines:
			self.addToLayer(Layer.HOLDING_LINES, AirportLinearObjectItem(qpath, 'AD_holding_lines'), resets)
		for boundary in ad_boundaries:
			self.addToLayer(Layer.AD_BOUNDARY, AirportLinearObjectItem(boundary, 'nav_airfield'), resets)
		for pos, height, name in ad_data.viewpoints:
			item = TowerItem(name)
			item.setPos(pos.toQPointF())
			self.addToLayer(Layer.OBJECT_ICONS, item, resets)
		for windsock_coords in ad_data.windsocks:
			self.addToLayer(Layer.OBJECT_ICONS, WindsockItem(windsock_coords), resets)
		for i in range(ad_data.physicalRunwayCount()):
			self.addToLayer(Layer.RUNWAYS, RunwayItem(ad_data, i), resets)
		for h in ad_data.helipads():
			self.addToLayer(Layer.RUNWAYS, HelipadItem(h), resets)
		for pk in ad_data.ground_net.parkingPositions():
			pos, hdg = ad_data.ground_net.parkingPosInfo(pk)[0:2]
			item = MouseOverLabelledItem(ParkingPositionItem(ad_data.navpoint.code, pk, hdg), 'AD_parking_position', self.pinned_pkpos_layer)
			item.setMouseOverText(pk)
			item.setPos(pos.toQPointF())
			self.addToLayer(Layer.PARKING_POSITIONS, item, resets)
		self.addToLayer(Layer.GROUND_NET, AirportGroundNetItem(ad_data.ground_net), resets)
		self.updateRunwayNamesVisibility()
	
	def coloursReloaded(self):
		self.setBackgroundBrush(settings.colours['radar_background'])
		self.updateContacts()
	
	def redrawBackgroundImages(self):
		for img_item in self.layerItems(Layer.BG_IMAGES):
			self.removeItem(img_item)
		for is_pixmap, src, title, constr in settings.radar_background_images:
			item = BgPixmapItem(src, title, *constr) if is_pixmap else BgTextDrawingItem(src, title, constr)
			self.addToLayer(Layer.BG_IMAGES, item)
		self.imagesRedrawn.emit()
	
	def addToLayer(self, layer, item, resets=False):
		item.setParentItem(self.layers[layer])
		if resets:
			self.additional_AD_items.append(item)
	
	def indicatePoint(self, coords):
		self.point_indicator.setPos(coords.toQPointF())
		self.point_indicator.setVisible(True)
		self.point_indicator_timer.start(navpoint_indicator_timeout)
	
	def pinNavpoint(self, p):
		try:
			next(item for item in self.layerItems(navpoint_layers[p.type]) if item.child_item.navpoint is p).pinLabel(True)
		except StopIteration:
			print('Problem pinning navpoint %s.' % p, file=stderr)
	
	def pinPkgPos(self, ad, pkg):
		try:
			next(item for item in self.layerItems(Layer.PARKING_POSITIONS) \
				if item.child_item.ad == ad and item.child_item.name == pkg).pinLabel(True)
		except StopIteration:
			print('Problem pinning PKG position %s.' % pkg, file=stderr)
	
	def layerItems(self, layer):
		return self.layers[layer].childItems()
	
	def pinnedNavpoints(self):
		return [item.child_item.navpoint for item in self.pinned_navpoints_layer.childItems()]
	
	def pinnedParkingPositions(self):
		return [(item.child_item.ad, item.child_item.name) for item in self.pinned_pkpos_layer.childItems()]
	
	def customLabels(self):
		return [(item.earthCoords(), item.label()) for item in self.layerItems(Layer.CUSTOM_LABELS)]
	
	def drawnAirports(self):
		return [item.child_item.navpoint.code for item in self.replaced_AD_items_layer.childItems()]
	
	def speedMarkCount(self):
		return self.speed_mark_count

	def currentRotation(self):
		return self.current_rotation
	
	
	## SHOW TIME
	
	def showLandingHelper(self, rwy, toggle):
		for item in self.layerItems(Layer.RUNWAYS):
			if isinstance(item, RunwayItem):
				app_guide_item = item.rwyAppGuideItem(rwy)
				if app_guide_item is not None:
					app_guide_item.setVisible(toggle)
					return
	
	def showGroundNetworks(self, toggle):
		self.show_ground_networks = toggle
		self.layers[Layer.GROUND_NET].setVisible(False)
		self.layers[Layer.GROUND_NET].setVisible(True)
	
	def showTaxiwayNames(self, toggle):
		self.show_taxiway_names = toggle
		for gnd_net_item in self.layerItems(Layer.GROUND_NET):
			gnd_net_item.updateLabelsVisibility()

	def showMiscObjects(self, toggle):
		self.layers[Layer.OBJECT_ICONS].setVisible(toggle)
		self.layers[Layer.AD_BOUNDARY].setVisible(toggle)

	def highlightEdgesOnMouseover(self, toggle):
		self.mouseover_highlights_groundnet_edges = toggle
	
	def setRunwayNamesAlwaysVisible(self, toggle):
		self.runway_names_always_visible = toggle
		self.updateRunwayNamesVisibility()
	
	def showSlopeAltitudes(self, toggle):
		self.show_slope_altitudes = toggle
		self.updateAppGuideItems()
	
	def showInterceptionCones(self, toggle):
		self.show_interception_cones = toggle
		self.updateAppGuideItems()
	
	def showVectors(self, toggle):
		self.show_all_vectors = toggle
		self.updateContacts()
	
	def showRoutes(self, toggle):
		self.show_all_routes = toggle
		self.updateContacts()

	def showSelectionPositionHistory(self, toggle):
		self.show_selected_ACFT_full_history = toggle
		self.updateContacts()
	
	def showSelectionAssignments(self, toggle):
		self.show_selected_ACFT_assignments = toggle
		self.updateContacts()
	
	def showUnlinkedTags(self, toggle):
		self.show_unlinked_tags = toggle
		self.updateContacts()
	
	def showSeparationRings(self, toggle):
		self.show_separation_rings = toggle
		self.updateContacts()
	
	def showSequenceNumbers(self, toggle):
		self.show_sequence_numbers = toggle
		self.updateContacts()
	
	def showGndModes(self, toggle):
		self.show_GND_modes = toggle
		self.updateContacts()

	def showMachNumbers(self, toggle):
		self.show_mach_numbers = toggle
		self.updateContacts()
	
	def showRdfLine(self, toggle):
		self.show_RDF_line = toggle
	
	def lockMousePanAndZoom(self, toggle):
		self.lock_pan_zoom = toggle
	
	def drawAdditionalAirportData(self, ad_data):
		try: # look for item to replace
			try: # in pinned items...
				replaced = next(item for item in self.pinned_navpoints_layer.childItems() if \
						isinstance(item.child_item, NavAirfieldItem) and item.child_item.navpoint.code == ad_data.navpoint.code)
				replaced._was_pinned = True
			except StopIteration: # ... and in other airfields
				replaced = next(item for item in self.layerItems(Layer.NAV_AIRFIELDS) if item.child_item.navpoint.code == ad_data.navpoint.code)
				replaced._was_pinned = False
		except StopIteration: # item already drawn
			pass
		else: # item found!
			replaced.setParentItem(self.replaced_AD_items_layer)
			self._drawAirportData(ad_data, True)
	
	def resetAirportItems(self):
		while self.additional_AD_items != []:
			self.removeItem(self.additional_AD_items.pop())
		for item in self.replaced_AD_items_layer.childItems():
			item.setParentItem(self.pinned_navpoints_layer if item._was_pinned else self.layers[Layer.NAV_AIRFIELDS])
	
	def setSpeedMarkCount(self, new_value):
		self.speed_mark_count = new_value
		self.updateContacts()
	
	def updateRdfLine(self):
		if settings.radio_direction_finding and self.show_RDF_line:
			sig = env.rdf.strongestSignal()
			if sig is None:
				self.rdf_line_item.hide()
			else:
				self.rdf_line_item.showSignal(sig)
		else:
			self.rdf_line_item.hide()

	
	## UPDATING SCENE ITEMS, etc.
	
	def addAircraftItem(self, contact):
		self.addToLayer(Layer.AIRCRAFT, AircraftItem(contact))
	
	def addCustomLabel(self, lbl, qpos):
		item = CustomLabelItem(lbl)
		item.setPos(qpos)
		self.addToLayer(Layer.CUSTOM_LABELS, item)
	
	def removeAircraftItem(self, zombie):
		try:
			acft_item = next(item for item in self.layerItems(Layer.AIRCRAFT) if item.radar_contact is zombie)
			self.removeItem(acft_item)
		except StopIteration:
			print('Graphics item not found for zombie %s' % zombie.identifier, file=stderr)
	
	def updateAircraftItem(self, acft):
		try:
			next(item for item in self.layerItems(Layer.AIRCRAFT) if item.radar_contact is acft).updateGraphics()
		except StopIteration:
			print('No graphics item found to update %s' % acft.identifier, file=stderr)
		self.updateRunways()  # RWY occupation might have changed
	
	def updateRunways(self):
		for item in self.layerItems(Layer.RUNWAYS):
			if isinstance(item, RunwayItem):
				item.updateBorders()
	
	def updateContacts(self):
		for item in self.layerItems(Layer.AIRCRAFT):
			item.updateGraphics()

	def updateAfterViewRotation(self, rot):
		self.current_rotation = rot
		for item in self.layerItems(Layer.RUNWAYS):
			item.updateNumbersRotation()
		for item in self.layerItems(Layer.OBJECT_ICONS):
			item.setRotation(-self.currentRotation())
	
	def updateAfterGeneralSettingsChanged(self):
		for item in self.layerItems(Layer.AIRCRAFT):
			item.updateAfterGeneralSettingsChanged()
		self.updateRunways() # in case runway occupation monitor toggled
	
	def updateAfterLocationSettingsChanged(self):
		self.updateAppGuideItems()
		self.radar_range_item.updateRadius()
		self.rdf_line_item.updateLength()
		for item in self.layerItems(Layer.AIRCRAFT):
			item.updateAfterLocationSettingsChanged()
	
	def updateAppGuideItems(self):
		for item in self.layerItems(Layer.RUNWAYS):
			if isinstance(item, RunwayItem):
				item.appGuide_item1.updateFromSettings()
				item.appGuide_item2.updateFromSettings()
	
	def updateRunwayNamesVisibility(self):
		for item in self.layerItems(Layer.RUNWAYS):
			item.updateNumbersVisibility()

	
	## MOUSE EVENTS

	def _mouseInfo_flyToMouse(self, radarXY):
		ref_contact = selection.acft
		if ref_contact is None:
			self.mouseInfo.emit('')
		else:
			acftXY = ref_contact.coords().toRadarCoords()
			dist = acftXY.distanceTo(radarXY)
			disp = '%s°, %s' % (acftXY.headingTo(radarXY).read(), dist_str(dist))
			spd = ref_contact.groundSpeed()
			if spd is not None:
				try:
					disp += ', TTF ' + TTF_str(dist, spd)
				except ValueError:
					pass
			self.mouseInfo.emit('To mouse: ' + disp)
	
	def _mouseInfo_elevation(self, radarXY):
		if env.elevation_map is not None:
			try:
				self.mouseInfo.emit('Elevation: %.1f' % env.elevation_map.elev(radarXY))
			except ValueError: # outside of map
				pass
	
	def mousePressEvent(self, event):
		QGraphicsScene.mousePressEvent(self, event)
		if not event.isAccepted():
			if event.button() == Qt.RightButton:
				self.using_special_tool = settings.session_manager.session_type == SessionType.TEACHER \
					and settings.session_manager.isRunning() and event.modifiers() & Qt.ShiftModifier
				self.measuring_tool.setPos(event.scenePos())
				self.measuring_tool.setDisplayDistances(not self.using_special_tool) # special tool if creating teacher traffic
				self.measuring_tool.startTool()
				if self.using_special_tool:
					self.mouseInfo.emit('Creating traffic...')
				else: # using normal measuring tool
					self._mouseInfo_elevation(RadarCoords.fromQPointF(event.scenePos()))
			if not event.button() == Qt.LeftButton or event.modifiers() & Qt.ShiftModifier: # not panning
				event.accept()
	
	def mouseMoveEvent(self, event):
		rxy = RadarCoords.fromQPointF(event.scenePos())
		if self.measuring_tool.isVisible():
			self.measuring_tool.updateMouseXY(event.scenePos())
			if not self.using_special_tool:
				self._mouseInfo_elevation(rxy)
		elif not event.isAccepted():
			self._mouseInfo_flyToMouse(rxy)
		QGraphicsScene.mouseMoveEvent(self, event)
	
	def mouseReleaseEvent(self, event):
		rxy = RadarCoords.fromQPointF(event.scenePos())
		if self.measuring_tool.isVisible() and event.button() in [Qt.LeftButton, Qt.RightButton]:
			hdg = self.measuring_tool.measuredHeading()
			if self.using_special_tool:
				if hdg is not None:
					stxy = RadarCoords.fromQPointF(self.measuring_tool.pos())
					signals.specialTool.emit(EarthCoords.fromRadarCoords(stxy), hdg)
			else: # using normal measuring tool
				if settings.measuring_tool_logs_coordinates:
					txt = EarthCoords.fromRadarCoords(self.measuring_tool.pos()).toString()
					if hdg is None: # static mouse click
						txt += ' (mouse click)'
					else:
						txt += ' to %s' % EarthCoords.fromRadarCoords(rxy).toString()
						txt += ' (%s°, %s)' % (hdg.read(), dist_str(self.measuring_tool.measuredDistance()))
					signals.measuringLogEntry.emit(txt)
				if hdg is not None:
					signals.hdgDistMeasured.emit(hdg, self.measuring_tool.measuredDistance())
			self.measuring_tool.stopTool()
		elif event.button() == Qt.LeftButton:
			if self.prevent_mouse_release_deselect or self.mouseGrabberItem() is not None:
				self.prevent_mouse_release_deselect = False
			else:
				selection.deselect()
		self._mouseInfo_flyToMouse(rxy)
		QGraphicsScene.mouseReleaseEvent(self, event)

	def mouseDoubleClickEvent(self, event):
		QGraphicsScene.mouseDoubleClickEvent(self, event)
		if not event.isAccepted() and event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier:
			text, ok = QInputDialog.getText(self.parent(), 'Add custom label', 'Text:')
			if ok and text.strip() != '':
				self.addCustomLabel(text, event.scenePos())
