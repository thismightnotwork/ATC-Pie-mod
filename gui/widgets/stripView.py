
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

from datetime import timedelta

from PyQt5.QtCore import Qt, QSize, QRect, QItemSelectionModel, QSortFilterProxyModel, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QIcon, QPen, QBrush, QFont, QColor
from PyQt5.QtWidgets import QTableView, QHeaderView, QAbstractItemView, QStyledItemDelegate, \
	QTabWidget, QTabBar, QMessageBox, QMenu, QAction, QPushButton, QToolButton

from base.fpl import FPL
from base.strip import strip_mime_type, received_from_detail, recycled_detail, auto_printed_detail, \
		runway_box_detail, rack_detail, soft_link_detail, departure_clearance_detail
from base.utc import duration_str

from gui.actions import new_strip_dialog, discard_strip, push_details_to_FPL, pull_XPDR_details, pull_FPL_details
from gui.dialogs.depClearance import DepartureClearanceEditDialog
from gui.dialogs.racks import EditRackDialog
from gui.graphics.flightStrips import strip_size_hint, strip_mouse_press, paint_strip_box
from gui.graphics.miscGraphics import new_pen, coloured_square_icon
from gui.misc import signals, selection, IconFile

from session.config import settings
from session.env import env


# ---------- Constants ----------

strip_placeholder_margin = 5 # for delegate text document and deco
strip_icon_max_width = 20
max_RWY_sep_time_disp = timedelta(minutes=5)

# -------------------------------



