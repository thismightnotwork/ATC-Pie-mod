
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

from PyQt5.QtWidgets import QWidget, QMenu, QAction, QActionGroup, QMessageBox
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QSortFilterProxyModel

from ui.fplPanel import Ui_fplPanel

from base.util import some
from base.fpl import FPL
from base.nav import world_navpoint_db, NavpointError
from base.utc import timestr

from session.config import settings
from session.env import env
from session.manager import OnlineFplActionBlocked

from gui.misc import signals, selection, IconFile
from gui.dialogs.detailSheets import FPLdetailSheetDialog


# ---------- Constants ----------

filter_includes_missing_dates = True

# -------------------------------




def AD_on_map(icao):
	try:
		return env.pointOnMap(world_navpoint_db.findAirfield(icao).coordinates)
	except NavpointError:
		return False



acceptAll = lambda x: True


def ckArrDepAltAD(fpl, f):
	return fpl[FPL.ICAO_DEP] is not None and f(fpl[FPL.ICAO_DEP]) \
			or fpl[FPL.ICAO_ARR] is not None and f(fpl[FPL.ICAO_ARR]) \
			or fpl[FPL.ICAO_ALT] is not None and f(fpl[FPL.ICAO_ALT])




class FplFilterModel(QSortFilterProxyModel):
	def __init__(self, base_model, parent=None):
		QSortFilterProxyModel.__init__(self, parent)
		self.accept_closed = True
		self.accept_outdated = True
		self.callsign_filter = acceptAll
		self.arrDep_filter = acceptAll
		self.date_filter = acceptAll
		self.setSourceModel(base_model)

	def filterAcceptsRow(self, sourceRow, sourceParent):
		fpl = self.sourceModel().FPL_list[sourceRow]
		return (self.accept_closed or fpl.onlineStatus() != FPL.CLOSED) \
				and (self.accept_outdated or not fpl.isOutdated()) \
				and self.callsign_filter(fpl) and self.arrDep_filter(fpl) \
				and (filter_includes_missing_dates if fpl[FPL.TIME_OF_DEP] is None else self.date_filter(fpl))
	
	def filter_statusToggle_closed(self, toggle):
		self.accept_closed = toggle
		self.invalidateFilter()
	
	def filter_statusToggle_outdated(self, toggle):
		self.accept_outdated = toggle
		self.invalidateFilter()
	
	def filter_callsign(self, fstring):
		lower = fstring.lower()
		self.callsign_filter = lambda fpl: lower in some(fpl[FPL.CALLSIGN], '').lower()
		self.invalidateFilter()
	
	def filter_date_today(self):
		self.date_filter = lambda fpl: fpl.flightIsInTimeWindow(timedelta(hours=24))
		self.invalidateFilter()
	
	def filter_date_week(self):
		self.date_filter = lambda fpl: fpl.flightIsInTimeWindow(timedelta(days=7))
		self.invalidateFilter()
	
	def filter_arrDep_all(self):
		self.arrDep_filter = acceptAll
		self.invalidateFilter()
	
	def filter_arrDep_inRange(self):
		self.arrDep_filter = lambda fpl: ckArrDepAltAD(fpl, AD_on_map)
		self.invalidateFilter()
	
	def filter_arrDep_here(self):
		here = settings.location_code
		self.arrDep_filter = lambda fpl: ckArrDepAltAD(fpl, (lambda ad: ad is not None and ad.upper() == here))
		self.invalidateFilter()




# ================================================ #

#                     WIDGETS                      #

# ================================================ #

