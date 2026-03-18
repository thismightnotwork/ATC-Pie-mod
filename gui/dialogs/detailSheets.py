
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

from datetime import timedelta, timezone

from PyQt5.QtWidgets import QDialog
from PyQt5.QtCore import QDateTime
from PyQt5.QtGui import QIcon

from ui.fplDetailsDialog import Ui_fplDetailsDialog
from ui.stripDetailsDialog import Ui_stripDetailsDialog

from base.db import wake_turb_cat
from base.fpl import FPL
from base.route import Route
from base.strip import rack_detail, assigned_SQ_detail, assigned_heading_detail, assigned_speed_detail, assigned_altitude_detail
from base.util import some

from gui.misc import IconFile, RadioKeyEventFilter
from gui.dialogs.routeInfo import RouteDialog
from gui.widgets.basicWidgets import flash_widget, recognisedValue_lineEdit_styleSheet

from session.config import settings
from session.env import env


# ---------- Constants ----------

unracked_strip_str = '(unracked)'

# -------------------------------


def FPL_match_test(callsign_filter, fpl):
	return fpl.onlineStatus() != FPL.CLOSED \
			and env.linkedStrip(fpl) is None \
			and callsign_filter.upper() in some(fpl[FPL.CALLSIGN], '').upper() \
			and fpl.flightIsInTimeWindow(timedelta(hours=24))