class StripItemDelegate(QStyledItemDelegate):
	def __init__(self, parent):
		QStyledItemDelegate.__init__(self, parent)
		self.show_icons = True
	
	def setShowIcons(self, b):
		self.show_icons = b
	
	def sizeHint(self, option, index): # QStyleOptionViewItem, QModelIndex
		return strip_size_hint(option.font) + QSize(2 * strip_placeholder_margin, 2 * strip_placeholder_margin)
	
	def paint(self, painter, option, index):
		strip = index.model().stripAt(index)
		# STYLE: rely ONLY on models' data to avoid redefining "stripAt"
		# for every model, e.g. here: strip = env.strips.stripAt(index.data())
		icon = None
		if self.show_icons and strip is not None:
			if strip.lookup(recycled_detail):
				icon = QIcon(IconFile.pixmap_recycle)
			elif strip.lookup(received_from_detail) is not None:
				icon = QIcon(IconFile.panel_ATCs)
			elif strip.lookup(auto_printed_detail) is not None:
				icon = QIcon(IconFile.pixmap_printer)
		smw = option.rect.width() # width of strip with margins
		m2 = 2 * strip_placeholder_margin
		h = option.rect.height()
		painter.save()
		painter.translate(option.rect.topLeft())
		if icon is None:
			iw = 0
		else:
			iw = min(strip_icon_max_width, h - m2) # icon width
			smw -= iw + strip_placeholder_margin
			icon.paint(painter, 0, (h - iw) // 2, iw, iw)
		if strip is not None:
			paint_strip_box(self, painter, strip, QRect(strip_placeholder_margin + iw, strip_placeholder_margin, smw - m2, h - m2))
		painter.restore()





class RackedStripsFilterModel(QSortFilterProxyModel):
	def __init__(self, parent):
		QSortFilterProxyModel.__init__(self, parent)
		self.rack_filter_list = [] # WARNING: should keep source model rack order (this is just a filter model)
		self.setSourceModel(env.strips)
	
	def setRackFilter(self, racks):
		self.rack_filter_list = [r for r in env.strips.rackNames() if r in racks] # keep source order
		self.invalidateFilter()
	
	def updateRackFilter(self, renamed_racks):
		self.setRackFilter([renamed_racks.get(r, r) for r in self.rack_filter_list]) # this also removes those no more existing
	
	def rackName(self, proxy_column):
		return self.rack_filter_list[proxy_column]
	
	def stripAt(self, proxy_index):
		return self.sourceModel().stripAt(self.mapToSource(proxy_index))
	
	def stripModelIndex(self, strip):
		smi = self.sourceModel().stripModelIndex(strip)
		return None if smi is None else self.mapFromSource(smi)

	## MODEL STUFF
	def filterAcceptsColumn(self, sourceCol, sourceParent):
		return self.sourceModel().rackName(sourceCol) in self.rack_filter_list
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		check_src_indexes = [si for si, sr in enumerate(self.sourceModel().rackNames()) if sr in self.rack_filter_list]
		if len(check_src_indexes) == 0:
			return False
		else:
			return sourceRow < max(self.sourceModel().rackLength(i) for i in check_src_indexes)
	
	def dropMimeData(self, mime, drop_action, row, column, parent):
		if not parent.isValid() and 0 <= column < len(self.rack_filter_list): # capture dropping under last strip
			src_rack_index = self.sourceModel().rackIndex(self.rackName(column))
			return self.sourceModel().dropMimeData(mime, drop_action, row, src_rack_index, parent)
		return QSortFilterProxyModel.dropMimeData(self, mime, drop_action, row, column, parent)






##----------------------------##
##                            ##
##           BUTTONS          ##
##                            ##
##----------------------------##

class StripMenuButton(QToolButton):
	def __init__(self, parent):
		QToolButton.__init__(self, parent)
		self.setIcon(QIcon(IconFile.pixmap_strip))
		self.setPopupMode(QToolButton.InstantPopup)
		self.depClearance_action = QAction('Register/view DEP clearance...', self)
		self.rmDepClearance_action = QAction('Edit/remove DEP clearance...', self)
		self.saveAcftType_action = QAction('Save ACFT type for callsign', self)
		self.pullFplDetails_action = QAction('Pull FPL details', self)
		self.pullXpdrDetails_action = QAction('Pull XPDR details', self)
		self.pushToFpl_action = QAction('Push details to FPL', self)
		self.deleteStrip_action = QAction('Delete strip', self)
		strip_menu = QMenu(self)
		strip_menu.addAction(self.depClearance_action)
		strip_menu.addAction(self.rmDepClearance_action)
		strip_menu.addAction(self.saveAcftType_action)
		strip_menu.addSeparator()
		strip_menu.addAction(self.pullFplDetails_action)
		strip_menu.addAction(self.pullXpdrDetails_action)
		strip_menu.addAction(self.pushToFpl_action)
		strip_menu.addSeparator()
		strip_menu.addAction(self.deleteStrip_action)
		self.setMenu(strip_menu)
		self.depClearance_action.triggered.connect(self.registerViewDepClearance)
		self.rmDepClearance_action.triggered.connect(self.editRemoveDepClearance)
		self.saveAcftType_action.triggered.connect(self.saveAcftType)
		self.pullFplDetails_action.triggered.connect(lambda: pull_FPL_details(self))
		self.pullXpdrDetails_action.triggered.connect(lambda: pull_XPDR_details(self))
		self.pushToFpl_action.triggered.connect(lambda: push_details_to_FPL(self))
		self.deleteStrip_action.triggered.connect(lambda: discard_strip(self, selection.strip, False))

	def updateButtonsAndActions(self):
		self.setEnabled(selection.strip is not None)
		if selection.strip is not None:
			self.rmDepClearance_action.setEnabled(selection.strip.lookup(departure_clearance_detail) is not None)
			self.pushToFpl_action.setEnabled(selection.strip.linkedFPL() is not None)
			self.pullFplDetails_action.setEnabled(selection.strip.linkedFPL() is not None)
			self.pullXpdrDetails_action.setEnabled(selection.strip.linkedAircraft() is not None)

	def saveAcftType(self):
		if selection.strip is not None:
			cs = selection.strip.callsign() # always upper case
			typ = selection.strip.lookup(FPL.ACFT_TYPE)
			if cs and typ:
				got = settings.known_aircraft.get(cs)
				if not got or QMessageBox.question(self, 'Save ACFT type', '%s already known as %s. Override?' % (cs, got)) == QMessageBox.Yes:
					settings.known_aircraft[cs] = typ
					QMessageBox.information(self, 'Save ACFT type', 'Saved %s as known %s.' % (cs, typ))
			else:
				QMessageBox.critical(self, 'Save ACFT type', 'Missing callsign or ACFT type value.')

	def registerViewDepClearance(self):
		if selection.strip is not None:
			if selection.strip.lookup(departure_clearance_detail):
				signals.depClearanceDispRequest.emit(selection.strip)
			else:
				DepartureClearanceEditDialog(self, selection.strip).exec()

	def editRemoveDepClearance(self):
		if selection.strip is not None and selection.strip.lookup(departure_clearance_detail) is not None:
			DepartureClearanceEditDialog(self, selection.strip).exec()




class ShelfButtonWidget(QPushButton):
	def __init__(self, parent=None):
		QPushButton.__init__(self, parent)
		self.setIcon(QIcon(IconFile.button_shelf))
		self.setToolTip('Strip shelf')
		self.setFlat(True)
		self.setAcceptDrops(True)
		self.clicked.connect(signals.openShelfRequest.emit)

	def dragEnterEvent(self, event):
		if event.mimeData().hasFormat(strip_mime_type):
			event.acceptProposedAction()

	def dropEvent(self, event):
		mime_data = event.mimeData()
		if mime_data.hasFormat(strip_mime_type):
			discard_strip(self, env.strips.fromMimeDez(mime_data), True)
			event.acceptProposedAction()






##############################

##        TABLE VIEW        ##

##############################

class StripTableView(QTableView):
	"""
	CAUTION: this is derived for *ANY* table view with draggable strips,
	incl. rack tables, tabbed racks, and even RWY boxes
	"""
	def __init__(self, parent):
		QTableView.__init__(self, parent)
		self.horizontalHeader().setSectionsMovable(True)
		self.setItemDelegate(StripItemDelegate(self))
		self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
		self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
		self.setSelectionMode(QAbstractItemView.SingleSelection)
		self.setDragEnabled(True)
		self.setAcceptDrops(True)
		self.setShowGrid(False)
		self.horizontalHeader().sectionDoubleClicked.connect(self.columnDoubleClicked)
	
	def setDivideHorizWidth(self, toggle):
		for section in range(self.horizontalHeader().count()):
			self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch if toggle else QHeaderView.Interactive)
	
	def updateSelection(self):
		self.clearSelection()
		if selection.strip is not None:
			mi = self.model().stripModelIndex(selection.strip)
			if mi is not None:
				self.selectionModel().select(mi, QItemSelectionModel.ClearAndSelect)
				self.scrollTo(mi)
	
	def mousePressEvent(self, event):
		QTableView.mousePressEvent(self, event)
		index = self.indexAt(event.pos())
		strip = self.model().stripAt(index) if index.isValid() else None
		if strip is None:
			selection.deselect()
		else:
			strip_mouse_press(strip, event)
			signals.selectionChanged.emit() # resync selection if event did not change it
	
	def dropEvent(self, event):
		QTableView.dropEvent(self, event)
		if not event.isAccepted(): # happens when outside of table area
			column = self.horizontalHeader().logicalIndexAt(event.pos())
			row = self.verticalHeader().logicalIndexAt(event.pos())
			if self.model().dropMimeData(event.mimeData(), event.dropAction(), row, column, QModelIndex()):
				event.acceptProposedAction()
		if event.isAccepted():
			signals.selectionChanged.emit()
	
	def mouseDoubleClickEvent(self, event):
		strip = selection.strip
		if strip is None: # double-clicked off strip
			self.doubleClickOffStrip(event)
		elif event.button() == Qt.LeftButton: # double-clicked on a strip
			event.accept()
			if event.modifiers() & Qt.ShiftModifier: # indicate radar link or identification
				acft = strip.linkedAircraft()
				if acft is None:
					acft = strip.lookup(soft_link_detail)
				if acft is not None:
					signals.indicatePoint.emit(acft.coords())
			elif event.modifiers() & Qt.AltModifier: # open CPDLC dialogue
				cs = selection.selectedCallsign()
				if cs is not None:
					signals.cpdlcDialogueRequest.emit(cs, False)
			else: # request strip edit
				signals.stripEditRequest.emit(strip)
		if not event.isAccepted():
			QTableView.mouseDoubleClickEvent(self, event)
	
	def columnDoubleClicked(self, column):
		if column != -1:
			EditRackDialog(self, self.model().rackName(column)).exec()
	
	def doubleClickOffStrip(self, event):
		column = self.horizontalHeader().logicalIndexAt(event.pos())
		if column != -1 and not event.modifiers() & Qt.ShiftModifier:
			rack = self.model().rackName(column)
			new_strip_dialog(self, rack)
			event.accept()




	


