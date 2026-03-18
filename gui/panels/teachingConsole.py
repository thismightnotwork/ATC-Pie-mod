
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

from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMessageBox, QInputDialog
from ui.teachingPanel import Ui_teachingConsole

from base.util import some
from base.params import Heading
from base.utc import rel_session_datetime_str
from base.radio import CommFrequency
from base.strip import assigned_SQ_detail, student_ok_detail
from base.weather import mkWeather, gust_diff_threshold

from gui.actions import kill_aircraft, teacher_cpdlc_transfer, send_strip
from gui.misc import IconFile, signals, selection
from gui.workspace import WorkspaceDockablePanel

from session.config import settings
from session.env import env
from session.manager import SessionType, student_callsign, teacher_callsign, CpdlcOperationBlocked


# ---------- Constants ----------

teaching_console_flash_stylesheet = 'QGroupBox#selectedAircraft_box::title { background: yellow }'

# -------------------------------


def valid_new_ATC_name(name):
	return name not in env.ATCs.knownAtcCallsigns() + ['', teacher_callsign, student_callsign] \
			+ [acft.identifier for acft in settings.session_manager.getAircraft()]


# =============================================== #

#                     MODELS                      #

# =============================================== #

class TeachingAtcModel(QAbstractTableModel):
	columns = ['Callsign', 'Frequency']
	
	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.ATCs = [] # callsign list
	
	def rowCount(self, parent=None):
		return len(self.ATCs)
	
	def columnCount(self, parent):
		return len(TeachingAtcModel.columns)
	
	def flags(self, index):
		return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable
	
	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return TeachingAtcModel.columns[section]
	
	def data(self, index, role):
		atc = self.ATCs[index.row()]
		col = index.column()
		if role == Qt.DisplayRole:
			if col == 0: # callsign
				return atc
			elif col == 1: # frequency
				frq = env.ATCs.getATC(atc).frequency
				if frq is not None:
					return str(frq)
	
	def setData(self, index, value, role=Qt.EditRole):
		col = index.column()
		row = index.row()
		atc = self.ATCs[row]
		value = value.strip()
		if col == 0 and valid_new_ATC_name(value):
			frq = env.ATCs.getATC(atc).frequency
			env.ATCs.updateATC(value, None, None, frq) # adds new ATC to env
			env.ATCs.removeATC(atc) # removes old ATC from env
			self.ATCs[row] = value
		elif col == 1:
			try:
				env.ATCs.updateATC(atc, None, None, (None if value == '' else CommFrequency(value)))
			except ValueError:
				return False
		self.dataChanged.emit(index, index)
		settings.session_manager.sendATCs() # updates distant student list
		return True
	
	def addAtc(self, atc):
		position = self.rowCount()
		self.beginInsertRows(QModelIndex(), position, position)
		self.ATCs.append(atc)
		self.endInsertRows()
	
	def atcRemovedOnRow(self, row):
		self.beginRemoveRows(QModelIndex(), row, row)
		popped = self.ATCs.pop(row)
		self.endRemoveRows()
		return popped
	
	def clearList(self):
		self.beginResetModel()
		self.ATCs.clear()
		self.endResetModel()



class SituationSnapshotModel(QAbstractTableModel):
	columns = ['Situation', 'Traffic']
	
	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.snapshots = [] # (situation, name) list

	def rowCount(self, parent=None):
		return len(self.snapshots)

	def columnCount(self, parent):
		return len(SituationSnapshotModel.columns)

	def flags(self, index):
		basic_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
		return basic_flags | Qt.ItemIsEditable if index.column() == 0 else basic_flags

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return SituationSnapshotModel.columns[section]

	def data(self, index, role):
		(t, traffic), name = self.snapshots[index.row()]
		col = index.column()
		if role == Qt.DisplayRole:
			if col == 0:
				return some(name, 'Saved %s' % rel_session_datetime_str(t, seconds=True))
			elif col == 1:
				spawned = len([acft for acft in traffic if acft[4]])
				return '%d + %d' % (spawned, len(traffic) - spawned)
		elif role == Qt.ToolTipRole:
			if col == 0:
				return 'Double-click to name this entry.' if name is None else 'Saved %s' % rel_session_datetime_str(t, seconds=True)
			elif col == 1:
				return 'Spawned + unspawned count'

	def setData(self, index, value, role=Qt.EditRole):
		if index.column() == 0:
			row = index.row()
			sit, old_name = self.snapshots[row]
			self.snapshots[row] = sit, (None if value == '' else value)
			self.dataChanged.emit(index, index)
			return True
		else:
			return False

	def situationOnRow(self, row):
		return self.snapshots[row][0]
	
	def addSnapshot(self, snapshot):
		position = self.rowCount()
		self.beginInsertRows(QModelIndex(), position, position)
		self.snapshots.insert(position, (snapshot, None))
		self.endInsertRows()
	
	def removeSnapshot(self, row):
		self.beginRemoveRows(QModelIndex(), row, row)
		del self.snapshots[row]
		self.endRemoveRows()




