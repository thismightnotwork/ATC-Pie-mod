
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

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QPlainTextEdit, QPushButton, QLabel

from base.db import acft_cat
from ui.depClearanceDialog import Ui_depClearanceDialog

from base.fpl import FPL
from base.strip import assigned_SQ_detail, assigned_altitude_detail, parsed_route_detail, departure_clearance_detail
from base.utc import timestr
from base.util import some

from gui.misc import RadioKeyEventFilter, signals, IconFile

from session.config import settings
from session.env import env


# ---------- Constants ----------

# -------------------------------


class DepartureClearanceViewDialog(QDialog):
	def __init__(self, parent):
		QDialog.__init__(self, parent)
		self.setWindowFlags(Qt.Window)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.setWindowTitle('Departure clearance')
		self.label = QLabel(self)
		self.clearance_disp = QPlainTextEdit(self)
		self.clearance_disp.setReadOnly(True)
		self.close_button = QPushButton('Close', self)
		self.layout = QVBoxLayout(self)
		self.layout.addWidget(self.label)
		self.layout.addWidget(self.clearance_disp)
		self.layout.addWidget(self.close_button)
		self.close_button.clicked.connect(self.close)
		signals.closeNonDockableWindows.connect(self.close)

	def updateView(self, strip):
		cs = strip.callsign()
		if cs:
			self.label.setText('Clearance for %s at %s' % (cs, timestr(settings.session_manager.clockTime())))
		else:
			self.label.setText('Clearance at %s (missing callsign)' % timestr(settings.session_manager.clockTime()))
		self.clearance_disp.setPlainText(strip.lookup(departure_clearance_detail))



class DepartureClearanceEditDialog(QDialog, Ui_depClearanceDialog):
	def __init__(self, parent, strip):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.clear_button.setIcon(QIcon(IconFile.button_clear))
		self.installEventFilter(RadioKeyEventFilter(self))
		self.strip = strip
		for tick_box in self.route_tickBox, self.initFl_tickBox, self.depFreq_tickBox, self.xpdrCode_tickBox:
			tick_box.setChecked(True)
		self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
		self.initFl_edit.syncWithEnv(True)
		self.expectFl_edit.syncWithEnv(True)
		if env.airport_data is not None:
			rwys = env.airport_data.directionalRunways()
			hpads = env.airport_data.helipads()
			self.rwy_edit.addItems(sfc.name for sfc in rwys + hpads)
			try:
				t = self.strip.lookup(FPL.ACFT_TYPE, fpl=True)
				if t is not None and acft_cat(t) == 'helos':
					self.rwy_edit.setCurrentText(next(hpad.name for hpad in hpads if hpad.use_for_departures))
				else:
					self.rwy_edit.setCurrentText(next(rwy.name for rwy in rwys if rwy.use_for_departures))
			except StopIteration:
				pass
		self.depFreq_edit.addFrequencies((frq, descr) for frq, descr, t in env.frequencies())
		try:
			self.depFreq_edit.setCurrentIndex(next(i for i, (frq, descr, t) in enumerate(env.frequencies()) if t == 'DEP'))
		except StopIteration:
			pass
		dest = self.strip.lookup(FPL.ICAO_ARR, fpl=True)
		if dest is not None:
			self.clearanceLimit_edit.setText(dest)
		self.routeAsFiled_radio.setChecked(self.strip.lookup(FPL.ROUTE, fpl=False) is None and self.strip.linkedFPL() is not None)
		route = self.strip.lookup(FPL.ROUTE, fpl=True)
		if route is not None:
			self.route_edit.setPlainText(route)
		assfl = self.strip.lookup(assigned_altitude_detail)
		if assfl is not None:
			self.initFl_edit.setAltFlSpec(assfl)
		cruise = self.strip.lookup(FPL.CRUISE_ALT, fpl=True)
		if cruise is not None:
			self.expectFl_edit.setAltFlSpec(cruise)
		parsed_route = self.strip.lookup(parsed_route_detail)
		if parsed_route is not None:
			self.expectFlAfterPoint_edit.setText(some(parsed_route.SID(), ''))
		sq = self.strip.lookup(assigned_SQ_detail)
		if sq is not None:
			self.xpdrCode_edit.setSQ(sq)
		if settings.last_recorded_ATIS is not None:
			self.atis_edit.setLetter(settings.last_recorded_ATIS[0])
		old_clearance_text = self.strip.lookup(departure_clearance_detail)
		if old_clearance_text is not None:
			self.newClearanceText_edit.setPlainText(old_clearance_text)
			self.toolBox.setCurrentWidget(self.newClearance_page)
		self.editPrepClearance_button.clicked.connect(self.editPreparedClearance)
		self.toolBox.currentChanged.connect(self.pageSwitched)
		self.clear_button.clicked.connect(self.newClearanceText_edit.clear)
		self.buttonBox.accepted.connect(self.doAccept)
		self.buttonBox.rejected.connect(self.reject)
		self.pageSwitched() # to update buttons and focus

	def pageSwitched(self):
		self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(self.toolBox.currentWidget() is self.newClearance_page)
		if self.toolBox.currentWidget() is self.prepClearance_page:
			self.clearanceLimit_edit.setFocus()
		else:
			self.newClearanceText_edit.setFocus()

	def editPreparedClearance(self):
		sections = []
		if self.rwy_tickBox.isChecked():
			sections.append('RWY ' + self.rwy_edit.currentText())
		if self.sid_tickBox.isChecked():
			sections.append('SID ' + self.sid_edit.text())
		clr_rte_txt = 'Cleared to ' + self.clearanceLimit_edit.text()
		if self.route_tickBox.isChecked():
			if self.routeAsFiled_radio.isChecked():
				clr_rte_txt += ' as filed'
			else:
				clr_rte_txt += ' via ' + self.route_edit.toPlainText().replace('\n', ' ')
		sections.append(clr_rte_txt)
		if self.initFl_tickBox.isChecked():
			spec = self.initFl_edit.altFlSpec()
			sections.append(('Initial ' if spec.isFL() else 'Initial altitude ') + spec.toStr(unit=True))
		if self.expectFl_tickBox.isChecked():
			if self.expectFlAfterTime_radio.isChecked():
				expect_cond_str = '%i minutes after departure' % self.expectFlAfterTime_edit.value()
			else:
				expect_cond_str = 'at %s' % self.expectFlAfterPoint_edit.text()
			sections.append('Expect %s ' % self.expectFl_edit.altFlSpec().toStr() + expect_cond_str)
		if self.depFreq_tickBox.isChecked():
			sections.append('DEP frequency %s' % self.depFreq_edit.getFrequency())
		if self.xpdrCode_tickBox.isChecked():
			sections.append('Squawk %04o' % self.xpdrCode_edit.getSQ())
		if self.atis_tickBox.isChecked():
			sections.append('ATIS ' + self.atis_edit.currentLetter())
		self.newClearanceText_edit.setPlainText('\n'.join(sections))
		self.toolBox.setCurrentWidget(self.newClearance_page)

	def doAccept(self):
		self.strip.writeDetail(departure_clearance_detail, self.newClearanceText_edit.toPlainText().replace('\n', '  '))
		signals.stripInfoChanged.emit()
		self.accept()
