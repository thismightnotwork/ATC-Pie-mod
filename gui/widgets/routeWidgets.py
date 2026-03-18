
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

from PyQt5.QtWidgets import QWidget, QInputDialog, QMessageBox
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import pyqtSignal
from ui.routeEditWidget import Ui_routeEditWidget

from base.util import some
from base.utc import datestr, timestr
from base.nav import world_navpoint_db, world_routing_db, NavpointError

from session.config import settings

from ext.data import route_presets_file

from gui.misc import IconFile


# ---------- Constants ----------

manual_entry_exit_point_max_dist = 100 # NM

# -------------------------------


def input_entry_exit_point(parent_widget, is_exit, ad):
	"""
	returns None if cancelled
	"""
	res = None
	eestr = ['entry', 'exit'][is_exit]
	while res is None:
		txt, ok = QInputDialog.getText(parent_widget, 'Missing %s point' % eestr,
			'No %s points specified for %s (see "CONFIG/nav/Notice" for more details).\nManual entry:' % (eestr, ad.code))
		if not ok:
			return None
		try:
			p = world_navpoint_db.findClosest(ad.coordinates, code=txt)
			if p.coordinates.distanceTo(ad.coordinates) <= manual_entry_exit_point_max_dist:
				res = p
			else:
				raise NavpointError()
		except NavpointError:
			QMessageBox.critical(parent_widget, 'Entry/exit point error', 'No such navpoint in the vicinity of %s' % ad.code)
	return res





class RouteEditWidget(QWidget, Ui_routeEditWidget):
	viewRoute_signal = pyqtSignal()
	
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.view_button.setIcon(QIcon(IconFile.button_view))
		self.clear_button.setIcon(QIcon(IconFile.button_clear))
		self.suggest_button.setIcon(QIcon(IconFile.button_suggest))
		self.saveAsPreset_button.setIcon(QIcon(IconFile.button_save))
		self.recallPreset_button.setIcon(QIcon(IconFile.button_recall))
		self.setFocusProxy(self.route_edit)
		self.origin_AD = None # Airfield
		self.dest_AD = None # Airfield
		self._updateButtons()
		self.route_edit.textChanged.connect(self._updateButtons)
		self.suggest_button.clicked.connect(self.suggestRoute)
		self.recallPreset_button.clicked.connect(self.recallPreset)
		self.view_button.clicked.connect(self.viewRoute_signal.emit)
		self.saveAsPreset_button.clicked.connect(self.savePreset)
		self.clear_button.clicked.connect(self.clearRoute)
	
	def _updateButtons(self):
		if self.origin_AD is None or self.dest_AD is None:
			for button in self.view_button, self.suggest_button, self.recallPreset_button, self.saveAsPreset_button:
				button.setEnabled(False)
		else:
			self.view_button.setEnabled(True)
			self.suggest_button.setEnabled(self.origin_AD.code != self.dest_AD.code)
			self.recallPreset_button.setEnabled((self.origin_AD.code, self.dest_AD.code) in settings.route_presets)
			self.saveAsPreset_button.setEnabled(self.getRouteText() != '')
		self.clear_button.setEnabled(self.getRouteText() != '')
	
	def setDEP(self, airport): # None resets
		self.origin_AD = airport
		self._updateButtons()
	
	def setARR(self, airport): # None resets
		self.dest_AD = airport
		self._updateButtons()
	
	def setRouteText(self, txt):
		self.route_edit.setPlainText(txt)
	
	def getRouteText(self):
		return self.route_edit.toPlainText()
	
	def suggestRoute(self):
		p1 = p2 = None
		if len(world_routing_db.exitsFrom(self.origin_AD)) == 0:
			p1 = input_entry_exit_point(self, True, self.origin_AD)
			if p1 is None: # cancelled
				return
		if len(world_routing_db.entriesTo(self.dest_AD)) == 0:
			p2 = input_entry_exit_point(self, False, self.dest_AD) # may be None
			if p2 is None: # cancelled
				return
		try:
			sugg_route_str = world_routing_db.shortestRouteStr(some(p1, self.origin_AD), some(p2, self.dest_AD))
			if p1 is not None:
				sugg_route_str = p1.code + ' ' + sugg_route_str
			if p2 is not None:
				sugg_route_str += ' ' + p2.code
			if self.getRouteText() == '' or QMessageBox.question(self, 'Route suggestion',
					'Accept route suggestion below?\n' + sugg_route_str) == QMessageBox.Yes:
				self.setRouteText(sugg_route_str)
		except ValueError:
			QMessageBox.critical(self, 'Route suggestion', 'No route found.')
	
	def recallPreset(self):
		suggestions = settings.route_presets[self.origin_AD.code, self.dest_AD.code]
		if self.getRouteText() == '' and len(suggestions) == 1:
			self.setRouteText(suggestions[0])
		else:
			text, ok = QInputDialog.getItem(self, 'Route suggestions',
				'From %s to %s:' % (self.origin_AD, self.dest_AD), suggestions, editable=False)
			if ok:
				self.setRouteText(text)
		self.route_edit.setFocus()
	
	def savePreset(self):
		icao_pair = self.origin_AD.code, self.dest_AD.code
		route_txt = ' '.join(self.getRouteText().split())
		got_routes = settings.route_presets.get(icao_pair, [])
		if route_txt == '' or route_txt in got_routes:
			QMessageBox.critical(self, 'Saving route preset', 'This route entry is already saved!')
			return
		msg = 'Confirm saving route preset below, from %s to %s?' % icao_pair
		if len(got_routes) > 0:
			msg += '\n(%d route%s already saved for these end airports)' % (len(got_routes), ('s' if len(got_routes) != 1 else ''))
		if QMessageBox.question(self, 'Saving route preset', msg) == QMessageBox.Yes:
			try:
				settings.route_presets[icao_pair].append(route_txt)
			except KeyError:
				settings.route_presets[icao_pair] = [route_txt]
			self.recallPreset_button.setEnabled(True)
			try:
				with open(route_presets_file, mode='a', encoding='utf8') as f:
					print('\n# Saved on %s at %s:' % (datestr(settings.session_manager.clockTime()), timestr(settings.session_manager.clockTime(), z=True)), file=f)
					print('%s %s\t%s' % (self.origin_AD.code, self.dest_AD.code, route_txt), file=f)
					print(file=f)
				QMessageBox.information(self, 'Route preset saved', 'Check file %s to remove or edit.' % route_presets_file)
			except OSError:
				QMessageBox.critical(self, 'Error', 'There was an error writing to "%s".\nYour preset will be lost at the end of the session.')
	
	def clearRoute(self):
		self.route_edit.setPlainText('') # "clear" would remove undo/redo history
		self.route_edit.setFocus()