###############################

##        TABBED VIEW        ##

###############################

class StripRackTabs(QTabWidget):
	def __init__(self, parent=None):
		QTabWidget.__init__(self, parent)
		self.tab_bar = StripRackTabBar(self)
		self.setTabBar(self.tab_bar)
		self.updateTabIcons()
	
	def rackTabs(self):
		"""
		Enumerates the tabbed rack view widgets.
		"""
		return [self.widget(i) for i in range(self.count())]
	
	def setTabs(self, racks):
		for index, rack in enumerate(racks):
			try:
				i = next(i for i in range(self.count()) if self.widget(i).singleRackFilter() == rack)
				if i > index:
					self.tabBar().moveTab(i, index)
			except StopIteration: # must insert view here
				self.insertTab(index, SingleRackColumnView(self, rack), rack)
		n = len(racks)
		while self.count() > n:
			w = self.widget(n)
			self.removeTab(n)
			w.deleteLater()
	
	def updateTabName(self, old_name, new_name):
		for i, w in enumerate(self.rackTabs()):
			if w.singleRackFilter() == old_name: # replace tab
				self.removeTab(i)
				w.deleteLater()
				self.insertTab(i, SingleRackColumnView(self, new_name), new_name)
				self.setCurrentIndex(i)
				break
	
	def updateTabIcons(self):
		for i, w in enumerate(self.rackTabs()):
			try:
				self.setTabIcon(i, coloured_square_icon(settings.rack_colours[w.singleRackFilter()], width=12))
			except KeyError:
				self.setTabIcon(i, QIcon())
	
	def updateSelection(self):
		for i in range(self.count()):
			self.widget(i).updateSelection()
		strip = selection.strip
		if strip is not None and strip.lookup(runway_box_detail) is None: # strip is racked or loose
			for w in self.rackTabs():
				if w.singleRackFilter() == strip.lookup(rack_detail):
					self.setCurrentWidget(w)
					break