class SharedDetailSheet:
	"""
	WARNING! Methods to define in subclasses:
	- get_detail (reads from strip or FPL)
	- set_detail (writes to strip or FPL)
	- resetData (should call this resetData after doing its additional work)
	- saveChangesAndClose (call this shared saveChangesAndClose)
	"""
	def __init__(self):
		self.route_edit.viewRoute_signal.connect(self.viewRoute)
		self.depAirportPicker_widget.recognised.connect(self.route_edit.setDEP)
		self.arrAirportPicker_widget.recognised.connect(self.route_edit.setARR)
		self.depAirportPicker_widget.unrecognised.connect(lambda: self.route_edit.setDEP(None))
		self.arrAirportPicker_widget.unrecognised.connect(lambda: self.route_edit.setARR(None))
		self.resetData()
		if settings.use_known_aircraft:
			#TODO self.autoFillAcftType_button.setChecked(last state); also for WTC?
			self.callsign_edit.textChanged.connect(self.autoFillAcftTypeFromCallsign)
			self.autoFillAcftType_button.toggled.connect(self.autoFillAcftTypeToggled)
		else:
			self.autoFillAcftType_button.hide()
		self.aircraftType_edit.editTextChanged.connect(self.autoFillWtcFromAcftType)
		self.autoFillWTC_button.toggled.connect(self.autoFillWtcToggled)
		self.buttonBox.accepted.connect(self.saveChangesAndClose)
		self.buttonBox.rejected.connect(self.reject)

	def autoFillAcftTypeFromCallsign(self, cs):
		if settings.use_known_aircraft and self.autoFillAcftType_button.isChecked():
			cs_upper = cs.upper()
			try:
				self.aircraftType_edit.setCurrentText(settings.known_aircraft[cs_upper])
				flash_widget(self.aircraftType_edit.lineEdit(), recognisedValue_lineEdit_styleSheet)
				self.callsign_edit.setText(cs_upper)
			except KeyError:
				pass
	
	def autoFillWtcFromAcftType(self, dez):
		if self.autoFillWTC_button.isChecked():
			self.wakeTurbCat_select.setCurrentText(some(wake_turb_cat(dez), ''))

	def autoFillAcftTypeToggled(self, toggle):
		if toggle:
			self.autoFillAcftTypeFromCallsign(self.callsign_edit.text())
	
	def autoFillWtcToggled(self, toggle):
		if toggle:
			self.autoFillWtcFromAcftType(self.aircraftType_edit.currentText())
	
	def viewRoute(self):
		origin_AD = self.depAirportPicker_widget.recognisedAirfield()
		dest_AD = self.arrAirportPicker_widget.recognisedAirfield()
		if origin_AD is not None and dest_AD is not None:
			route_to_view = Route(origin_AD, dest_AD, self.route_edit.getRouteText())
			tas = self.TAS_edit.speedValue() if self.TAS_enable.isChecked() else None
			RouteDialog(route_to_view, speedHint=tas, acftHint=self.aircraftType_edit.getAircraftType(), parent=self).exec()
	
	def resetData(self):
		# FPL.CALLSIGN
		self.callsign_edit.setText(some(self.get_detail(FPL.CALLSIGN), ''))
		#	FLIGHT_RULES
		self.flightRules_select.setCurrentText(some(self.get_detail(FPL.FLIGHT_RULES), ''))
		# FPL.ACFT_TYPE
		self.aircraftType_edit.setCurrentText(some(self.get_detail(FPL.ACFT_TYPE), ''))
		# FPL.WTC
		self.wakeTurbCat_select.setCurrentText(some(self.get_detail(FPL.WTC), ''))
		# FPL.ICAO_DEP
		self.depAirportPicker_widget.setEditText(some(self.get_detail(FPL.ICAO_DEP), ''))
		# FPL.ICAO_ARR
		self.arrAirportPicker_widget.setEditText(some(self.get_detail(FPL.ICAO_ARR), ''))
		#	ROUTE
		self.route_edit.setRouteText(some(self.get_detail(FPL.ROUTE), ''))
		# CRUISE_ALT
		cr_alt = self.get_detail(FPL.CRUISE_ALT)
		self.cruiseAlt_enable.setChecked(cr_alt is not None)
		if cr_alt is not None:
			self.cruiseAlt_edit.setAltFlSpec(cr_alt)
		#	TAS
		tas = self.get_detail(FPL.TAS)
		self.TAS_enable.setChecked(tas is not None)
		if tas is not None:
			self.TAS_edit.setSpeedValue(tas)
		#	COMMENTS
		self.comments_edit.setPlainText(some(self.get_detail(FPL.COMMENTS), ''))
		self.callsign_edit.setFocus()
		
	def saveChangesAndClose(self):
		# FPL.CALLSIGN
		self.set_detail(FPL.CALLSIGN, self.callsign_edit.text().upper())
		# FPL.FLIGHT_RULES
		self.set_detail(FPL.FLIGHT_RULES, self.flightRules_select.currentText())
		# FPL.ACFT_TYPE
		self.set_detail(FPL.ACFT_TYPE, self.aircraftType_edit.getAircraftType())
		# FPL.WTC
		self.set_detail(FPL.WTC, self.wakeTurbCat_select.currentText())
		# FPL.ICAO_DEP
		self.set_detail(FPL.ICAO_DEP, self.depAirportPicker_widget.currentText())
		# FPL.ICAO_ARR
		self.set_detail(FPL.ICAO_ARR, self.arrAirportPicker_widget.currentText())
		# FPL.ROUTE
		self.set_detail(FPL.ROUTE, self.route_edit.getRouteText())
		# FPL.CRUISE_ALT
		self.set_detail(FPL.CRUISE_ALT, (self.cruiseAlt_edit.altFlSpec() if self.cruiseAlt_enable.isChecked() else None))
		# FPL.TAS
		self.set_detail(FPL.TAS, (self.TAS_edit.speedValue() if self.TAS_enable.isChecked() else None))
		# FPL.COMMENTS
		self.set_detail(FPL.COMMENTS, self.comments_edit.toPlainText())





# =========== STRIP =========== #

