
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
from ui.towerViewCtrlPanel import Ui_towerViewCtrlPanel

from base.params import Heading

from session.config import settings
from session.env import env

from ext.fgfs import initial_FOV
from gui.misc import signals, selection


# ---------- Constants ----------

true_panel_directions = True

# -------------------------------

class TowerViewControllerPanel(QWidget, Ui_towerViewCtrlPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self._dir_rwys = self._helipads = []
		if env.airport_data is not None:
			self._dir_rwys = env.airport_data.directionalRunways()
			self._helipads = env.airport_data.helipads()
			self.runwayHelipad_select.addItems(rwy.name for rwy in self._dir_rwys)
			self.runwayHelipad_select.addItems(hpad.name for hpad in self._helipads)
			self.runwayHelipad_select.currentIndexChanged.connect(lambda i: self.runwayPoint_select.setEnabled(i < len(self._dir_rwys)))
		self.setEnabled(False)
		self.target_acft = None
		signals.towerViewToggled.connect(self.setEnabled)
		self.lookAtAircraft_OK_button.clicked.connect(self.lookAtSelectedAircraft)
		self.lookAtRwyHelipad_OK_button.clicked.connect(self.lookAtRwyHelipad)
		self.lookAtLastRdf_OK_button.clicked.connect(self.lookAtLastRdf)
		self.lookNorth_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(360, true_panel_directions)))
		self.lookNE_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(45, true_panel_directions)))
		self.lookEast_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(90, true_panel_directions)))
		self.lookSE_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(135, true_panel_directions)))
		self.lookSouth_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(180, true_panel_directions)))
		self.lookSW_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(225, true_panel_directions)))
		self.lookWest_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(270, true_panel_directions)))
		self.lookNW_button.clicked.connect(lambda: settings.controlled_tower_viewer.lookInDirection(Heading(315, true_panel_directions)))
		self.useBinoculars_button.clicked.connect(lambda: settings.controlled_tower_viewer.setFOV(initial_FOV / self.binocularsFactor_edit.value()))
		self.dropBinoculars_button.clicked.connect(lambda: settings.controlled_tower_viewer.setFOV(initial_FOV))

	def _targetAircraftPositionNoFail(self):
		if self.target_acft is None: # safeguard because may be called back by tower view tracker after a target_acft reset (return an arbitrary default point)
			pt, alt = env.viewpoint()
			return pt.moved(Heading(360, True), 1), alt
		else:
			pos = self.target_acft.liveCoords()
			try:
				return pos, self.target_acft.liveRealAlt()
			except ValueError: # happens with PlaybackAcft when not enough radar data to work out a real altitude
				return pos, env.viewpoint()[1]
	
	def lookAtSelectedAircraft(self):
		self.target_acft = selection.acft
		if self.target_acft is None:
			settings.controlled_tower_viewer.stopTracking()
		elif self.trackAircraft_tickBox.isChecked():
			settings.controlled_tower_viewer.startTracking(self._targetAircraftPositionNoFail) # callback argument
		else:
			settings.controlled_tower_viewer.lookAtPoint(*self._targetAircraftPositionNoFail()) # stops tracking
		
	def lookAtRwyHelipad(self):
		index = self.runwayHelipad_select.currentIndex()
		if index < len(self._dir_rwys): # RWY selected
			if self.runwayPoint_select.currentIndex() == 0: # RWY threshold
				p = self._dir_rwys[index].threshold()
			else: # RWY far end point
				p = self._dir_rwys[index].opposite().threshold()
		else: # helipad selected
			p = self._helipads[index - len(self._dir_rwys)].centre
		settings.controlled_tower_viewer.lookAtPoint(p, env.elevation(p)) # stops tracking

	def lookAtLastRdf(self):
		sig = env.rdf.latestSignal()
		if sig is not None:
			settings.controlled_tower_viewer.lookInDirection(sig.direction)