class FlightPlansPanel(QWidget, Ui_fplPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.list_model = FplFilterModel(env.FPLs, self)
		self.list_view.setModel(self.list_model)
		self.list_view.horizontalHeader().resizeSection(0, 40)
		# Status filters
		status_filter_menu = QMenu(self)
		status_filter_menu.addAction(self._filter_toggle('Show closed', self.list_model.filter_statusToggle_closed))
		status_filter_menu.addAction(self._filter_toggle('Show outdated', self.list_model.filter_statusToggle_outdated))
		self.filterStatus_button.setMenu(status_filter_menu)
		# Airport filters
		arrDep_action_group = QActionGroup(self)
		arrDep_action_group.addAction(self._filter_action('All', self.list_model.filter_arrDep_all, ticked=True))
		arrDep_action_group.addAction(self._filter_action('On map', self.list_model.filter_arrDep_inRange))
		if env.airport_data is not None:
			arrDep_action_group.addAction(self._filter_action('Here only', self.list_model.filter_arrDep_here))
		arrDep_filter_menu = QMenu(self)
		arrDep_filter_menu.addActions(arrDep_action_group.actions())
		self.filterArrDep_button.setMenu(arrDep_filter_menu)
		# Date filters
		date_action_group = QActionGroup(self)
		date_action_group.addAction(self._filter_action('+/- 3 days', self.list_model.filter_date_week))
		date_action_group.addAction(self._filter_action('Today (~24 h)', self.list_model.filter_date_today, ticked=True))
		date_filter_menu = QMenu(self)
		date_filter_menu.addActions(date_action_group.actions())
		self.filterDate_button.setMenu(date_filter_menu)
		# Local actions
		localActions_menu = QMenu()
		self.newLocalFpl_action = QAction(QIcon(IconFile.action_newFPL), 'New FPL', self)
		self.revertLocalChanges_action = QAction('Revert local changes', self)
		self.removeLocalFpl_action = QAction(QIcon(IconFile.button_bin), 'Delete FPL', self)
		localActions_menu.addActions([self.newLocalFpl_action, self.revertLocalChanges_action, self.removeLocalFpl_action])
		self.localActions_menuButton.setMenu(localActions_menu)
		# Online actions
		onlineActions_menu = QMenu()
		self.publishOnline_action = QAction('File plan or push changes', self)
		self.openFpl_action = QAction('Open FPL', self)
		self.closeFpl_action = QAction('Close FPL', self)
		onlineActions_menu.addActions([self.publishOnline_action, self.openFpl_action, self.closeFpl_action])
		self.onlineActions_menuButton.setMenu(onlineActions_menu)
		# Finish up
		self.updateActions()
		self.filterCallsign_edit.textChanged.connect(self.list_model.filter_callsign)
		self.newLocalFpl_action.triggered.connect(lambda: self.createLocalFPL(link=None))
		self.revertLocalChanges_action.triggered.connect(self.revertLocalChanges)
		self.removeLocalFpl_action.triggered.connect(self.removeFPL)
		self.publishOnline_action.triggered.connect(self.publishFplOnline)
		self.openFpl_action.triggered.connect(self.openFplOnline)
		self.closeFpl_action.triggered.connect(self.closeFplOnline)
		self.checkNow_button.clicked.connect(self.syncOnlineNow)
		signals.selectionChanged.connect(self.updateActions)
		signals.fplEditRequest.connect(self.editFPL)
		signals.sessionStarted.connect(self.sessionStarts)
		signals.sessionEnded.connect(self.sessionEnds)

	def _filter_toggle(self, text, toggle_function, ticked=False):
		action = QAction(text, self)
		action.setCheckable(True)
		action.setChecked(ticked)
		toggle_function(ticked)
		action.toggled.connect(toggle_function)
		return action
	
	def _filter_action(self, text, f, ticked=False):
		action = QAction(text, self)
		action.setCheckable(True)
		action.setChecked(ticked)
		action.triggered.connect(f)
		if ticked:
			f()
		return action

	def sessionStarts(self):
		self.onlineActions_menuButton.setEnabled(True)
		self.checkNow_button.setEnabled(True)
		self.updateActions()

	def sessionEnds(self):
		self.onlineActions_menuButton.setEnabled(False)
		self.checkNow_button.setEnabled(False)
		self.updateActions()

	def updateActions(self):
		fpl = selection.fpl
		self.revertLocalChanges_action.setEnabled(fpl is not None and fpl.hasLocalChanges())
		self.removeLocalFpl_action.setEnabled(fpl is not None and not fpl.isOnline() and env.linkedStrip(fpl) is None)
		self.publishOnline_action.setEnabled(fpl is not None and (not fpl.isOnline() or fpl.hasLocalChanges()))
		self.openFpl_action.setEnabled(fpl is not None and fpl.onlineStatus() == FPL.FILED)
		self.closeFpl_action.setEnabled(fpl is not None and fpl.onlineStatus() == FPL.OPEN)
	
	def createLocalFPL(self, link=None):
		"""
		Optional strip to link to after FPL is created. If given, it must already be in the live strips model.
		"""
		new_fpl = FPL()
		if link is not None:
			for d in FPL.details:
				new_fpl[d] = link.lookup(d, fpl=False)
		dialog = FPLdetailSheetDialog(self, new_fpl)
		dialog.exec()
		if dialog.result() > 0: # not rejected
			env.FPLs.addFPL(new_fpl)
			if link is not None:
				link.linkFPL(new_fpl)
			selection.selectFPL(new_fpl)
	
	def editFPL(self, fpl):
		FPLdetailSheetDialog(self, fpl).exec()
		self.updateActions()
	
	def publishFplOnline(self):
		if settings.session_manager.isRunning():
			fpl = selection.fpl
			if fpl is not None:
				try:
					settings.session_manager.pushFplOnline(fpl)
				except OnlineFplActionBlocked as err:
					QMessageBox.critical(self, 'FPL upload error', str(err))
				self.updateActions()
	
	def syncOnlineNow(self):
		try:
			settings.session_manager.syncOnlineFPLs()
		except OnlineFplActionBlocked as err:
			QMessageBox.critical(self, 'FPL sync error', str(err))
	
	def openFplOnline(self):
		fpl = selection.fpl
		if fpl is not None and settings.session_manager.isRunning():
			tnow = settings.session_manager.clockTime()
			button = QMessageBox.question(self, 'Open FPL', 'Opening flight plan at %s...\nAlso update as new DEP date & time?' % timestr(tnow),
					buttons=(QMessageBox.Cancel | QMessageBox.No | QMessageBox.Yes))
			if button == QMessageBox.Yes:
				fpl[FPL.TIME_OF_DEP] = tnow
			if button != QMessageBox.Cancel:
				try:
					settings.session_manager.changeFplStatus(fpl, FPL.OPEN)
				except OnlineFplActionBlocked as err:
					QMessageBox.critical(self, 'FPL open/close error', str(err))
				self.updateActions()
	
	def closeFplOnline(self):
		if settings.session_manager.isRunning():
			fpl = selection.fpl
			if fpl is not None and QMessageBox.question(self, 'Close FPL',
					'Time is %s.\nClose the flight plan online?' % timestr(settings.session_manager.clockTime())) == QMessageBox.Yes:
				try:
					settings.session_manager.changeFplStatus(fpl, FPL.CLOSED)
				except OnlineFplActionBlocked as err:
					QMessageBox.critical(self, 'FPL open/close error', str(err))
				self.updateActions()
	
	def revertLocalChanges(self):
		if selection.fpl is not None:
			selection.fpl.revertToOnlineValues()
			env.FPLs.refreshViews()
			self.updateActions()
	
	def removeFPL(self):
		if selection.fpl is not None:
			env.FPLs.removeFPL(selection.fpl)
			selection.deselect()
			self.updateActions()
