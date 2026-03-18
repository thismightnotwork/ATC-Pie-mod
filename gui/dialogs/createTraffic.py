
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

from PyQt5.QtWidgets import QDialog, QDialogButtonBox
from ui.createTrafficDialog import Ui_createTrafficDialog

from ai.status import Status, FlightParams

from base.util import some
from base.db import all_airline_codes, all_aircraft_types, cruise_speed, acft_cat
from base.params import PressureAlt, Speed

from gui.misc import RadioKeyEventFilter

from session.config import settings
from session.env import env, generate_unused_callsign, CallsignGenerationError
from session.manager import student_callsign, teacher_callsign


# ---------- Constants ----------

max_spawn_DEP_dist = .25 # NM
max_spawn_PKG_dist = .05 # NM
max_spawn_GND_dist = 1 # NM

# -------------------------------


class CreateTrafficDialog(QDialog, Ui_createTrafficDialog):
	last_known_acft_type_used = 'B772'
	last_strip_link = True
	last_start_frozen = False

	def __init__(self, spawn_coords, spawn_hdg, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.createAircraftType_edit.setAircraftFilter(lambda t: cruise_speed(t) is not None)
		self.airline_codes = all_airline_codes()
		self.createAircraftType_edit.setEditText(CreateTrafficDialog.last_known_acft_type_used)
		self.startFrozen_tickBox.setChecked(CreateTrafficDialog.last_start_frozen)
		self.createStripLink_tickBox.setChecked(CreateTrafficDialog.last_strip_link)
		self.suggestCallsign()
		if env.airport_data is None:
			self.allow_taxi = False
			self.closest_PKG = None
			self.nearby_THRs = []
			self.nearby_helipads = []
		else: # AD mode
			self.allow_taxi = env.airport_data.ground_net.closestNode(spawn_coords, maxdist=max_spawn_GND_dist) is not None
			self.closest_PKG = env.airport_data.ground_net.closestParkingPosition(spawn_coords, maxdist=max_spawn_PKG_dist)
			self.nearby_THRs = [rwy for rwy in env.airport_data.directionalRunways() if rwy.threshold().distanceTo(spawn_coords) <= max_spawn_DEP_dist]
			self.nearby_helipads = [hpad for hpad in env.airport_data.helipads() if hpad.centre.distanceTo(spawn_coords) <= max_spawn_DEP_dist]
			self.depSurface_select.addItems(sfc.name for sfc in self.nearby_THRs + self.nearby_helipads)
		self.closestParkingPosition_info.setText(some(self.closest_PKG, ''))
		self.spawn_coords = spawn_coords
		self.spawn_hdg = spawn_hdg
		if self.allow_taxi:
			self.taxi_status_radioButton.toggled.connect(self.toggleGroundStatus)
			self.taxi_status_radioButton.setChecked(True)
			if self.closest_PKG is not None:
				self.parked_tickBox.setChecked(True)
		else:
			self.taxi_status_radioButton.setEnabled(False)
			self.toggleGroundStatus(False)
		self.depSurface_select.setEnabled(False)
		if len(self.nearby_THRs) + len(self.nearby_helipads) == 0:
			self.ready_status_radioButton.setEnabled(False)
		elif self.closest_PKG is None: # initialising to "ready for DEP"
			self.ready_status_radioButton.setChecked(True)
		self.updateButtons()
		self.createCallsign_edit.textChanged.connect(self.updateButtons)
		self.createAircraftType_edit.editTextChanged.connect(self.updateButtons)
		self.ready_status_radioButton.toggled.connect(self.updateButtons)
		self.depSurface_select.currentIndexChanged.connect(self.updateButtons)
		self.createAircraftType_edit.editTextChanged.connect(self.suggestCallsign)
		self.accepted.connect(self.rememberOptions)
	
	def toggleGroundStatus(self, toggle):
		self.parked_tickBox.setEnabled(toggle and self.closest_PKG is not None)
		self.closestParkingPosition_info.setEnabled(toggle and self.closest_PKG is not None)
	
	def suggestCallsign(self):
		t = self.createAircraftType_edit.getAircraftType()
		if t in all_aircraft_types():
			try:
				self.createCallsign_edit.setText(generate_unused_callsign(t, self.airline_codes))
			except CallsignGenerationError:
				self.createCallsign_edit.clear()
	
	def updateButtons(self):
		cs = self.createCallsign_edit.text()
		t = self.createAircraftType_edit.getAircraftType()
		ok = cs not in ['', student_callsign, teacher_callsign]
		ok &= cs not in env.ATCs.knownAtcCallsigns()
		ok &= all(cs != c for c in env.knownAcftCallsigns(sessionMgr=True))
		ok &= t in all_aircraft_types() and cruise_speed(t) is not None
		if self.ready_status_radioButton.isChecked():
			try:
				ok &= self.nearby_THRs[self.depSurface_select.currentIndex()].acceptsAcftType(t)
			except IndexError:
				ok &= acft_cat(t) == 'helos'
		self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(ok)

	def acftCallsign(self):
		return self.createCallsign_edit.text()
	
	def acftType(self):
		return self.createAircraftType_edit.getAircraftType()
	
	def startFrozen(self):
		return self.startFrozen_tickBox.isChecked()
	
	def createStrip(self):
		return self.createStripLink_tickBox.isChecked()
	
	def acftInitParamsAndStatus(self):
		if self.taxi_status_radioButton.isChecked():
			status = Status(airborne=False)
		elif self.ready_status_radioButton.isChecked():
			isfc = self.depSurface_select.currentIndex()
			status = Status.mkReadyForDep(self.nearby_THRs[isfc] if isfc < len(self.nearby_THRs) else self.nearby_helipads[isfc - len(self.nearby_THRs)])
		else: # airborne status radio button must be ticked
			status = Status(airborne=True)
		pos = self.spawn_coords
		hdg = self.spawn_hdg
		if self.airborne_status_radioButton.isChecked():
			alt = PressureAlt.fromFL(self.airborneFL_edit.value())
			ias = cruise_speed(self.createAircraftType_edit.getAircraftType()).tas2ias(alt)
		else: # on ground
			alt = env.groundPressureAlt(pos)
			ias = Speed(0)
			if self.parked_tickBox.isChecked() and self.closest_PKG is not None:
				pkinf = env.airport_data.ground_net.parkingPosInfo(self.closest_PKG)
				pos = pkinf[0]
				hdg = pkinf[1]
		return FlightParams(pos, alt, hdg, ias, xpdrCode=settings.uncontrolled_VFR_XPDR_code), status
	
	def rememberOptions(self): # on dialog accept
		t = self.acftType()
		if t in all_aircraft_types(): # normally it is since we do not allow others for now
			CreateTrafficDialog.last_known_acft_type_used = t
		CreateTrafficDialog.last_strip_link = self.createStrip()
		CreateTrafficDialog.last_start_frozen = self.startFrozen()
