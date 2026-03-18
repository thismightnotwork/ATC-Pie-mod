
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

import re
from datetime import timedelta, timezone
from sys import stderr

from PyQt5.QtCore import Qt, QRegExp, QTime
from PyQt5.QtGui import QIcon, QColor, QRegExpValidator
from PyQt5.QtWidgets import QWidget, QMessageBox, QMenu, QAction, \
		QLabel, QLineEdit, QSpinBox, QComboBox, QTimeEdit, QMdiSubWindow

from ui.cpdlcPanel import Ui_cpdlcPanel
from ui.cpdlcDialoguePanel import Ui_cpdlcDialoguePanel

from base.cpdlc import CpdlcMessage, RspId, CPDLC_element_formats, CPDLC_element_display_text
from base.fpl import FPL
from base.instr import Instruction
from base.strip import assigned_SQ_detail, assigned_heading_detail, assigned_altitude_detail, assigned_speed_detail, departure_clearance_detail
from base.utc import rel_session_datetime_str

from gui.actions import instruction_to_strip, non_teacher_cpdlc_transfer
from gui.dialogs.miscDialogs import TextInputDialog
from gui.misc import selection, signals, IconFile, SimpleStringListModel, RadioKeyEventFilter
from gui.widgets.basicWidgets import flash_widget, HeadingEditWidget, XpdrCodeSpinBox, \
		AtisCodeEditWidget, AltFlEditWidget, SpeedEditWidget, FrequencyPickCombo
from gui.workspace import WorkspaceDockablePanel

from session.env import env
from session.config import settings
from session.manager import SessionType, CpdlcOperationBlocked
from session.models.dataLinks import CpdlcHistoryFilterModel, ConnectionStatus


# ---------- Constants ----------

cpdlc_panel_flash_stylesheet = 'QGroupBox#listFilters_box::title { background: yellow }'
dialogue_window_flash_stylesheet_fmt = 'QLabel#acftCallsign_info { background-color: %s }'
message_buffer_flash_stylesheet = 'QListView#msgBuffer_view { background-color: yellow }'
elt_button_font_min_size = 10  # point size
elt_button_font_reduce_factor = .6

max_recommended_element_count = 4

# -------------------------------

#DEP clearance information = one or more of the following:
#  - departure airport;
#  - departure runway;
#  - cleared to position;
#  - departure route data specified as either:
#    - the route is as filed;
#    - a SID and optionally that the rest of the route after the SID is as filed (i.e. then as filed);
#  - departure level, and any constraint on the level (duration or until position);
#  - expected level and any constraint on the level (duration or until position);
#  - departure speed and any constraint on the speed (duration or until position);
#  - departure heading in degrees;
#  - indication when no delay is expected;
#  - target start-up approval time;
#  - arrival and/or approach procedures
#  - instructions;
#  - SSR code;
#  - ATIS code;
#  - departure frequency.

fmt_arg_key_disp = {
	'ATIS': 'ATIS code',
	'CALLSIGN': 'callsign',
	'CLRTYPE': 'clearance type',
	'DEGREES': 'degrees',
	'DEVTYPE': 'dev. type',
	'DIRECTION': 'direction',
	'FL_ALT': 'FL/alt.',
	'FREQ': 'frequency',
	'FUEL': 'remaining fuel',
	'HDIST': 'distance',
	'LEGTYPE': 'leg type',
	'MINUTES': 'minutes',
	'NDEG': 'number of degrees',
	'POB': 'POB',
	'POINT': 'position',
	'PRESSURE': 'altimeter setting',
	'PROCEDURE': 'procedure',
	'REASON': 'reason',
	'ROUTE': 'route',
	'SPDTYPE': 'speed type',
	'SPEED': 'speed',
	'TEXT': 'text',
	'TIME': 'time',
	'VSPEED': 'vert. rate',
	'XPDR': 'XPDR code'
}


# Each class below is a widget usable for one or more types of argument in CPDLC message elements.
# It must contain:
#  - an initialiseValue(eltid, callsign) method initialising the value to display on msg element selection (arg is connected ACFT);
#  - an argStr() method encoding its argument, so presumably without spaces unless arg alone or last.

