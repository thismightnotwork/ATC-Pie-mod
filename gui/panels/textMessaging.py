
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

from PyQt5.QtCore import Qt, QObject, QEvent
from PyQt5.QtWidgets import QWidget, QInputDialog, QMenu, QAction, QMessageBox, QCompleter
from ui.textRadioPanel import Ui_textRadioPanel
from ui.atcTextChatPanel import Ui_atcTextChatPanel

from base.util import some
from base.text import TextMessage, replace_text_aliases

from session.env import env
from session.config import settings
from session.manager import SessionType, TextMsgBlocked, teacher_callsign, student_callsign
from session.models.textMessages import TextMsgHistoryModel, TextRadioFilterModel, AtcChatFilterModel

from gui.misc import selection, signals


# ---------- Constants ----------

text_snip_separator = '|'

# -------------------------------


# =============================================== #

#                   TEXT RADIO                    #

# =============================================== #

def process_msg_line(full_line, value_error_if_missing):
	message = full_line.split(text_snip_separator, maxsplit=1)[-1]
	return replace_text_aliases(message, selection, value_error_if_missing)



class MsgCompleterPopupEventFilter(QObject):
	def __init__(self, on_return_pressed, parent=None):
		QObject.__init__(self, parent)
		self.on_return_pressed = on_return_pressed

	def eventFilter(self, popup_menu, event): # reimplementing
		if event.type() == QEvent.KeyPress and event.key() in [Qt.Key_Return, Qt.Key_Enter]:
			self.on_return_pressed()
			popup_menu.hide()
			return True
		return False



