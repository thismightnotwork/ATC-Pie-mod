
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

from math import log, exp
from sys import stderr

from PyQt5.QtCore import pyqtSignal, Qt, QThread
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMenu, QAction, QMessageBox, QInputDialog
from ui.radarScopePanel import Ui_radarScopePanel

from base.ad import AirportData
from base.nav import Navpoint, NavpointError
from base.strip import parsed_route_detail

from ext.xplane import get_airport_data

from gui.workspace import WorkspaceDockablePanel
from gui.misc import signals, selection, IconFile
from gui.widgets.adWidgets import AirportListSearchDialog
from gui.graphics.radarScene import Layer, RadarScene
from gui.graphics.radarTag import TextBoxItem
from gui.graphics.miscGraphics import BgPixmapItem
from gui.dialogs.bgImg import PositionBgImgDialog
from gui.dialogs.miscDialogs import RouteSpecsLostDialog

from session.config import settings
from session.env import env


# ---------- Constants ----------

max_zoom_factor = 1000
max_zoom_range = .1 # NM
init_zoom_level_AD = 50 # %
init_zoom_level_CTR = 20 # %
auto_bgimg_spec_file_prefix = 'auto-'

# -------------------------------



class AdDataReaderThread(QThread):
	airportDataReady = pyqtSignal(AirportData)
	
	def __init__(self, parent):
		QThread.__init__(self, parent)
		self.to_draw = [] # queue with head first
	
	def readAD(self, ad_code):
		self.to_draw.append(ad_code)
		self.start() # does nothing if already running
		
	def run(self):
		while len(self.to_draw) > 0:
			ad = self.to_draw.pop(0)
			try:
				self.airportDataReady.emit(get_airport_data(ad))
			except NavpointError:
				print('ERROR: No airport "%s" found. Please report with details.' % ad, file=stderr)