# ============================================== #

#                  THE CONSOLE                   #

# ============================================== #

class TeachingConsole(WorkspaceDockablePanel, Ui_teachingConsole): # is a QWidget
	def __init__(self):
		WorkspaceDockablePanel.__init__(self)
		self.setupUi(self)
		self.setWindowIcon(QIcon(IconFile.panel_teaching))
		self.onTouchDown_groupBox.setVisible(env.airport_data is not None)
		self.removeSituation_button.setIcon(QIcon(IconFile.button_bin))
		self.ATCs_tableModel = TeachingAtcModel(self)
		self.ATCs_tableView.setModel(self.ATCs_tableModel)
		self.situationSnapshots_tableModel = SituationSnapshotModel(self)
		self.situationSnapshots_tableView.setModel(self.situationSnapshots_tableModel)
		self.windHdg_radioButton.setText('%s°' % self._windDialHdg().readTrue())
		self.setEnabled(False)
		self.disp_acft = None # the ACFT currently displayed on the left-hand side
		# ACFT callsign/status section
		self.spawn_button.clicked.connect(self.spawnAcft)
		self.freezeACFT_button.toggled.connect(self.freezeAcft)
		self.kill_button.clicked.connect(self.killAcft)
		# ACFT XPDR section
		self.xpdrMode_select.currentIndexChanged.connect(self.setXpdrMode)
		self.squat_tickBox.toggled.connect(self.toggleSquat)
		self.xpdrCode_select.codeChanged.connect(self.setXpdrCode)
		self.squawkVFR_button.clicked.connect(lambda: self.xpdrCode_select.setSQ(settings.uncontrolled_VFR_XPDR_code))
		self.xpdrIdent_tickBox.toggled.connect(self.toggleXpdrIdent)
		self.pushSQtoStrip_button.clicked.connect(self.SQcodeToStrip)
		# ACFT CPDLC section
		self.cpdlcLogOn_button.clicked.connect(self.cpdlcLogOn)
		self.cpdlcTransfer_button.clicked.connect(self.cpdlcTransfer)
		self.showDataLinkWindow_button.clicked.connect(self.openCpdlcDialogue)
		# ACFT "on touch-down" section
		self.onTouchDown_touchAndGo_radioButton.toggled.connect(self.toggleTouchAndGo)
		self.onTouchDown_skidOffRwy_radioButton.toggled.connect(self.toggleSkidOffRwy)
		# Weather section
		self.windHdg_dial.valueChanged.connect(lambda: self.windHdg_radioButton.setText('%s°' % self._windDialHdg().readTrue()))
		self.windSpeed_edit.valueChanged.connect(lambda spd: self.windGusts_edit.setMinimum(spd + gust_diff_threshold))
		self.visibility_edit.editingFinished.connect(self._roundVisibilityValue)
		self.cloudLayer_select.currentIndexChanged.connect(self._updateCloudLayerHeightWidgets)
		self.cloudLayerHeight_edit.valueChanged.connect(self._updateCloudLayerHeightWidgets)
		self.applyWeather_button.clicked.connect(self.applyWeather)
		# ATC section
		self.addATC_button.clicked.connect(self.addATC)
		self.removeATC_button.clicked.connect(self.removeATC)
		self.ATCs_tableView.selectionModel().selectionChanged.connect(self._updateAtcButtons)
		# Snapshots section
		self.snapshotSituation_button.clicked.connect(self.snapshotSituation)
		self.restoreSituation_button.clicked.connect(self.restoreSituation)
		self.removeSituation_button.clicked.connect(self.removeSituation)
		self.situationSnapshots_tableView.selectionModel().selectionChanged.connect(self._updateSnapshotsButtons)
		# Other
		self.sendStripToStudent_button.clicked.connect(self.sendSelectedStripToStudent)
		self.unmarkPlus_button.clicked.connect(self.unmarkStrip)
		self.touchDownWithoutClearance_tickBox.toggled.connect(self.toggleAcftTouchDownWithoutClearance)
		self.pauseSim_button.toggled.connect(self.togglePause)
		self.skipFwd_button.clicked.connect(self.skipTimeForwardOnce)
		signals.locationSettingsChanged.connect(self.xpdrCode_select.updateXPDRranges)
		signals.sessionPaused.connect(lambda: self.pauseSim_button.setChecked(True))
		signals.sessionResumed.connect(lambda: self.pauseSim_button.setChecked(False))
		signals.cpdlcStatusChanged.connect(self._cpdlcStatusChanged)
		signals.sessionStarted.connect(self.sessionHasStarted)
		signals.sessionEnded.connect(self.sessionHasEnded)

	def flashStyleSheet(self):
		return teaching_console_flash_stylesheet

	def _windDialHdg(self):
		return Heading(5 * self.windHdg_dial.value(), True)
	
	def sessionHasStarted(self, session_type):
		if session_type == SessionType.TEACHER:
			self.setEnabled(True)
			self.show()
			signals.selectionChanged.connect(self.updateAcftAndStripSection)
			self.updateAcftAndStripSection()
			self._updateCloudLayerHeightWidgets()
			self._updateAtcButtons()
			self._updateSnapshotsButtons()
			self.applyWeather() # initialises the weather for the session
	
	def sessionHasEnded(self, session_type):
		if session_type == SessionType.TEACHER:
			signals.selectionChanged.disconnect(self.updateAcftAndStripSection)
			self.ATCs_tableModel.clearList()
			self.setEnabled(False)
			self.hide()
	
	def _cpdlcStatusChanged(self, callsign):
		if self.disp_acft is not None and callsign == self.disp_acft.identifier:
			link = env.cpdlc.lastDataLink(self.disp_acft.identifier)
			self.cpdlcStatus_info.setText('Never connected' if link is None else link.statusStr())
			self.showDataLinkWindow_button.setEnabled(link is not None)
			self.cpdlcLogOn_button.setEnabled(link is None or link.isTerminated())
			self.cpdlcTransfer_button.setEnabled(link is None or not link.isLive()) # it can still be pending for student to accept
	
	def updateAcftAndStripSection(self):
		self.disp_acft = selection.acft
		if self.disp_acft is None:
			self.selectedAircraft_box.setEnabled(False)
			self.acftCallsign_info.clear()
			self.spawn_button.setVisible(False)
		else:
			# callsign section
			self.selectedAircraft_box.setEnabled(True)
			self.acftCallsign_info.setText(self.disp_acft.identifier if self.disp_acft.spawned else '%s (unspawned)' % self.disp_acft.identifier)
			self.spawn_button.setVisible(not self.disp_acft.spawned)
			self.freezeACFT_button.setChecked(self.disp_acft.frozen)
			# XPDR box
			self.xpdrMode_select.setCurrentIndex('0ACS'.index(self.disp_acft.params.XPDR_mode))
			self.squat_tickBox.setEnabled(self.disp_acft.params.XPDR_mode == 'S')
			self.squat_tickBox.setChecked(self.disp_acft.mode_S_squats)
			self.xpdrCode_select.setSQ(self.disp_acft.params.XPDR_code)
			self.xpdrIdent_tickBox.setChecked(self.disp_acft.params.XPDR_idents)
			# CPDLC box
			self._cpdlcStatusChanged(self.disp_acft.identifier) # updates the whole box
			# "On touch-down" box
			self.onTouchDown_groupBox.setEnabled(not self.disp_acft.isHelo())
			if self.disp_acft.skid_off_RWY_on_LDG:
				self.onTouchDown_skidOffRwy_radioButton.setChecked(True)
			elif self.disp_acft.touch_and_go_on_LDG:
				self.onTouchDown_touchAndGo_radioButton.setChecked(True)
			else:
				self.onTouchDown_land_radioButton.setChecked(True)
		self.selectedStrip_box.setEnabled(selection.strip is not None)
		self.unmarkPlus_button.setVisible(selection.strip is None or not selection.strip.lookup(student_ok_detail))
	
	def _roundVisibilityValue(self):
		self.visibility_edit.setValue((self.visibility_edit.value() + 50) // 100 * 100)
	
	def _updateCloudLayerHeightWidgets(self):
		self.cloudLayerHeight_edit.setEnabled(self.cloudLayer_select.currentIndex() != 0)
		self.cloudLayerHeight_edit.setPrefix(max(0, 3 - len(str(self.cloudLayerHeight_edit.value()))) * '0')
	
	def _updateAtcButtons(self):
		self.removeATC_button.setEnabled(len(self.ATCs_tableView.selectionModel().selectedRows()) == 1)
	
	def _updateSnapshotsButtons(self):
		one_selected = len(self.situationSnapshots_tableView.selectionModel().selectedRows()) == 1
		self.restoreSituation_button.setEnabled(one_selected)
		self.removeSituation_button.setEnabled(one_selected)
	
	
	## ACFT status actions
	
	def spawnAcft(self):
		if self.disp_acft is not None:
			self.disp_acft.spawned = True
		self.updateAcftAndStripSection()
	
	def freezeAcft(self, toggle):
		if self.disp_acft is not None:
			self.disp_acft.frozen = toggle
		self.updateAcftAndStripSection()
	
	def killAcft(self):
		to_kill = self.disp_acft
		if to_kill is not None:
			selection.deselect() # this resets "disp" ACFT
			kill_aircraft(to_kill)
			self.updateAcftAndStripSection()
	
	
	## ACFT transponder actions
	
	def setXpdrMode(self, drop_down_index):
		if self.disp_acft is not None:
			self.disp_acft.params.XPDR_mode = '0ACS'[drop_down_index]
		self.updateAcftAndStripSection()
	
	def SQcodeToStrip(self):
		strip = selection.strip
		if strip is not None:
			strip.writeDetail(assigned_SQ_detail, self.xpdrCode_select.getSQ())
			signals.stripInfoChanged.emit()
	
	def setXpdrCode(self):
		if self.disp_acft is not None:
			self.disp_acft.params.XPDR_code = self.xpdrCode_select.getSQ()
	
	def toggleSquat(self, toggle):
		if self.disp_acft is not None:
			self.disp_acft.mode_S_squats = toggle
	
	def toggleXpdrIdent(self, toggle):
		if self.disp_acft is not None:
			self.disp_acft.params.XPDR_idents = toggle
	
	
	## ACFT CPDLC actions
	
	def openCpdlcDialogue(self):
		if self.disp_acft is not None:
			signals.cpdlcDialogueRequest.emit(self.disp_acft.identifier, False)
	
	def cpdlcLogOn(self):
		if self.disp_acft is not None:
			try:
				settings.session_manager.requestCpdlcLogOn(self.disp_acft.identifier)
			except CpdlcOperationBlocked as err:
				QMessageBox.critical(self, 'CPDLC log-on error', str(err))
	
	def cpdlcTransfer(self):
		if self.disp_acft is not None:
			if env.cpdlc.liveDataLink(selection.acft.identifier) is None:
				teacher_cpdlc_transfer(self, self.disp_acft) # also handles case of pending XFR cancellation
			else:
				QMessageBox.critical(self, 'CPDLC transfer error', 'A data link is already live for this ACFT.')
	
	
	## ACFT "on touch-down" actions
	
	def toggleTouchAndGo(self, b):
		if self.disp_acft is not None:
			self.disp_acft.touch_and_go_on_LDG = b
	
	def toggleSkidOffRwy(self, b):
		if self.disp_acft is not None:
			self.disp_acft.skid_off_RWY_on_LDG = b
	
	
	## WEATHER actions
	
	def applyWeather(self):
		if self.windCalm_radioButton.isChecked():
			wind_str = '00000KT'
		else:
			wind_str = 'VRB' if self.windVRB_radioButton.isChecked() else self._windDialHdg().readTrue() # main dir chars
			wind_str += '%02d' % self.windSpeed_edit.value() # main speed chars
			if self.windGusts_edit.isEnabled():
				wind_str += 'G%02d' % self.windGusts_edit.value()
			wind_str += 'KT'
			if self.windHdgRange_edit.isEnabled():
				w = self._windDialHdg().trueAngle()
				v = self.windHdgRange_edit.value()
				wind_str += ' %sV%s' % (Heading(w - v, True).readTrue(), Heading(w + v, True).readTrue())
		visibility = self.visibility_edit.value()
		if visibility == self.visibility_edit.minimum(): # special 10-km value
			visibility = 10000
		if self.cloudLayer_select.currentIndex() == 0:
			cl = 'NSC'
		else:
			cl = '%s%03d' % (self.cloudLayer_select.currentText(), self.cloudLayerHeight_edit.value())
		weather = mkWeather(settings.primary_METAR_station, settings.session_manager.clockTime(), wind=wind_str, vis=visibility, clouds=cl, qnh=self.QNH_edit.value())
		settings.session_manager.setWeather(weather)
	
	
	## ATC actions

	def addATC(self):
		txt, ok = QInputDialog.getText(self, 'Add ATC to list', 'ATC callsign:')
		if ok:
			atc = txt.strip()
			if valid_new_ATC_name(atc):
				self.ATCs_tableModel.addAtc(atc)
				env.ATCs.updateATC(atc, None, None, None) # adds new ATC to env
			else:
				QMessageBox.critical(self, 'Add ATC to list', 'Invalid or duplicate callsign.')
	
	def removeATC(self):
		try:
			index = self.ATCs_tableView.selectedIndexes()[0]
			atc = self.ATCs_tableModel.atcRemovedOnRow(index.row())
			llm = settings.session_manager.phoneLineManager()
			if llm is not None:
				llm.destroyPhoneLine(atc)
			env.ATCs.removeATC(atc)
			settings.session_manager.sendATCs() # updates distant student list
		except IndexError:
			pass # No ATC selected to remove.
	
	
	## Situation snapshot actions
	
	def snapshotSituation(self):
		self.situationSnapshots_tableModel.addSnapshot(settings.session_manager.situationSnapshot())
	
	def restoreSituation(self):
		try:
			index = self.situationSnapshots_tableView.selectedIndexes()[0]
		except IndexError:
			pass # No situation selected to restore.
		else:
			snapshot = self.situationSnapshots_tableModel.situationOnRow(index.row())
			settings.session_manager.restoreSituation(snapshot)
			env.radar.instantSweep()
	
	def removeSituation(self):
		try:
			index = self.situationSnapshots_tableView.selectedIndexes()[0]
		except IndexError:
			pass # No situation selected to remove.
		else:
			if QMessageBox.question(self, 'Remove situation', 'Permanently remove selected entry?') == QMessageBox.Yes:
				self.situationSnapshots_tableModel.removeSnapshot(index.row())
	
	
	## Other actions

	def sendSelectedStripToStudent(self):
		if selection.strip is not None:
			txt, ok = QInputDialog.getItem(self, 'Strip handover', 'Send strip to student from:', [teacher_callsign] + env.ATCs.knownAtcCallsigns(), editable=False)
			if ok:
				send_strip(selection.strip, txt)
			self.updateAcftAndStripSection()

	def unmarkStrip(self):
		if selection.strip is not None:
			selection.strip.writeDetail(student_ok_detail, True)
			self.updateAcftAndStripSection()

	def toggleAcftTouchDownWithoutClearance(self, b):
		settings.teacher_ACFT_touch_down_without_clearance = b
	
	def togglePause(self, toggle):
		if toggle:
			settings.session_manager.pause()
		else:
			settings.session_manager.resume()

	def skipTimeForwardOnce(self):
		settings.session_manager.skipTimeForward(timedelta(seconds=10))
