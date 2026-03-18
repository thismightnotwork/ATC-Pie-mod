
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
from hashlib import md5

from PyQt5.QtCore import Qt, QUrl, QAbstractListModel, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QDesktopServices, QIcon, QPixmap
from PyQt5.QtWidgets import QDialog, QStyledItemDelegate, QMessageBox, QInputDialog, QColorDialog, QFileDialog, QSpinBox

from ui.fgfsViewersSettingsDialog import Ui_fgfsViewersSettingsDialog
from ui.fgSystemSettingsDialog import Ui_fgSystemSettingsDialog
from ui.fsdSystemSettingsDialog import Ui_fsdSystemSettingsDialog
from ui.generalSettingsDialog import Ui_generalSettingsDialog
from ui.locationSettingsDialog import Ui_locationSettingsDialog
from ui.soloRuntimeSettingsDialog import Ui_soloRuntimeSettingsDialog
from ui.soloSystemSettingsDialog import Ui_soloSystemSettingsDialog
from ui.viewpointsSettingsDialog import Ui_viewpointsSettingsDialog
from ui.voiceSettingsDialog import Ui_voiceSettingsDialog

from base.nav import world_navpoint_db, NavpointError
from base.util import some, INET_addr_str, INET_addr_from_str

from ext.audio import pyaudio_available
from ext.fgcom import test_FGCom_Mumble
from ext.fgfs import fgTwrCommonOptions
from ext.hoppie import Hoppie_account_URL
from ext.sr import speech_recognition_available
from ext.tts import speech_synthesis_available

from gui.misc import signals, SimpleStringListModel, RadioKeyEventFilter, IconFile
from gui.dialogs.adSurfaces import RunwayParametersWidget, HelipadParametersWidget
from gui.graphics.miscGraphics import coloured_square_icon
from gui.panels.notifier import Notification, icon_files, sound_files
from gui.widgets.basicWidgets import AircraftTypeCombo, XpdrCodeSpinBox

from session.config import settings, SemiCircRule, XpdrAssignmentRange
from session.env import env, default_tower_height
from session.manager import SessionType


# ---------- Constants ----------

default_viewpoint_height = 100 # ft

# -------------------------------


# =================================
#
#      F G F S   V I E W E R S
#
# =================================

class AdditionalViewersListModel(QAbstractListModel):
	def __init__(self, parent):
		QAbstractListModel.__init__(self, parent)
		self.viewers = settings.additional_viewers[:]
		self.tick_list = [i in settings.activated_additional_viewers for i, viewer in enumerate(self.viewers)]

	def applyChoices(self):
		settings.additional_viewers = self.viewers
		settings.activated_additional_viewers = set(i for i, b in enumerate(self.tick_list) if b)

	# MODEL STUFF
	def rowCount(self, parent=None):
		return len(self.viewers)

	def flags(self, index):
		return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable # not selectable, not to confuse with ticked "selection" for activation

	def data(self, index, role):
		if role == Qt.DisplayRole:
			host, port = self.viewers[index.row()]
			return INET_addr_str(host, port)
		if role == Qt.CheckStateRole:
			return Qt.Checked if self.tick_list[index.row()] else Qt.Unchecked

	def setData(self, index, value, role):
		if index.isValid() and role == Qt.CheckStateRole:
			self.tick_list[index.row()] = value == Qt.Checked
			return True
		return False

	def globalSelect(self, b):
		self.tick_list = len(self.viewers) * [b]
		self.dataChanged.emit(self.index(0, 0), self.index(0, len(self.viewers)))

	def addEntry(self, host, port):
		self.beginInsertRows(QModelIndex(), len(self.viewers), len(self.viewers))
		self.viewers.append((host, port))
		self.tick_list.append(False)
		self.endInsertRows()

	def removeSelection(self):
		for row, ticked in reversed(list(enumerate(self.tick_list))):
			if ticked:
				self.beginRemoveRows(QModelIndex(), row, row)
				del self.viewers[row]
				del self.tick_list[row]
				self.endRemoveRows()