class StripRackTabBar(QTabBar):
	def __init__(self, parent=None):
		QTabBar.__init__(self, parent)
		self.setAcceptDrops(True)
		self.setChangeCurrentOnDrag(True)
	
	def dropEvent(self, event):
		if event.mimeData().hasFormat(strip_mime_type):
			itab = self.currentIndex()
			strip = env.strips.fromMimeDez(event.mimeData())
			rack = self.parentWidget().widget(itab).singleRackFilter()
			env.strips.repositionStrip(strip, rack)
			event.acceptProposedAction()
			signals.selectionChanged.emit()
	
	def mouseDoubleClickEvent(self, event):
		itab = self.tabAt(event.pos())
		if itab != -1:
			rack = self.parentWidget().widget(itab).singleRackFilter()
			EditRackDialog(self, rack).exec()
			event.accept()
		else:
			QTabBar.mouseDoubleClickEvent(self, event)



class SingleRackColumnView(StripTableView):
	def __init__(self, parent, single_rack_filter):
		StripTableView.__init__(self, parent)
		self.table_model = RackedStripsFilterModel(self)
		self.setModel(self.table_model)
		self.single_rack_filter = single_rack_filter # assigned below
		self.table_model.setRackFilter([single_rack_filter])
		self.horizontalHeader().setStretchLastSection(True)
		self.horizontalHeader().setVisible(False)
	
	def singleRackFilter(self):
		return self.single_rack_filter





##############################

##       RUNWAY BOXES       ##

##############################

