
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

from PyQt5.QtCore import Qt, QAbstractTableModel, QSortFilterProxyModel, QModelIndex

from base.utc import rel_session_datetime_str

from session.config import settings
from session.manager import SessionType, student_callsign


# ---------- Constants ----------

# -------------------------------



class TextMsgHistoryModel(QAbstractTableModel):
	columns = ['Time', 'From', 'Message']

	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.msg_list = []

	def rowCount(self, parent=None):
		return len(self.msg_list)

	def columnCount(self, parent):
		return len(TextMsgHistoryModel.columns)

	def data(self, index, role):
		if role == Qt.DisplayRole:
			msg = self.messageOnRow(index.row())
			col = index.column()
			if col == 0:
				return rel_session_datetime_str(msg.timeStamp(), seconds=True)
			if col == 1:
				return msg.sender()
			if col == 2:
				return msg.txtMsg()

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return TextMsgHistoryModel.columns[section]
	
	def messageOnRow(self, index):
		return self.msg_list[index]
	
	def privateChatCallsigns(self):
		if settings.session_manager.session_type == SessionType.TEACHER:
			return set(msg.recipient() if msg.sender() == student_callsign else msg.sender() for msg in self.msg_list if msg.isPrivate())
		else:
			return set(msg.recipient() if msg.isFromMe() else msg.sender() for msg in self.msg_list if msg.isPrivate())
	
	def addMessage(self, msg):
		position = self.rowCount()
		self.beginInsertRows(QModelIndex(), position, position)
		self.msg_list.insert(position, msg)
		self.endInsertRows()
		return True
	
	def clearHistory(self):
		self.beginResetModel()
		self.msg_list.clear()
		self.endResetModel()




class TextRadioFilterModel(QSortFilterProxyModel):
	def __init__(self, base_model, parent=None):
		QSortFilterProxyModel.__init__(self, parent)
		self.setSourceModel(base_model)
	
	def messageOnRow(self, filtered_list_row):
		source_index = self.mapToSource(self.index(filtered_list_row, 0)).row()
		return self.sourceModel().messageOnRow(source_index)
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		msg = self.sourceModel().messageOnRow(sourceRow)
		return msg.sender() not in settings.text_radio_senders_blacklist \
			and (settings.text_radio_history_time is None or settings.session_manager.clockTime() - msg.timeStamp() <= settings.text_radio_history_time)



class AtcChatFilterModel(QSortFilterProxyModel):
	def __init__(self, base_model, parent=None):
		QSortFilterProxyModel.__init__(self, parent)
		self.selected_ATC = None # None for public messages (public chat room)
		self.setSourceModel(base_model)
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		return self.filterAcceptsMessage(self.sourceModel().messageOnRow(sourceRow))
	
	def filterAcceptsMessage(self, msg):
		if msg.isPrivate():
			return msg.involves(self.selected_ATC)
		else:
			return self.selected_ATC is None

	def filterPublic(self):
		self.selected_ATC = None
		self.invalidateFilter()
	
	def filterInvolving(self, callsign):
		self.selected_ATC = callsign
		self.invalidateFilter()
	
	def filteredATC(self):
		"""
		returns None if currently selecting non-private messages
		"""
		return self.selected_ATC
