
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

from PyQt5.QtCore import Qt, pyqtSignal, QModelIndex, QAbstractTableModel, QMimeData, QByteArray

from session.config import settings

from base.util import some
from base.strip import Strip, strip_mime_type, rack_detail, runway_box_detail, duplicate_callsign_detail, assigned_SQ_detail
from base.fpl import FPL

from gui.graphics.miscGraphics import coloured_square_icon


# ---------- Constants ----------

default_rack_name = 'Default'

# -------------------------------


class LiveStripModel(QAbstractTableModel):
	stripMoved = pyqtSignal(Strip)
	rwyBoxFilled = pyqtSignal(int, Strip) # physical RWY index, strip boxed
	rwyBoxFreed = pyqtSignal(int, Strip) # physical RWY index, strip moved out of box
	
	def __init__(self, parent=None):
		QAbstractTableModel.__init__(self, parent)
		self.rack_names = settings.saved_strip_racks[:] # ordered rack names
		if default_rack_name not in self.rack_names:
			self.rack_names.insert(0, default_rack_name)
		self.racked_strips = [[] for r in self.rack_names] # (Strip list) list, in rack order
		self.unracked_strips = [] # Strip list, in either loose bays or runway boxes
	
	def refreshViews(self): # [[*]]
		all_strips = self.listAll()
		for s in all_strips:
			s.writeDetail(duplicate_callsign_detail, None)
		while len(all_strips) > 0:
			s = all_strips.pop()
			cs = s.callsign()
			if cs is not None:
				for s2 in all_strips:
					cs2 = s2.callsign()
					if cs2 is not None and cs.upper() == cs2.upper():
						s.writeDetail(duplicate_callsign_detail, True)
						s2.writeDetail(duplicate_callsign_detail, True)
		self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))
	
	def validNewRackName(self, name):
		return name not in ['', default_rack_name] + self.rackNames()
	
	def nextSquawkCodeAssignment(self, assignment_range):
		most_free = None
		mem_count = float('+inf')
		for sq in range(assignment_range.lo, assignment_range.hi + 1):
			count = self.count(lambda s: s.lookup(assigned_SQ_detail) == sq)
			if count == 0: # Code is not assigned
				return sq
			elif count < mem_count:
				most_free = sq
				mem_count = count
		return most_free
	
	
	## STRIP ACCESSORS ##
	
	def _findStripIndex(self, pred):
		"""
		Returns:
		- (False, int) if strip is loose, int is index in self.unracked_strips
		- (True, QModelIndex) otherwise
		Raises StopIteration is strip was not found
		"""
		for irack, lst in enumerate(self.racked_strips):
			try:
				return True, self.index(next(i for i, s in enumerate(lst) if pred(s)), irack)
			except StopIteration:
				pass
		return False, next(i for i, s in enumerate(self.unracked_strips) if pred(s))
	
	def stripModelIndex(self, strip):
		try:
			racked, mi = self._findStripIndex(lambda s: s is strip)
			return mi if racked else None
		except StopIteration: # WARNING: This was reported (thus guarded here), but not thought possible. Investigate?
			return None
	
	def stripAt(self, model_index):
		"""
		Returns None if no strip at given model index
		"""
		try:
			return self.racked_strips[model_index.column()][model_index.row()]
		except IndexError:
			return None

	def count(self, pred=None):
		"""
		Returns a count of all strips, possibly filtered if bool function is given
		"""
		return len(self.listAll() if pred is None else self.findAll(pred))
	
	def listAll(self):
		return [s for lst in self.racked_strips for s in lst] + self.unracked_strips
	
	def findAll(self, pred):
		"""
		Returns a list of all strips verifying bool predicate
		"""
		return [s for s in self.listAll() if pred(s)]
	
	def findStrip(self, pred):
		"""
		Returns a strip satisfying pred, and its index.
		Raises StopIteration is none is found.
		"""
		racked, index = self._findStripIndex(pred) # or StopIteration
		return self.stripAt(index) if racked else self.unracked_strips[index]
	
	def findUniqueForCallsign(self, callsign):
		strips = self.findAll(lambda s: s.callsign() is not None and s.callsign().upper() == callsign.upper())
		return strips[0] if len(strips) == 1 else None
	
	
	## STRIP MODIFIERS ##
	
	def addStrip(self, strip, pos=None):
		rack = strip.lookup(rack_detail)
		if rack is None: # loose or boxed strip to add
			self.unracked_strips.append(strip)
			box = strip.lookup(runway_box_detail)
			if box is not None:
				self.rwyBoxFilled.emit(box, strip)
			return True
		irack = self.rackIndex(rack)
		n = self.rackLength(irack)
		if n == self.rowCount(): # is already longest column
			self.beginInsertRows(QModelIndex(), n, n)
			self.endInsertRows()
		if pos is None:
			pos = n
		self.racked_strips[irack].insert(pos, strip)
		self.dataChanged.emit(self.index(pos, irack), self.index(n, irack))
		return True
	
	def removeStrip(self, strip):
		racked, index = self._findStripIndex(lambda s: s is strip)
		if racked:
			rack_list = self.racked_strips[index.column()]
			del rack_list[index.row()]
			n = len(rack_list)
			if all(len(lst) <= n for lst in self.racked_strips): # was the only longest column
				self.beginRemoveRows(QModelIndex(), n, n)
				self.endRemoveRows()
			self.dataChanged.emit(index, self.index(n - 1, index.column()))
			strip.writeDetail(rack_detail, None)
		else: # strip is loose or in a runway box
			strip = self.unracked_strips.pop(index) # this removes the strip from the model
			old_box = strip.lookup(runway_box_detail)
			if old_box is not None:
				self.rwyBoxFreed.emit(old_box, strip)
			strip.writeDetail(runway_box_detail, None)
		return True
	
	def removeAllStrips(self):
		self.beginRemoveRows(QModelIndex(), 0, self.rowCount() - 1)
		self.unracked_strips.clear()
		for lst in self.racked_strips:
			lst.clear()
		self.endRemoveRows()
		return True
	
	def repositionStrip(self, strip, new_rack, pos=None, box=None):
		"""
		new_rack can be None to make strip loose or boxed
		pos is rack sequence number, or bottom of rack if None (illegal arg if new_rack is None)
		box is written as runway_box_detail (illegal arg if new_rack is not None)
		"""
		assert pos is None or box is None
		self.beginResetModel()
		old_rack = strip.lookup(rack_detail)
		old_box = strip.lookup(runway_box_detail)
		if old_rack is not None or new_rack is not None or old_box != box: # not loose to loose or box to same box
			racked, index = self._findStripIndex(lambda s: s is strip)
			self.removeStrip(strip)
			if racked and pos is not None and old_rack == new_rack and pos > index.row():
				pos -= 1
			strip.writeDetail(rack_detail, new_rack)
			strip.writeDetail(runway_box_detail, box)
			self.addStrip(strip, pos)
		self.stripMoved.emit(strip)
		self.endResetModel()
	
	
	## RACK ACCESSORS ##
	
	def rackNames(self):
		return self.rack_names
	
	def rackName(self, i):
		return self.rack_names[i]
	
	def rackIndex(self, rack):
		return self.rack_names.index(rack)
	
	def rackLength(self, rack):
		return len(self.racked_strips[rack])
	
	def stripSequenceNumber(self, strip):
		try:
			racked, index = self._findStripIndex(lambda s: s is strip)
		except StopIteration:
			raise ValueError('Strip not in model: %s' % strip)
		if not racked:
			raise ValueError('Unracked strip has no sequence number.')
		return index.row() + 1
	
	def previousInSequence(self, strip):
		try:
			racked, index = self._findStripIndex(lambda s: s is strip)
		except StopIteration:
			raise ValueError('Strip not in model: %s' % strip)
		if racked and index.row() != 0:
			return self.racked_strips[index.column()][index.row() - 1]
		else:
			return None
	
	
	## RACK MODIFIERS ##
	
	def addRack(self, name):
		n = self.columnCount()
		self.beginInsertColumns(QModelIndex(), n, n)
		self.rack_names.append(name)
		self.racked_strips.append([])
		self.endInsertColumns()
	
	def removeRack(self, name):
		c = self.rackIndex(name)
		self.beginRemoveColumns(QModelIndex(), c, c)
		del self.racked_strips[c]
		del self.rack_names[c]
		self.endRemoveColumns()
	
	def renameRack(self, old_name, new_name):
		col = self.rackIndex(old_name)
		self.rack_names[col] = new_name
		for strip in self.racked_strips[col]:
			strip.writeDetail(rack_detail, new_name)
		self.dataChanged.emit(self.index(0, col), self.index(self.rowCount() - 1, col))
		self.headerDataChanged.emit(Qt.Horizontal, col, col)


	## MODEL STUFF ##

	def rowCount(self, parent=QModelIndex()):
		if self.racked_strips == [] or parent.isValid():
			return 0
		else:
			return max(len(lst) for lst in self.racked_strips)

	def columnCount(self, parent=QModelIndex()):
		return 0 if parent.isValid() else len(self.rack_names)
	
	def headerData(self, section, orientation, role):
		if orientation == Qt.Horizontal:
			rack_name = self.rack_names[section]
			if role == Qt.DisplayRole:
				return rack_name
			elif role == Qt.DecorationRole:
				try:
					return coloured_square_icon(settings.rack_colours[rack_name])
				except KeyError:
					return None
		elif orientation == Qt.Vertical:
			if role == Qt.DisplayRole:
				return str(section + 1)
	
	def data(self, index, role):
		strip = self.stripAt(index)
		if strip is None:
			return None
		if role == Qt.DisplayRole:
			return str(strip)
		elif role == Qt.ToolTipRole:
			return some(strip.lookup(FPL.COMMENTS), '')
	
	def flags(self, index):
		flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
		if index.isValid():
			flags |= Qt.ItemIsDragEnabled
			if self.stripAt(index) is None and index.row() == self.rackLength(index.column()):
				flags |= Qt.ItemIsDropEnabled
		else:
			flags |= Qt.ItemIsDropEnabled
		return flags

	## Drag & drop
	def supportedDragActions(self):
		return Qt.MoveAction
	
	def supportedDropActions(self):
		return Qt.MoveAction
	
	def mimeTypes(self):
		return [strip_mime_type]
	
	def mimeData(self, indices):
		assert len(indices) == 1
		return self.mkMimeDez(self.stripAt(indices[0]))
	
	def dropMimeData(self, mime, drop_action, row, column, parent):
		if drop_action == Qt.MoveAction and mime.hasFormat(strip_mime_type):
			if parent.isValid():
				column = parent.column()
				row = parent.row()
			if column >= 0:
				if row < 0:
					row = self.rackLength(column)
				self.repositionStrip(self.fromMimeDez(mime), self.rackName(column), pos=row)
				return True
		return False
	
	# A "MIME dez" is a unique str identifier of this full strip model,
	# containing two tokens (rack, sequence number) if strip is racked,
	# or one (int index in unracked_strips) otherwise.
	
	def mkMimeDez(self, strip):
		racked, index = self._findStripIndex(lambda s: s is strip)
		str_data = '%d %d' % (index.row(), index.column()) if racked else str(index)
		data = QByteArray()
		data.append(str_data.encode('utf8'))
		mime = QMimeData()
		mime.setData(strip_mime_type, data)
		return mime
	
	def fromMimeDez(self, mime_data):
		str_data = mime_data.data(strip_mime_type).data().decode('utf8')
		tokens = [int(tok) for tok in str_data.split()]
		if len(tokens) == 1: # loose strip index
			return self.unracked_strips[tokens[0]]
		elif len(tokens) == 2: # racked strip
			return self.stripAt(self.index(*tokens))
		else:
			raise ValueError('Please report: bad MIME data format "%s"' % str_data)
