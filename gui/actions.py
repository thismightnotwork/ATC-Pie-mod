
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
from PyQt5.QtWidgets import QMessageBox

from base.cpdlc import CpdlcMessage
from base.fpl import FPL
from base.instr import Instruction
from base.strip import Strip, recycled_detail, auto_printed_detail, shelved_detail, student_ok_detail, \
		runway_box_detail, rack_detail, sent_to_detail, received_from_detail, departure_clearance_detail, \
		assigned_heading_detail, assigned_altitude_detail, assigned_speed_detail, assigned_SQ_detail
from base.utc import rel_session_datetime_str
from base.util import some

from ext.tts import speech_str2txt

from gui.misc import signals, selection
from gui.dialogs.detailSheets import StripDetailSheetDialog
from gui.dialogs.miscDialogs import CpdlcXfrOptionsDialog, select_ATC_callsign

from session.config import settings
from session.env import env
from session.manager import SessionType, student_callsign, teacher_callsign, CpdlcOperationBlocked, HandoverBlocked
from session.models.liveStrips import default_rack_name


# ---------- Constants ----------

# -------------------------------


def kill_aircraft(acft):
	link = env.cpdlc.liveDataLink(acft.identifier)
	if link is not None:
		link.terminate(False)
		link.resolveProblems()
	strip = env.linkedStrip(acft)
	if strip is not None:
		strip.linkAircraft(None) # to avoid "linkedContactLost" signal after ACFT has disappeared from radar
	settings.session_manager.killAircraft(acft) # WARNING: killAircraft method must exist
	env.radar.forgetContact(acft)



def register_weather_information(weather):
	station = weather.station()
	prev = env.weatherInformation(station)
	if prev is None or weather.isNewerThan(prev):
		env.weather_information[station] = weather
		signals.newWeather.emit(station, weather)
		settings.session_recorder.proposeWeatherChange(settings.session_manager.clockTime(), weather)



def generic_transfer_action(parent_widget):
	if settings.session_manager.session_type != SessionType.TEACHER:
		selected_callsign = selection.selectedCallsign()
		live_link = None if selected_callsign is None else env.cpdlc.liveDataLink(selected_callsign)
		if live_link: # CPDLC transfer (strip can automatically follow on accept)
			non_teacher_cpdlc_transfer(parent_widget, live_link) # also handles pending XFR cancellation
		elif selection.strip is not None: # strip handover only
			atc = select_ATC_callsign(parent_widget, 'Strip handover')
			if atc is not None:
				send_strip(selection.strip, atc)




#############################

##    MANIPULATE STRIPS    ##

#############################

def new_strip_dialog(parent_widget, rack, linkToSelection=False):
	"""
	Returns the created strip if operation not aborted
	"""
	new_strip = Strip()
	new_strip.writeDetail(rack_detail, rack)
	if linkToSelection:
		new_strip.linkAircraft(selection.acft)
		if settings.strip_autofill_on_ACFT_link:
			new_strip.fillFromXPDR()
		new_strip.linkFPL(selection.fpl)
	dialog = StripDetailSheetDialog(parent_widget, new_strip)
	dialog.exec()
	if dialog.result() > 0: # not rejected
		new_strip.writeDetail(rack_detail, dialog.selectedRack())
		env.strips.addStrip(new_strip)
		selection.selectStrip(new_strip)
		return new_strip
	else:
		return None



def edit_strip(parent_widget, strip):
	old_rack = strip.lookup(rack_detail) # may be None
	dialog = StripDetailSheetDialog(parent_widget, strip)
	dialog.exec()
	new_rack = dialog.selectedRack()
	if dialog.result() > 0 and new_rack != old_rack: # not rejected and rack changed
		env.strips.repositionStrip(strip, new_rack)
	signals.stripInfoChanged.emit()
	signals.selectionChanged.emit()



