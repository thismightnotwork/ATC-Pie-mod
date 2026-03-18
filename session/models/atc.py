
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

from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QIcon

from base.phone import PhoneLineStatus
from base.coords import dist_str
from base.instr import Instruction
from base.strip import strip_mime_type
from base.util import some

from gui.actions import strip_dropped_on_ATC
from gui.misc import signals, IconFile

from session.config import settings
from session.env import env
from session.manager import SessionType


# ---------- Constants ----------

nearby_dist_threshold = .1 # NM

# -------------------------------



class ATC:
	def __init__(self, callsign):
		self.callsign = callsign
		self.social_name = None
		self.position = None
		self.frequency = None
	
	def toolTipText(self):
		txt = ''
		if self.social_name is not None:
			txt += self.social_name + '\n'
		txt += 'Position: '
		if self.position is None:
			txt += 'unknown'
		else:
			distance = env.radarPos().distanceTo(self.position)
			if distance < nearby_dist_threshold:
				txt += 'nearby'
			else:
				txt += '%s°, %s' % (env.radarPos().headingTo(self.position).readTrue(), dist_str(distance))
		return txt









class AtcTableModel(QAbstractTableModel):
	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.textChat_received_icon = QIcon(IconFile.panel_atcChat)
		self.gui = parent
		self.mouse_drop_has_ALT = False # CAUTION: set by external drop event
		self.ATCs = [] # list of ATC objects to appear in the table view
		self.temp_ATCs = set() # subset of self.ATCs; complementing set is the entries known from "updateATC", and kept until explicit "removeATC"
		self.unread_private_msg_from = set() # callsigns who have sent ATC messages since their last view switch
		self.flashing_icons_toggle = False # will keep toggling
	
	def _emitAtcChanged(self, callsign, column=None):
		try:
			row = next(i for i, atc in enumerate(self.ATCs) if atc.callsign == callsign)
			self.dataChanged.emit(self.index(row, some(column, 0)), self.index(row, some(column, self.columnCount() - 1)))
		except StopIteration:
			pass

	def _flashRingingIcons(self):
		self.flashing_icons_toggle = not self.flashing_icons_toggle
		self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount(), 0))
	
	def columnCount(self, parent=QModelIndex()):
		return 3  # 0: phone line; 1: callsign/PMs; 2: frequency

	def rowCount(self, parent=QModelIndex()):
		return len(self.ATCs)
	
	def flags(self, index):
		flags = Qt.ItemIsEnabled
		if index.isValid() and index.column() == 1: # callsign column
			flags |= Qt.ItemIsDropEnabled
		return flags
		
	def data(self, index, role):
		atc = self.ATCs[index.row()]
		col = index.column()
		llm = settings.session_manager.phoneLineManager()
		
		if role == Qt.DisplayRole:
			if col == 1:
				return atc.callsign
			elif col == 2:
				if atc.frequency is not None:
					return str(atc.frequency)
		
		elif role == Qt.DecorationRole:
			if col == 0 and llm is not None:
				lls = llm.lineStatus(atc.callsign)
				if lls == PhoneLineStatus.IDLE:
					return QIcon(IconFile.pixmap_telephone_idle)
				elif lls == PhoneLineStatus.CALLING and self.flashing_icons_toggle:
					return QIcon(IconFile.pixmap_telephone_placedCall)
				elif lls == PhoneLineStatus.RINGING and self.flashing_icons_toggle:
					return QIcon(IconFile.pixmap_telephone_incomingCall)
				elif lls == PhoneLineStatus.HELD_INCOMING:
					return QIcon(IconFile.pixmap_telephone_incomingCall)
				elif lls == PhoneLineStatus.HELD_OUTGOING:
					return QIcon(IconFile.pixmap_telephone_placedCall)
				elif lls == PhoneLineStatus.IN_CALL:
					return QIcon(IconFile.pixmap_telephone_inCall)
			elif col == 1:
				if atc.callsign in self.unread_private_msg_from:
					return self.textChat_received_icon
		
		elif role == Qt.ToolTipRole:
			if col == 0 and llm is not None:
				lls = llm.lineStatus(atc.callsign)
				if lls is not None:
					return {
							PhoneLineStatus.IDLE: 'Phone line idle',
							PhoneLineStatus.CALLING: 'Placed phone call',
							PhoneLineStatus.RINGING: 'Incoming phone call',
							PhoneLineStatus.HELD_INCOMING: 'Call ended/held (by us), line still requested',
							PhoneLineStatus.HELD_OUTGOING: 'Call ended/held (by them), still requesting',
							PhoneLineStatus.IN_CALL: 'Call in progress'
						}[lls]
			return atc.toolTipText()
	
	
	## ACCESS FUNCTIONS

	def knownAtcCallsigns(self):
		return [atc.callsign for atc in self.ATCs]
	
	# by callsign, raise KeyError if not in model
	def getATC(self, cs):
		try:
			return next(atc for atc in self.ATCs if atc.callsign == cs)
		except StopIteration:
			raise KeyError(cs)
	
	def handoverInstructionTo(self, atc):
		try:
			frq = self.getATC(atc).frequency # may be None
		except KeyError:
			frq = None
		return Instruction(Instruction.HAND_OVER, arg=atc, arg2=(None if frq is None else str(frq)))
	
	
	## MODIFICATION FUNCTIONS
	
	def _addTemp(self, callsign):
		row = len(self.ATCs)
		self.beginInsertRows(QModelIndex(), row, row)
		self.ATCs.append(ATC(callsign))
		self.temp_ATCs.add(callsign)
		self.endInsertRows()
	
	def updateATC(self, callsign, pos, name, frq):
		"""
		Updates an ATC if already present; adds it otherwise with the given details. ATC is no more "temp" display after this.
		"""
		self.temp_ATCs.discard(callsign) # no more a "temp" if it was at this point
		try:
			row, atc = next((i, atc) for i, atc in enumerate(self.ATCs) if atc.callsign == callsign)
		except StopIteration:
			atc = ATC(callsign)
			row = len(self.ATCs)
			self.beginInsertRows(QModelIndex(), row, row)
			self.ATCs.append(atc)
			signals.newATC.emit(callsign)
			self.endInsertRows()
		atc.social_name = name
		atc.position = pos
		atc.frequency = frq
		self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1)) # whole row
	
	def removeATC(self, callsign): # clear from list unless a phone line or PM status requires it to stay (becomes "temp")
		try:
			row = next(i for i, atc in enumerate(self.ATCs) if atc.callsign == callsign)
			llm = settings.session_manager.phoneLineManager()
			if llm is None or not (llm.isOpenIncoming(callsign) or llm.isOpenOutgoing(callsign) or callsign in self.unread_private_msg_from):
				self.beginRemoveRows(QModelIndex(), row, row)
				del self.ATCs[row]
				self.endRemoveRows()
			else:
				self.temp_ATCs.add(callsign) # NOTE: might have been there already
		except StopIteration:
			pass
	
	def updatePhoneLineStatus(self, callsign):
		try:
			row = next(i for i, atc in enumerate(self.ATCs) if atc.callsign == callsign)
			if callsign in self.temp_ATCs:
				self.removeATC(callsign) # will be kept if new status is neither None nor IDLE
			else:
				self._emitAtcChanged(callsign, column=0)
		except StopIteration:
			llm = settings.session_manager.phoneLineManager()
			if llm is not None and (llm.isOpenIncoming(callsign) or llm.isOpenOutgoing(callsign)):
				self._addTemp(callsign)
	
	def markUnreadPMs(self, callsign, b):
		if b:
			self.unread_private_msg_from.add(callsign)
			if not any(atc.callsign == callsign for atc in self.ATCs):
				self._addTemp(callsign)
		else:
			self.unread_private_msg_from.discard(callsign)
			if callsign in self.temp_ATCs:
				self.removeATC(callsign) # will be kept in temp if non-idle phone line
		self._emitAtcChanged(callsign, column=1)
	
	def clear(self):
		self.beginResetModel()
		self.ATCs.clear()
		self.temp_ATCs.clear()
		self.unread_private_msg_from.clear()
		self.endResetModel()
	
	
	## MOUSE STUFF
	
	def itemDoubleClicked(self, index, shift):
		atc = self.ATCs[index.row()].callsign
		if shift:
			pos = self.getATC(atc).position
			if pos is None:
				signals.statusBarMsg.emit('Position unknown for %s' % atc)
			else:
				signals.indicatePoint.emit(pos)
		else: # double-clicked without SHIFT
			col = index.column()
			if col == 0 and settings.session_manager.session_type != SessionType.PLAYBACK:
				llm = settings.session_manager.phoneLineManager()
				if llm is not None:
					if llm.isOpenOutgoing(atc):
						llm.dropPhoneLine(atc)
					else:
						llm.requestPhoneLine(atc)
			elif col == 1:
				signals.privateAtcChatRequest.emit(atc)
	
	def supportedDropActions(self):
		return Qt.MoveAction
	
	def mimeTypes(self):
		return [strip_mime_type]
	
	def dropMimeData(self, mime, drop_action, row, column, parent):
		if drop_action == Qt.MoveAction and mime.hasFormat(strip_mime_type):
			strip = env.strips.fromMimeDez(mime)
			atc_callsign = self.ATCs[parent.row()].callsign
			strip_dropped_on_ATC(strip, atc_callsign, self.mouse_drop_has_ALT)
			return True
		return False
