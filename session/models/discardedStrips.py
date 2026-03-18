
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

from PyQt5.QtCore import Qt, QModelIndex, QAbstractListModel, QSortFilterProxyModel
from PyQt5.QtGui import QIcon

from base.util import some, pop_all
from base.utc import rel_session_datetime_str
from base.strip import sent_to_detail, shelved_detail

from gui.misc import IconFile

from session.config import settings


# ---------- Constants ----------

# -------------------------------


class DiscardedStripModel(QAbstractListModel):
	def __init__(self, parent):
		QAbstractListModel.__init__(self, parent)
		self.discarded_strips = [] # (strip, timestamp) list
		self.handed_over_icon = QIcon(IconFile.panel_ATCs)
		self.deleted_icon = QIcon(IconFile.button_bin)
		self.shelved_icon = QIcon(IconFile.button_shelf)

	def rowCount(self, parent=None):
		return len(self.discarded_strips)
	
	def data(self, index, role):
		strip, timestamp = self.discarded_strips[index.row()]
		if role == Qt.DisplayRole:
			line1 = some(strip.callsign(), '?')
			toATC = strip.lookup(sent_to_detail)
			if toATC is None:
				line2 = 'Shelved ' if strip.lookup(shelved_detail) else 'Deleted '
			else:
				line1 += ' >> ' + toATC
				line2 = 'Sent '
			line2 += rel_session_datetime_str(timestamp)
			## RETURN
			return '%s\n  %s' % (line1, line2)
		elif role == Qt.DecorationRole:
			if strip.lookup(sent_to_detail) is None: # was deleted or shelved
				return self.shelved_icon if strip.lookup(shelved_detail) else self.deleted_icon
			else: # was handed over
				return self.handed_over_icon

	def listAll(self):
		return [s for s, t in self.discarded_strips]
	
	def getStrip(self, row):
		return self.discarded_strips[row][0]

	def count(self, pred=None):
		return len(self.discarded_strips) if pred is None else sum(pred(s) for s, t in self.discarded_strips)
	
	def addStrip(self, strip):
		self.beginInsertRows(QModelIndex(), 0, 0)
		self.discarded_strips.insert(0, (strip, settings.session_manager.clockTime()))
		self.endInsertRows()
	
	def forgetStrips(self, pred):
		self.beginResetModel()
		pop_all(self.discarded_strips, lambda elt: pred(elt[0]))
		self.endResetModel()

	def remove(self, strip):
		self.forgetStrips(lambda s: s is strip)




class ShelfFilterModel(QSortFilterProxyModel):
	def __init__(self, parent, source, shelf):
		QSortFilterProxyModel.__init__(self, parent)
		self.is_shelf = shelf
		self.setSourceModel(source)
	
	def stripAt(self, index):
		return self.sourceModel().getStrip(self.mapToSource(index).row())
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		return bool(self.sourceModel().getStrip(sourceRow).lookup(shelved_detail)) == self.is_shelf
	
	def forgetStrips(self):
		self.sourceModel().forgetStrips(lambda strip: bool(strip.lookup(shelved_detail)) == self.is_shelf)