def discard_strip(parent_widget, strip, shelve):
	"""
	Argument "shelve" is True to shelve; False to delete.
	"""
	if strip is None:
		return
	acft = strip.linkedAircraft()
	fpl = strip.linkedFPL()
	if shelve: # shelving strip
		selected_callsign = selection.selectedCallsign()
		if selected_callsign is not None and env.cpdlc.liveDataLink(selected_callsign) is not None and QMessageBox.question(settings.session_manager.gui,
				'Open CPDLC dialogue', 'You are shelving a strip whose callsign matches an unterminated CPDLC dialogue. Open dialogue window instead?') == QMessageBox.Yes:
			signals.cpdlcDialogueRequest.emit(selected_callsign, False)
			return # abort shelving
		if fpl is not None and (not fpl.isOnline() or fpl.hasLocalChanges() or strip.fplConflicts()):
			if settings.confirm_lossy_strip_releases and QMessageBox.question(parent_widget, 'Lossy shelving',
					'Strip linked to a FPL with local changes or mismatching details. Release contact anyway?') != QMessageBox.Yes:
				return # abort shelving
	else: # deleting strip (not shelving)
		if acft is not None or fpl is not None:
			if settings.confirm_linked_strip_deletions and QMessageBox.question(parent_widget, 'Delete strip', 'Strip is linked. Delete anyway?') != QMessageBox.Yes:
				return # abort deletion
	strip.linkAircraft(None)
	strip.linkFPL(None)
	env.strips.removeStrip(strip)
	strip.writeDetail(shelved_detail, shelve)
	env.discarded_strips.addStrip(strip)
	if strip is selection.strip:
		selection.deselect()
	if strip is not None and not shelve:
		signals.stripDeleted.emit(strip)



def instruction_to_strip(instr, callsign=None):
	if callsign is None: # use selection
		strip = selection.strip
	else: # find a unique strip
		strip = env.strips.findUniqueForCallsign(callsign)
	if strip is not None:
		# vectors
		if instr.type == Instruction.VECTOR_HDG:
			strip.writeDetail(assigned_heading_detail, instr.arg)
		elif instr.type in [Instruction.VECTOR_DCT, Instruction.FOLLOW_ROUTE, Instruction.HOLD_AT_FIX,
				Instruction.INTERCEPT_NAV, Instruction.INTERCEPT_LOC, Instruction.CLEARED_APP, Instruction.CLEARED_LDG]:
			strip.writeDetail(assigned_heading_detail, None)
		if instr.type == Instruction.VECTOR_ALT:
			strip.writeDetail(assigned_altitude_detail, instr.arg)
		elif instr.type in [Instruction.CLEARED_APP, Instruction.CLEARED_LDG]:
			strip.writeDetail(assigned_altitude_detail, None)
		if instr.type == Instruction.VECTOR_SPD:
			strip.writeDetail(assigned_speed_detail, instr.arg)
		elif instr.type in [Instruction.CANCEL_SPD, Instruction.HOLD_AT_FIX, Instruction.CLEARED_LDG]:
			strip.writeDetail(assigned_speed_detail, None)
		# transponder assignment
		if instr.type == Instruction.SQUAWK:
			strip.writeDetail(assigned_SQ_detail, instr.arg)
		# ROUTE and DEP_CLEARANCE are usually taken *from* strip so would need no update, EXCEPT when sending a requested CPDLC instr (or executing)
		if instr.type == Instruction.DEP_CLEARANCE:
			strip.writeDetail(FPL.ROUTE, instr.arg)
		elif instr.type == Instruction.DEP_CLEARANCE: # NOTE never really useful in the end because AI ACFT reject this instr
			strip.writeDetail(departure_clearance_detail, instr.arg)
		signals.stripInfoChanged.emit()



def push_details_to_FPL(parent_widget):
	if selection.strip is None:
		return # safeguard (should not be called at all: menu action disabled)
	overwrite = False
	clst = selection.strip.fplConflicts()
	if len(clst) > 0:
		button = QMessageBox.question(parent_widget, 'Strip details to FPL',
				'Overwrite FPL details below?\n' + ', '.join(FPL.detailStrNames[d] for d in clst),
				buttons=(QMessageBox.Cancel | QMessageBox.No | QMessageBox.Yes))
		if button == QMessageBox.Cancel:
			return
		else:
			overwrite = button == QMessageBox.Yes
	selection.strip.pushToFPL(ovr=overwrite)
	env.FPLs.refreshViews()