class RunwayBoxItemDelegate(QStyledItemDelegate):
	def __init__(self, parent):
		QStyledItemDelegate.__init__(self, parent)
	
	def sizeHint(self, option, index):
		return strip_size_hint(option.font) + QSize(2 * strip_placeholder_margin, 2 * strip_placeholder_margin)
	
	def paint(self, painter, option, index):
		strip = index.model().stripAt(index)
		# STYLE: rely ONLY on models' data to avoid needing stripAt redef for every model
		# e.g. here: strip = env.strips.stripAt(index.data())
		physical_RWY_index = index.model().boxAt(index)
		rwy_txt = env.airport_data.physicalRunwayNameFromUse(physical_RWY_index)
		m2 = 2 * strip_placeholder_margin
		painter.save()
		painter.translate(option.rect.topLeft())
		box = QRect(strip_placeholder_margin, strip_placeholder_margin, option.rect.width() - m2, option.rect.height() - m2)
		vertical_sep = int(box.height() * .6)
		if strip is None:
			timer, wtc = env.airport_data.rwySepTimer(physical_RWY_index)
			if timer > max_RWY_sep_time_disp:
				timer_txt = ''
			else:
				timer_txt = duration_str(timer)
				if wtc is not None:
					timer_txt += ' / %s' % wtc
			painter.setPen(QPen(Qt.NoPen))
			painter.setBrush(QBrush(QColor('#EEEEEE')))
			painter.drawRect(box)
			painter.setPen(new_pen(Qt.black))
			painter.drawText(box.adjusted(0, vertical_sep, 0, 0), Qt.AlignCenter, timer_txt) # Normal font
			font = QFont(painter.font())
			font.setPointSize(font.pointSize() + 3)
			painter.setFont(font)
			painter.drawText(box.adjusted(0, 0, 0, -vertical_sep), Qt.AlignCenter, rwy_txt)
		else:
			paint_strip_box(self, painter, strip, box)
			txt_box = box.adjusted(box.width() - 50, vertical_sep, 0, 0)
			painter.setPen(QPen(Qt.NoPen))
			painter.setBrush(QBrush(QColor('#EEEEEE')))
			painter.drawRect(txt_box)
			painter.setPen(new_pen(Qt.black))
			painter.drawText(txt_box, Qt.AlignCenter, rwy_txt)
		painter.restore()





class RunwayBoxTableModel(QAbstractTableModel):
	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.box_count = 0 if env.airport_data is None else env.airport_data.physicalRunwayCount()
		self.vertical = False

	def rowCount(self, parent=QModelIndex()):
		if parent.isValid():
			return 0
		return self.box_count if self.vertical else 1

	def columnCount(self, parent=QModelIndex()):
		if parent.isValid():
			return 0
		return 1 if self.vertical else self.box_count
	
	def data(self, index, role):
		strip = self.stripAt(index)
		if role == Qt.DisplayRole:
			if strip is None:
				return 'Physical RWY %s' % self.boxAt(index)
			else:
				return str(strip)
	
	def flags(self, index):
		flags = Qt.ItemIsEnabled
		if index.isValid():
			if self.stripAt(index) is None:
				flags |= Qt.ItemIsDropEnabled
			else:
				flags |= Qt.ItemIsDragEnabled | Qt.ItemIsSelectable
		return flags

	## DRAG AND DROP STUFF
	def supportedDragActions(self):
		return Qt.MoveAction
	
	def supportedDropActions(self):
		return Qt.MoveAction
	
	def mimeTypes(self):
		return [strip_mime_type]
	
	def mimeData(self, indices):
		assert len(indices) == 1
		return env.strips.mkMimeDez(self.stripAt(indices[0]))
	
	def dropMimeData(self, mime, drop_action, row, column, parent):
		if parent.isValid() and drop_action == Qt.MoveAction and mime.hasFormat(strip_mime_type):
			drop_rwy = self.boxAt(parent)
			dropped_strip = env.strips.fromMimeDez(mime)
			was_in_box = dropped_strip.lookup(runway_box_detail)
			if was_in_box is not None:
				mi1 = self.boxModelIndex(was_in_box)
				self.dataChanged.emit(mi1, mi1)
			env.strips.repositionStrip(dropped_strip, None, box=drop_rwy)
			mi2 = self.boxModelIndex(drop_rwy)
			self.dataChanged.emit(mi2, mi2)
			return True
		return False

	## ACCESSORS
	def boxAt(self, index):
		return index.row() if self.vertical else index.column()
	
	def boxModelIndex(self, section):
		return self.index(section, 0) if self.vertical else self.index(0, section)
	
	def stripAt(self, index):
		try:
			return env.strips.findStrip(lambda strip: strip.lookup(runway_box_detail) == self.boxAt(index))
		except StopIteration:
			return None
	
	def stripModelIndex(self, strip):
		rwy = strip.lookup(runway_box_detail)
		return None if rwy is None else self.boxModelIndex(rwy)

	## MODIFIERS
	def setVertical(self, toggle):
		self.beginResetModel()
		self.vertical = toggle
		self.endResetModel()
	
	def updateVisibleRwySepTimers(self):
		for i in range(self.box_count):
			mi = self.boxModelIndex(i)
			if self.stripAt(mi) is None:
				self.dataChanged.emit(mi, mi)




