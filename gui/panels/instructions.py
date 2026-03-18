
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

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QMessageBox
from ui.instructionPanel import Ui_instructionPanel

from base.util import some, pop_all
from base.fpl import FPL
from base.instr import Instruction, ApproachType
from base.strip import parsed_route_detail, departure_clearance_detail

from session.config import settings
from session.env import env
from session.manager import SessionType

from gui.actions import docked_panel_instruction_clicked
from gui.misc import signals, selection


# ---------- Constants ----------

# -------------------------------


class InstructionsPanel(QWidget, Ui_instructionPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.navpoint_edit.setClearButtonEnabled(True)
		self.taxiAvoidsRunways_tickBox.setChecked(settings.taxi_instructions_avoid_runways)
		# Buttons and signals
		self.sayIntentions_OK_button.modClicked.connect(self.sendInstruction_sayIntentions)
		if env.airport_data is None:
			self.depInstr_page.setEnabled(False)
			self.appInstr_page.setEnabled(False)
			self.instr_tabs.setCurrentIndex(2) # self.navInstr_page
		else:
			self.setupDepArrSurfacesLists()
			signals.adSfcUseChanged.connect(self.setupDepArrSurfacesLists)
			signals.locationSettingsChanged.connect(self.setupDepArrSurfacesLists) # in case a RWY param changed
			signals.selectionChanged.connect(self.setupDepArrSurfacesLists)
			# Taxi & DEP tab buttons
			self.depClearance_OK_button.modClicked.connect(self.sendInstruction_depClearance)
			self.taxiAvoidsRunways_tickBox.toggled.connect(self.setTaxiAvoidsRunways)
			self.reportReady_OK_button.modClicked.connect(self.sendInstruction_expectDepartureRunway)
			self.holdPosition_OK_button.modClicked.connect(self.sendInstruction_holdPosition)
			self.lineUp_OK_button.modClicked.connect(self.sendInstruction_lineUp)
			self.takeOff_OK_button.modClicked.connect(self.sendInstruction_takeOff)
			# Arrival buttons
			self.interceptLOC_OK_button.modClicked.connect(self.sendInstruction_interceptLocaliser)
			self.clearedAPP_OK_button.modClicked.connect(self.sendInstruction_clearedIlsVisualApproach)
			self.makeStraightInApp_OK_button.modClicked.connect(self.sendInstruction_makeStraightInApproach)
			self.expectArrRWY_OK_button.modClicked.connect(self.sendInstruction_expectArrivalRunway)
			self.clearedToLand_OK_button.modClicked.connect(self.sendInstruction_clearToLand)
			self.cancelApproach_OK_button.modClicked.connect(self.sendInstruction_cancelApproach)
		# Nav buttons
		self.DCT_OK_button.modClicked.connect(self.sendInstruction_DCT)
		self.hold_OK_button.modClicked.connect(self.sendInstruction_hold)
		self.interceptNav_OK_button.modClicked.connect(self.sendInstruction_interceptNav)
		self.speedYourDiscretion_OK_button.modClicked.connect(self.sendInstruction_speedYourDiscretion)
		self.followRoute_OK_button.modClicked.connect(self.sendInstruction_followRoute)
		# Other signals
		signals.selectionChanged.connect(self.updateDestOnNewSelection)
		signals.navpointClick.connect(lambda p: self.navpoint_edit.setText(p.code))
		signals.sessionStarted.connect(self.sessionHasStarted)
		signals.sessionEnded.connect(self.sessionHasEnded)
	
	def sessionHasStarted(self, session_type):
		if session_type == SessionType.TEACHER:
			self.dest_edit.setText('selection')
			self.dest_edit.setEnabled(False)
			self.depClearance_OK_button.setEnabled(False)
	
	def sessionHasEnded(self):
		self.depClearance_OK_button.setEnabled(True)
		self.dest_edit.setEnabled(True)
		self.dest_edit.clear()
	
	def updateDestOnNewSelection(self):
		if settings.session_manager.session_type != SessionType.TEACHER:
			self.dest_edit.setText(some(selection.selectedCallsign(), ''))
	
	def setupDepArrSurfacesLists(self):
		if env.airport_data is not None:
			all_lst = env.airport_data.directionalRunways() + env.airport_data.helipads()
			dep_lst = [sfc for sfc in all_lst if sfc.use_for_departures]
			arr_lst = [sfc for sfc in all_lst if sfc.use_for_arrivals]
			acft_type = None if selection.strip is None else selection.strip.lookup(FPL.ACFT_TYPE, fpl=True)
			if acft_type is not None:
				pop_all(dep_lst, lambda sfc: not sfc.acceptsAcftType(acft_type))
				pop_all(arr_lst, lambda sfc: not sfc.acceptsAcftType(acft_type))
			if not dep_lst:
				dep_lst = all_lst
			if not arr_lst:
				arr_lst = all_lst
			self.reportReadyRWY_select.clear()
			self.expectArrRWY_select.clear()
			self.reportReadyRWY_select.addItems([sfc.name for sfc in dep_lst])
			self.expectArrRWY_select.addItems([sfc.name for sfc in arr_lst])
	
	def setTaxiAvoidsRunways(self, b):
		settings.taxi_instructions_avoid_runways = b
	
	
	# SENDING INSTRUCTION TO CORRECT CALLSIGN
	
	def sendInstruction(self, instr, click_modifiers): # NOTE: callsign field text will be ignored if teaching
		docked_panel_instruction_clicked(instr, self.dest_edit.text(), click_modifiers & Qt.AltModifier)
	
	
	# BUTTON CLICKS
	
	def sendInstruction_sayIntentions(self, mods):
		self.sendInstruction(Instruction(Instruction.SAY_INTENTIONS), mods)


	def sendInstruction_depClearance(self, mods):
		clearance = None if selection.strip is None else selection.strip.lookup(departure_clearance_detail)
		if clearance is None:
			QMessageBox.critical(self, 'Instruction error', 'No strip selected or no clearance recorded.')
		else:
			self.sendInstruction(Instruction(Instruction.DEP_CLEARANCE, arg=clearance), mods)
	
	
	def sendInstruction_expectDepartureRunway(self, mods):
		self.sendInstruction(Instruction(Instruction.EXPECT_SFC, arg=self.reportReadyRWY_select.currentText()), mods)
	
	def sendInstruction_holdPosition(self, mods):
		self.sendInstruction(Instruction(Instruction.HOLD_POSITION), mods)
	
	
	def sendInstruction_lineUp(self, mods):
		self.sendInstruction(Instruction(Instruction.LINE_UP), mods)
	
	def sendInstruction_takeOff(self, mods):
		self.sendInstruction(Instruction(Instruction.CLEARED_TKOF), mods)
	
	
	def sendInstruction_expectArrivalRunway(self, mods):
		self.sendInstruction(Instruction(Instruction.EXPECT_SFC, arg=self.expectArrRWY_select.currentText()), mods)
	
	def sendInstruction_interceptLocaliser(self, mods):
		self.sendInstruction(Instruction(Instruction.INTERCEPT_LOC), mods)
	
	def sendInstruction_clearedIlsVisualApproach(self, mods):
		self.sendInstruction(Instruction(Instruction.CLEARED_APP), mods)

	def sendInstruction_makeStraightInApproach(self, mods):
		self.sendInstruction(Instruction(Instruction.CLEARED_APP, arg2=ApproachType.STRAIGHT_IN), mods)
	
	def sendInstruction_clearToLand(self, mods):
		self.sendInstruction(Instruction(Instruction.CLEARED_LDG), mods)
	
	def sendInstruction_cancelApproach(self, mods):
		self.sendInstruction(Instruction(Instruction.CANCEL_APP), mods)
	
	
	def sendInstruction_DCT(self, mods):
		self.sendInstruction(Instruction(Instruction.VECTOR_DCT, arg=self.navpoint_edit.text()), mods)
	
	def sendInstruction_hold(self, mods):
		txt = self.navpoint_edit.text()
		if txt == '':
			self.sendInstruction(Instruction(Instruction.HOLD_POSITION), mods)
		else:
			self.sendInstruction(Instruction(Instruction.HOLD_AT_FIX, arg=txt), mods)
	
	def sendInstruction_interceptNav(self, mods):
		heading = self.intercept_heading_edit.headingValue(False)
		self.sendInstruction(Instruction(Instruction.INTERCEPT_NAV, arg=self.navpoint_edit.text(), arg2=heading), mods)
	
	def sendInstruction_speedYourDiscretion(self, mods):
		self.sendInstruction(Instruction(Instruction.CANCEL_SPD), mods)
	
	def sendInstruction_followRoute(self, mods):
		if selection.strip is None:
			QMessageBox.critical(self, 'Instruction error', 'No strip selected.')
		else:
			parsed_route = selection.strip.lookup(parsed_route_detail)
			if parsed_route is None:
				lookups = [selection.strip.lookup(d, fpl=True) for d in [FPL.ICAO_DEP, FPL.ROUTE, FPL.ICAO_ARR]]
				route_str = ' '.join(s for s in lookups if s is not None)
			elif selection.acft is None:
				route_str = str(parsed_route)
			else:
				route_str = parsed_route.toGoStr(selection.acft.coords())
			self.sendInstruction(Instruction(Instruction.FOLLOW_ROUTE, arg=route_str), mods)