def pull_XPDR_details(parent_widget):
	if selection.strip is None:
		return # safeguard (should not be called at all: menu action disabled)
	overwrite = False
	clst = selection.strip.xpdrConflicts()
	if len(clst) > 0:
		button = QMessageBox.question(parent_widget, 'XPDR details to strip', 'Overwrite details below with squawked values?\n'
				+ ', '.join(FPL.detailStrNames.get(d, ('CODE' if d == assigned_SQ_detail else '??' + str(d))) for d in clst),
				buttons=(QMessageBox.Cancel | QMessageBox.No | QMessageBox.Yes))
		if button == QMessageBox.Cancel:
			return
		else:
			overwrite = button == QMessageBox.Yes
	selection.strip.fillFromXPDR(ovr=overwrite)
	signals.stripInfoChanged.emit()



def pull_FPL_details(parent_widget):
	if selection.strip is None:
		return # safeguard (should not be called at all: menu action disabled)
	overwrite = False
	clst = selection.strip.fplConflicts()
	if len(clst) > 0:
		button = QMessageBox.question(parent_widget, 'FPL details to strip',
				'Overwrite details below with FPL values?\n' + ', '.join(FPL.detailStrNames[d] for d in clst),
				buttons=(QMessageBox.Cancel | QMessageBox.No | QMessageBox.Yes))
		if button == QMessageBox.Cancel:
			return
		else:
			overwrite = button == QMessageBox.Yes
	selection.strip.fillFromFPL(ovr=overwrite)
	signals.stripInfoChanged.emit()



def send_strip(strip, atc_callsign):
	if settings.strip_autofill_before_handovers:
		strip.fillFromFPL(ovr=False)
		strip.fillFromXPDR(ovr=False)
	try:
		settings.session_manager.sendStrip(strip, atc_callsign)
		cs = strip.callsign()
		rectxt = 'Strip '
		if cs is not None:
			rectxt += '"%s" ' % cs
		rectxt += 'sent to %s, ' % atc_callsign
		settings.session_recorder.proposeGenericEvent(settings.session_manager.clockTime(), rectxt)
	except HandoverBlocked as err:
		QMessageBox.critical(settings.session_manager.gui, 'Handover aborted', str(err))
	else: # handover accepted and performed by session manager
		if settings.session_manager.session_type == SessionType.TEACHER:
			strip.writeDetail(sent_to_detail, student_callsign)
			if atc_callsign != teacher_callsign:
				strip.writeDetail(received_from_detail, atc_callsign) # not really "received from" for the teacher, but shows nicely on strip
			strip.writeDetail(student_ok_detail, True)
			signals.stripInfoChanged.emit()
		else: # regular hand-off as ATC
			strip.writeDetail(sent_to_detail, atc_callsign)
			selection.deselect()
			strip.linkAircraft(None)
			strip.linkFPL(None)
			env.strips.removeStrip(strip)
			env.discarded_strips.addStrip(strip)



def receive_strip(strip):
	rack = strip.lookup(rack_detail)
	recv_from = strip.lookup(received_from_detail)
	cs = strip.callsign()
	if rack is None and recv_from is not None:
		rack = settings.ATC_collecting_racks.get(recv_from, default_rack_name)
	if rack not in env.strips.rackNames():
		rack = default_rack_name
	strip.writeDetail(rack_detail, rack)
	env.strips.addStrip(strip)
	rectxt = 'Strip '
	if cs is not None:
		rectxt += '"%s" ' % cs
	if recv_from is not None:
		rectxt += 'received from %s, ' % recv_from
	rectxt += 'collected on rack "%s"' % rack
	settings.session_recorder.proposeGenericEvent(settings.session_manager.clockTime(), rectxt)
	if settings.strip_autolink_open_FPL and strip.linkedFPL() is None:
		if cs is not None and env.strips.findUniqueForCallsign(cs) is not None:
			fpls = env.FPLs.findAll(lambda fpl: fpl.onlineStatus() == FPL.OPEN and fpl[FPL.CALLSIGN] and fpl[FPL.CALLSIGN].upper() == cs.upper() and env.linkedStrip(fpl) is None)
			if len(fpls) == 1:
				strip.linkFPL(fpls[0])



def recover_strip(strip):
	env.discarded_strips.remove(strip)
	strip.writeDetail(recycled_detail, True)
	strip.writeDetail(shelved_detail, None)
	strip.writeDetail(runway_box_detail, None)
	strip.writeDetail(rack_detail, default_rack_name)
	env.strips.addStrip(strip)





##################################