class StripDetailSheetDialog(QDialog, Ui_stripDetailsDialog, SharedDetailSheet):
	def __init__(self, gui, strip):
		QDialog.__init__(self, gui)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.setWindowIcon(QIcon(IconFile.pixmap_strip))
		self.assignedAltitude_edit.syncWithEnv(True)
		self.strip = strip
		self.FPL_matches = [] # flight plans matching the last callsign edit
		self.selected_FPL_link = None # last deliberate FPL selection among matches
		if self.strip.lookup(rack_detail) is None: # unracked strip
			self.rack_select.addItem(unracked_strip_str)
			self.rack_select.setEnabled(False)
		else:
			self.rack_select.addItems(env.strips.rackNames())
		self.callsign_edit.textChanged.connect(self.updateDupLabel)
		self.depAirportPicker_widget.recognised.connect(lambda ad: self.depAirportName_info.setText(ad.long_name))
		self.arrAirportPicker_widget.recognised.connect(lambda ad: self.arrAirportName_info.setText(ad.long_name))
		self.depAirportPicker_widget.unrecognised.connect(self.depAirportName_info.clear)
		self.arrAirportPicker_widget.unrecognised.connect(self.arrAirportName_info.clear)
		self.cruiseAlt_enable.toggled.connect(self.assignCruiseAlt_button.setEnabled)
		self.assignCruiseAlt_button.clicked.connect(self.assignCruiseLevel)
		SharedDetailSheet.__init__(self) # this will fill some fields
		self.updateDupLabel(self.callsign_edit.text())
		fpl = self.strip.linkedFPL()
		if fpl is None:
			self.linkedFpl_widget.hide()
			self.callsign_edit.textChanged.connect(self.updateMatchingFPLs)
			self.linkFpl_select.activated.connect(self.selectFplToLink) # triggers only on deliberate selection
			self.updateMatchingFPLs(self.callsign_edit.text())
		else: # a flight plan is already linked
			self.linkFpl_widget.hide()
			self.linkedFplStatus_info.setText({FPL.FILED: 'filed online', FPL.OPEN: 'open', FPL.CLOSED: 'closed'}.get(fpl.onlineStatus(), 'not online'))
			self.linkedFplStatus_info.setToolTip(fpl.shortDescr())

	def updateDupLabel(self, cs):
		self.duplicateCallsign_label.setVisible(cs != '' and any(s is not self.strip
				and s.callsign() is not None and s.callsign().upper() == cs.upper() for s in env.strips.listAll()))
	
	def updateMatchingFPLs(self, cs):
		self.FPL_matches = env.FPLs.findAll(lambda fpl: FPL_match_test(cs, fpl))
		self.linkFpl_select.clear()
		self.linkFpl_select.addItem('none')
		self.linkFpl_select.addItems(fpl.shortDescr() for fpl in self.FPL_matches)
		self.linkFpl_matching_info.setText('(%i)' % len(self.FPL_matches))
		self.linkFpl_select.setCurrentIndex(next((i for i, fpl in enumerate(self.FPL_matches, start=1) if self.selected_FPL_link is fpl), 0))

	def selectFplToLink(self, index): # deliberate selection
		if index == 0:
			self.selected_FPL_link = None
		else:
			self.selected_FPL_link = self.FPL_matches[index - 1]
			cs = self.selected_FPL_link[FPL.CALLSIGN]
			if cs is not None:
				self.callsign_edit.setText(cs)
				self.callsign_edit.selectAll()
				self.callsign_edit.setFocus()
	
	def assignCruiseLevel(self):
		self.assignedAltitude_edit.setAltFlSpec(self.cruiseAlt_edit.altFlSpec())
		self.assignAltitude.setChecked(True)

	def get_detail(self, detail):
		return self.strip.lookup(detail)
	
	def set_detail(self, detail, new_val):
		self.strip.writeDetail(detail, new_val)
	
	def selectedRack(self):
		return None if self.strip.lookup(rack_detail) is None else self.rack_select.currentText()
	
	def resetData(self):
		## Rack
		self.rack_select.setCurrentText(some(self.strip.lookup(rack_detail), unracked_strip_str))
		## Assigned stuff
		# Squawk code
		assSQ = self.strip.lookup(assigned_SQ_detail)
		self.assignSquawkCode.setChecked(assSQ is not None)
		if assSQ is not None:
			self.xpdrCode_select.setSQ(assSQ)
		# Heading
		assHdg = self.strip.lookup(assigned_heading_detail)
		self.assignHeading.setChecked(assHdg is not None)
		if assHdg is not None:
			self.assignedHeading_edit.setValue(int(assHdg.read()))
		# Altitude/FL
		assAlt = self.strip.lookup(assigned_altitude_detail)
		self.assignAltitude.setChecked(assAlt is not None)
		if assAlt is not None:
			self.assignedAltitude_edit.setAltFlSpec(assAlt)
		# Speed
		assSpd = self.strip.lookup(assigned_speed_detail)
		self.assignSpeed.setChecked(assSpd is not None)
		if assSpd is not None:
			self.assignedSpeed_edit.setSpeedValue(assSpd)
		SharedDetailSheet.resetData(self)
	
	def saveChangesAndClose(self):
		SharedDetailSheet.saveChangesAndClose(self)
		## Assigned stuff
		# Squawk code
		if self.assignSquawkCode.isChecked():
			self.set_detail(assigned_SQ_detail, self.xpdrCode_select.getSQ())
		else:
			self.set_detail(assigned_SQ_detail, None)
		# Heading
		if self.assignHeading.isChecked():
			self.set_detail(assigned_heading_detail, self.assignedHeading_edit.headingValue(False))
		else:
			self.set_detail(assigned_heading_detail, None)
		# Altitude/FL
		if self.assignAltitude.isChecked():
			self.set_detail(assigned_altitude_detail, self.assignedAltitude_edit.altFlSpec())
		else:
			self.set_detail(assigned_altitude_detail, None)
		# Speed
		if self.assignSpeed.isChecked():
			self.set_detail(assigned_speed_detail, self.assignedSpeed_edit.speedValue())
		else:
			self.set_detail(assigned_speed_detail, None)
		# DONE with details
		if self.strip.linkedFPL() is None and self.linkFpl_select.currentIndex() != 0:
			self.strip.linkFPL(self.selected_FPL_link)
		self.accept()
		# WARNING: must deal with rack change after dialog accepted (use selectedRack method); STYLE deal with this here





