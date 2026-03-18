
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

from PyQt5.QtCore import Qt, QAbstractTableModel, QSortFilterProxyModel, QModelIndex

from base.coords import dist_str
from base.nav import Navpoint
from base.util import upper_1st

from session.env import env


# ---------- Constants ----------

# -------------------------------


class NavpointTableModel(QAbstractTableModel):
	column_headers = ['Type', 'Code/ID', 'Name/info']

	def __init__(self, parent, navpoints, include_local_parking):
		QAbstractTableModel.__init__(self, parent)
		self.navpoints = navpoints
		if env.airport_data is None or not include_local_parking:
			self.pk_pos = []
		else:
			self.pk_pos = env.airport_data.ground_net.parkingPositions()

	def rowCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.navpoints) + len(self.pk_pos)

	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(NavpointTableModel.column_headers)

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return NavpointTableModel.column_headers[section]

	def data(self, index, role):
		row = index.row()
		col = index.column()
		if role == Qt.DisplayRole:
			if row < len(self.navpoints): # row is a navpoint
				navpoint = self.navpoints[row]
				if col == 0:
					return Navpoint.tstr(navpoint.type)
				elif col == 1:
					return navpoint.code
				elif col == 2:
					return navpoint.long_name
			else: # row is a parking position
				pk = self.pk_pos[row - len(self.navpoints)]
				#EarthCoords, Heading, str (gate|hangar|misc|tie-down), str list (heavy|jets|turboprops|props|helos)
				if col == 0:
					return 'PKG'
				elif col == 1:
					return pk
				elif col == 2:
					pk_info = env.airport_data.ground_net.parkingPosInfo(pk)
					txt = upper_1st(pk_info[2])
					if len(pk_info[3]) > 0:
						txt += ' for ' + ', '.join(pk_info[3])
					return txt
		
		elif role == Qt.ToolTipRole:
			coords = self.coordsForRow(row)
			if env.radarPos() is None:
				return str(coords)
			else:
				distance = env.radarPos().distanceTo(coords)
				return '%s°, %s' % (env.radarPos().headingTo(coords).readTrue(), dist_str(distance))
	
	## data accessors
	
	def navpointOnRow(self, row): # WARNING: fails if row is a parking position
		return self.navpoints[row]
	
	def navTypeForRow(self, row):
		return self.navpoints[row].type if row < len(self.navpoints) else None
	
	def codeForRow(self, row):
		return self.navpoints[row].code if row < len(self.navpoints) else self.pk_pos[row - len(self.navpoints)]
	
	def coordsForRow(self, row):
		if row < len(self.navpoints): # row is a navpoint
			return self.navpoints[row].coordinates
		else: # row is a parking position
			return env.airport_data.ground_net.parkingPosition(self.pk_pos[row - len(self.navpoints)])





class MapNavpointFilterModel(QSortFilterProxyModel):
	def __init__(self, nav_db, parent=None):
		QSortFilterProxyModel.__init__(self, parent)
		self.text_filter = re.compile('') # set to None when input regexp is invalid
		self.navtype_filters = {t: True for t in Navpoint.types}
		self.include_pkg = True
		self.search_in_names = True
		self.setSourceModel(NavpointTableModel(parent, nav_db.findAll(), True))
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		t = self.sourceModel().navTypeForRow(sourceRow) # None if parking pos
		if self.text_filter is None or t is None and not self.include_pkg or t is not None and not self.navtype_filters[t]:
			return False # problem with regexp or row filtered out by type
		elif self.text_filter.search(self.sourceModel().codeForRow(sourceRow)):
			return True
		elif t is None or not self.search_in_names:
			return False
		else: # only thing left: search in long name
			return bool(self.text_filter.search(self.sourceModel().navpointOnRow(sourceRow).long_name))
		
	def setTypeFilters(self, ad=None, aid=None, fix=None, rnav=None, pkg=None):
		if ad is not None:
			self.navtype_filters[Navpoint.AD] = ad
		if aid is not None:
			for t in [Navpoint.VOR, Navpoint.NDB, Navpoint.ILS]:
				self.navtype_filters[t] = aid
		if fix is not None:
			self.navtype_filters[Navpoint.FIX] = fix
		if rnav is not None:
			self.navtype_filters[Navpoint.RNAV] = rnav
		if pkg is not None:
			self.include_pkg = pkg
		self.invalidateFilter()
	
	def setSearchInNames(self, b):
		self.search_in_names = b
		self.invalidateFilter()
	
	def setTextFilter(self, string):
		try:
			self.text_filter = re.compile(string, flags=re.IGNORECASE)
		except re.error:
			self.text_filter = None
		self.invalidateFilter()




class AirportNameFilterModel(QSortFilterProxyModel):
	def __init__(self, nav_db, parent=None):
		QSortFilterProxyModel.__init__(self, parent)
		self.filter_switch = True # text filter looks in: AD names if True; codes if False
		self.text_filter = re.compile('') # set to None when input regexp is invalid
		self.setSourceModel(NavpointTableModel(parent, nav_db.byType(Navpoint.AD), False))

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				if section == 0:
					return 'Code'
				elif section == 1:
					return 'Name'
	
	def filterAcceptsColumn(self, sourceCol, sourceParent):
		return sourceParent.isValid() or sourceCol != 0
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		if self.text_filter is None:
			return False
		else:
			navpoint = self.sourceModel().navpointOnRow(sourceRow)
			return bool(self.text_filter.search(navpoint.long_name if self.filter_switch else navpoint.code))
	
	def navpointAtIndex(self, model_index):
		return self.sourceModel().navpointOnRow(self.mapToSource(model_index).row())
	
	def _setTextFilter(self, string):
		try:
			self.text_filter = re.compile(string, flags=re.IGNORECASE)
		except re.error:
			self.text_filter = None
		self.invalidateFilter()
	
	def setCodeFilter(self, string):
		self.filter_switch = False
		self._setTextFilter(string)
	
	def setNameFilter(self, string):
		self.filter_switch = True
		self._setTextFilter(string)