##     INSTRUCTION GESTURES     ##

##################################


def teacher_instr_on_selected(instr, is_cpdlc_request):
	"""
	Direct control of the selected aircraft with the given instruction.
	"""
	if selection.acft is None:
		QMessageBox.critical(settings.session_manager.gui, 'Traffic command error', 'No aircraft selected.')
	elif is_cpdlc_request:
		link = env.cpdlc.liveDataLink(selection.acft.identifier)
		if link is None:
			QMessageBox.critical(settings.session_manager.gui, 'CPDLC request error', 'No live connection for %s.' % selection.acft.identifier)
		else:
			try:
				signals.appendCpdlcMsgElement.emit(selection.acft.identifier, instr.toCpdlcDownlinkRequestElt(selection.acft))
			except ValueError:
				QMessageBox.critical(settings.session_manager.gui, 'CPDLC request error', 'Downlink request not supported for this instruction.')
	else: # instruct selected aircraft
		instruction_to_strip(instr)
		try:
			selection.acft.instruct([instr], True) # read back to allow checking + answer to "say intentions"
		except Instruction.Error as err:
			QMessageBox.critical(settings.session_manager.gui, 'Instruction error', speech_str2txt(str(err)))



def teacher_cpdlc_transfer(parent_widget, acft):
	link = env.cpdlc.lastDataLink(acft.identifier)
	try:
		if link is None or link.isTerminated(): # simulate new transfer
			atc = select_ATC_callsign(parent_widget, 'CPDLC transfer', prompt='Select ATC transferring data authority to student:')
			if atc is not None:
				settings.session_manager.sendCpdlcTransferRequest(acft.identifier, atc, True) # or CpdlcOperationBlocked
				env.cpdlc.beginDataLink(acft.identifier, transferFrom=atc)
		elif link.pendingTransferFrom() is not None: # XFR to student already pending
			if QMessageBox.question(parent_widget, 'CPDLC transfer',
					'Abort already pending transfer from %s to student?' % link.pendingTransferFrom()) == QMessageBox.Yes:
				settings.session_manager.sendCpdlcTransferRequest(acft.identifier, link.pendingTransferFrom(), False) # or CpdlcOperationBlocked
				link.terminate(True)
	except CpdlcOperationBlocked as err:
		QMessageBox.critical(parent_widget, 'CPDLC transfer error', str(err))



def non_teacher_cpdlc_transfer(parent_widget, live_link, nextAtc=None):
	acft_callsign = live_link.acftCallsign()
	pending_cpdlc_xfr = live_link.pendingTransferTo()
	if pending_cpdlc_xfr is None or nextAtc is None:
		if live_link.expectingMsg() or live_link.markedProblemTime():
			QMessageBox.warning(parent_widget, 'CPDLC transfer warning', 'Connection still expecting a message or has problems to resolve.')
		try:
			if pending_cpdlc_xfr is None: # new transfer
				if nextAtc is None:
					try:
						nextAtc = select_ATC_callsign(parent_widget, 'CPDLC transfer')
						if nextAtc is None:
							return
					except IndexError:
						QMessageBox.critical(parent_widget, 'Transfer error', 'No ATCs to transfer to.')
						return
				msg = CpdlcMessage('SYSU-2 ' + nextAtc) # "NEXT DATA AUTHORITY"
				settings.session_manager.sendCpdlcMsg(acft_callsign, msg)
				live_link.appendMessage(msg)
				settings.session_manager.sendCpdlcTransferRequest(acft_callsign, nextAtc, True)
				live_link.setTransferTo(nextAtc)
				signals.cpdlcDialogueRequest.emit(acft_callsign, False)
				settings.session_recorder.proposeCpdlcSys(msg.timeStamp(), acft_callsign, xfr=nextAtc)
			elif QMessageBox.question(parent_widget, 'Pending CPDLC transfer', 'Cancel pending transfer to %s?' % pending_cpdlc_xfr) == QMessageBox.Yes:
				msg = CpdlcMessage('SYSU-2') # "NEXT DATA AUTHORITY" without a callsign = cancels previously given value
				settings.session_manager.sendCpdlcMsg(acft_callsign, msg)
				live_link.appendMessage(msg)
				settings.session_manager.sendCpdlcTransferRequest(acft_callsign, pending_cpdlc_xfr, False)
				live_link.setTransferTo(None)
				settings.session_recorder.proposeCpdlcSys(msg.timeStamp(), acft_callsign, xfr=nextAtc)
		except CpdlcOperationBlocked as err:
			QMessageBox.critical(parent_widget, 'CPDLC error', str(err))
	elif pending_cpdlc_xfr != nextAtc: # else just ignore: retransferring to the same callsign
		QMessageBox.critical(parent_widget, 'Pending CPDLC transfer', 'A transfer is already pending to %s.' % pending_cpdlc_xfr)



