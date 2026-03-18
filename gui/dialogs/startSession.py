
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

from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QFileDialog

from ui.startSoloAdDialog import Ui_startSoloAdDialog
from ui.startSoloCtrDialog import Ui_startSoloCtrDialog
from ui.startFgSessionDialog import Ui_startFgSessionDialog
from ui.startFsdDialog import Ui_startFsdDialog
from ui.startStudentSessionDialog import Ui_startStudentSessionDialog
from ui.startTeacherSessionDialog import Ui_startTeacherSessionDialog
from ui.startPlaybackSessionDialog import Ui_startPlaybackDialog

from base.coords import dist_str
from base.timeline import read_timeline_data, header_kwd_loc_code, header_kwd_loc_coords, header_kwd_recording_version
from base.utc import timestr, datestr, duration_str

from ext.audio import pyaudio_available
from ext.irc import IRC_available

from gui.dialogs.adSurfaces import AdSfcUseDialog
from gui.dialogs.settings import FgFsdVoiceSettingsDialog, SoloRuntimeSettingsDialog, SoloSystemSettingsDialog, FgSystemSettingsDialog, FsdSystemSettingsDialog

from session.config import settings
from session.env import env


# ---------- Constants ----------

# -------------------------------


class StartSoloDialog_AD(QDialog, Ui_startSoloAdDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		if env.airport_data is not None and len(env.airport_data.ground_net.taxiways()) > 0 \
				and len(env.airport_data.ground_net.parkingPositions()) > 0: # GND can be enabled
			self.GND_tickBox.toggled.connect(self.updateOKbutton)
		else: # GND must be disabled
			self.GND_tickBox.setEnabled(False)
			self.GND_tickBox.setToolTip('Missing parking positions or taxi routes.')
		self.TWR_tickBox.toggled.connect(self.updateOKbutton)
		self.APP_tickBox.toggled.connect(self.updateOKbutton)
		self.DEP_tickBox.toggled.connect(self.updateOKbutton)
		self.updateOKbutton()
		self.soloSettings_button.clicked.connect(lambda: SoloSystemSettingsDialog(self).exec())
		self.simOptions_button.clicked.connect(lambda: SoloRuntimeSettingsDialog(self).exec())
		self.tkofLdgSurfaces_button.clicked.connect(lambda: AdSfcUseDialog(self).exec())
		self.buttonBox.accepted.connect(self.doOK) # UI connects reject
	
	def updateOKbutton(self):
		gnd, twr, app, dep = (box.isChecked() for box in [self.GND_tickBox, self.TWR_tickBox, self.APP_tickBox, self.DEP_tickBox])
		self.buttonBox.button(QDialogButtonBox.Ok).setEnabled((gnd or twr or app or dep) and (not gnd or twr or not app and not dep))
	
	def doOK(self):
		settings.solo_role_GND = self.GND_tickBox.isChecked()
		settings.solo_role_TWR = self.TWR_tickBox.isChecked()
		settings.solo_role_APP = self.APP_tickBox.isChecked()
		settings.solo_role_DEP = self.DEP_tickBox.isChecked()
		self.accept()
	
	def chosenInitialTrafficCount(self):
		return self.initTrafficCount_edit.value()


class StartSoloDialog_CTR(QDialog, Ui_startSoloCtrDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.soloSettings_button.clicked.connect(lambda: SoloSystemSettingsDialog(self).exec())
		self.simOptions_button.clicked.connect(lambda: SoloRuntimeSettingsDialog(self).exec())
		self.buttonBox.accepted.connect(self.accept) # UI connects reject

	def chosenInitialTrafficCount(self):
		return self.initTrafficCount_edit.value()




class StartFgSessionDialog(QDialog, Ui_startFgSessionDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.irc_subSystem_tickBox.setEnabled(IRC_available)
		self.phone_subSystem_tickBox.setEnabled(IRC_available and pyaudio_available)
		self.fgSettings_button.clicked.connect(lambda: FgSystemSettingsDialog(self).exec())
		self.voiceSettings_button.clicked.connect(lambda: FgFsdVoiceSettingsDialog(self).exec())
		self.buttonBox.accepted.connect(self.doOK) # UI connects reject
	
	def showEvent(self, event):
		self.callsign_edit.setText(settings.location_code + 'obs') # should contain no whitespace, cf. use with IRC
		self.clientPort_edit.setValue(settings.FGMS_client_port)
		self.irc_subSystem_tickBox.setEnabled(IRC_available)
		self.irc_subSystem_tickBox.setChecked(IRC_available and settings.FG_IRC_enabled)
		self.fgcom_subSystem_tickBox.setChecked(settings.FGCom_enabled)
		self.phone_subSystem_tickBox.setChecked(IRC_available and pyaudio_available and settings.phone_lines_enabled)
		self.orsx_subSystem_tickBox.setChecked(settings.FG_ORSX_enabled)
		self.callsign_edit.setFocus()
	
	def doOK(self):
		cs = self.callsign_edit.text()
		if cs == '' or ' ' in cs or ',' in cs:
			QMessageBox.critical(self, 'FG session start error', 'Invalid callsign.')
		elif settings.MP_social_name == '':
			QMessageBox.critical(self, 'FG session start error', 'No social name set; please edit system settings.')
		elif self.irc_subSystem_tickBox.isChecked() and settings.FG_IRC_channel == '':
			QMessageBox.critical(self, 'FG session start error', 'IRC channel required for native ATC-pie messaging; please edit system settings.')
		elif self.fgcom_subSystem_tickBox.isChecked() and settings.FGCom_mumble_host == '':
			QMessageBox.critical(self, 'FG session start error', 'Running host name required for FGCom-mumble; please edit system settings.')
		elif self.phone_subSystem_tickBox.isChecked() and not self.irc_subSystem_tickBox.isChecked():
			QMessageBox.critical(self, 'FG session start error', 'Native messaging subsystem required for ATC phone lines.')
		elif self.phone_subSystem_tickBox.isChecked() and settings.reachable_phone_IP == '':
			QMessageBox.critical(self, 'FG session start error', 'Reachable IP required for ATC phone lines; please edit system settings.')
		elif self.orsx_subSystem_tickBox.isChecked() and settings.ORSX_server_name == '':
			QMessageBox.critical(self, 'FG session start error', 'OpenRadar server address missing; please edit system settings.')
		else: # all OK; update settings and accept dialog
			settings.FGMS_client_port = self.clientPort_edit.value()
			settings.FG_IRC_enabled = IRC_available and self.irc_subSystem_tickBox.isChecked()
			settings.FGCom_enabled = self.fgcom_subSystem_tickBox.isChecked()
			settings.phone_lines_enabled = IRC_available and pyaudio_available and self.phone_subSystem_tickBox.isChecked()
			settings.FG_ORSX_enabled = self.orsx_subSystem_tickBox.isChecked()
			settings.FGC = self.orsx_subSystem_tickBox.isChecked()
			self.accept()
	
	def chosenCallsign(self):
		return self.callsign_edit.text()




class StartFsdDialog(QDialog, Ui_startFsdDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.use_phoneLines_tickBox.setEnabled(pyaudio_available)
		self.fsdSettings_button.clicked.connect(lambda: FsdSystemSettingsDialog(self).exec())
		self.voiceSettings_button.clicked.connect(lambda: FgFsdVoiceSettingsDialog(self).exec())
		self.use_FGComMumble_tickBox.toggled.connect(lambda b: self.voicePort_edit.setEnabled(b or self.use_phoneLines_tickBox.isChecked()))
		self.use_phoneLines_tickBox.toggled.connect(lambda b: self.voicePort_edit.setEnabled(b or self.use_FGComMumble_tickBox.isChecked()))
		self.buttonBox.accepted.connect(self.doOK) # UI connects reject

	def showEvent(self, event):
		self.callsign_edit.setText(settings.location_code)
		self.visibilityRange_edit.setValue(settings.FSD_visibility_range)
		self.voicePort_edit.setValue(settings.FSD_voice_system_port)
		self.use_phoneLines_tickBox.setChecked(pyaudio_available and settings.phone_lines_enabled)
		self.use_FGComMumble_tickBox.setChecked(settings.FGCom_enabled)
		self.use_HoppieAcars_tickBox.setChecked(settings.FSD_Hoppie_enabled)

	def doOK(self):
		if ':' in settings.MP_social_name:
			QMessageBox.critical(self, 'FSD start error', 'Invalid social name for FSD. Please change in system settings.')
			return
		cs = self.callsign_edit.text()
		if cs == '' or ' ' in cs or ':' in cs:
			QMessageBox.critical(self, 'FSD start error', 'Invalid callsign.')
		elif settings.MP_social_name == '' or ':' in settings.MP_social_name:
			QMessageBox.critical(self, 'FSD start error', 'Missing or invalid social name; please edit system settings.')
		elif self.use_phoneLines_tickBox.isChecked() and settings.reachable_phone_IP == '':
			QMessageBox.critical(self, 'FSD start error', 'Reachable IP required for ATC phone lines; please edit system settings.')
		elif self.use_FGComMumble_tickBox.isChecked() and settings.FGCom_mumble_host == '':
			QMessageBox.critical(self, 'FSD start error', 'No client given for FGCom-mumble; please edit system settings.')
		elif self.use_HoppieAcars_tickBox.isChecked() and settings.FSD_Hoppie_logon == '':
			QMessageBox.critical(self, 'FSD start error', 'Hoppie logon code required; please edit system settings.')
		else: # all OK; accept dialog
			settings.FSD_visibility_range = self.visibilityRange_edit.value()
			settings.FSD_voice_system_port = self.voicePort_edit.value()
			settings.phone_lines_enabled = self.use_phoneLines_tickBox.isChecked()
			settings.FGCom_enabled = self.use_FGComMumble_tickBox.isChecked()
			settings.FSD_Hoppie_enabled = self.use_HoppieAcars_tickBox.isChecked()
			self.accept()
	
	def chosenCallsign(self):
		return self.callsign_edit.text()




class StartStudentSessionDialog(QDialog, Ui_startStudentSessionDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.teachingServiceHost_edit.setText(settings.teaching_service_host)
		self.teachingServicePort_edit.setValue(settings.teaching_service_port)
		self.updateOKbutton()
		self.teachingServiceHost_edit.textChanged.connect(self.updateOKbutton)
		self.buttonBox.accepted.connect(self.doOK) # UI connects reject
	
	def updateOKbutton(self):
		self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(self.teachingServiceHost_edit.text() != '')
	
	def doOK(self):
		settings.teaching_service_host = self.teachingServiceHost_edit.text()
		settings.teaching_service_port = self.teachingServicePort_edit.value()
		self.accept()




class StartTeacherSessionDialog(QDialog, Ui_startTeacherSessionDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.usePyAudio_tickBox.setEnabled(pyaudio_available)
		self.usePyAudio_tickBox.setChecked(pyaudio_available and settings.phone_lines_enabled)
		self.teachingServicePort_edit.setValue(settings.teaching_service_port)
		self.buttonBox.accepted.connect(self.doOK) # UI connects reject

	def doOK(self):
		settings.teaching_service_port = self.teachingServicePort_edit.value()
		settings.phone_lines_enabled = self.usePyAudio_tickBox.isChecked()
		self.accept()




class StartPlaybackDialog(QDialog, Ui_startPlaybackDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.dataFile_info.clear()
		self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
		self.sourced_timeline = None
		self.browse_button.clicked.connect(self.browseForSourceData)
		self.buttonBox.accepted.connect(self.accept) # UI connects reject

	def browseForSourceData(self):
		filename, _ = QFileDialog.getOpenFileName(self, caption='Select source file')
		if filename != '':
			try:
				self.sourced_timeline, meta_data = read_timeline_data(filename)
				self.dataFile_info.setText(filename)
				info = 'Start time: %s, %s' % (datestr(self.sourced_timeline.startTime()), timestr(self.sourced_timeline.startTime()))
				info += '\nTimeline duration: %s' % duration_str(self.sourced_timeline.duration())
				try:
					info += '\nRecorded with ATC-pie version %s.' % meta_data[header_kwd_recording_version]
				except KeyError:
					info += '\nRecorded with unknown ATC-pie version.'
				info += '\n'
				info += '\nWarning: experimental session type!'
				try:
					tl_code = meta_data[header_kwd_loc_code]
					if tl_code != settings.location_code:
						info += '\nWarning: mismatching recorded location code "%s".' % tl_code
				except KeyError:
					pass
				try:
					tl_coords = meta_data[header_kwd_loc_coords]
					if not env.pointOnMap(tl_coords):
						info += '\nWarning: data was recorded %s away from current location.' % dist_str(env.radarPos().distanceTo(tl_coords))
				except KeyError:
					pass
				self.timeline_info.setText(info)
				self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(True)
			except FileNotFoundError:
				QMessageBox.critical(self, 'Playback start error', 'File not found')
			except ValueError as err:
				QMessageBox.critical(self, 'Playback start error', 'Error in source file: %s' % err)

	def sourcedTimeline(self):
		return self.sourced_timeline