class TextRadioPanel(QWidget, Ui_textRadioPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.send_button.setEnabled(False)
		self.dest_combo.lineEdit().setClearButtonEnabled(True)
		self.msgLine_combo.lineEdit().setClearButtonEnabled(True)
		self.msgHistory_baseModel = TextMsgHistoryModel(parent=self)
		self.msgHistory_filteredModel = TextRadioFilterModel(self.msgHistory_baseModel, parent=self)
		self.msgHistory_view.setModel(self.msgHistory_filteredModel)
		self.updatePresetMessages()
		self.msgLine_combo.completer().setCompletionMode(QCompleter.PopupCompletion)
		self.msgLine_combo.completer().setFilterMode(Qt.MatchContains)
		self.msgLine_combo.completer().popup().installEventFilter(MsgCompleterPopupEventFilter(self.sendLine, parent=self))
		# Build "opts" menu
		self.clearMessageHistory_action = QAction('Clear message history', self)
		self.blacklistAsSender_action = QAction('Blacklist recipient', self)
		self.showBlacklistedSenders_action = QAction('Show blacklisted senders', self)
		self.clearBlacklist_action = QAction('Clear blacklist', self)
		checkMsgReplacements_action = QAction('Check message replacements', self)
		opts_menu = QMenu(self)
		opts_menu.addAction(self.clearMessageHistory_action)
		opts_menu.addSeparator()
		opts_menu.addAction(self.blacklistAsSender_action)
		opts_menu.addAction(self.showBlacklistedSenders_action)
		opts_menu.addAction(self.clearBlacklist_action)
		opts_menu.addSeparator()
		opts_menu.addAction(checkMsgReplacements_action)
		self.menu_button.setMenu(opts_menu)
		self.blacklistAsSender_action.setEnabled(False)
		self.clearBlacklist_action.setEnabled(False)
		# Signal connections
		checkMsgReplacements_action.triggered.connect(lambda: self.checkMsgReplacements('Check/edit message'))
		self.clearMessageHistory_action.triggered.connect(self.msgHistory_baseModel.clearHistory)
		self.blacklistAsSender_action.triggered.connect(self.addDestToSendersBlacklist)
		self.showBlacklistedSenders_action.triggered.connect(self.showSendersBlacklist)
		self.clearBlacklist_action.triggered.connect(self.clearSendersBlacklist)
		self.dest_combo.editTextChanged.connect(lambda cs: self.blacklistAsSender_action.setEnabled(cs != ''))
		self.msgLine_combo.editTextChanged.connect(lambda txt: self.send_button.setEnabled(txt != ''))
		self.send_button.clicked.connect(self.sendLine)
		self.msgLine_combo.lineEdit().returnPressed.connect(self.sendLine)
		self.dest_combo.lineEdit().returnPressed.connect(self.sendLine)
		self.msgHistory_view.clicked.connect(self.recallMessage)
		signals.selectionChanged.connect(self.suggestDestFromNewSelection)
		signals.textInstructionSuggestion.connect(self.fillInstruction)
		signals.incomingTextRadioMsg.connect(self.collectTextRadioMessage)
		signals.generalSettingsChanged.connect(self.updatePresetMessages)
		signals.generalSettingsChanged.connect(self.msgHistory_filteredModel.invalidateFilter)
		signals.slowClockTick.connect(self.updateDestList)
		signals.newATC.connect(self.updateDestList)
		signals.sessionStarted.connect(lambda t: self.toFrom_label.setText('From:' if t == SessionType.TEACHER else 'To:'))
		env.radar.newContact.connect(self.updateDestList)
	
	def focusInEvent(self, event):
		QWidget.focusInEvent(self, event)
		self.msgLine_combo.setFocus()
		self.msgLine_combo.lineEdit().selectAll()
	
	def collectTextRadioMessage(self, msg):
		if settings.session_manager.session_type == SessionType.TEACHER and msg.recipient() != student_callsign: # detecting automatic readback
			msg.setDispPrefix('R') # helps teacher distinguish these messages from those sent to student
		self.msgHistory_baseModel.addMessage(msg)
		self.msgHistory_filteredModel.invalidateFilter()
		self.msgHistory_view.scrollToBottom()
		settings.session_recorder.proposeTextRadioMsg(msg)
	
	def _postLine(self, txt):
		if txt == '':
			return # Do not send empty lines
		if settings.session_manager.session_type == SessionType.TEACHER:
			msg = TextMessage(self.dest_combo.currentText(), txt, recipient=student_callsign) # CAUTION: "collectTextRadioMessage" relies on recipient
		else:
			msg = TextMessage(settings.my_callsign, txt, recipient=self.dest_combo.currentText())
		if settings.session_manager.isRunning():
			try:
				settings.session_manager.postTextRadioMsg(msg)
				self.collectTextRadioMessage(msg)
				self.msgLine_combo.setCurrentIndex(-1)
				self.msgLine_combo.clearEditText()
			except TextMsgBlocked as err:
				QMessageBox.critical(self, 'Text radio error', str(err))
		else:
			QMessageBox.critical(self, 'Text radio error', 'No session is running.')
		self.msgLine_combo.setFocus()
	
	def sendLine(self):
		try:
			self._postLine(process_msg_line(self.msgLine_combo.currentText(), True))
		except ValueError:
			self.checkMsgReplacements('Alias replacements failed!')
	
	def checkMsgReplacements(self, box_title):
		dest = self.dest_combo.currentText()
		prompt = 'Send'
		if dest:
			prompt += ' from ' if settings.session_manager.session_type == SessionType.TEACHER else ' to '
			prompt += dest
		txt, ok = QInputDialog.getText(self, box_title, prompt + ':', text=process_msg_line(self.msgLine_combo.currentText(), False))
		if ok:
			self._postLine(txt)
		else:
			self.msgLine_combo.setFocus()
	
	def fillInstruction(self, dest, msg):
		self.dest_combo.setEditText(dest)
		self.msgLine_combo.setEditText(msg)
		self.msgLine_combo.setFocus()
	
	def updateDestList(self):
		current_text = self.dest_combo.currentText()
		self.dest_combo.clear()
		top_sugg = [] if settings.session_manager.session_type == SessionType.TEACHER else ['All traffic']
		self.dest_combo.addItems(top_sugg + sorted(env.knownAcftCallsigns()))
		self.dest_combo.setEditText(current_text)
	
	def suggestDestFromNewSelection(self):
		cs = selection.selectedCallsign()
		if cs is not None:
			self.dest_combo.setEditText(cs)
		
	def updatePresetMessages(self):
		self.msgLine_combo.clear()
		self.msgLine_combo.addItems(settings.radio_msg_presets)
		self.msgLine_combo.clearEditText()
	
	def recallMessage(self, index):
		msg = self.msgHistory_filteredModel.messageOnRow(index.row())
		if settings.session_manager.session_type == SessionType.TEACHER:
			if msg.sender() != student_callsign:
				self.dest_combo.setEditText(msg.sender())
				self.msgLine_combo.setEditText(msg.txtOnly())
		elif msg.isFromMe():
			self.dest_combo.setEditText(some(msg.recipient(), ''))
			self.msgLine_combo.setEditText(msg.txtOnly())
		else:
			self.dest_combo.setEditText(msg.sender())
		self.msgLine_combo.setFocus()
	
	def addDestToSendersBlacklist(self):
		cs = self.dest_combo.currentText()
		if cs != '' and QMessageBox.question(self, 'Text radio blacklist', 'Hide past and future messages from %s?' % cs) == QMessageBox.Yes:
			settings.text_radio_senders_blacklist.add(cs)
			self.msgHistory_filteredModel.invalidateFilter()
			self.clearBlacklist_action.setEnabled(True)
	
	def clearSendersBlacklist(self):
		settings.text_radio_senders_blacklist.clear()
		self.msgHistory_filteredModel.invalidateFilter()
		self.clearBlacklist_action.setEnabled(False)
	
	def showSendersBlacklist(self):
		if len(settings.text_radio_senders_blacklist) == 0:
			txt = 'No blacklisted senders.'
		else:
			txt = 'Blacklisted senders: %s.' % ', '.join(settings.text_radio_senders_blacklist)
		QMessageBox.information(self, 'Senders blacklist', txt)




# ================================================ #

#                ATC TEXT MESSAGING                #

# ================================================ #

class AtcTextChatPanel(QWidget, Ui_atcTextChatPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.send_button.setEnabled(False)
		self.chatHistory_baseModel = TextMsgHistoryModel(parent=self)
		self.chatHistory_filteredModel = AtcChatFilterModel(self.chatHistory_baseModel, parent=self)
		self.chatHistory_view.setModel(self.chatHistory_filteredModel)
		self.publicChannel_radioButton.setChecked(True)
		# Signal connections
		self.publicChannel_radioButton.toggled.connect(self.switchToGuiSelectedChannel)
		self.privateChannel_edit.activated.connect(self.switchToGuiSelectedChannel)
		self.privateChannel_edit.editTextChanged.connect(self.switchToGuiSelectedChannel)
		self.send_button.clicked.connect(self.sendLine)
		self.msgLine_edit.textEdited.connect(self.unmarkUnreadPMsForFilter)
		self.msgLine_edit.returnPressed.connect(self.sendLine)
		self.msgLine_edit.textChanged.connect(lambda txt: self.send_button.setEnabled(txt != ''))
		signals.incomingAtcTextMsg.connect(self.collectAtcTextMessage)
		signals.privateAtcChatRequest.connect(self.switchToPrivateChannel)
		signals.newATC.connect(self.updateAtcSuggestions)
		signals.sessionStarted.connect(self.sessionHasStarted)
		signals.sessionEnded.connect(lambda: self.publicChannel_radioButton.setEnabled(True))

	def sessionHasStarted(self, session_type):
		self.chatHistory_baseModel.clearHistory()
		if session_type == SessionType.TEACHER or session_type == SessionType.STUDENT:
			self.updateAtcSuggestions()
			self.switchToPrivateChannel(teacher_callsign)
			self.publicChannel_radioButton.setEnabled(False)
		else:
			self.switchToPublicChannel()
	
	def focusInEvent(self, event):
		QWidget.focusInEvent(self, event)
		self.focusMsgInputLine()

	def updateAtcSuggestions(self):
		save = self.privateChannel_edit.currentText()
		self.privateChannel_edit.clear()
		suggestions = sorted(set(env.ATCs.knownAtcCallsigns()) | self.chatHistory_baseModel.privateChatCallsigns())
		if settings.session_manager.session_type == SessionType.TEACHER or settings.session_manager.session_type == SessionType.STUDENT:
			suggestions.insert(0, teacher_callsign)
		self.privateChannel_edit.addItems(suggestions)
		self.privateChannel_edit.setCurrentText(save)
	
	def focusMsgInputLine(self):
		self.unmarkUnreadPMsForFilter()
		self.msgLine_edit.setFocus()
		self.msgLine_edit.selectAll()
	
	def currentChat(self): # returns the callsign to click on to get the current chat panel
		return self.chatHistory_filteredModel.filteredATC()
	
	def unmarkUnreadPMsForFilter(self):
		current = self.currentChat()
		if current is not None:
			env.ATCs.markUnreadPMs(current, False)
	
	def collectAtcTextMessage(self, msg):
		self.chatHistory_baseModel.addMessage(msg)
		self.chatHistory_view.resizeColumnToContents(0)
		self.chatHistory_view.resizeColumnToContents(1)
		if settings.session_manager.session_type == SessionType.TEACHER: # no public msg when tutoring
			msg_goes_to = msg.recipient() if msg.sender() == student_callsign else msg.sender()
			marks_PM = msg.sender() == student_callsign
		elif msg.isPrivate():
			msg_goes_to = msg.recipient() if msg.isFromMe() else msg.sender()
			marks_PM = not msg.isFromMe()
		else: # public
			marks_PM = False
			msg_goes_to = None
		current_chat = self.currentChat()
		if marks_PM and (msg_goes_to != current_chat or not self.msgLine_edit.hasFocus()):
			if settings.private_ATC_msg_auto_raise:
				signals.privateAtcChatRequest.emit(msg_goes_to) # switches, raises and scrolls table
			else:
				env.ATCs.markUnreadPMs(msg_goes_to, True)
		if msg_goes_to == current_chat:
			self.chatHistory_view.scrollToBottom()
		settings.session_recorder.proposeAtcTextMsg(msg)

	def switchToGuiSelectedChannel(self):
		if self.publicChannel_radioButton.isChecked():
			self.chatHistory_filteredModel.filterPublic()
		else: # private channel
			self.chatHistory_filteredModel.filterInvolving(self.privateChannel_edit.currentText())
		self.chatHistory_view.scrollToBottom()
		if not self.privateChannel_edit.lineEdit().hasFocus():
			self.focusMsgInputLine()
	
	def switchToPublicChannel(self):
		self.publicChannel_radioButton.setChecked(True)
	
	def switchToPrivateChannel(self, atc_callsign):
		self.privateChannel_edit.setCurrentText(atc_callsign)
		if self.privateChannel_radioButton.isChecked():
			self.switchToGuiSelectedChannel()
		else:
			self.privateChannel_radioButton.setChecked(True)
	
	def sendLine(self):
		msg_line = self.msgLine_edit.text()
		if msg_line == '':
			return # Do not send empty lines
		if settings.session_manager.isRunning():
			curr_chan = self.currentChat()
			if settings.session_manager.session_type == SessionType.TEACHER:
				send_from = curr_chan
				send_to = student_callsign
			else:
				send_from = settings.my_callsign
				send_to = curr_chan
			msg = TextMessage(send_from, replace_text_aliases(msg_line, selection, False), recipient=send_to, private=(curr_chan is not None))
			try:
				settings.session_manager.postAtcChatMsg(msg)
				self.collectAtcTextMessage(msg)
				self.msgLine_edit.clear()
			except TextMsgBlocked as err:
				QMessageBox.critical(self, 'ATC text message error', str(err))
		else:
			QMessageBox.critical(self, 'Text radio error', 'No session is running.')
		self.msgLine_edit.setFocus()