# =========== FPL =========== #

class FPLdetailSheetDialog(QDialog, Ui_fplDetailsDialog, SharedDetailSheet):
	def __init__(self, gui, fpl):
		QDialog.__init__(self, gui)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.setWindowIcon(QIcon(IconFile.panel_FPLs))
		self.fpl = fpl
		if fpl.isOnline():
			self.onlineStatus_info.setText(fpl.onlineStatusStr())
			self.localChanges_info.setText(', '.join(FPL.detailStrNames[d] for d in fpl.modified_details) if fpl.modified_details else 'none')
		else:
			self.onlineStatus_info.setText('not online')
			self.localChanges_info.setText('N/A')
		strip = env.linkedStrip(fpl)
		if strip is None:
			self.stripLinked_info.setText('none')
		else:
			ovr = strip.fplConflicts()
			if ovr:
				self.stripLinked_info.setText('overrides ' + ', '.join(FPL.detailStrNames[d] for d in ovr))
			else:
				self.stripLinked_info.setText('all details matching')
		SharedDetailSheet.__init__(self)
	
	def get_detail(self, detail):
		return self.fpl[detail]
	
	def set_detail(self, detail, new_val):
		self.fpl[detail] = new_val
	
	def resetData(self):
		# FPL.TIME_OF_DEP
		dep = self.fpl[FPL.TIME_OF_DEP]
		self.depTime_enable.setChecked(dep is not None)
		if dep is None:
			dep = settings.session_manager.clockTime()
		self.depTime_edit.setDateTime(QDateTime(dep.year, dep.month, dep.day, dep.hour, dep.minute))
		# FPL.EET
		eet = self.fpl[FPL.EET]
		self.EET_enable.setChecked(eet is not None)
		if eet is not None:
			minutes = int(eet.total_seconds() / 60 + .5)
			self.EETh_edit.setValue(minutes // 60)
			self.EETmin_edit.setValue(minutes % 60)
		#	ICAO_ALT
		self.altAirportPicker_widget.setEditText(some(self.fpl[FPL.ICAO_ALT], ''))
		#	SOULS
		souls = self.fpl[FPL.SOULS]
		self.soulsOnBoard_enable.setChecked(souls is not None)
		if souls is not None:
			self.soulsOnBoard_edit.setValue(souls)
		SharedDetailSheet.resetData(self)
	
	def saveChangesAndClose(self):
		SharedDetailSheet.saveChangesAndClose(self)
		# FPL.TIME_OF_DEP
		if self.depTime_enable.isChecked():
			self.set_detail(FPL.TIME_OF_DEP, self.depTime_edit.dateTime().toPyDateTime().replace(tzinfo=timezone.utc))
		else:
			self.set_detail(FPL.TIME_OF_DEP, None)
		# FPL.EET
		if self.EET_enable.isChecked():
			self.set_detail(FPL.EET, timedelta(hours=self.EETh_edit.value(), minutes=self.EETmin_edit.value()))
		else:
			self.set_detail(FPL.EET, None)
		# FPL.ICAO_ALT
		self.set_detail(FPL.ICAO_ALT, self.altAirportPicker_widget.currentText())
		# FPL.SOULS
		self.set_detail(FPL.SOULS, (self.soulsOnBoard_edit.value() if self.soulsOnBoard_enable.isChecked() else None))
		# Done details!
		self.accept()