class AtisCodeArgWidget(AtisCodeEditWidget):
	def __init__(self, parent):
		AtisCodeEditWidget.__init__(self, parent)
	def initialiseValue(self, eltid, callsign):
		if settings.last_recorded_ATIS is not None:
			return self.setLetter(settings.last_recorded_ATIS[0])
	def argStr(self):
		return self.currentLetter()

class AltArgWidget(AltFlEditWidget):
	def __init__(self, parent):
		AltFlEditWidget.__init__(self, parent)
		self.syncWithEnv(True)
	def initialiseValue(self, eltid, callsign):
		alt = None
		strip = env.strips.findUniqueForCallsign(callsign)
		if strip is not None:
			alt = strip.lookup(assigned_altitude_detail)
		if alt is not None:
			self.setAltFlSpec(alt)
	def argStr(self):
		return self.altFlSpec().toStr(unit=False) # avoid space before unit

class ChoiceArgWidget(QComboBox):
	def __init__(self, parent, str_items):
		QComboBox.__init__(self, parent)
		self.addItems(str_items)
	def initialiseValue(self, eltid, callsign):
		self.setCurrentIndex(0)
	def argStr(self):
		return self.currentText()

class FrqArgWidget(FrequencyPickCombo):
	def __init__(self, parent):
		FrequencyPickCombo.__init__(self, parent)
	def initialiseValue(self, eltid, callsign):
		pass # not much better to propose than last state of widget
	def argStr(self):
		frq = self.getFrequency()
		return '' if frq is None else str(frq)

class HeadingArgWidget(HeadingEditWidget):
	def __init__(self, parent):
		HeadingEditWidget.__init__(self, parent)
	def initialiseValue(self, eltid, callsign):
		hdg = None
		strip = env.strips.findUniqueForCallsign(callsign)
		if strip is not None:
			hdg = strip.lookup(assigned_heading_detail)
		if hdg is not None:
			self.setValue(int(hdg.magneticAngle()))
	def argStr(self):
		return self.headingValue(False).read()

class IntArgWidget(QSpinBox):
	def __init__(self, parent, lo, hi, step, init, unit, f_val2str):
		QSpinBox.__init__(self, parent)
		self.init_value = init
		self.val2str = f_val2str
		self.setMinimum(lo)
		self.setMaximum(hi)
		self.setSingleStep(step)
		if unit is not None:
			self.setSuffix(' ' + unit)
	def initialiseValue(self, eltid, callsign):
		self.setValue(self.init_value)
	def argStr(self):
		return self.val2str(self.value())

class RouteArgWidget(QLineEdit):
	def __init__(self, parent):
		QLineEdit.__init__(self, parent)
		self.setClearButtonEnabled(True)
	def initialiseValue(self, eltid, callsign):
		rte = None
		strip = env.strips.findUniqueForCallsign(callsign)
		if strip is not None:
			rte = strip.lookup(FPL.ROUTE)
		if rte is None:
			self.clear()
		else:
			self.setText(rte)
	def argStr(self):
		return self.text()

class SpeedArgWidget(SpeedEditWidget):
	def __init__(self, parent):
		SpeedEditWidget.__init__(self, parent)
	def initialiseValue(self, eltid, callsign):
		spd = None
		strip = env.strips.findUniqueForCallsign(callsign)
		if strip is not None:
			spd = strip.lookup(assigned_speed_detail)
		if spd is not None:
			self.setValue(int(spd.kt()))
	def argStr(self):
		return str(self.speedValue().kt())