class RunwayBoxFilterModel(QSortFilterProxyModel):
	def __init__(self, parent, source_model):
		QSortFilterProxyModel.__init__(self, parent)
		self.setSourceModel(source_model)
	
	def boxAt(self, model_index):
		return self.sourceModel().boxAt(self.mapToSource(model_index))
	
	def stripAt(self, model_index):
		return self.sourceModel().stripAt(self.mapToSource(model_index))
	
	def stripModelIndex(self, strip):
		smi = self.sourceModel().stripModelIndex(strip)
		return None if smi is None else self.mapFromSource(smi)

	## FILTERING	
	def acceptPhysicalRunway(self, phyrwy):
		rwy1, rwy2 = env.airport_data.physicalRunway(phyrwy)
		return rwy1.inUse() or rwy2.inUse()

	## MODEL STUFF
	def filterAcceptsColumn(self, sourceCol, sourceParent):
		return self.sourceModel().vertical or self.acceptPhysicalRunway(sourceCol) \
			or self.sourceModel().stripAt(self.sourceModel().boxModelIndex(sourceCol)) is not None
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		return not self.sourceModel().vertical or self.acceptPhysicalRunway(sourceRow) \
			or self.sourceModel().stripAt(self.sourceModel().boxModelIndex(sourceRow)) is not None



class RunwayBoxesView(StripTableView):
	def __init__(self, parent=None):
		StripTableView.__init__(self, parent)
		self.full_model = RunwayBoxTableModel(self)
		self.filter_model = RunwayBoxFilterModel(self, self.full_model)
		self.setShowGrid(True)
		self.horizontalHeader().setVisible(False)
		self.verticalHeader().setVisible(False)
		self.setItemDelegate(RunwayBoxItemDelegate(self))
		self.setDivideHorizWidth(True)
		if env.airport_data is None:
			self.setEnabled(False)
		else:
			self.setModel(self.filter_model)
			env.strips.rwyBoxFreed.connect(self.refilter)
			signals.selectionChanged.connect(self.updateSelection) # self.updateSelection is inherited from StripTableView
			signals.adSfcUseChanged.connect(self.refilter)
			signals.fastClockTick.connect(self.full_model.updateVisibleRwySepTimers)
	
	def refilter(self):
		self.filter_model.invalidateFilter()
		self.setDivideHorizWidth(True)
	
	def setVerticalLayout(self, toggle):
		self.full_model.setVertical(toggle)
	
	def doubleClickOffStrip(self, event):
		index = self.indexAt(event.pos())
		if env.airport_data is not None and index.isValid() and event.button() == Qt.LeftButton:
			phy_rwy = self.filter_model.boxAt(index)
			timer, last_wtc = env.airport_data.rwySepTimer(phy_rwy)
			if QMessageBox.question(self, 'Reset RWY separation timer', 'Start/reset runway separation timer?') == QMessageBox.Yes:
				env.airport_data.resetRwySepTimer(phy_rwy, (last_wtc if timer <= max_RWY_sep_time_disp else None))
			event.accept()