def docked_panel_instruction_clicked(instr, callsign_field_text, alt_key_pressed):
	# NOTE: callsign_field_text is ignored if teaching
	if settings.session_manager.session_type == SessionType.TEACHER:
		teacher_instr_on_selected(instr, alt_key_pressed)
	else: # not teaching
		if alt_key_pressed:
			msg_elt = instr.toCpdlcUplinkMsgElt(env.radarContactByCallsign(callsign_field_text))
			signals.appendCpdlcMsgElement.emit(callsign_field_text, msg_elt)
		else:
			instruction_to_strip(instr, callsign=callsign_field_text)
			settings.session_manager.instructAircraftByCallsign(callsign_field_text, instr)



def mouse_vector_tool_released(instr, alt_key_pressed): # all four VECTOR_(HDG|ALT|SPD|DCT) instructions
	if settings.session_manager.session_type == SessionType.TEACHER:
		teacher_instr_on_selected(instr, alt_key_pressed)
	else: # not teaching
		sel = some(selection.selectedCallsign(), '') # WARNING this could refer to an ACFT different to selection.acft
		if alt_key_pressed:
			msg_elt = instr.toCpdlcUplinkMsgElt(env.radarContactByCallsign(sel))
			signals.appendCpdlcMsgElement.emit(sel, msg_elt)
		else:
			instruction_to_strip(instr)
			settings.session_manager.instructAircraftByCallsign(sel, instr)



def mouse_taxi_tool_released(instr):
	if settings.session_manager.session_type == SessionType.TEACHER:
		teacher_instr_on_selected(instr, False)
	else: # not teaching
		settings.session_manager.instructAircraftByCallsign(some(selection.selectedCallsign(), ''), instr)



def strip_dropped_on_ATC(strip, atc_callsign, alt_key_pressed):
	if settings.session_manager.session_type == SessionType.TEACHER:
		if alt_key_pressed: # CPDLC "contact" instruction request
			teacher_instr_on_selected(env.ATCs.handoverInstructionTo(atc_callsign), True)
	
	else: # non-teaching strip drop on non-teacher ATC
		selected_callsign = selection.selectedCallsign()
		live_link = None if selected_callsign is None else env.cpdlc.liveDataLink(selected_callsign)
		ho_instr = env.ATCs.handoverInstructionTo(atc_callsign)
		if alt_key_pressed:
			if live_link is None:
				QMessageBox.critical(settings.session_manager.gui, 'No data link', 'No live data link with %s.' % selected_callsign)
			else:
				msg_elt = ho_instr.toCpdlcUplinkMsgElt(selection.acft)
				dialog = CpdlcXfrOptionsDialog(settings.session_manager.gui, msg_elt)
				dialog.exec()
				if dialog.result() > 0: # CPDLC transfer or "contact" instr
					if dialog.transferOptionSelected():
						non_teacher_cpdlc_transfer(settings.session_manager.gui, live_link, nextAtc=atc_callsign)
					else:
						signals.appendCpdlcMsgElement.emit(selected_callsign, msg_elt)
		elif live_link is not None and QMessageBox.question(settings.session_manager.gui, 'Active data link',
				'You are sending a strip whose callsign matches a live data link connection. Open connection window instead?') == QMessageBox.Yes:
			signals.cpdlcDialogueRequest.emit(selected_callsign, False)
		elif not settings.confirm_handovers or QMessageBox.question(settings.session_manager.gui, 'Confirm handover', 'Send strip to %s?' % atc_callsign) == QMessageBox.Yes:
			settings.session_manager.instructAircraftByCallsign(some(selected_callsign, ''), ho_instr)
			send_strip(strip, atc_callsign)




##############################

##     STRIP AUTO-PRINT     ##

##############################