class ScopeFrame(WorkspaceDockablePanel, Ui_radarScopePanel): # is a QWidget
	def __init__(self):
		WorkspaceDockablePanel.__init__(self, defaultTitle='Radar scope')
		self.setupUi(self)
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.setWindowIcon(QIcon(IconFile.panel_radarScreen))
		self.setRadarTagTextBoxSizes()
		self.lockPanZoom_button.setIcon(QIcon(IconFile.pixmap_lock))
		self.AD_data_reader = AdDataReaderThread(self)
		self.mouse_info.clear()
		self.scene = RadarScene(self)
		self.scopeView.setScene(self.scene)
		self.courseLineFlyTime_edit.setValue(self.scene.speedMarkCount())
		self.last_airfield_clicked = None
		self.LDG_disp_actions = {}
		# BG IMAGES menu
		self.rebuildImgToggleMenu()
		# Nav menu
		nav_menu = QMenu(self)
		self._addMenuToggleAction(nav_menu, 'Navaids', True, self.scene.layers[Layer.NAV_AIDS].setVisible)
		self._addMenuToggleAction(nav_menu, 'Fixes', False, self.scene.layers[Layer.NAV_FIXES].setVisible)
		self._addMenuToggleAction(nav_menu, 'RNAV points', False, self.scene.layers[Layer.RNAV_POINTS].setVisible)
		nav_menu.addSeparator()
		self._addMenuToggleAction(nav_menu, 'Airfields', False, self.scene.layers[Layer.NAV_AIRFIELDS].setVisible)
		self.nav_menuButton.setMenu(nav_menu)
		# AD menu
		AD_menu = QMenu(self)
		self._addMenuToggleAction(AD_menu, 'Ground routes', False, self.scene.showGroundNetworks)
		self._addMenuToggleAction(AD_menu, 'Taxiway names', False, self.scene.showTaxiwayNames)
		self._addMenuToggleAction(AD_menu, 'Highlight TWYs under mouse', True, self.scene.highlightEdgesOnMouseover)
		self._addMenuToggleAction(AD_menu, 'RWY names always visible', False, self.scene.setRunwayNamesAlwaysVisible)
		AD_menu.addSeparator()
		self._addMenuToggleAction(AD_menu, 'Parking positions', True, self.scene.layers[Layer.PARKING_POSITIONS].setVisible)
		self._addMenuToggleAction(AD_menu, 'Holding lines', False, self.scene.layers[Layer.HOLDING_LINES].setVisible)
		self._addMenuToggleAction(AD_menu, 'Taxiway centre lines', False, self.scene.layers[Layer.TAXIWAY_LINES].setVisible)
		self._addMenuToggleAction(AD_menu, 'Other objects', True, self.scene.showMiscObjects)
		self.AD_menuButton.setMenu(AD_menu)
		# LDG menu
		if env.airport_data is None:
			self.LDG_menuButton.setEnabled(False)
		else:
			LDG_menu = QMenu(self)
			self.syncLDG_action = self._addMenuToggleAction(LDG_menu, 'Sync with arrival runway selection', True, self.setSyncLDG)
			for rwy in env.airport_data.directionalRunways(): # all menu options set to False below; normally OK at start
				txt = 'RWY %s' % rwy.name
				if rwy.ILS_cat is not None:
					txt += ' (%s)' % rwy.ILS_cat
				action = self._addMenuToggleAction(LDG_menu, txt, False, lambda b, r=rwy.name: self.scene.showLandingHelper(r, b))
				action.triggered.connect(lambda b: self.syncLDG_action.setChecked(False)) # cancel sync when one is set manually (triggered)
				self.LDG_disp_actions[rwy.name] = action
			LDG_menu.addSeparator()
			self._addMenuToggleAction(LDG_menu, 'Slope altitudes', True, self.scene.showSlopeAltitudes)
			self._addMenuToggleAction(LDG_menu, 'LOC interception cones', False, self.scene.showInterceptionCones)
			self.LDG_menuButton.setMenu(LDG_menu)
		# ACFT menu
		ACFT_menu = QMenu(self)
		self._addMenuToggleAction(ACFT_menu, 'Unlinked GND traffic', True, self.scene.showGndModes)
		self._addMenuToggleAction(ACFT_menu, 'Unlinked tags (compact)', True, self.scene.showUnlinkedTags)
		ACFT_menu.addSeparator()
		self._addMenuToggleAction(ACFT_menu, 'Selected ACFT full history', False, self.scene.showSelectionPositionHistory)
		self._addMenuToggleAction(ACFT_menu, 'Selected ACFT course/assignments', True, self.scene.showSelectionAssignments)
		self._addMenuToggleAction(ACFT_menu, 'All courses/vectors', False, self.scene.showVectors)
		self._addMenuToggleAction(ACFT_menu, 'All known routes', False, self.scene.showRoutes)
		ACFT_menu.addSeparator()
		self.machNumbers_action = self._addMenuToggleAction(ACFT_menu, 'Mach speeds', False, self.scene.showMachNumbers)
		self._addMenuToggleAction(ACFT_menu, 'Rack sequence numbers', False, self.scene.showSequenceNumbers)
		self._addMenuToggleAction(ACFT_menu, 'Separation rings', False, self.scene.showSeparationRings)
		self.ACFT_menuButton.setMenu(ACFT_menu)
		# OPTIONS menu
		options_menu = QMenu(self)
		self.autoCentre_action = self._addMenuToggleAction(options_menu, 'Centre on indications', False, None)
		self._addMenuToggleAction(options_menu, 'Show custom labels', True, self.scene.layers[Layer.CUSTOM_LABELS].setVisible)
		self.showRdfLine_action = self._addMenuToggleAction(options_menu, 'Show RDF line', False, self.scene.showRdfLine)
		self.rotateScreen_action = QAction('Set screen rotation...', self)
		self.rotateScreen_action.triggered.connect(self.setScreenRotationAction)
		options_menu.addAction(self.rotateScreen_action)
		options_menu.addSeparator()
		drawAirport_action = QAction('Draw additional airport...', self)
		drawAirport_action.triggered.connect(self.drawAdditionalAirport)
		resetAirports_action = QAction('Reset drawn airports', self)
		resetAirports_action.triggered.connect(self.scene.resetAirportItems)
		options_menu.addAction(drawAirport_action)
		options_menu.addAction(resetAirports_action)
		self.options_menuButton.setMenu(options_menu)
		# Other actions and signals
		self.lockPanZoom_button.toggled.connect(self.lockRadar)
		self.courseLineFlyTime_edit.valueChanged.connect(self.scene.setSpeedMarkCount)
		self.scene.mouseInfo.connect(self.mouse_info.setText)
		self.scene.addRemoveRouteNavpoint.connect(self.addRemoveRouteNavpointToSelection)
		self.scene.imagesRedrawn.connect(self.rebuildImgToggleMenu)
		self.zoomLevel_slider.valueChanged.connect(self.changeZoomLevel)
		self.scopeView.zoom_signal.connect(self.zoom)
		self.AD_data_reader.airportDataReady.connect(self._drawAdditionalAirportData)
		# External signal connections below. CAUTION: these must all be disconnected on widget deletion
		signals.toggleMachNumbers.connect(self.machNumbers_action.trigger)
		signals.selectionChanged.connect(self.mouse_info.clear)
		signals.adSfcUseChanged.connect(self.updateLdgMenuAndDisplay)
		signals.locationSettingsChanged.connect(self.updateRdfMenuAction)
		signals.navpointClick.connect(self.setLastAirfieldClicked)
		signals.indicatePoint.connect(self.indicatePoint)
		signals.mainStylesheetApplied.connect(self.setRadarTagTextBoxSizes)
		# Finish up
		self.sync_LDG_display = True
		self.updateLdgMenuAndDisplay()
		self.updateRdfMenuAction()
		self.f_scale = lambda x: max_zoom_factor / exp(x * log(settings.map_range / max_zoom_range)) # x in [0, 1]
		self.zoomLevel_slider.setValue(init_zoom_level_CTR if env.airport_data is None else init_zoom_level_AD)
		self.scopeView.moveToShow(env.radarPos())
	
	def _addMenuToggleAction(self, menu, text, init_state, toggle_function):
		action = QAction(text, self)
		action.setCheckable(True)
		menu.addAction(action)
		action.setChecked(init_state)
		if toggle_function is not None:
			toggle_function(init_state)
			action.toggled.connect(toggle_function)
		return action
	
	def setRadarTagTextBoxSizes(self):
		TextBoxItem.setBoxSizesFromTextFont(self.scopeView.font())
	
	def indicatePoint(self, coords):
		if env.pointOnMap(coords):
			if not self.lockPanZoom_button.isChecked() and self.autoCentre_action.isChecked():
				self.scopeView.moveToShow(coords)
			# if not in view: mouse_info
			self.scene.indicatePoint(coords)
		else:
			self.mouse_info.setText('Point is ' + env.mapLocStr(coords))
	
	
	## GUI UPDATES
	
	def rebuildImgToggleMenu(self):
		img_list = self.scene.layerItems(Layer.BG_IMAGES)
		img_menu = QMenu(self)
		for img_item in img_list:
			self._addMenuToggleAction(img_menu, img_item.title, False, img_item.setVisible)
		self.bgImg_menuButton.setMenu(img_menu)
		self.bgImg_menuButton.setEnabled(img_list != [])
	
	def setLastAirfieldClicked(self, navpoint):
		if navpoint.type == Navpoint.AD:
			self.last_airfield_clicked = navpoint
	
	def updateRdfMenuAction(self):
		self.showRdfLine_action.setEnabled(settings.radio_direction_finding)
	
	def updateLdgMenuAndDisplay(self):
		if self.sync_LDG_display and env.airport_data is not None:
			for rwy, action in self.LDG_disp_actions.items():
				action.setChecked(env.airport_data.runway(rwy).use_for_arrivals)
	
	def changeZoomLevel(self, percent_level):
		"""
		percent_level is a value in [0, 100]
		"""
		self.scopeView.setScaleFactor(self.f_scale(1 - percent_level / 100))
	
	
	## ACTIONS
	
	def setSyncLDG(self, toggle):
		self.sync_LDG_display = toggle
		if toggle:
			self.updateLdgMenuAndDisplay()
	
	def setScreenRotationAction(self):
		value, ok = QInputDialog.getDouble(self, 'Set screen rotation', 'Degrees from true North at top (clockwise):',
				value=self.scene.currentRotation(), min=0, max=359.9, decimals=1)
		if ok:
			self.setScreenRotation(value)

	def setScreenRotation(self, rot):
		self.scopeView.rotate(rot - self.scene.currentRotation())
		self.scene.updateAfterViewRotation(rot)
	
	def drawAdditionalAirport(self):
		init = '' if self.last_airfield_clicked is None else self.last_airfield_clicked.code
		dialog = AirportListSearchDialog(self, env.navpoints, initCodeFilter=init)
		dialog.exec()
		if dialog.result() > 0:
			self.AD_data_reader.readAD(dialog.selectedAirport().code)
			self.last_airfield_clicked = None
	
	def _drawAdditionalAirportData(self, ad_data):
		self.scene.drawAdditionalAirportData(ad_data)
		self.indicatePoint(ad_data.navpoint.coordinates)
	
	def zoom(self, zoom_in):
		step = self.zoomLevel_slider.pageStep()
		if not zoom_in: # zooming OUT
			step = -step
		self.zoomLevel_slider.setValue(self.zoomLevel_slider.value() + step)
	
	def lockRadar(self, lock):
		scroll = Qt.ScrollBarAlwaysOff if lock else Qt.ScrollBarAsNeeded
		self.scopeView.setVerticalScrollBarPolicy(scroll)
		self.scopeView.setHorizontalScrollBarPolicy(scroll)
		self.zoomLevel_slider.setVisible(not lock)
		self.autoCentre_action.setEnabled(not lock)
		self.rotateScreen_action.setEnabled(not lock)
		self.scene.lockMousePanAndZoom(lock)
	
	def positionVisibleBgImages(self):
		imglst_all = self.scene.layerItems(Layer.BG_IMAGES)
		imglst_moving = [item for item in imglst_all if item.isVisible() and isinstance(item, BgPixmapItem)]
		PositionBgImgDialog(imglst_moving, self).exec()
		file_name = settings.outputFileName(auto_bgimg_spec_file_prefix + settings.location_code, ext='lst', windowID=False)
		with open(file_name, 'w', encoding='utf8') as f:
			for item in imglst_all:
				print(item.specLine(), file=f)
			for src, img, scale, title in settings.loose_strip_bay_backgrounds:
				print('%s\tLOOSE %g\t%s' % (src, scale, title), file=f)
		if imglst_moving:
			QMessageBox.information(self, 'Image positioning', 'Changes have so far only affected the radar in the main window.'
				' If you like it the way it is, make sure you update your .lst file and reload your images.'
				'\nFile %s was generated with your new corner coordinates for you to copy.' % file_name)
	
	def addRemoveRouteNavpointToSelection(self, navpoint):
		strip = selection.strip
		if strip is None:
			QMessageBox.critical(self, 'Add/remove point to route', 'No strip in current selection.')
			return
		route = strip.lookup(parsed_route_detail)
		if route is None:
			QMessageBox.critical(self, 'Add/remove point to route', 'Departure or arrival airport not recognised on strip.')
			return
		dialog = None
		if navpoint in route: # Remove navpoint from route
			lost_before, lost_after = strip.removeRouteWaypoint(navpoint)
			if lost_before != [] or lost_after != []:
				dialog = RouteSpecsLostDialog(self, 'Waypoint %s removed' % navpoint,
						'%s [%s] %s' % (' '.join(lost_before), navpoint, ' '.join(lost_after)))
		else: # Add navpoint to route
			lost_specs = strip.insertRouteWaypoint(navpoint)
			if lost_specs:
				dialog = RouteSpecsLostDialog(self, 'Waypoint %s inserted' % navpoint, ' '.join(lost_specs))
		if dialog is not None:
			dialog.exec()
			if dialog.mustOpenStripDetails():
				signals.stripEditRequest.emit(strip)
		signals.stripInfoChanged.emit()
	
	
	## SAVED STATES
	
	def stateSave(self):
		if self.lockPanZoom_button.isChecked():
			xy = self.scopeView.mapToScene(self.scopeView.viewport().rect().center())
			res = {
				'lock': '1',
				'zoom': str(self.zoomLevel_slider.value()),
				'centre_x': str(xy.x()),
				'centre_y': str(xy.y())
			}
		else:
			res = {'lock': '0'}
		res['rotation'] = str(self.scene.currentRotation())
		res['cvline_fly_time'] = str(self.courseLineFlyTime_edit.value())
		res['draw_ad'] = self.scene.drawnAirports()
		res['pin_navpoint'] = ['%s~%s' % (p, p.coordinates.toString()) for p in self.scene.pinnedNavpoints()]
		res['pin_pkg'] = ['%s %s' % (ad, pos) for ad, pos in self.scene.pinnedParkingPositions()]
		res['label'] = ['%s %s' % (pos.toString(), lbl) for pos, lbl in self.scene.customLabels()]
		for menu_button, menu_attr in (self.bgImg_menuButton, 'bg_menu'), (self.nav_menuButton, 'nav_menu'), \
				(self.AD_menuButton, 'ad_menu'), (self.LDG_menuButton, 'ldg_menu'), \
				(self.ACFT_menuButton, 'acft_menu'), (self.options_menuButton, 'opts_menu'):
			menu = menu_button.menu()
			if menu is not None:
				menu_state = 0
				for i, action in enumerate(menu.actions()):
					menu_state |= int(action.isChecked()) << i
				res[menu_attr] = str(menu_state)
		return res
	
	def restoreState(self, saved_state):
		# lock/pan/zoom
		try:
			radar_locked = bool(int(saved_state['lock']))
			self.lockPanZoom_button.setChecked(radar_locked)
			if radar_locked:
				self.zoomLevel_slider.setValue(int(saved_state['zoom']))
				self.scopeView.centerOn(float(saved_state['centre_x']), float(saved_state['centre_y']))
			self.setScreenRotation(float(saved_state['rotation']))
		except (KeyError, ValueError):
			pass
		# menu options
		for menu_button, menu_attr in (self.bgImg_menuButton, 'bg_menu'), (self.nav_menuButton, 'nav_menu'), \
				(self.AD_menuButton, 'ad_menu'), (self.LDG_menuButton, 'ldg_menu'), \
				(self.ACFT_menuButton, 'acft_menu'), (self.options_menuButton, 'opts_menu'):
			menu = menu_button.menu()
			if menu is not None:
				try:
					menu_state = int(saved_state[menu_attr])
					for i, action in enumerate(menu.actions()):
						if action.isCheckable() and action.isChecked() != bool(1 << i & menu_state):
							action.toggle()
				except KeyError:
					pass
		if self.sync_LDG_display:
			self.updateLdgMenuAndDisplay()
		# course/vector line fly time
		try:
			self.courseLineFlyTime_edit.setValue(int(saved_state['cvline_fly_time']))
		except (KeyError, ValueError):
			pass
		# additional ADs
		for ad in saved_state.get('draw_ad', []):
			self.scene.drawAdditionalAirportData(get_airport_data(ad)) # STYLE check if data exists?
		# pinned points
		for spec in saved_state.get('pin_navpoint', []): # str specs
			try:
				self.scene.pinNavpoint(env.navpoints.fromSpec(spec))
			except NavpointError:
				print('Cannot identify navpoint to pin: %s' % spec, file=stderr)
		for spec in saved_state.get('pin_pkg', []): # ad+pkg specs
			split = spec.split(maxsplit=1)
			if len(split) == 2:
				self.scene.pinPkgPos(*split)
			else:
				print('Cannot identify parking position to pin: %s' % spec, file=stderr)
		# custom labels
		for spec in saved_state.get('label', []): # ad+pkg specs
			split = spec.split(maxsplit=1)
			if len(split) == 2:
				try:
					self.scene.addCustomLabel(split[1], env.navpoints.coordsFromPointSpec(split[0]).toQPointF())
				except NavpointError:
					print('Cannot restore label: bad position string "%s"' % split[0], file=stderr)
			else:
				print('Cannot restore label (missing text or position): %s' % spec, file=stderr)
	
	
	## CLOSING

	def closeEvent(self, event):
		self.AD_data_reader.wait()
		self.scene.prepareForDeletion()
		signals.toggleMachNumbers.disconnect(self.machNumbers_action.trigger)
		signals.selectionChanged.disconnect(self.mouse_info.clear)
		signals.adSfcUseChanged.disconnect(self.updateLdgMenuAndDisplay)
		signals.locationSettingsChanged.disconnect(self.updateRdfMenuAction)
		signals.navpointClick.disconnect(self.setLastAirfieldClicked)
		signals.indicatePoint.disconnect(self.indicatePoint)
		signals.mainStylesheetApplied.disconnect(self.setRadarTagTextBoxSizes)
		event.accept()
		WorkspaceDockablePanel.closeEvent(self, event)