class FgfsViewersDialog(QDialog, Ui_fgfsViewersSettingsDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.list_model = AdditionalViewersListModel(self)
		self.viewers_list.setModel(self.list_model)
		for box in self.towerViewerProcess_box, self.towerViewerIpc_box:
			box.setEnabled(not settings.controlled_tower_viewer.isRunning())
		self.fillFromSettings()
		self.produceExtViewerCmd_button.clicked.connect(self.showExternalViewerFgOptions)
		self.selectAll_button.clicked.connect(lambda: self.list_model.globalSelect(True))
		self.selectNone_button.clicked.connect(lambda: self.list_model.globalSelect(False))
		self.addViewer_button.clicked.connect(self.addViewer)
		self.removeViewer_button.clicked.connect(self.list_model.removeSelection)
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def addViewer(self):
		text, ok = QInputDialog.getText(self, 'Additional viewer', 'Enter "host:port" of additional viewer:')
		if ok:
			try:
				self.list_model.addEntry(*INET_addr_from_str(text))
			except ValueError as err:
				QMessageBox.critical(self, 'Additional viewer', str(err))

	def showExternalViewerFgOptions(self):
		required_options = fgTwrCommonOptions()
		required_options.append('--multiplay=out,100,this_host,%d' % settings.FGFS_views_send_port)
		required_options.append('--multiplay=in,100,,%d' % self.towerView_fgmsPort_edit.value())
		required_options.append('--telnet=,,100,,%d,' % self.towerView_telnetPort_edit.value())
		print('Options required for external FlightGear viewer with current dialog options: ' + ' '.join(
			required_options))
		msg = 'Options required with present configuration (also sent to console):\n'
		msg += '\n'.join('  ' + opt for opt in required_options)
		msg += '\n\nNB: Replace "this_host" with appropriate value.'
		QMessageBox.information(self, 'Required FlightGear options', msg)

	def fillFromSettings(self):
		## Tower view
		(self.towerView_external_radioButton if settings.external_tower_viewer_process else self.towerView_internal_radioButton).setChecked(True)
		self.towerView_fgmsPort_edit.setValue(settings.tower_viewer_UDP_port)
		self.towerView_telnetPort_edit.setValue(settings.tower_viewer_telnet_port)
		self.fgCommand_edit.setText(settings.FGFS_executable)
		self.fgRootDir_edit.setText(settings.FGFS_root_dir)
		self.fgAircraftDir_edit.setText(settings.FGFS_aircraft_dir)
		self.fgSceneryDir_edit.setText(settings.FGFS_scenery_dir)
		self.externalTowerViewerHost_edit.setText(settings.external_tower_viewer_host)

	def storeSettings(self):
		self.list_model.applyChoices()
		settings.external_tower_viewer_process = self.towerView_external_radioButton.isChecked()
		settings.tower_viewer_UDP_port = self.towerView_fgmsPort_edit.value()
		settings.tower_viewer_telnet_port = self.towerView_telnetPort_edit.value()
		settings.FGFS_executable = self.fgCommand_edit.text()
		settings.FGFS_root_dir = self.fgRootDir_edit.text()
		settings.FGFS_aircraft_dir = self.fgAircraftDir_edit.text()
		settings.FGFS_scenery_dir = self.fgSceneryDir_edit.text()
		settings.external_tower_viewer_host = self.externalTowerViewerHost_edit.text()
		self.accept()



# =================================
#
#        V I E W P O I N T S
#
# =================================

class HeightEditDelegate(QStyledItemDelegate):
	def __init__(self, parent):
		QStyledItemDelegate.__init__(self, parent)

	def createEditor(self, parent, option, index):
		res = QSpinBox(parent)
		res.setMinimum(10)
		res.setMaximum(999)
		res.setSuffix(' ft ASFC')
		return res

	def setEditorData(self, editor, index):
		editor.setValue(int(index.data(Qt.EditRole)))

	def setModelData(self, editor, model, index):
		model.setData(index, editor.value(), Qt.EditRole)

	def updateEditorGeometry(self, editor, option, index):
		editor.setGeometry(option.rect)



class ViewpointTableModel(QAbstractTableModel):
	columns = ['', 'Label', 'Position', 'Height']

	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.parent_widget = parent
		self.xplane_viewpoints = env.airport_data.viewpoints[:] # (EarthCoords, float, str) list
		self.custom_viewpoints = settings.custom_viewpoints[:]  # (str spec, float, str) list
		self.selected_viewpoint = settings.selected_viewpoint
		if self.selected_viewpoint >= len(self.xplane_viewpoints) + len(self.custom_viewpoints):
			self.selected_viewpoint = 0

	def applyChoices(self):
		settings.custom_viewpoints = self.custom_viewpoints
		settings.selected_viewpoint = self.selected_viewpoint

	def addEditableEntry(self):
		self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
		self.custom_viewpoints.append((settings.location_code, default_viewpoint_height, 'Unnamed viewpoint'))
		self.endInsertRows()

	def removeSelected(self):
		if self.selected_viewpoint >= len(self.xplane_viewpoints):
			self.beginRemoveRows(QModelIndex(), self.selected_viewpoint, self.selected_viewpoint)
			del self.custom_viewpoints[self.selected_viewpoint - len(self.xplane_viewpoints)]
			self.endRemoveRows()
			self.selected_viewpoint = 0
			self.dataChanged.emit(self.index(self.selected_viewpoint, 0), self.index(self.selected_viewpoint, 0))

	# MODEL STUFF
	def rowCount(self, parent=None):
		return len(self.xplane_viewpoints) + len(self.custom_viewpoints)

	def columnCount(self, parent):
		return len(ViewpointTableModel.columns)

	def flags(self, index):
		col = index.column()
		if col == 0:
			return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
		else: # pos, height, label
			if index.row() < len(self.xplane_viewpoints): # data-defined viewpoint (locked)
				return Qt.NoItemFlags
			else: # custom viewpoint (editable)
				return Qt.ItemIsEnabled | Qt.ItemIsEditable

	def headerData(self, section, orientation, role):
		if orientation == Qt.Horizontal and role == Qt.DisplayRole:
			return ViewpointTableModel.columns[section]

	def data(self, index, role):
		row = index.row()
		col = index.column()
		xplane_src = row < len(self.xplane_viewpoints)
		pos, height, label = self.xplane_viewpoints[row] if xplane_src else self.custom_viewpoints[row - len(self.xplane_viewpoints)]
		if role == Qt.DisplayRole or role == Qt.EditRole:
			if col == 1:
				return label
			elif col == 2:
				return str(pos) if xplane_src else pos
			elif col == 3:
				return '%i ft' % height if role == Qt.DisplayRole else height
		elif role == Qt.CheckStateRole:
			if col == 0:
				return Qt.Checked if row == self.selected_viewpoint else Qt.Unchecked
		elif role == Qt.ToolTipRole:
			if xplane_src:
				if col > 0:
					return 'Specified in airport data'
			elif col == 2:
				try:
					return str(world_navpoint_db.coordsFromPointSpec(pos))
				except ValueError as err:
					return 'Invalid point specification: %s' % err
		elif role == Qt.DecorationRole:
			if col == 0 and xplane_src:
				return QIcon(QPixmap(IconFile.pixmap_lock))

	def setData(self, index, value, role):
		row = index.row()
		col = index.column()
		if role == Qt.CheckStateRole and col == 0:
			if value == Qt.Checked:
				was = self.selected_viewpoint
				self.selected_viewpoint = row
				self.dataChanged.emit(self.index(was, 0), self.index(was, 0))
				return True
		elif role == Qt.EditRole:
			custom_idx = row - len(self.xplane_viewpoints)
			posspec, height, label = self.custom_viewpoints[custom_idx]
			try:
				if col == 1: # label
					self.custom_viewpoints[custom_idx] = posspec, height, value
				elif col == 2: # position
					ignore_result = world_navpoint_db.coordsFromPointSpec(value)
					self.custom_viewpoints[custom_idx] = value, height, label
				elif col == 3: # height
					self.custom_viewpoints[custom_idx] = posspec, value, label
				return True
			except NavpointError as err:
				QMessageBox.critical(self.parent_widget, 'Invalid entry', 'Unknown named point: %s' % err)
			except ValueError as err:
				QMessageBox.critical(self.parent_widget, 'Invalid entry', 'Error: %s' % err)
		return False



class ViewpointDialog(QDialog, Ui_viewpointsSettingsDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.table_model = ViewpointTableModel(self)
		self.table_view.setModel(self.table_model)
		self.table_view.setItemDelegateForColumn(3, HeightEditDelegate(self))
		self.table_view.resizeColumnsToContents()
		if env.airport_data is not None and env.airport_data.viewpoints:
			self.info_label.hide()
		self.createViewpoint_button.clicked.connect(self.addViewpoint)
		self.removeViewpoint_button.clicked.connect(self.table_model.removeSelected)
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def addViewpoint(self):
		self.table_model.addEditableEntry()
		self.table_view.resizeColumnToContents(1)
		self.table_view.scrollToBottom()

	def storeSettings(self):
		self.table_model.applyChoices()
		QDialog.accept(self)




# =================================
#
#             V O I C E
#
# =================================

class FgFsdVoiceSettingsDialog(QDialog, Ui_voiceSettingsDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.pyaudioPhone_groupBox.setEnabled(pyaudio_available)
		self.fillFromSettings()
		self.testFGComMumble_button.clicked.connect(self.testFGComMumble)
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def testFGComMumble(self):
		test_FGCom_Mumble(self, self.fgcomMumbleHost_edit.text(), self.fgcomMumblePort_edit.value(), self.fgcomMumbleSoundEffects_tickBox.isChecked())

	def fillFromSettings(self):
		self.fgcomMumbleHost_edit.setText(settings.FGCom_mumble_host)
		self.fgcomMumblePort_edit.setValue(settings.FGCom_mumble_port)
		self.fgcomMumbleSoundEffects_tickBox.setChecked(settings.FGCom_mumble_sound_effects)
		self.phoneIP_edit.setText(settings.reachable_phone_IP)

	def storeSettings(self):
		settings.FGCom_mumble_host = self.fgcomMumbleHost_edit.text()
		settings.FGCom_mumble_port = self.fgcomMumblePort_edit.value()
		settings.FGCom_mumble_sound_effects = self.fgcomMumbleSoundEffects_tickBox.isChecked()
		settings.reachable_phone_IP = self.phoneIP_edit.text()
		self.accept()




# =================================
#
#              S O L O
#
# =================================

class SoloRuntimeSettingsDialog(QDialog, Ui_soloRuntimeSettingsDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.cpdlcConnections_label.setEnabled(settings.controller_pilot_data_link)
		self.cpdlcConnections_widget.setEnabled(settings.controller_pilot_data_link)
		self.airportMode_groupBox.setVisible(env.airport_data is not None)
		self.voiceInstr_off_radioButton.setChecked(True) # sets a default; auto-excludes if voice instr selected below
		self.readBack_off_radioButton.setChecked(True) # sets a default; auto-excludes if other selection below
		self.voiceInstr_on_radioButton.setEnabled(speech_recognition_available and not (settings.session_manager.session_type == SessionType.SOLO
				and settings.session_manager.isRunning() and settings.session_manager.voice_instruction_recogniser is None))
		self.readBack_voice_radioButton.setEnabled(speech_synthesis_available)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.fillFromSettings()
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject
	
	def fillFromSettings(self):
		self.maxAircraftCount_edit.setValue(settings.solo_max_aircraft_count)
		self.minSpawnDelay_seconds_edit.setValue(int(settings.solo_min_spawn_delay.total_seconds()))
		self.maxSpawnDelay_minutes_edit.setValue(int(settings.solo_max_spawn_delay.total_seconds() / 60))
		self.distractorCount_edit.setValue(settings.solo_distracting_traffic_count)
		self.cpdlcConnectionBalance_edit.setValue(int(100 * settings.solo_CPDLC_balance))
		self.ARRvsDEP_edit.setValue(int(100 * settings.solo_ARRvsDEP_balance))
		self.ILSvsVisual_edit.setValue(int(100 * settings.solo_ILSvsVisual_balance))
		self.helosRequestILS_tickBox.setChecked(settings.solo_helos_request_ILS)
		self.misapProb_edit.setValue(int(100 * settings.solo_MISAP_probability))
		self.soloWeatherChangeInterval_edit.setValue(0 if settings.solo_weather_change_interval is None
				else int(settings.solo_weather_change_interval.total_seconds() / 60))
		self.voiceInstr_on_radioButton.setChecked(self.voiceInstr_on_radioButton.isEnabled() and settings.solo_voice_instructions)
		self.readBack_wilcoBeep_radioButton.setChecked(settings.solo_wilco_beeps)
		self.readBack_voice_radioButton.setChecked(self.readBack_voice_radioButton.isEnabled() and settings.solo_voice_readback)
	
	def storeSettings(self):
		settings.solo_max_aircraft_count = self.maxAircraftCount_edit.value()
		settings.solo_min_spawn_delay = timedelta(seconds=self.minSpawnDelay_seconds_edit.value())
		settings.solo_max_spawn_delay = timedelta(minutes=self.maxSpawnDelay_minutes_edit.value())
		settings.solo_distracting_traffic_count = self.distractorCount_edit.value()
		settings.solo_CPDLC_balance = self.cpdlcConnectionBalance_edit.value() / 100
		settings.solo_ARRvsDEP_balance = self.ARRvsDEP_edit.value() / 100
		settings.solo_MISAP_probability = self.misapProb_edit.value() / 100
		settings.solo_ILSvsVisual_balance = self.ILSvsVisual_edit.value() / 100
		settings.solo_helos_request_ILS = self.helosRequestILS_tickBox.isChecked()
		settings.solo_weather_change_interval = None if self.soloWeatherChangeInterval_edit.value() == 0 \
				else timedelta(minutes=self.soloWeatherChangeInterval_edit.value())
		settings.solo_voice_instructions = self.voiceInstr_on_radioButton.isChecked()
		settings.solo_wilco_beeps = self.readBack_wilcoBeep_radioButton.isChecked()
		settings.solo_voice_readback = self.readBack_voice_radioButton.isChecked()
		signals.soloRuntimeSettingsChanged.emit()
		self.accept()



class SoloSystemSettingsDialog(QDialog, Ui_soloSystemSettingsDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.speechRecognition_groupBox.setEnabled(speech_recognition_available)
		self.fillFromSettings()
		self.browseForSphinxAcousticModel_button.clicked.connect(self.browseForSphinxAcousticModel)
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def browseForSphinxAcousticModel(self):
		txt = QFileDialog.getExistingDirectory(self, caption='Choose Sphinx acoustic model directory')
		if txt != '':
			self.sphinxAcousticModel_edit.setText(txt)

	def fillFromSettings(self):
		self.soloAircraftTypes_edit.setPlainText('\n'.join(settings.solo_aircraft_types))
		self.restrictAirlineChoiceToLiveries_tickBox.setChecked(settings.solo_restrict_to_available_liveries)
		self.preferEntryExitAirports_tickBox.setChecked(settings.solo_prefer_entry_exit_ADs)
		self.sphinxAcousticModel_edit.setText(settings.sphinx_acoustic_model_dir)

	def storeSettings(self):
		settings.solo_aircraft_types = [s for s in self.soloAircraftTypes_edit.toPlainText().split('\n') if s != '']
		settings.solo_restrict_to_available_liveries = self.restrictAirlineChoiceToLiveries_tickBox.isChecked()
		settings.solo_prefer_entry_exit_ADs = self.preferEntryExitAirports_tickBox.isChecked()
		settings.sphinx_acoustic_model_dir = self.sphinxAcousticModel_edit.text()
		self.accept()




# =================================
#
#        F L I G H T G E A R
#
# =================================

class FgSystemSettingsDialog(QDialog, Ui_fgSystemSettingsDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.lennyPasswordChange_info.clear()
		self.lennyPassword_edit.setPlaceholderText('No password set' if settings.lenny64_password_md5 == '' else '(unchanged)')
		self.fillFromSettings()
		self.lennyPassword_edit.textChanged.connect(self._updateLennyPasswordInfo)
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def _updateLennyPasswordInfo(self, s):
		self.lennyPasswordChange_info.setText('Changing password' if s != '' and settings.lenny64_password_md5 != '' else '')

	def fillFromSettings(self):
		self.fgmsServerHost_edit.setText(settings.FGMS_server_host)
		self.fgmsServerPort_edit.setValue(settings.FGMS_server_port)
		self.fgSocialName_edit.setText(settings.MP_social_name)
		self.ircChannel_edit.setText(settings.FG_IRC_channel)
		self.orsxServer_edit.setText(settings.ORSX_server_name)
		self.orsxHandoverRange_edit.setValue(some(settings.ORSX_handover_range, 0))
		self.lennyAccountEmail_edit.setText(settings.lenny64_account_email)
		self.lennyPassword_edit.clear()  # unchanged if stays blank
		self.fgFplLookUpInterval_edit.setValue(0 if settings.FG_FPL_update_interval is None else int(settings.FG_FPL_update_interval.total_seconds() / 60))
		self.fgWeatherLookUpInterval_edit.setValue(0 if settings.FG_METAR_update_interval is None else int(settings.FG_METAR_update_interval.total_seconds() / 60))

	def storeSettings(self):
		settings.FGMS_server_host = self.fgmsServerHost_edit.text()
		settings.FGMS_server_port = self.fgmsServerPort_edit.value()
		settings.MP_social_name = self.fgSocialName_edit.text().strip()
		settings.FG_IRC_channel = self.ircChannel_edit.text()
		settings.ORSX_server_name = self.orsxServer_edit.text()
		settings.ORSX_handover_range = None if self.orsxHandoverRange_edit.value() == 0 else self.orsxHandoverRange_edit.value()
		settings.lenny64_account_email = self.lennyAccountEmail_edit.text()
		new_lenny64_pwd = self.lennyPassword_edit.text()
		if new_lenny64_pwd != '':  # password change!
			digester = md5()
			digester.update(bytes(new_lenny64_pwd, 'utf8'))
			settings.lenny64_password_md5 = ''.join('%02x' % x for x in digester.digest())
		fgwxint = self.fgWeatherLookUpInterval_edit.value()
		settings.FG_METAR_update_interval = None if fgwxint == 0 else timedelta(minutes=fgwxint)
		fgfplint = self.fgFplLookUpInterval_edit.value()
		settings.FG_FPL_update_interval = None if fgfplint == 0 else timedelta(minutes=fgfplint)
		self.accept()






# =================================
#
#               F S D
#
# =================================

class FsdSystemSettingsDialog(QDialog, Ui_fsdSystemSettingsDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.fillFromSettings()
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def fillFromSettings(self):
		self.fsdServerHost_edit.setText(settings.FSD_server_host)
		self.fsdServerPort_edit.setValue(settings.FSD_server_port)
		self.fsdCid_edit.setText(settings.FSD_cid)
		self.fsdRating_edit.setValue(settings.FSD_rating)
		self.fsdPassword_edit.setText(settings.FSD_password)
		self.fsdSocialName_edit.setText(settings.MP_social_name)
		self.hoppieLogonCode_edit.setText(settings.FSD_Hoppie_logon)
		(self.fsdWeather_askFsd_radioButton if settings.FSD_weather_from_server else self.fsdWeather_fetchReal_radioButton).setChecked(True)
		self.fsdWeatherLookUpInterval_edit.setValue(0 if settings.FSD_METAR_update_interval is None else int(settings.FSD_METAR_update_interval.total_seconds() / 60))

	def storeSettings(self):
		settings.FSD_server_host = self.fsdServerHost_edit.text()
		settings.FSD_server_port = self.fsdServerPort_edit.value()
		settings.FSD_cid = self.fsdCid_edit.text()
		settings.FSD_rating = self.fsdRating_edit.value()
		settings.FSD_password = self.fsdPassword_edit.text()
		new_Hoppie_logon = self.hoppieLogonCode_edit.text()
		if settings.FSD_Hoppie_logon == '' and new_Hoppie_logon != '':  # new Hoppie logon entered
			QMessageBox.information(self, 'New Hoppie logon code', 'You have entered a new Hoppie logon code. '
					'Check your Hoppie account to make sure your network is set to "None" (opening page in web browser).')
			QDesktopServices.openUrl(QUrl(Hoppie_account_URL))
		settings.FSD_Hoppie_logon = new_Hoppie_logon
		# self.fsdSocialName_edit already saved by self.fgSocialName_edit
		settings.FSD_weather_from_server = self.fsdWeather_askFsd_radioButton.isChecked()
		fsdwxint = self.fsdWeatherLookUpInterval_edit.value()
		settings.FSD_METAR_update_interval = None if fsdwxint == 0 else timedelta(minutes=fsdwxint)
		self.accept()






# =================================
#
#           G E N E R A L
#
# =================================

class AcftTypeDelegate(QStyledItemDelegate):
	def __init__(self, parent):
		QStyledItemDelegate.__init__(self, parent)

	def createEditor(self, parent, option, index):
		return AircraftTypeCombo(parent)

	def setEditorData(self, editor, index):
		editor.setCurrentText(index.data())

	def setModelData(self, editor, model, index):
		model.setData(index, some(editor.getAircraftType(), ''), Qt.EditRole)

	def updateEditorGeometry(self, editor, option, index):
		editor.setGeometry(option.rect)


class KnownAcftTableModel(QAbstractTableModel):
	columns = ['Callsign', 'ACFT type']

	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.assoc_list = []

	def rowCount(self, parent=None):
		return len(self.assoc_list)

	def columnCount(self, parent):
		return len(KnownAcftTableModel.columns)

	def flags(self, index):
		return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return KnownAcftTableModel.columns[section]

	def data(self, index, role):
		if role == Qt.DisplayRole:
			return self.assoc_list[index.row()][index.column()]

	def setData(self, index, value, role=Qt.EditRole):
		row = index.row()
		col = index.column()
		if col == 0:
			self.assoc_list[row] = value.strip().upper(), self.assoc_list[row][1]
		elif col == 1:
			self.assoc_list[row] = self.assoc_list[row][0], value.strip()
		self.dataChanged.emit(index, index)
		return True

	def resetFromDict(self, full_data_dict):
		self.beginResetModel()
		self.assoc_list = sorted(full_data_dict.items())
		self.endResetModel()
		return True

	def addEntry(self):
		self.beginInsertRows(QModelIndex(), len(self.assoc_list), len(self.assoc_list))
		self.assoc_list.append(('', ''))
		self.endInsertRows()

	def removeEntry(self, row):
		self.beginRemoveRows(QModelIndex(), row, row)
		del self.assoc_list[row]
		self.endRemoveRows()

	def checkValues(self):
		cslst = [cs.upper() for cs, typ in self.assoc_list]
		try:
			raise ValueError('Duplicate callsign "%s"' % next(cs for i, cs in enumerate(cslst) if cs in cslst[i+1:]))
		except StopIteration:
			pass

	def getDict(self):
		return {cs.upper(): typ for cs, typ in self.assoc_list if cs and typ}


class SoundNotificationsListModel(QAbstractListModel):
	def __init__(self, parent):
		QAbstractListModel.__init__(self, parent)
		self.listed_types = sorted([t for t in Notification.types if t in sound_files], key=Notification.tstr)
		self.tick_list = [t in settings.sound_notifications for t in self.listed_types]
	
	def applyChoices(self):
		settings.sound_notifications.clear()
		for i, t in enumerate(self.listed_types):
			if self.tick_list[i]:
				settings.sound_notifications.add(t)
	
	# MODEL STUFF
	def rowCount(self, parent=None):
		return len(self.listed_types)
	
	def flags(self, index):
		return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
	
	def data(self, index, role):
		if role == Qt.DisplayRole:
			t = self.listed_types[index.row()]
			txt = Notification.tstr(t)
			if t not in icon_files:
				txt += ' (*)' # UI key under table: "not logged in the notification panel"
			return txt
		if role == Qt.CheckStateRole:
			return Qt.Checked if self.tick_list[index.row()] else Qt.Unchecked
	
	def setData(self, index, value, role):
		if index.isValid() and role == Qt.CheckStateRole:
			self.tick_list[index.row()] = value == Qt.Checked
			return True
		return False



class GeneralSettingsDialog(QDialog, Ui_generalSettingsDialog):
	#STATIC:
	last_tab_used = 0
	
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.known_acft_model = KnownAcftTableModel(self)
		self.knownAcft_tableView.setModel(self.known_acft_model)
		self.knownAcft_tableView.setItemDelegateForColumn(1, AcftTypeDelegate(self))
		self.msg_presets_model = SimpleStringListModel(self, True)
		self.messageList_view.setModel(self.msg_presets_model)
		self.sound_notification_model = SoundNotificationsListModel(self)

		self.fillFromSettings()
		self.settings_tabs.setCurrentIndex(GeneralSettingsDialog.last_tab_used)
		self.addKnownAcft_button.clicked.connect(self.addKnownAcft)
		self.removeKnownAcft_button.clicked.connect(self.removeKnownAcft)
		self.addMsgPreset_button.clicked.connect(self.addPresetMessage)
		self.rmMsgPreset_button.clicked.connect(self.removePresetMessage)
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def addKnownAcft(self):
		self.known_acft_model.addEntry()

	def removeKnownAcft(self):
		ilst = self.knownAcft_tableView.selectedIndexes()
		if ilst:
			self.known_acft_model.removeEntry(ilst[0].row()) # model is set to SingleSelection and SelectRows
	
	def addPresetMessage(self):
		msg, ok = QInputDialog.getText(self, 'New preset text message', 'Enter message (aliases allowed):')
		if ok:
			self.msg_presets_model.appendString(msg)

	def removePresetMessage(self):
		ilst = self.messageList_view.selectedIndexes()
		if ilst:
			self.msg_presets_model.removeRow(ilst[0].row()) # model is set to SingleSelection and SelectRows

	def fillFromSettings(self):
		self.routeVectWarnings_tickBox.setChecked(settings.strip_route_vect_warnings)
		self.cpdlcStatusIntegrationToStrips_tickBox.setChecked(settings.strip_CPDLC_integration)
		self.verticalRwyBoxLayout_tickBox.setChecked(settings.vertical_runway_box_layout)
		self.confirmHandovers_tickBox.setChecked(settings.confirm_handovers)
		self.confirmLossyStripReleases_tickBox.setChecked(settings.confirm_lossy_strip_releases)
		self.confirmLinkedStripDeletions_tickBox.setChecked(settings.confirm_linked_strip_deletions)
		self.autoFillStripFromXPDR_tickBox.setChecked(settings.strip_autofill_on_ACFT_link)
		self.autoFillStripFromFPL_tickBox.setChecked(settings.strip_autofill_on_FPL_link)
		self.autoFillStripBeforeHandovers_tickBox.setChecked(settings.strip_autofill_before_handovers)
		self.autoLinkStripModeS_tickBox.setChecked(settings.strip_autolink_mode_S)
		self.autoLinkStripOpenFpl_tickBox.setChecked(settings.strip_autolink_open_FPL)

		self.knownAircraft_groupBox.setChecked(settings.use_known_aircraft)
		self.known_acft_model.resetFromDict(settings.known_aircraft)

		self.sweepDispUpdate_radioButton.setChecked(settings.radar_sweeping_display)
		self.syncDispUpdate_radioButton.setChecked(not settings.radar_sweeping_display)
		self.positionHistoryTraceTime_edit.setValue(int(settings.radar_contact_trace_time.total_seconds() / 60))
		self.toleratedInvisibleSweeps_edit.setValue(settings.invisible_blips_before_contact_lost)
		self.flSpeedLine2_radioButton.setChecked(not settings.radar_tag_FL_at_bottom)
		self.flSpeedLine3_radioButton.setChecked(settings.radar_tag_FL_at_bottom)
		self.tagSpeedUnits_radioButton.setChecked(not settings.radar_tag_speed_tens)
		self.tagSpeedTens_radioButton.setChecked(settings.radar_tag_speed_tens)
		{0: self.wtcNotShown_radioButton, 1: self.wtcFollowsType_radioButton, 2: self.wtcFollowsSpeed_radioButton}.get(
				settings.radar_tag_WTC_position, self.wtcNotShown_radioButton).setChecked(True)
		self.interpretXpdrFl_tickBox.setChecked(settings.radar_tag_interpret_XPDR_FL)
		
		self.headingTolerance_edit.setValue(settings.heading_tolerance)
		self.altitudeTolerance_edit.setValue(settings.altitude_tolerance)
		self.speedTolerance_edit.setValue(settings.speed_tolerance)
		self.conflictWarningTime_edit.setValue(int(settings.route_conflict_anticipation.total_seconds() / 60))
		self.trafficConsidered_select.setCurrentIndex(settings.route_conflict_traffic)
		self.hintOpt_minCombinedGain_edit.setValue(int(settings.seq_opt_min_combo_gain.total_seconds() / 60))
		self.hintOpt_maxAcftLoss_edit.setValue(int(settings.seq_opt_max_acft_loss.total_seconds() / 60))

		self.cpdlcTimeout_edit.setValue(0 if settings.CPDLC_ACK_timeout is None else int(settings.CPDLC_ACK_timeout.total_seconds()))
		self.cpdlcAutoComu9Messages_tickBox.setChecked(settings.CPDLC_send_COMU9_to_accepted_transfers)
		self.cpdlcXfrAcceptedSendsStrip_tickBox.setChecked(settings.CPDLC_send_strips_on_accepted_transfers)
		self.cpdlcRaiseWindows_tickBox.setChecked(settings.CPDLC_raises_windows)
		self.cpdlcCloseWindows_tickBox.setChecked(settings.CPDLC_closes_windows)

		self.autoAtcChatWindowPopUp_tickBox.setChecked(settings.private_ATC_msg_auto_raise)
		self.notifyPublicChatRoomMsg_tickBox.setChecked(settings.ATC_chatroom_msg_notifications)
		self.textMessagesVisibleTime_edit.setValue(0 if settings.text_radio_history_time is None
				else int(settings.text_radio_history_time.total_seconds() / 60))
		self.msg_presets_model.setStringList(settings.radio_msg_presets)

		self.soundNotification_listView.setModel(self.sound_notification_model)
		self.pttMutesSounds_tickBox.setChecked(settings.PTT_mutes_notifications)
	
	def storeSettings(self):
		## CHECK SETTINGS FIRST
		try:
			self.known_acft_model.checkValues()
		except ValueError as err:
			QMessageBox.critical(self, 'ACFT type list error', str(err))
			return

		## ALL SETTINGS OK. Save them and accept the dialog.
		GeneralSettingsDialog.last_tab_used = self.settings_tabs.currentIndex()
		
		settings.strip_route_vect_warnings = self.routeVectWarnings_tickBox.isChecked()
		settings.strip_CPDLC_integration = self.cpdlcStatusIntegrationToStrips_tickBox.isChecked()
		settings.vertical_runway_box_layout = self.verticalRwyBoxLayout_tickBox.isChecked()
		settings.confirm_handovers = self.confirmHandovers_tickBox.isChecked()
		settings.confirm_lossy_strip_releases = self.confirmLossyStripReleases_tickBox.isChecked()
		settings.confirm_linked_strip_deletions = self.confirmLinkedStripDeletions_tickBox.isChecked()
		settings.strip_autofill_on_ACFT_link = self.autoFillStripFromXPDR_tickBox.isChecked()
		settings.strip_autofill_on_FPL_link = self.autoFillStripFromFPL_tickBox.isChecked()
		settings.strip_autofill_before_handovers = self.autoFillStripBeforeHandovers_tickBox.isChecked()
		settings.strip_autolink_mode_S = self.autoLinkStripModeS_tickBox.isChecked()
		settings.strip_autolink_open_FPL = self.autoLinkStripOpenFpl_tickBox.isChecked()

		settings.use_known_aircraft = self.knownAircraft_groupBox.isChecked()
		settings.known_aircraft = self.known_acft_model.getDict()

		settings.radar_sweeping_display = self.sweepDispUpdate_radioButton.isChecked()
		settings.radar_contact_trace_time = timedelta(minutes=self.positionHistoryTraceTime_edit.value())
		settings.invisible_blips_before_contact_lost = self.toleratedInvisibleSweeps_edit.value()
		settings.radar_tag_FL_at_bottom = self.flSpeedLine3_radioButton.isChecked()
		settings.radar_tag_speed_tens = self.tagSpeedTens_radioButton.isChecked()
		settings.radar_tag_WTC_position = next((i for i, rb in enumerate([self.wtcNotShown_radioButton,
				self.wtcFollowsType_radioButton, self.wtcFollowsSpeed_radioButton]) if rb.isChecked()), 0)
		settings.radar_tag_interpret_XPDR_FL = self.interpretXpdrFl_tickBox.isChecked()
		
		settings.heading_tolerance = self.headingTolerance_edit.value()
		settings.altitude_tolerance = self.altitudeTolerance_edit.value()
		settings.speed_tolerance = self.speedTolerance_edit.value()
		settings.route_conflict_anticipation = timedelta(minutes=self.conflictWarningTime_edit.value())
		settings.route_conflict_traffic = self.trafficConsidered_select.currentIndex()
		settings.seq_opt_min_combo_gain = timedelta(minutes=self.hintOpt_minCombinedGain_edit.value())
		settings.seq_opt_max_acft_loss = timedelta(minutes=self.hintOpt_maxAcftLoss_edit.value())

		settings.CPDLC_ACK_timeout = None if self.cpdlcTimeout_edit.value() == 0 \
				else timedelta(seconds=self.cpdlcTimeout_edit.value())
		settings.CPDLC_send_COMU9_to_accepted_transfers = self.cpdlcAutoComu9Messages_tickBox.isChecked()
		settings.CPDLC_send_strips_on_accepted_transfers = self.cpdlcXfrAcceptedSendsStrip_tickBox.isChecked()
		settings.CPDLC_raises_windows = self.cpdlcRaiseWindows_tickBox.isChecked()
		settings.CPDLC_closes_windows = self.cpdlcCloseWindows_tickBox.isChecked()

		settings.private_ATC_msg_auto_raise = self.autoAtcChatWindowPopUp_tickBox.isChecked()
		settings.ATC_chatroom_msg_notifications = self.notifyPublicChatRoomMsg_tickBox.isChecked()
		settings.text_radio_history_time = None if self.textMessagesVisibleTime_edit.value() == 0 \
				else timedelta(minutes=self.textMessagesVisibleTime_edit.value())
		settings.radio_msg_presets = self.msg_presets_model.stringList()
		
		self.sound_notification_model.applyChoices()
		settings.PTT_mutes_notifications = self.pttMutesSounds_tickBox.isChecked()
		
		signals.generalSettingsChanged.emit()
		self.accept()






# =================================
#
#          L O C A T I O N
#
# =================================

class XpdrCodeDelegate(QStyledItemDelegate):
	def __init__(self, parent):
		QStyledItemDelegate.__init__(self, parent)

	def createEditor(self, parent, option, index):
		return XpdrCodeSpinBox(parent)

	def setEditorData(self, editor, index):
		editor.setValue(index.data(Qt.EditRole))

	def setModelData(self, editor, model, index):
		model.setData(index, editor.value())

	def updateEditorGeometry(self, editor, option, index):
		editor.setGeometry(option.rect)


class XpdrRangesTableModel(QAbstractTableModel):
	columns = ['Name', 'From', 'To', 'Radar colour']

	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.ranges = [] # XpdrAssignmentRange list

	def rowCount(self, parent=None):
		return len(self.ranges)

	def columnCount(self, parent):
		return len(XpdrRangesTableModel.columns)

	def flags(self, index):
		flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
		if index.column() < 3:
			flags |= Qt.ItemIsEditable
		return flags

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return XpdrRangesTableModel.columns[section]

	def data(self, index, role):
		row = index.row()
		col = index.column()
		rng = self.ranges[row]
		if role == Qt.DisplayRole:
			if col == 0:
				return rng.name
			elif col == 1:
				return '%04o' % rng.lo
			elif col == 2:
				return '%04o' % rng.hi
		elif role == Qt.EditRole:
			if col == 0:
				return rng.name
			elif col == 1:
				return rng.lo
			elif col == 2:
				return rng.hi
			elif col == 3:
				return rng.col
		elif role == Qt.ToolTipRole:
			if col == 3:
				return 'Double-click to pick' if rng.col is None else 'Double-click to reset'
		elif role == Qt.DecorationRole:
			if col == 3:
				return None if rng.col is None else coloured_square_icon(rng.col)

	def setData(self, index, value, role=Qt.EditRole):
		row = index.row()
		col = index.column()
		rng = self.ranges[row]
		if col == 0:
			rng.name = value
		elif col == 1:
			rng.lo = value
		elif col == 2:
			rng.hi = value
		elif col == 3:
			rng.col = value
		self.dataChanged.emit(index, index)
		return True

	def fillData(self, rnglst):
		self.beginResetModel()
		self.ranges = sorted(rnglst, key=(lambda rng: rng.name))
		self.endResetModel()
		return True

	def addEntry(self):
		self.beginInsertRows(QModelIndex(), len(self.ranges), len(self.ranges))
		sugg_code = next((c for c in range(0o0001, 0o7777 + 1) if not any(rng.lo <= c <= rng.hi for rng in self.ranges)), 0o0000)
		self.ranges.append(XpdrAssignmentRange('New range', sugg_code, sugg_code, None))
		self.endInsertRows()

	def removeEntry(self, row):
		self.beginRemoveRows(QModelIndex(), row, row)
		del self.ranges[row]
		self.endRemoveRows()

	def checkValues(self):
		if len(set(rng.name for rng in self.ranges)) < len(self.ranges) or any(rng.name == '' for rng in self.ranges):
			raise ValueError('Duplicate or empty range names.')
		try:
			raise ValueError('Invalid values for range "%s".' % next(rng.name for rng in self.ranges if rng.lo > rng.hi))
		except StopIteration:
			pass
		try:
			raise ValueError('Ranges "%s" and "%s" overlap.' % next((rng.name, rng2.name)
					for i, rng in enumerate(self.ranges) for rng2 in self.ranges[i+1:] if not (rng.hi < rng2.lo or rng2.hi < rng.lo)))
		except StopIteration:
			pass

	def getFullData(self):
		return self.ranges


class LocationSettingsDialog(QDialog, Ui_locationSettingsDialog):
	#STATIC:
	last_tab_used = 0
	
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.xpdr_ranges_model = XpdrRangesTableModel(self)
		self.xpdrRanges_tableView.setModel(self.xpdr_ranges_model)
		self.xpdrRanges_tableView.setItemDelegateForColumn(1, XpdrCodeDelegate(self))
		self.xpdrRanges_tableView.setItemDelegateForColumn(2, XpdrCodeDelegate(self))
		self.setWindowTitle('%s location setup - %s' % (('CTR' if env.airport_data is None else 'AD'), settings.location_code))
		if env.airport_data is None: # CTR session
			self.stripPrinter_groupBox.setEnabled(False)
			self.settings_tabs.removeTab(self.settings_tabs.indexOf(self.surfaces_tab))
			self.settings_tabs.removeTab(self.settings_tabs.indexOf(self.ATIS_tab))
			self.soloSessions_AD_groupBox.hide()
			self.spawnCTR_minFL_edit.valueChanged.connect(self.spawnCTR_minFL_valueChanged)
			self.spawnCTR_maxFL_edit.valueChanged.connect(self.spawnCTR_maxFL_valueChanged)
		else: # AD session
			for rwy in env.airport_data.directionalRunways():
				self.depLdgSurfaces_tabs.addTab(RunwayParametersWidget(self, rwy), rwy.name)
			for hpad in env.airport_data.helipads():
				self.depLdgSurfaces_tabs.addTab(HelipadParametersWidget(self, hpad), hpad.name)
			if env.airport_data.transition_altitude is not None:
				self.transitionAltitude_edit.setEnabled(False)
				self.transitionAltitude_edit.setToolTip('Fixed by airport data')
			self.soloSessions_CTR_groupBox.hide()
			self.spawnAPP_minFL_edit.valueChanged.connect(self.spawnAPP_minFL_valueChanged)
			self.spawnAPP_maxFL_edit.valueChanged.connect(self.spawnAPP_maxFL_valueChanged)
			self.TWRrangeCeiling_edit.valueChanged.connect(self.TWRrangeCeiling_valueChanged)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.fillFromSettings()
		self.settings_tabs.setCurrentIndex(GeneralSettingsDialog.last_tab_used)
		self.xpdrRanges_tableView.doubleClicked.connect(self.xpdrRangeTableDoubleClicked)
		self.addXpdrRange_button.clicked.connect(self.xpdr_ranges_model.addEntry)
		self.removeXpdrRange_button.clicked.connect(self.removeXpdrRange)
		self.buttonBox.accepted.connect(self.storeSettings) # UI connects reject

	def xpdrRangeTableDoubleClicked(self, table_index):
		if table_index.isValid() and table_index.column() == 3:
			if self.xpdr_ranges_model.data(table_index, Qt.EditRole) is None:
				colour = QColorDialog.getColor(parent=self, title='Pick radar contact colour', initial=Qt.white)
				if colour.isValid():
					self.xpdr_ranges_model.setData(table_index, colour)
			else:
				self.xpdr_ranges_model.setData(table_index, None)

	def removeXpdrRange(self):
		ilst = self.xpdrRanges_tableView.selectedIndexes()
		if ilst:
			self.xpdr_ranges_model.removeEntry(ilst[0].row()) # model is set to SingleSelection and SelectRows
	
	def spawnAPP_minFL_valueChanged(self, v):
		if v < self.TWRrangeCeiling_edit.value():
			self.TWRrangeCeiling_edit.setValue(v)
		if v > self.spawnAPP_maxFL_edit.value():
			self.spawnAPP_maxFL_edit.setValue(v)
	
	def spawnAPP_maxFL_valueChanged(self, v):
		if v < self.spawnAPP_minFL_edit.value():
			self.spawnAPP_minFL_edit.setValue(v)
	
	def TWRrangeCeiling_valueChanged(self, v):
		if v > self.spawnAPP_minFL_edit.value():
			self.spawnAPP_minFL_edit.setValue(v)
	
	def spawnCTR_minFL_valueChanged(self, v):
		if v > self.spawnCTR_maxFL_edit.value():
			self.spawnCTR_maxFL_edit.setValue(v)
	
	def spawnCTR_maxFL_valueChanged(self, v):
		if v < self.spawnCTR_minFL_edit.value():
			self.spawnCTR_minFL_edit.setValue(v)
		
	def selectSemiCircRule(self, rule):
		radio_button = {
				SemiCircRule.OFF: self.semiCircRule_radioButton_off,
				SemiCircRule.E_W: self.semiCircRule_radioButton_EW,
				SemiCircRule.N_S: self.semiCircRule_radioButton_NS
			}[rule]
		radio_button.setChecked(True)
		
	def selectedSemiCircRule(self):
		if self.semiCircRule_radioButton_off.isChecked():
			return SemiCircRule.OFF
		elif self.semiCircRule_radioButton_EW.isChecked():
			return SemiCircRule.E_W
		elif self.semiCircRule_radioButton_NS.isChecked():
			return SemiCircRule.N_S

	def fillFromSettings(self):
		# Equipment tab
		self.radioDirectionFinding_tickBox.setChecked(settings.radio_direction_finding)
		self.cpdlc_tickBox.setChecked(settings.controller_pilot_data_link)
		self.capability_noSSR_radioButton.setChecked(settings.SSR_mode_capability == '0')
		self.capability_modeA_radioButton.setChecked(settings.SSR_mode_capability == 'A')
		self.capability_modeC_radioButton.setChecked(settings.SSR_mode_capability == 'C')
		self.capability_modeS_radioButton.setChecked(settings.SSR_mode_capability == 'S')
		self.radarHorizontalRange_edit.setValue(settings.radar_range)
		self.radarFloor_edit.setValue(settings.radar_signal_floor_level)
		self.radarUpdateInterval_edit.setValue(int(settings.radar_sweep_interval.total_seconds()))
		self.stripAutoPrint_DEP_tickBox.setChecked(settings.auto_print_strips_include_DEP)
		self.stripAutoPrint_ARR_tickBox.setChecked(settings.auto_print_strips_include_ARR)
		self.stripAutoPrint_ifrOnly_tickBox.setChecked(settings.auto_print_strips_IFR_only)
		self.stripAutoPrint_leadTime_edit.setValue(int(settings.auto_print_strips_anticipation.total_seconds() / 60))
		# Env./rules tab
		self.primaryMetarStation_edit.setText(settings.primary_METAR_station.upper())
		self.radioName_edit.setText(settings.location_radio_name)
		self.transitionAltitude_edit.setValue(env.transitionAltitude())
		self.uncontrolledVFRcode_edit.setValue(settings.uncontrolled_VFR_XPDR_code)
		self.magneticDeclination_edit.setValue(settings.magnetic_declination)
		self.horizontalSeparation_edit.setValue(settings.horizontal_separation)
		self.verticalSeparation_edit.setValue(settings.vertical_separation)
		self.conflictWarningFloorFL_edit.setValue(settings.conflict_warning_floor_FL)
		self.xpdr_ranges_model.fillData(settings.XPDR_assignment_ranges)
		# Other settings tabs
		if env.airport_data is None: # CTR mode
			self.spawnCTR_minFL_edit.setValue(settings.solo_CTR_floor_FL)
			self.spawnCTR_maxFL_edit.setValue(settings.solo_CTR_ceiling_FL)
			self.CTRrangeDistance_edit.setValue(settings.solo_CTR_range_dist)
			self.routingPoints_edit.setText(' '.join(settings.solo_CTR_routing_points))
			self.selectSemiCircRule(settings.solo_CTR_semi_circular_rule)
		else: # AD mode
			self.atisCustomAppendix_edit.setPlainText(settings.ATIS_custom_appendix)
			self.spawnAPP_minFL_edit.setValue(settings.solo_APP_ceiling_FL_min)
			self.spawnAPP_maxFL_edit.setValue(settings.solo_APP_ceiling_FL_max)
			self.TWRrangeDistance_edit.setValue(settings.solo_TWR_range_dist)
			self.TWRrangeCeiling_edit.setValue(settings.solo_TWR_ceiling_FL)
	
	def storeSettings(self):
		## CHECK SETTINGS FIRST
		try:
			self.xpdr_ranges_model.checkValues()
		except ValueError as err:
			QMessageBox.critical(self, 'XPDR range error', str(err))
			return
		if env.airport_data is None:
			try:
				bad = next(p for p in self.routingPoints_edit.text().split() if len(env.navpoints.findAll(code=p)) != 1)
				QMessageBox.critical(self, 'Invalid entry', 'Unknown navpoint or navpoint not unique: %s' % bad)
				return
			except StopIteration:
				pass # no bad navpoints
		
		## ALL SETTINGS OK. Save them and accept the dialog.
		GeneralSettingsDialog.last_tab_used = self.settings_tabs.currentIndex()
		
		if env.airport_data is not None:
			for i in range(self.depLdgSurfaces_tabs.count()):
				self.depLdgSurfaces_tabs.widget(i).applyParams()
		
		settings.radio_direction_finding = self.radioDirectionFinding_tickBox.isChecked()
		settings.controller_pilot_data_link = self.cpdlc_tickBox.isChecked()
		settings.SSR_mode_capability = '0' if self.capability_noSSR_radioButton.isChecked() \
				else 'A' if self.capability_modeA_radioButton.isChecked() \
				else 'C' if self.capability_modeC_radioButton.isChecked() else 'S'
		settings.radar_range = self.radarHorizontalRange_edit.value()
		settings.radar_signal_floor_level = self.radarFloor_edit.value()
		settings.radar_sweep_interval = timedelta(seconds=self.radarUpdateInterval_edit.value())
		settings.auto_print_strips_include_DEP = self.stripAutoPrint_DEP_tickBox.isChecked()
		settings.auto_print_strips_include_ARR = self.stripAutoPrint_ARR_tickBox.isChecked()
		settings.auto_print_strips_IFR_only = self.stripAutoPrint_ifrOnly_tickBox.isChecked()
		settings.auto_print_strips_anticipation = timedelta(minutes=self.stripAutoPrint_leadTime_edit.value())

		settings.primary_METAR_station = self.primaryMetarStation_edit.text().upper()
		settings.location_radio_name = self.radioName_edit.text()
		settings.transition_altitude = self.transitionAltitude_edit.value() # NOTE useless if a TA is set in apt.dat
		settings.uncontrolled_VFR_XPDR_code = self.uncontrolledVFRcode_edit.value()
		settings.magnetic_declination = self.magneticDeclination_edit.value()
		settings.horizontal_separation = self.horizontalSeparation_edit.value()
		settings.vertical_separation = self.verticalSeparation_edit.value()
		settings.conflict_warning_floor_FL = self.conflictWarningFloorFL_edit.value()
		settings.XPDR_assignment_ranges = self.xpdr_ranges_model.getFullData()
		
		if env.airport_data is None: # CTR mode
			settings.solo_CTR_floor_FL = self.spawnCTR_minFL_edit.value()
			settings.solo_CTR_ceiling_FL = self.spawnCTR_maxFL_edit.value()
			settings.solo_CTR_range_dist = self.CTRrangeDistance_edit.value()
			settings.solo_CTR_routing_points = self.routingPoints_edit.text().split()
			settings.solo_CTR_semi_circular_rule = self.selectedSemiCircRule()
		else: # AD mode
			settings.ATIS_custom_appendix = self.atisCustomAppendix_edit.toPlainText()
			settings.solo_APP_ceiling_FL_min = self.spawnAPP_minFL_edit.value() // 10 * 10
			settings.solo_APP_ceiling_FL_max = ((self.spawnAPP_maxFL_edit.value() - 1) // 10 + 1) * 10
			settings.solo_TWR_range_dist = self.TWRrangeDistance_edit.value()
			settings.solo_TWR_ceiling_FL = self.TWRrangeCeiling_edit.value()
		
		signals.locationSettingsChanged.emit()
		self.accept()