class TimeArgWidget(QTimeEdit):
	def __init__(self, parent):
		QTimeEdit.__init__(self, parent)
	def initialiseValue(self, eltid, callsign):
		t = settings.session_manager.clockTime() + timedelta(minutes=15)
		self.setTime(QTime(t.hour, 10 * (t.minute // 10)))
	def argStr(self):
		t = self.time().toPyTime().replace(tzinfo=timezone.utc)
		return '%02d%02dZ' % (t.hour, t.minute)

class TxtArgWidget(QLineEdit):
	def __init__(self, parent, allow_spaces):
		QLineEdit.__init__(self, parent)
		self.setClearButtonEnabled(True)
		if not allow_spaces:
			self.setValidator(QRegExpValidator(QRegExp('[^ ]*')))
	def initialiseValue(self, eltid, callsign):
		self.clear()
	def argStr(self):
		return self.text()

class XpdrCodeArgWidget(XpdrCodeSpinBox):
	def __init__(self, parent):
		XpdrCodeSpinBox.__init__(self, parent)
	def initialiseValue(self, eltid, callsign):
		sq = None
		strip = env.strips.findUniqueForCallsign(callsign)
		if strip is not None:
			sq = strip.lookup(assigned_SQ_detail)
		if sq is not None:
			self.setValue(sq)
	def argStr(self):
		return '%04o' % self.value()

def mk_msg_elt_arg_widget(arg_type, parent):
	if arg_type == 'ATIS':
		widget = AtisCodeArgWidget(parent)
	elif arg_type == 'CALLSIGN':
		widget = TxtArgWidget(parent, False)
	elif arg_type == 'CLRTYPE':
		widget = ChoiceArgWidget(parent, ['APPROACH', 'DEPARTURE', 'FURTHER', 'OCEANIC', 'PUSHBACK', 'STARTUP', 'TAXI'])
	elif arg_type == 'DEGREES':
		widget = HeadingArgWidget(parent)
	elif arg_type == 'DEVTYPE':
		widget = ChoiceArgWidget(parent, ['LATERAL', 'LEVEL', 'SPEED'])
	elif arg_type == 'DIRECTION':
		widget = ChoiceArgWidget(parent, ['LEFT', 'RIGHT'])
	elif arg_type == 'FL_ALT':
		widget = AltArgWidget(parent)
	elif arg_type == 'FREQ':
		widget = FrqArgWidget(parent)
	elif arg_type == 'FUEL':
		widget = TxtArgWidget(parent, True)
	elif arg_type == 'HDIST':
		widget = IntArgWidget(parent, 0, 999, 1, 10, 'NM', '%iNM'.__mod__) # does NOT allow spaces because of SPCD-3..5
	elif arg_type == 'LEGTYPE':
		widget = TxtArgWidget(parent, True)
	elif arg_type == 'MINUTES':
		widget = IntArgWidget(parent, 0, 99, 1, 5, 'min', '%i MINUTES'.__mod__)
	elif arg_type == 'NDEG':
		widget = IntArgWidget(parent, 1, 360, 5, 10, None, int.__str__)
	elif arg_type == 'POB':
		widget = IntArgWidget(parent, 1, 999, 1, 1, None, int.__str__)
	elif arg_type == 'POINT':
		widget = TxtArgWidget(parent, False)
	elif arg_type == 'PRESSURE':
		widget = IntArgWidget(parent, 850, 1100, 1, 1013, 'hPa', '%i HECTOPASCALS'.__mod__)
	elif arg_type == 'PROCEDURE':
		widget = TxtArgWidget(parent, False)
	elif arg_type == 'REASON':
		widget = TxtArgWidget(parent, True)
	elif arg_type == 'ROUTE':
		widget = RouteArgWidget(parent)
	elif arg_type == 'SPDTYPE':
		widget = ChoiceArgWidget(parent, ['GROUND', 'INDICATED', 'MACH', 'TRUE'])
	elif arg_type == 'SPEED':
		widget = SpeedArgWidget(parent)
	elif arg_type == 'TEXT':
		widget = TxtArgWidget(parent, True)
	elif arg_type == 'TIME':
		widget = TimeArgWidget(parent)
	elif arg_type == 'VSPEED':
		widget = IntArgWidget(parent, 0, 10000, 100, 1000, 'ft/min', '%i FT/MIN'.__mod__)
	elif arg_type == 'XPDR':
		widget = XpdrCodeArgWidget(parent)
	else:
		raise KeyError(arg_type)
	tip = fmt_arg_key_disp[arg_type]
	widget.setToolTip(tip[0].upper() + tip[1:])
	return widget


def elt_id_sort_key(elt_id):
	lft, rgt = elt_id.split('-')
	return lft[:3], int(rgt)



class CpdlcDialoguePanel(QWidget, Ui_cpdlcDialoguePanel):
	def __init__(self, parent, data_link_model):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.resolveProblems_button.setIcon(QIcon(IconFile.button_clear))
		self.cancelElement_button.setIcon(QIcon(IconFile.button_clear))
		self.clearMsgBuffer_button.setIcon(QIcon(IconFile.button_clear))
		self.atc_pov = settings.session_manager.session_type != SessionType.TEACHER
		self.transfer_button.setVisible(self.atc_pov) # ACFT cannot transfer
		self.delEltId_button.setVisible(self.atc_pov) # ACFT cannot issue DEP clearances
		self.receivedRequestedInstr_button.setText('Instruct as requested' if self.atc_pov else 'WILCO + execute')
		self.message_buffer_display_model = SimpleStringListModel(self, False) # reordering here will not sync with "self.message_buffer"
		self.msgBuffer_view.setModel(self.message_buffer_display_model)
		self.data_link_model = data_link_model # CAUTION: accessed for identity test outside of class
		self.messages_tableView.setModel(self.data_link_model)
		self.current_formatted_elt_id = None
		self.current_formatted_elt_arg_widgets = []
		self.message_buffer = []
		# initialise display
		self._linkStatusChanged()
		self.clearMessageBuffer()
		# buttons/actions, signal connections
		self.transfer_button.clicked.connect(self.transferButtonClicked)
		self.disconnect_button.clicked.connect(self.disconnectLink)
		self.resolveProblems_button.clicked.connect(self.resolveProblems)
		self.accept_button.clicked.connect(lambda: self.acceptRejectTransfer(True))
		self.reject_button.clicked.connect(lambda: self.acceptRejectTransfer(False))
		self.delEltId_button.clicked.connect(self.depClearanceElementSelected)
		self.txtEltId_button.clicked.connect(self.freeTextElementSelected)
		menu_buttons = {
			'RTE': self.rteEltId_button, 'LAT': self.latEltId_button, 'LVL': self.lvlEltId_button, 'CST': self.cstEltId_button,
			'SPD': self.spdEltId_button, 'ADV': self.advEltId_button, 'RSP': self.rspEltId_button
		}
		for button in [self.delEltId_button, self.txtEltId_button, self.otherEltId_button] + list(menu_buttons.values()):
			font = button.font()
			font.setPointSize(max(elt_button_font_min_size, int(elt_button_font_reduce_factor * font.pointSize())))
			button.setFont(font)
		elt_menus = {group: QMenu(self) for group in menu_buttons}
		other_elt_menu = QMenu(self)
		for elt_id, elt_fmt in sorted(CPDLC_element_formats.items(), key=lambda pair: elt_id_sort_key(pair[0])):
			if self.atc_pov and elt_id[3] == 'U' or not self.atc_pov and elt_id[3] == 'D':
				if not elt_id.startswith('SYS') and elt_id != 'RTEU-1' and not elt_id.startswith('TXT'): # DEL has own dialog; TXT has own panel
					fmt_disp = re.sub(r'\{(\w+)}', (lambda match: '[%s]' % fmt_arg_key_disp[match.group(1)]), elt_fmt)
					action = QAction('%s: %s' % (elt_id, fmt_disp), self)
					action.triggered.connect(lambda ignore_checked, eid=elt_id: self.menuElementSelected(eid))
					elt_menus.get(elt_id[:3], other_elt_menu).addAction(action)
		for group, menu in elt_menus.items():
			button = menu_buttons.get(group, self.otherEltId_button)
			if menu.isEmpty():
				button.setVisible(False)
			else:
				button.setMenu(menu)
		self.otherEltId_button.setMenu(other_elt_menu)
		self.cancelElement_button.clicked.connect(self.eltEdit_widget.hide)
		self.appendElement_button.clicked.connect(self.appendElement)
		self.sendElement_button.clicked.connect(self.sendUniqueElement)
		self.clearMsgBuffer_button.clicked.connect(self.clearMessageBuffer)
		self.sendMsgBuffer_button.clicked.connect(self.sendMessageBuffer)
		self.receivedRequestedInstr_button.clicked.connect(self.appendRequestedInstructions if self.atc_pov else self.executeReceivedInstructions)
		# CAUTION: the following connections must be disconnected before window deletion
		self.data_link_model.statusChanged.connect(self._linkStatusChanged)
		self.data_link_model.rowsInserted.connect(self.messages_tableView.scrollToBottom)

	def closingYourWindow(self):
		self.data_link_model.rowsInserted.disconnect(self.messages_tableView.scrollToBottom)
		self.data_link_model.statusChanged.disconnect(self._linkStatusChanged)
	
	def _linkStatusChanged(self):
		lvnoxfr = self.data_link_model.isLive() and self.data_link_model.pendingTransferTo() is None
		# UPDATE DISPLAY/BUTTONS
		self.acftCallsign_info.setText(self.data_link_model.acftCallsign())
		self.status_info.setText(self.data_link_model.statusStr())
		pbt = self.data_link_model.markedProblemTime()
		self.status_info.setToolTip('' if pbt is None else 'Problem occurred at ' + rel_session_datetime_str(pbt))
		# Top buttons
		self.transfer_button.setEnabled(self.data_link_model.isLive())
		self.disconnect_button.setEnabled(lvnoxfr)
		self.resolveProblems_button.setVisible(self.data_link_model.statusColour() == ConnectionStatus.PROBLEM)
		self.acceptReject_panel.setVisible(self.atc_pov and self.data_link_model.pendingTransferFrom() is not None)
		# Bottom
		self.input_panel.setVisible(lvnoxfr)
		self.msgBuffer_box.setVisible(lvnoxfr and len(self.message_buffer) > 0)
		self.receivedRequestedInstr_button.setVisible(self.data_link_model.pendingInstrMsg(not self.atc_pov) is not None)

	def appendElementsToMsgBuffer(self, msg_elements):
		self.message_buffer.extend(msg_elements)
		for elt in msg_elements:
			self.message_buffer_display_model.appendString(CPDLC_element_display_text(elt))
		self.msgBuffer_box.show()
		self.sendElement_button.hide()
		self.sendMsgBuffer_button.setEnabled(True)
		self.msgBuffer_view.scrollToBottom()
		if len(self.message_buffer) > max_recommended_element_count:
			QMessageBox.warning(self, 'Long CPDLC message', 'You are exceeding the recommended maximum CPDLC message element count. Consider splitting.')
		flash_widget(self, message_buffer_flash_stylesheet)

	def _currentElementInput(self):
		if self.editElement_stack.currentWidget() is self.depClearance_page:
			return 'RTEU-1 ' + self.depClearance_info.text()
		if self.editElement_stack.currentWidget() is self.freeTextEdit_page:
			return 'TXT%s-%i %s' % ('DU'[self.atc_pov], 1, self.freeText_edit.text()) # TXTU-1 resp. attr. "R", TXTD-1 "Y"
		if self.editElement_stack.currentWidget() is self.formattedEdit_page:
			return ' '.join([self.current_formatted_elt_id] + [w.argStr() for w in self.current_formatted_elt_arg_widgets])
	
	
	## TOP BUTTONS

	def transferButtonClicked(self): # NOTE: button hidden from teacher
		non_teacher_cpdlc_transfer(self, self.data_link_model)

	def disconnectLink(self):
		if self.data_link_model.pendingTransferTo() is not None: # failsafe: button should not be clickable
			print('CPDLC: Cannot disconnect while a transfer is pending.', file=stderr)
		cs = self.data_link_model.acftCallsign()
		if QMessageBox.question(self, 'Terminate data link', 'Disconnect current data link with %s?' % cs) == QMessageBox.Yes:
			try:
				settings.session_manager.sendCpdlcDisconnect(cs)
				self.data_link_model.terminate(self.atc_pov)
			except CpdlcOperationBlocked as err:
				QMessageBox.critical(self, 'CPDLC error', str(err))
	
	def resolveProblems(self):
		self.data_link_model.resolveProblems()
	
	def acceptRejectTransfer(self, accept):
		xfr = self.data_link_model.pendingTransferFrom()
		if xfr is not None:
			try:
				acft_callsign = self.data_link_model.acftCallsign()
				settings.session_manager.sendCpdlcTransferResponse(acft_callsign, xfr, accept)
				if accept:
					self.data_link_model.acceptIncomingTransfer()
					if settings.CPDLC_send_COMU9_to_accepted_transfers: # auto "CURRENT ATC UNIT"
						try:
							unit_name = settings.my_callsign
							if settings.location_radio_name:
								unit_name += ' ' + settings.location_radio_name
							settings.session_manager.sendCpdlcMsg(acft_callsign, CpdlcMessage('COMU-9 ' + unit_name.upper()))
						except CpdlcOperationBlocked as err:
							print('ERROR sending automatic COMU-9 message to %s.' % acft_callsign, file=stderr)
				else:
					self.data_link_model.terminate(False)
			except CpdlcOperationBlocked as err:
				QMessageBox.critical(self, 'CPDLC error', str(err))


	## INSTRUCT AS REQUESTED

	def appendRequestedInstructions(self):  # Assuming ATC point of view
		pendmsg = self.data_link_model.pendingInstrMsg(False) # contains instructions requested by ACFT
		if pendmsg is not None: # safeguard but button should not have been reachable
			acft = env.radarContactByCallsign(self.data_link_model.acftCallsign())
			self.appendElementsToMsgBuffer(
				[instr.toCpdlcUplinkMsgElt(acft) for instr in pendmsg.recognisedInstructions()])

	def executeReceivedInstructions(self):  # Assuming ACFT point of view (as teacher)
		pendmsg = self.data_link_model.pendingInstrMsg(True) # contains instructions received from ATC
		if pendmsg is not None: # safeguard but button should not have been reachable
			instructions = pendmsg.recognisedInstructions()
			acft_callsign = self.data_link_model.acftCallsign()
			try:
				acft = next(acft for acft in settings.session_manager.getAircraft() if acft.identifier == acft_callsign)
				try:
					acft.instruct(instructions, True) # read back to allow checking + answer to "say intentions"
					for instr in instructions:
						instruction_to_strip(instr, callsign=acft_callsign)
				except Instruction.Error as err:
					QMessageBox.critical(self, 'CPDLC instruction error', 'Unable to perform instruction: %s\nAborting.' % err)
				else:
					msg = CpdlcMessage(RspId.downlink_WILCO)
					try:
						settings.session_manager.sendCpdlcMsg(acft_callsign, msg)
						self.data_link_model.appendMessage(msg)
					except CpdlcOperationBlocked as err:
						QMessageBox.critical(self, 'CPDLC error', str(err))
			except StopIteration:
				print('CPDLC send error: ACFT "%s" not found.' % acft_callsign, file=stderr)
	
	
	## ELEMENT MENU SELECTION

	def depClearanceElementSelected(self):
		self.editElement_stack.setCurrentWidget(self.depClearance_page)
		self.eltEdit_widget.hide()
		strip = env.strips.findUniqueForCallsign(self.data_link_model.acftCallsign())
		got_clearance = None if strip is None else strip.lookup(departure_clearance_detail)
		dialog = TextInputDialog(self, 'RTEU-1 element', 'Departure clearance:', suggestion=(got_clearance if got_clearance else ''))
		dialog.installEventFilter(RadioKeyEventFilter(self))
		dialog.exec()
		txt = dialog.textResult()
		if txt is not None:
			if txt == '':
				QMessageBox.critical(self, 'RTEU-1 element', 'Empty departure clearance; aborting.')
			else:
				self.eltEdit_widget.show()
				self.depClearance_info.setText('  '.join(txt.upper().split('\n')))

	def freeTextElementSelected(self):
		self.editElement_stack.setCurrentWidget(self.freeTextEdit_page)
		self.eltEdit_widget.show()
		self.freeText_edit.clear()
		self.freeText_edit.setFocus()

	def menuElementSelected(self, elt_id):
		self.editElement_stack.setCurrentWidget(self.formattedEdit_page)
		self.eltEdit_widget.show()
		self.current_formatted_elt_id = elt_id
		# Clear and re-populate the argument zone
		self.current_formatted_elt_arg_widgets.clear()
		w = self.msgElementFormat_layout.takeAt(0)
		while w:
			w.widget().deleteLater()
			w = self.msgElementFormat_layout.takeAt(0)
		for part in re.split(r'(\{\w+})', CPDLC_element_formats[elt_id]):
			if part.startswith('{'):
				widget = mk_msg_elt_arg_widget(part[1:-1], self)
				widget.initialiseValue(elt_id, self.data_link_model.acftCallsign())
				self.current_formatted_elt_arg_widgets.append(widget)
			else:
				widget = QLabel(part.strip(), self)
			self.msgElementFormat_layout.addWidget(widget)
			widget.show()
		if self.current_formatted_elt_arg_widgets:
			self.current_formatted_elt_arg_widgets[0].setFocus()

	def appendElement(self):
		self.appendElementsToMsgBuffer([self._currentElementInput()])
		self.depClearance_info.clear() # get rid of height possibly stretching panels of other element types
		self.eltEdit_widget.hide()

	def sendUniqueElement(self):
		self.appendElementsToMsgBuffer([self._currentElementInput()])
		self.depClearance_info.clear() # get rid of height possibly stretching panels of other element types
		self.sendMessageBuffer()

	def clearMessageBuffer(self):
		self.message_buffer.clear()
		self.sendElement_button.show()
		self.eltEdit_widget.hide()
		self.sendMsgBuffer_button.setEnabled(False)
		self.msgBuffer_box.hide()
		self.message_buffer_display_model.clearList()

	def sendMessageBuffer(self):
		msg = CpdlcMessage(self.message_buffer[:])
		acft_callsign = self.data_link_model.acftCallsign()
		try:
			settings.session_manager.sendCpdlcMsg(acft_callsign, msg)
			if self.atc_pov:
				instrlst = msg.recognisedInstructions()
				if instrlst is not None:
					for instr in instrlst:
						instruction_to_strip(instr, callsign=acft_callsign)
			self.data_link_model.appendMessage(msg)
			self.clearMessageBuffer()
		except CpdlcOperationBlocked as err:
			QMessageBox.critical(self, 'CPDLC error', str(err))




##
##  MAIN CONNECTIONS PANEL
##

class CpdlcDialogueMdiSubWindow(QMdiSubWindow):
	def __init__(self, parent, data_link_model):
		QMdiSubWindow.__init__(self, parent)
		self.setWidget(CpdlcDialoguePanel(parent, data_link_model))
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.setWindowIcon(QIcon(IconFile.panel_CPDLC))
		self.setWindowTitle(data_link_model.acftCallsign())
		self.resize(self.widget().size())
		self.dlm = data_link_model
		self.dlm.statusChanged.connect(self._checkAutoClose) # CAUTION: external signal to disconnect

	def _checkAutoClose(self):
		if settings.CPDLC_closes_windows:
			if self.dlm.isTerminated() and self.dlm.statusColour() == ConnectionStatus.OK:
				self.close()

	def closeEvent(self, closeEvent):
		self.dlm.statusChanged.disconnect(self._checkAutoClose)
		widget = self.widget()
		widget.closingYourWindow()
		QMdiSubWindow.closeEvent(self, closeEvent)
		widget.deleteLater()




class CpdlcPanel(WorkspaceDockablePanel, Ui_cpdlcPanel): # is a QWidget
	def __init__(self):
		WorkspaceDockablePanel.__init__(self)
		self.setupUi(self)
		self.setWindowIcon(QIcon(IconFile.panel_CPDLC))
		self.clearHistory_button.setIcon(QIcon(IconFile.button_clear))
		self.last_selected_callsign = '' # will filter all ACFT
		self.filter_model = CpdlcHistoryFilterModel(self, env.cpdlc)
		self.connections_tableView.setModel(self.filter_model)
		# Signals
		self.activeConnections_radioButton.toggled.connect(self.setActiveFilter)
		self.expectingAndProblems_radioButtonradioButton.toggled.connect(self.setExpectingAndProblemsFilter)
		self.historyWith_radioButton.toggled.connect(self.setCallsignFilter)
		self.terminatedDialogues_radioButton.toggled.connect(self.setTerminatedFilter)
		self.callsignHistoryFilter_edit.textChanged.connect(self.updateCallsignFilter)
		self.clearHistory_button.clicked.connect(self.clearListedTerminated)
		self.connections_tableView.doubleClicked.connect(self.openFilteredDataLinkWindow)
		self.openListedWindows_button.clicked.connect(self.openListedWindows)
		self.listedWindowsOnly_button.clicked.connect(self.openListedWindowsOnly)
		self.cascadeWindows_button.clicked.connect(self.connections_mdiArea.cascadeSubWindows)
		self.closeAllWindows_button.clicked.connect(self.connections_mdiArea.closeAllSubWindows)
		# Finish setup
		self.activeConnections_radioButton.setChecked(True)
		signals.sessionStarted.connect(lambda: self.setWindowTitle('CPDLC (%s)' % settings.my_callsign))
		signals.sessionEnded.connect(lambda: self.setWindowTitle('CPDLC'))
		signals.cpdlcDialogueRequest.connect(self.openCallsignLatestDataLinkWindow)
		signals.appendCpdlcMsgElement.connect(self._catchMessageElementToAppend)
		signals.cpdlcInitLink.connect(self._checkAutoRaise)
		signals.cpdlcMessageReceived.connect(self.msgReceived)
		signals.cpdlcProblem.connect(self._checkAutoRaise) # signal has more arg's than method
		signals.selectionChanged.connect(self.updateCallsignFilterWithSelection)
		signals.selectionChanged.connect(self.connections_tableView.clearSelection)
		signals.sessionEnded.connect(self.connections_mdiArea.closeAllSubWindows)
		env.cpdlc.clearingFromHistory.connect(self.deleteDataLinkWindow)

	def flashStyleSheet(self):
		return cpdlc_panel_flash_stylesheet

	def _catchMessageElementToAppend(self, callsign, msg_element):
		link = env.cpdlc.lastDataLink(callsign)
		if link is not None:
			self._getRaiseDataLinkWidget(link, flash=False).appendElementsToMsgBuffer([msg_element])

	def _checkAutoRaise(self, callsign): # CAUTION: cpdlcProblem signal connected with more arg's
		if settings.CPDLC_raises_windows and not settings.session_start_temp_lock:
			self.openCallsignLatestDataLinkWindow(callsign, False)

	def _getRaiseDataLinkWidget(self, data_link_model, flash=True):
		try:
			window = next(w for w in self.connections_mdiArea.subWindowList() if w.widget().data_link_model is data_link_model)
		except StopIteration:
			window = CpdlcDialogueMdiSubWindow(self, data_link_model)
			self.connections_mdiArea.addSubWindow(window)
		self.show()
		self.raise_()
		window.show()
		window.raise_()
		if flash:
			flash_widget(window.widget(), dialogue_window_flash_stylesheet_fmt % QColor(ConnectionStatus.qt_colours[data_link_model.statusColour()]).name())
		return window.widget()

	def listedModels(self):
		return [env.cpdlc.dataLinkOnRow(self.filter_model.mapToSource(self.filter_model.index(row, 0)).row()) for row in range(self.filter_model.rowCount())]
	
	def msgReceived(self, sender, msg):
		if not msg.isAcknowledgement():
			self._checkAutoRaise(sender)

	def openCallsignLatestDataLinkWindow(self, callsign, only_if_live):
		link = env.cpdlc.lastDataLink(callsign)
		if link is None:
			QMessageBox.warning(self, 'Last CPDLC dialogue', 'No CPDLC history for %s.' % callsign)
		elif not only_if_live or link.isLive():
			self._getRaiseDataLinkWidget(link)
	
	def deleteDataLinkWindow(self, data_link_model):
		try:
			next(w for w in self.connections_mdiArea.subWindowList() if w.widget().data_link_model is data_link_model).close()
		except StopIteration:
			pass

	def updateCallsignFilterWithSelection(self):
		sel = selection.selectedCallsign()
		if sel:
			self.callsignHistoryFilter_edit.setText(sel)

	def setActiveFilter(self, b):
		if b:
			self.filter_model.setFilter(lambda dl: not dl.isTerminated())

	def setExpectingAndProblemsFilter(self, b):
		if b:
			self.filter_model.setFilter(lambda dl: dl.statusColour() != ConnectionStatus.OK)

	def setCallsignFilter(self, b):
		if b:
			self.filter_model.setFilter(lambda dl: dl.acftCallsign().upper() == self.callsignHistoryFilter_edit.text().upper())

	def setTerminatedFilter(self, b):
		if b:
			self.filter_model.setFilter(lambda dl: dl.isTerminated())

	def updateCallsignFilter(self, cs):
		if self.historyWith_radioButton.isChecked():
			self.setCallsignFilter(True)

	def clearListedTerminated(self):
		for dl_model in self.listedModels():
			if dl_model.isTerminated():
				env.cpdlc.clearHistory(lambda dl: dl is dl_model)

	def openFilteredDataLinkWindow(self, index):
		link = env.cpdlc.dataLinkOnRow(self.filter_model.mapToSource(index).row())
		self._getRaiseDataLinkWidget(link, flash=True)

	def openListedWindows(self):
		for link in self.listedModels():
			self._getRaiseDataLinkWidget(link, flash=False)

	def openListedWindowsOnly(self):
		to_open = self.listedModels()
		for subwindow in self.connections_mdiArea.subWindowList():
			link = subwindow.widget().data_link_model
			try:
				del to_open[next(i for i, lm in enumerate(to_open) if lm is link)]
			except StopIteration:
				subwindow.close()
		for link in to_open:
			self._getRaiseDataLinkWidget(link, flash=False)