def auto_print_strip_reason(fpl):
	"""
	Returns reason to print if strip should be auto-printed from FPL; None otherwise
	"""
	if fpl.onlineStatus() == FPL.CLOSED or fpl.strip_auto_printed \
			or settings.auto_print_strips_IFR_only and fpl[FPL.FLIGHT_RULES] != 'IFR' \
			or env.airport_data is None or env.linkedStrip(fpl) is not None:
		return None
	present_time = settings.session_manager.clockTime()
	ok_reason = None
	if settings.auto_print_strips_include_DEP: # check DEP time
		dep = fpl[FPL.TIME_OF_DEP]
		if dep is not None and fpl[FPL.ICAO_DEP] == env.airport_data.navpoint.code: # we know: fpl.onlineStatus() != FPL.CLOSED
			if dep - settings.auto_print_strips_anticipation <= present_time <= dep:
				ok_reason = 'departure due ' + rel_session_datetime_str(dep)
	if ok_reason is None and settings.auto_print_strips_include_ARR: # check arrival time
		eta = fpl.ETA()
		if eta is not None and fpl[FPL.ICAO_ARR] == env.airport_data.navpoint.code and fpl.onlineStatus() == FPL.OPEN:
			if eta - settings.auto_print_strips_anticipation <= present_time <= eta:
				ok_reason = 'arrival due ' + rel_session_datetime_str(eta)
	return ok_reason


def strip_auto_print_check():
	for fpl in env.FPLs.findAll():
		reason_to_print = auto_print_strip_reason(fpl)
		if reason_to_print is not None:
			strip = Strip()
			strip.linkFPL(fpl)
			strip.writeDetail(rack_detail, some(settings.auto_print_collecting_rack, default_rack_name))
			strip.writeDetail(auto_printed_detail, True)
			fpl.strip_auto_printed = True
			env.strips.addStrip(strip)
			signals.stripAutoPrinted.emit(strip, reason_to_print)
			signals.selectionChanged.emit()





#########################

##        CPDLC        ##

#########################

def receive_CPDLC_transfer_request(callsign, atc, proposing):
	link = env.cpdlc.lastDataLink(callsign)
	if proposing and (link is None or link.isTerminated()):  # ATC proposing us a transfer
		if settings.controller_pilot_data_link:
			env.cpdlc.beginDataLink(callsign, transferFrom=atc)
		else:
			try:
				settings.session_manager.sendCpdlcTransferResponse(callsign, atc, False)  # automatically reject
			except CpdlcOperationBlocked:
				pass  # no point looping; we were just trying to be nice and send note that we were not accepting XFRs
	elif not proposing and link is not None and link.pendingTransferFrom() == atc:  # ATC cancelling transfer
		link.terminate(True)
	else:
		print('ERROR: %s proposing or aborting CPDLC transfer without data authority for %s.' % (atc, callsign), file=stderr)


def receive_CPDLC_transfer_response(callsign, atc, accept):
	link = env.cpdlc.liveDataLink(callsign)
	if link is not None and link.pendingTransferTo() == atc:
		if accept:
			link.terminate(True)
			if settings.CPDLC_send_strips_on_accepted_transfers:
				strip = env.strips.findUniqueForCallsign(callsign)
				if strip is None:
					QMessageBox.warning(settings.session_manager.gui, 'Strip on accepted transfer',
							'No single matching strip found to complete transferring %s to %s.' % (callsign, atc))
				else:
					send_strip(strip, atc)
		else:  # our proposal rejected by ATC
			try:
				msg = CpdlcMessage('SYSU-2')  # "NEXT DATA AUTHORITY" with no callsign = cancels previously given value
				settings.session_manager.sendCpdlcMsg(callsign, msg)
				link.appendMessage(msg)
			except CpdlcOperationBlocked as err:
				print('ERROR sending SYSU-2 message to %s.' % callsign, file=stderr)
			link.setTransferTo(None)
			link.markProblem('Transfer rejected by %s' % atc)  # do not QMessageBox here because dialogs will stack
			settings.session_recorder.proposeCpdlcSys(settings.session_manager.clockTime(), callsign, connectFlag=False, xfr=atc)
	else:
		print('ERROR: %s responding to non proposed CPDLC transfer for %s.' % (atc, callsign), file=stderr)
