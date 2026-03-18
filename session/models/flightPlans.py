
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

from PyQt5.QtCore import Qt, QModelIndex, QAbstractTableModel

from base.util import pop_all, some
from base.fpl import FPL

from gui.misc import signals
from gui.graphics.miscGraphics import coloured_square_icon

from session.config import settings


# ---------- Constants ----------

# -------------------------------


# [[*]] STYLE [[*]]
# dataChanged.emit instructions in QAbstractTableModels cause error
# "QObject::connect: Cannot queue arguments of type 'QVector<int>'"
# if connected across threads, because of optional argument "roles".
# See also: https://bugreports.qt.io/browse/QTBUG-46517
# The work-around here is to use "refreshViews" from main thread after
# data changes have been made. Less efficient but OK as lists are small.



class FlightPlanModel(QAbstractTableModel):
	column_headers = ['Status', 'Callsign', 'Flight', 'Time']

	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.FPL_list = []
	
	def refreshViews(self): # [[*]]
		self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
	
	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return FlightPlanModel.column_headers[section]

	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.FPL_list)

	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(FlightPlanModel.column_headers)

	def data(self, index, role):
		fpl = self.FPL_list[index.row()]
		col = index.column()
		if role == Qt.DisplayRole:
			if col == 0:
				if fpl.isOnline() and fpl.hasLocalChanges(): # not in sync with online version
					return '*'
			elif col == 1:
				return some(fpl[FPL.CALLSIGN], '?')
			elif col == 2:
				return fpl.shortDescr_AD()
			elif col == 3:
				return fpl.shortDescr_time()
		
		elif role == Qt.DecorationRole:
			if col == 0:
				if fpl.isOnline():
					status = fpl.onlineStatus()
					if status == FPL.FILED:
						if fpl.isOutdated():
							colour = settings.colours['FPL_filed_outdated']
						else:
							colour = settings.colours['FPL_filed']
					elif status == FPL.OPEN:
						eta = fpl.ETA()
						if eta is None: # warning
							colour = settings.colours['FPL_open_noETA']
						elif settings.session_manager.clockTime() > eta: # overdue
							colour = settings.colours['FPL_open_overdue']
						else:
							colour = settings.colours['FPL_open']
					elif status == FPL.CLOSED:
						colour = settings.colours['FPL_closed']
					return coloured_square_icon(colour)
		
		elif role == Qt.ToolTipRole:
			if col == 0:
				if fpl.isOnline():
					status = fpl.onlineStatus()
					txt = 'Please report: unknown FPL status %s' % status # overridden below
					if status == FPL.FILED:
						txt = 'Outdated' if fpl.isOutdated() else 'Filed'
					elif status == FPL.OPEN:
						eta = fpl.ETA()
						if eta is None: # warning
							txt = 'Open, ETA unknown'
						else:
							txt = 'Open'
							minutes_overtime = int(round((settings.session_manager.clockTime() - eta).total_seconds())) // 60
							if minutes_overtime >= 1:
								txt += ', arrival overdue by %d h %02d min' % (minutes_overtime // 60, minutes_overtime % 60)
					elif status == FPL.CLOSED:
						txt = 'Closed'
					if fpl.hasLocalChanges():
						txt += ' (has local changes)'
					return txt
				else:
					return 'Not online'

	def addFPL(self, fpl):
		position = self.rowCount()
		self.beginInsertRows(QModelIndex(), position, position)
		self.FPL_list.insert(position, fpl)
		self.endInsertRows()
		return True
	
	def removeFPL(self, fpl):
		row = next(i for i in range(len(self.FPL_list)) if self.FPL_list[i] is fpl)
		self.beginRemoveRows(QModelIndex(), row, row)
		del self.FPL_list[row]
		self.endRemoveRows()
		return True
	
	def clearFPLs(self, pred=None):
		self.beginResetModel()
		if pred is None:
			self.FPL_list.clear()
		else:
			pop_all(self.FPL_list, lambda fpl: pred(fpl))
		self.endResetModel()
		return True
	
	def updateFromOnlineDownload(self, ref_fpl):
		try:
			row, to_update = next((i, fpl) for i, fpl in enumerate(self.FPL_list) if fpl.online_id == ref_fpl.online_id)
			to_update.setOnlineStatus(ref_fpl.onlineStatus())
			for d in FPL.details:
				if d in to_update.modified_details:
					to_update.modified_details[d] = ref_fpl[d]
				elif to_update[d] != ref_fpl[d]:
					to_update.details[d] = ref_fpl[d]
			self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))
		except StopIteration:
			self.addFPL(ref_fpl)
			signals.newFPL.emit(ref_fpl)
	
	def sourceIndex(self, fpl):
		return next(i for i, fpl2 in enumerate(self.FPL_list) if fpl2 is fpl) # or StopIteration
	
	def findAll(self, pred=None):
		"""
		Returns a list of the flight plans satisfying pred, or all if None.
		"""
		if pred is None:
			return self.FPL_list[:]
		else:
			return [fpl for fpl in self.FPL_list if pred(fpl)]
	
	def FPL(self, index):
		return self.FPL_list[index]
