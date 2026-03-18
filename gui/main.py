
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

from sys import stderr
from datetime import timedelta

from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtGui import QDesktopServices, QIcon
from PyQt5.QtWidgets import QMainWindow, QInputDialog, QFileDialog, QMessageBox, QActionGroup, QLabel

from ui.mainWindow import Ui_mainWindow

from base.coords import EarthCoords
from base.fpl import FPL
from base.nav import world_routing_db
from base.strip import soft_link_detail, departure_clearance_detail
from base.timeline import SessionRecorder
from base.utc import timestr
from base.weather import hPa2inHg, mkWeather

from ext.data import read_bg_img, read_route_presets, import_entry_exit_data, make_FGFS_models_liveries
from ext.fgfs import FlightGearTowerViewer
from ext.sct import extract_sector
from ext.sr import speech_recognition_available, prepare_SR_language_files, cleanup_SR_language_files

from gui.actions import new_strip_dialog, edit_strip, receive_strip, recover_strip, strip_auto_print_check, \
		kill_aircraft, receive_CPDLC_transfer_request, receive_CPDLC_transfer_response, generic_transfer_action
from gui.dialogs.adSurfaces import AdSfcUseDialog
from gui.dialogs.depClearance import DepartureClearanceEditDialog, DepartureClearanceViewDialog
from gui.dialogs.locInfo import LocationInfoDialog
from gui.dialogs.miscDialogs import AboutDialog, DiscardedStripsDialog, RadarMeasurementLog, RecordPlaybackDialog
from gui.dialogs.settings import LocationSettingsDialog, GeneralSettingsDialog, SoloRuntimeSettingsDialog, \
	FgfsViewersDialog, ViewpointDialog
from gui.dialogs.startSession import StartSoloDialog_AD, StartSoloDialog_CTR, StartFgSessionDialog, \
		StartFsdDialog, StartStudentSessionDialog, StartTeacherSessionDialog, StartPlaybackDialog
from gui.dialogs.statistics import StatisticsDialog
from gui.graphics.flightStrips import FlightStripItem
from gui.misc import IconFile, signals, selection, RadioKeyEventFilter
from gui.panels.cpdlcPanels import CpdlcPanel
from gui.panels.radarScope import ScopeFrame
from gui.panels.radios import AtisDialog
from gui.panels.selectionInfo import SelectionInfoToolbarWidget
from gui.panels.stripPanels import LooseStripPanel, StripRackPanel
from gui.panels.teachingConsole import TeachingConsole
from gui.panels.unitConv import UnitConversionWindow
from gui.widgets.adWidgets import WorldAirportNavigator
from gui.widgets.basicWidgets import flash_widget, Ticker, RdfStatusBarLabel, DoubleClickLabel
from gui.widgets.miscWidgets import AlarmClockInfoWidget, AlarmClocksPanel, RecordingIconWidget, QuickReference

from session.config import settings, radar_save_state_keyword, loosebay_save_state_keyword, stripracks_save_state_keyword
from session.env import env
from session.manager import SessionManager, SessionType, student_callsign, teacher_callsign
from session.managers.flightGearMP import FlightGearSessionManager
from session.managers.fsdMP import FsdSessionManager
from session.managers.teacher import TeacherSessionManager
from session.managers.student import StudentSessionManager
from session.managers.solo import SoloSessionManager_AD, SoloSessionManager_CTR
from session.managers.playback import PlaybackSessionManager
from session.models.discardedStrips import ShelfFilterModel
from session.models.liveStrips import default_rack_name


# ---------- Constants ----------

stylesheet_file = 'CONFIG/main-stylesheet.qss'
dock_layout_file = 'CONFIG/dock-layout.bin'

subsecond_tick_interval = 300 # ms
subminute_tick_interval = 10 * 1000 # ms
status_bar_message_timeout = 5000 # ms
session_start_temp_lock_duration = 5000 # ms
forward_time_skip = timedelta(seconds=10)
suggested_alarm_clock_timeout = 2 # minutes

dock_flash_stylesheet = 'QDockWidget::title { background: yellow }'

OSM_zoom_level = 7
OSM_base_URL_fmt = 'http://www.openstreetmap.org/#map=%d/%f/%f'

airport_gateway_URL = 'http://gateway.x-plane.com/airports/page'
lenny64_newEvent_URL = 'http://flightgear-atc.alwaysdata.net/new_event.php'
video_tutorial_URL = 'http://www.youtube.com/playlist?list=PL1EQKKHhDVJvvWpcX_BqeOIsmeW2A_8Yb'
FAQ_URL = 'http://wiki.flightgear.org/ATC-pie_FAQ'

# -------------------------------

user_panels_save_state_kwd = {
	radar_save_state_keyword: ScopeFrame,
	loosebay_save_state_keyword: LooseStripPanel,
	stripracks_save_state_keyword: StripRackPanel
}

def stateSaveKwd(panel):
	return next(kwd for kwd, t in user_panels_save_state_kwd.items() if isinstance(panel, t))


def mk_OSM_URL(coords):
	return OSM_base_URL_fmt % (OSM_zoom_level, coords.lat, coords.lon)


def setDockAndActionIcon(icon_file, action, dock):
	icon = QIcon(icon_file)
	action.setIcon(icon)
	dock.setWindowIcon(icon)
	
def raise_dock(dock):
	dock.show()
	dock.raise_()
	dock.widget().setFocus()
	flash_widget(dock, dock_flash_stylesheet)

def open_raise_window(window):
	window.show()
	window.raise_()



class MainWindow(QMainWindow, Ui_mainWindow):
	def __init__(self, launcher, parent=None):
		QMainWindow.__init__(self, parent)
		self.setupUi(self)
		self.playbackSession_system_action.setText(self.playbackSession_system_action.text() + ' (experimental)') # TODO remove
		self.installEventFilter(RadioKeyEventFilter(self))
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.launcher = launcher
		settings.controlled_tower_viewer = FlightGearTowerViewer(self)
		settings.session_manager = SessionManager(self, None) # Dummy manager
		settings.session_recorder = SessionRecorder()
		self.updateWindowTitle()
		self.user_panels = []
		self.session_start_temp_lock_timer = QTimer(self)
		self.session_start_temp_lock_timer.setSingleShot(True)
		self.session_start_temp_lock_timer.timeout.connect(self.releaseSessionStartTempLock)
		
		## Restore saved dock layout
		try:
			with open(dock_layout_file, 'rb') as f: # Restore saved dock arrangement
				self.restoreState(f.read())
		except FileNotFoundError: # Fall back on default dock arrangement
			# left docks, top zone: contact details (hidden), notepads (hidden), TWR ctrl (hidden), navigator, FPLs, weather (on top)
			self.tabifyDockWidget(self.selection_info_dock, self.notepads_dock)
			self.tabifyDockWidget(self.selection_info_dock, self.towerView_dock)
			self.tabifyDockWidget(self.selection_info_dock, self.navigator_dock)
			self.tabifyDockWidget(self.selection_info_dock, self.FPL_dock)
			self.tabifyDockWidget(self.selection_info_dock, self.weather_dock)
			self.selection_info_dock.hide()
			self.notepads_dock.hide()
			self.towerView_dock.hide()
			# left docks, bottom zone: instructions (hidden), radios (hidden), notifications (on top)
			self.tabifyDockWidget(self.instructions_dock, self.radio_dock)
			self.tabifyDockWidget(self.instructions_dock, self.notification_dock)
			self.instructions_dock.hide()
			self.radio_dock.hide()
			# right docks: RWY boxes (hidden), strips, ATC coord.
			self.rwyBoxes_dock.hide()
			# bottom docks (all hidden): text radio, playback control, ATC text chat (separate)
			self.tabifyDockWidget(self.textRadio_dock, self.playbackCtrl_dock)
			self.textRadio_dock.hide()
			self.playbackCtrl_dock.hide()
			self.atcTextChat_dock.hide()
			# toolbars, in order: general, strip/FPL actions (hidden), contact info, radar assistance (hidden), docks (right-most)
			self.insertToolBar(self.docks_toolbar, self.general_toolbar) # = "insert before"
			self.insertToolBar(self.docks_toolbar, self.stripFplActions_toolbar)
			self.insertToolBar(self.docks_toolbar, self.selectionInfo_toolbar)
			self.radarAssistance_toolbar.hide()
			self.stripFplActions_toolbar.hide()
			self.insertToolBar(self.docks_toolbar, self.radarAssistance_toolbar)
		
		## Permanent tool/status bar widgets
		self.selectionInfo_toolbarWidget = SelectionInfoToolbarWidget(self)
		self.selectionInfo_toolbar.addWidget(self.selectionInfo_toolbarWidget)
		self.METAR_statusBarLabel = DoubleClickLabel(self)
		self.PTT_statusBarLabel = QLabel()
		self.PTT_statusBarLabel.setToolTip('Keyboard PTT')
		self.RDF_statusBarLabel = RdfStatusBarLabel(self)
		self.wind_statusBarLabel = DoubleClickLabel(self)
		self.QNH_statusBarLabel = DoubleClickLabel(self)
		self.QNH_statusBarLabel.setToolTip('hPa / inHg')
		self.alarmClock_statusBarWidget = AlarmClockInfoWidget(self)
		self.recordingIcon_statusBarLabel = RecordingIconWidget(self)
		self.clock_statusBarLabel = QLabel()
		self.statusbar.addWidget(self.METAR_statusBarLabel)
		self.statusbar.addPermanentWidget(self.PTT_statusBarLabel)
		self.statusbar.addPermanentWidget(self.RDF_statusBarLabel)
		self.statusbar.addPermanentWidget(self.wind_statusBarLabel)
		self.statusbar.addPermanentWidget(self.QNH_statusBarLabel)
		self.statusbar.addPermanentWidget(self.alarmClock_statusBarWidget)
		self.statusbar.addPermanentWidget(self.recordingIcon_statusBarLabel)
		self.statusbar.addPermanentWidget(self.clock_statusBarLabel)

		## Memory-persistent windows and dialogs
		self.recall_cheat_dialog = DiscardedStripsDialog(self, ShelfFilterModel(self, env.discarded_strips, False), 'Sent and deleted strips')
		self.shelf_dialog = DiscardedStripsDialog(self, ShelfFilterModel(self, env.discarded_strips, True), 'Strip shelf')
		self.location_info_dialog = LocationInfoDialog(self)
		self.statistics_dialog = StatisticsDialog(self)
		self.about_dialog = AboutDialog(self)
		self.CPDLC_panel = CpdlcPanel()
		self.teaching_console = TeachingConsole()
		self.unit_converter = UnitConversionWindow(parent=self)
		self.world_airport_navigator = WorldAirportNavigator(parent=self)
		self.quick_reference = QuickReference(parent=self)
		self.DEP_clearance_view = DepartureClearanceViewDialog(parent=self)
		self.radar_measurement_log = RadarMeasurementLog(parent=self, visibilityAction=self.measuringLogsCoordinates_system_action)
		self.alarm_clocks_window = AlarmClocksPanel(parent=self)
		
		# Populate menus (toolbar visibility, central panel selection)
		self.general_viewToolbar_action = self.general_toolbar.toggleViewAction()
		self.stripActions_viewToolbar_action = self.stripFplActions_toolbar.toggleViewAction()
		self.docks_viewToolbar_action = self.docks_toolbar.toggleViewAction()
		self.selectionInfo_viewToolbar_action = self.selectionInfo_toolbar.toggleViewAction()
		self.radarAssistance_viewToolbar_action = self.radarAssistance_toolbar.toggleViewAction()
		self.view_toolbars_menu.addAction(self.general_viewToolbar_action)
		self.view_toolbars_menu.addAction(self.stripActions_viewToolbar_action)
		self.view_toolbars_menu.addAction(self.docks_viewToolbar_action)
		self.view_toolbars_menu.addAction(self.selectionInfo_viewToolbar_action)
		self.view_toolbars_menu.addAction(self.radarAssistance_viewToolbar_action)

		self.centralPanelSelection_actionGroup = QActionGroup(self)
		self.centralPanel_selectNone_action = self.centralPanelSelection_actionGroup.addAction('None')
		self.centralPanel_selectNone_action.setCheckable(True)
		self.centralPanel_selectNone_action.setChecked(True)
		self.centralPanel_selectNone_action.triggered.connect(lambda: self.central_workspace.setCurrentPanel(None))
		self.view_centralPanel_menu.addAction(self.centralPanel_selectNone_action)
		self.centralPanel_selectCpdlcPanel_action = self._mkCentralPanelAction(self.CPDLC_panel, False)
		self.centralPanel_selectTeachingConsole_action = self._mkCentralPanelAction(self.teaching_console, False)
		
		# Add the actions not used in the main window, or only in removable toolbars
		for action in self.newStrip_action, self.newLinkedStrip_action, self.newFPL_action, self.newLinkedFPL_action, \
				self.genericTransfer_action, self.flagUnflagSelection_action, self.toggleMachNumbers_action, \
				self.timerQuickStart_action:
			self.addAction(action)
		
		# Populate icons
		self.timerQuickStart_action.setIcon(QIcon(IconFile.pixmap_alarmClock))
		self.alarmClocks_view_action.setIcon(QIcon(IconFile.pixmap_alarmClock))
		self.newStrip_action.setIcon(QIcon(IconFile.action_newStrip))
		self.newLinkedStrip_action.setIcon(QIcon(IconFile.action_newLinkedStrip))
		self.newFPL_action.setIcon(QIcon(IconFile.action_newFPL))
		self.newLinkedFPL_action.setIcon(QIcon(IconFile.action_newLinkedFPL))
		self.teachingConsole_view_action.setIcon(QIcon(IconFile.panel_teaching))
		self.unitConversionTool_view_action.setIcon(QIcon(IconFile.panel_unitConv))
		self.worldAirportNavigator_view_action.setIcon(QIcon(IconFile.panel_airportList))
		self.locationInfo_view_action.setIcon(QIcon(IconFile.panel_locInfo))
		self.atis_view_action.setIcon(QIcon(IconFile.panel_atis))
		self.generalSettings_options_action.setIcon(QIcon(IconFile.action_generalSettings))
		self.soloSessionSettings_system_action.setIcon(QIcon(IconFile.action_sessionSettings))
		self.locationSettings_system_action.setIcon(QIcon(IconFile.action_locationSettings))
		self.adSurfacesUse_options_action.setIcon(QIcon(IconFile.action_adSfcUse))
		self.newLooseStripBay_view_action.setIcon(QIcon(IconFile.action_newLooseStripBay))
		self.newRadarScreen_view_action.setIcon(QIcon(IconFile.action_newRadarScreen))
		self.newStripRackPanel_view_action.setIcon(QIcon(IconFile.action_newRackPanel))
		self.cpdlcPanel_view_action.setIcon(QIcon(IconFile.panel_CPDLC))
		self.primaryRadar_options_action.setIcon(QIcon(IconFile.option_primaryRadar))
		self.approachSpacingHints_options_action.setIcon(QIcon(IconFile.option_approachSpacingHints))
		self.runwayOccupationWarnings_options_action.setIcon(QIcon(IconFile.option_runwayOccupationMonitor))
		self.routeConflictWarnings_options_action.setIcon(QIcon(IconFile.option_routeConflictWarnings))
		self.trafficIdentification_options_action.setIcon(QIcon(IconFile.option_identificationAssistant))
		self.recordSessionForPlayback_system_action.setIcon(QIcon(IconFile.option_recordSession))
		
		setDockAndActionIcon(IconFile.panel_ATCs, self.atcCoordination_dockView_action, self.atcCoordination_dock)
		setDockAndActionIcon(IconFile.panel_atcChat, self.atcTextChat_dockView_action, self.atcTextChat_dock)
		setDockAndActionIcon(IconFile.panel_FPLs, self.FPLs_dockView_action, self.FPL_dock)
		setDockAndActionIcon(IconFile.panel_instructions, self.instructions_dockView_action, self.instructions_dock)
		setDockAndActionIcon(IconFile.panel_navigator, self.navpoints_dockView_action, self.navigator_dock)
		setDockAndActionIcon(IconFile.panel_notepads, self.notepads_dockView_action, self.notepads_dock)
		setDockAndActionIcon(IconFile.panel_notifications, self.notificationArea_dockView_action, self.notification_dock)
		setDockAndActionIcon(IconFile.panel_playbackCtrl, self.playbackControl_dockView_action, self.playbackCtrl_dock)
		setDockAndActionIcon(IconFile.panel_radios, self.fgcom_dockView_action, self.radio_dock)
		setDockAndActionIcon(IconFile.panel_runwayBox, self.runwayBoxes_dockView_action, self.rwyBoxes_dock)
		setDockAndActionIcon(IconFile.panel_selInfo, self.radarContactDetails_dockView_action, self.selection_info_dock)
		setDockAndActionIcon(IconFile.panel_racks, self.strips_dockView_action, self.strip_dock)
		setDockAndActionIcon(IconFile.panel_txtRadio, self.textRadio_dockView_action, self.textRadio_dock)
		setDockAndActionIcon(IconFile.panel_twrView, self.towerView_dockView_action, self.towerView_dock)
		setDockAndActionIcon(IconFile.panel_weather, self.weather_dockView_action, self.weather_dock)
		
		# TICKED STATES set before connections
		self.muteNotifications_options_action.setChecked(settings.mute_notifications)
		self.primaryRadar_options_action.setChecked(settings.primary_radar_active)
		self.routeConflictWarnings_options_action.setChecked(settings.route_conflict_warnings)
		self.trafficIdentification_options_action.setChecked(settings.traffic_identification_assistant)
		self.runwayOccupationWarnings_options_action.setChecked(settings.monitor_runway_occupation)
		self.approachSpacingHints_options_action.setChecked(settings.APP_spacing_hints)
		
		# action CONNECTIONS
		# non-menu actions
		self.timerQuickStart_action.triggered.connect(self.quickStartTimer)
		self.METAR_statusBarLabel.doubleClicked.connect(self.weather_dockView_action.trigger)
		self.wind_statusBarLabel.doubleClicked.connect(self.weather_dockView_action.trigger)
		self.QNH_statusBarLabel.doubleClicked.connect(self.weather_dockView_action.trigger)
		self.alarmClock_statusBarWidget.doubleClicked.connect(self.alarmClocks_view_action.trigger)
		self.recordingIcon_statusBarLabel.doubleClicked.connect(self.recordSessionForPlayback_system_action.trigger)
		self.newStrip_action.triggered.connect(lambda: new_strip_dialog(self, default_rack_name, linkToSelection=False))
		self.newLinkedStrip_action.triggered.connect(lambda: new_strip_dialog(self, default_rack_name, linkToSelection=True))
		self.newFPL_action.triggered.connect(lambda: self.FPL_panel.createLocalFPL(link=None))
		self.newLinkedFPL_action.triggered.connect(lambda: self.FPL_panel.createLocalFPL(link=selection.strip))
		self.flagUnflagSelection_action.triggered.connect(self.flagUnflagSelection)
		self.toggleMachNumbers_action.triggered.connect(signals.toggleMachNumbers.emit)
		self.genericTransfer_action.triggered.connect(lambda: generic_transfer_action(self))
		# system menu
		self.soloSession_system_action.triggered.connect(lambda: self.startStopSession(self.start_solo))
		self.flightGearSession_system_action.triggered.connect(lambda: self.startStopSession(self.start_FlightGearSession))
		self.fsdConnection_system_action.triggered.connect(lambda: self.startStopSession(self.start_FSD))
		self.teacherSession_system_action.triggered.connect(lambda: self.startStopSession(self.start_teaching))
		self.studentSession_system_action.triggered.connect(lambda: self.startStopSession(self.start_learning))
		self.playbackSession_system_action.triggered.connect(lambda: self.startStopSession(self.start_playback))
		self.towerView_system_action.triggered.connect(self.toggleTowerWindow)
		self.fgViewersSettings_system_action.triggered.connect(self.configureFgViewers)
		self.locationViewpointsSettings_system_action.triggered.connect(self.configureViewpoints)
		self.reloadBgImages_system_action.triggered.connect(self.reloadBackgroundImages)
		self.reloadFgAcftModels_system_action.triggered.connect(self.reloadFgAcftModels)
		self.reloadRoutePresetsAndEntryExitPoints_system_action.triggered.connect(self.reloadRoutePresetsAndEntryExitPoints)
		self.reloadStylesheetAndColours_system_action.triggered.connect(self.reloadStylesheetAndColours)
		self.airportGateway_system_action.triggered.connect(lambda: self.goToURL(airport_gateway_URL))
		self.openStreetMap_system_action.triggered.connect(lambda: self.goToURL(mk_OSM_URL(env.radarPos())))
		self.announceFgSession_system_action.triggered.connect(lambda: self.goToURL(lenny64_newEvent_URL))
		self.measuringLogsCoordinates_system_action.toggled.connect(self.switchMeasuringCoordsLog)
		self.recordSessionForPlayback_system_action.toggled.connect(self.switchRecordSession)
		self.extractSectorFile_system_action.triggered.connect(self.extractSectorFile)
		self.repositionBgImages_system_action.triggered.connect(self.repositionRadarBgImages)
		self.phoneSquelchEdit_system_action.toggled.connect(self.atcCoordination_panel.phoneSquelch_widget.setVisible)
		self.locationSettings_system_action.triggered.connect(self.openLocationSettings)
		self.soloSessionSettings_system_action.triggered.connect(self.openSoloRuntimeSettings)
		self.changeLocation_system_action.triggered.connect(self.changeLocation)
		self.quit_system_action.triggered.connect(self.close)
		# view menu
		self.recallWindowState_view_action.triggered.connect(self.recallWindowState)
		self.saveDockLayout_view_action.triggered.connect(self.saveDockLayout)
		self.atcCoordination_dockView_action.triggered.connect(lambda: raise_dock(self.atcCoordination_dock))
		self.atcTextChat_dockView_action.triggered.connect(lambda: raise_dock(self.atcTextChat_dock))
		self.FPLs_dockView_action.triggered.connect(lambda: raise_dock(self.FPL_dock))
		self.instructions_dockView_action.triggered.connect(lambda: raise_dock(self.instructions_dock))
		self.navpoints_dockView_action.triggered.connect(lambda: raise_dock(self.navigator_dock))
		self.notepads_dockView_action.triggered.connect(lambda: raise_dock(self.notepads_dock))
		self.notificationArea_dockView_action.triggered.connect(lambda: raise_dock(self.notification_dock))
		self.playbackControl_dockView_action.triggered.connect(lambda: raise_dock(self.playbackCtrl_dock))
		self.fgcom_dockView_action.triggered.connect(lambda: raise_dock(self.radio_dock))
		self.runwayBoxes_dockView_action.triggered.connect(lambda: raise_dock(self.rwyBoxes_dock))
		self.radarContactDetails_dockView_action.triggered.connect(lambda: raise_dock(self.selection_info_dock))
		self.strips_dockView_action.triggered.connect(lambda: raise_dock(self.strip_dock))
		self.textRadio_dockView_action.triggered.connect(lambda: raise_dock(self.textRadio_dock))
		self.towerView_dockView_action.triggered.connect(lambda: raise_dock(self.towerView_dock))
		self.weather_dockView_action.triggered.connect(lambda: raise_dock(self.weather_dock))
		self.closeNonDockableWindows_view_action.triggered.connect(signals.closeNonDockableWindows.emit)
		self.newLooseStripBay_view_action.triggered.connect(lambda: self.newUserPanel(LooseStripPanel(), 'New loose strip panel'))
		self.newRadarScreen_view_action.triggered.connect(lambda: self.newUserPanel(ScopeFrame(), 'New radar panel'))
		self.newStripRackPanel_view_action.triggered.connect(lambda: self.newUserPanel(StripRackPanel(), 'New strip rack panel'))
		self.cpdlcPanel_view_action.triggered.connect(lambda: self.showRaisePanel(self.CPDLC_panel))
		self.teachingConsole_view_action.triggered.connect(lambda: self.showRaisePanel(self.teaching_console))
		self.selectedStrip_view_action.triggered.connect(self.openSelectedStrip)
		self.latestCpdlcDialogue_action.triggered.connect(self.showLastCpdlcDialogueForSelection)
		self.depClearance_view_action.triggered.connect(self.showDepClearanceForSelection)
		self.alarmClocks_view_action.triggered.connect(lambda: open_raise_window(self.alarm_clocks_window))
		self.atis_view_action.triggered.connect(self.openAtisDialog)
		self.locationInfo_view_action.triggered.connect(self.location_info_dialog.exec)
		self.statistics_view_action.triggered.connect(self.statistics_dialog.exec)
		self.unitConversionTool_view_action.triggered.connect(lambda: open_raise_window(self.unit_converter))
		self.worldAirportNavigator_view_action.triggered.connect(lambda: open_raise_window(self.world_airport_navigator))
		# options menu
		self.muteNotifications_options_action.toggled.connect(self.muteNotificationSounds)
		self.primaryRadar_options_action.toggled.connect(self.switchPrimaryRadar)
		self.routeConflictWarnings_options_action.toggled.connect(self.switchConflictWarnings)
		self.trafficIdentification_options_action.toggled.connect(self.switchTrafficIdentification)
		self.runwayOccupationWarnings_options_action.toggled.connect(self.switchRwyOccupationIndications)
		self.approachSpacingHints_options_action.toggled.connect(self.switchApproachSpacingHints)
		self.adSurfacesUse_options_action.triggered.connect(self.configureAdSfcUse)
		self.generalSettings_options_action.triggered.connect(self.openGeneralSettings)
		# cheat menu
		self.pauseSimulation_cheat_action.toggled.connect(self.pauseResumeSession)
		self.skipTimeForward_cheat_action.triggered.connect(self.skipTimeForwardOnce)
		self.spawnAircraft_cheat_action.triggered.connect(self.spawnAircraft)
		self.killSelectedAircraft_cheat_action.triggered.connect(self.killSelectedAircraft)
		self.popUpMsgOnRejectedInstr_cheat_action.toggled.connect(self.setRejectedInstrPopUp)
		self.showRecognisedVoiceStrings_cheat_action.toggled.connect(self.setShowRecognisedVoiceStrings)
		self.ensureClearWeather_cheat_action.toggled.connect(self.ensureClearWeather)
		self.ensureDayLight_cheat_action.triggered.connect(settings.controlled_tower_viewer.ensureDayLight)
		self.changeTowerHeight_cheat_action.triggered.connect(self.changeTowerHeight)
		self.radarCheatMode_cheat_action.toggled.connect(self.setRadarCheatMode)
		self.showAcftCheatToggles_cheat_action.toggled.connect(self.showAcftCheatToggles)
		self.recallDiscardedStrip_cheat_action.triggered.connect(self.recall_cheat_dialog.exec)
		# help menu
		self.quickReference_help_action.triggered.connect(lambda: open_raise_window(self.quick_reference))
		self.videoTutorial_help_action.triggered.connect(lambda: self.goToURL(video_tutorial_URL))
		self.FAQ_help_action.triggered.connect(lambda: self.goToURL(FAQ_URL))
		self.about_help_action.triggered.connect(self.about_dialog.exec)

		## More signal connections
		env.radar.lostContact.connect(self.aircraftHasDisappeared)
		env.strips.rwyBoxFreed.connect(lambda box, strip: env.airport_data.resetRwySepTimer(box, strip.lookup(FPL.WTC)))
		signals.openShelfRequest.connect(self.shelf_dialog.exec)
		signals.privateAtcChatRequest.connect(lambda: raise_dock(self.atcTextChat_dock))
		signals.weatherDockRaiseRequest.connect(lambda: raise_dock(self.weather_dock))
		signals.atisDialogRequest.connect(self.openAtisDialog)
		signals.stripRecall.connect(recover_strip)
		signals.statusBarMsg.connect(lambda msg: self.statusbar.showMessage(msg, status_bar_message_timeout))
		signals.sessionRecorderStarted.connect(self.recordingIcon_statusBarLabel.show)
		signals.sessionRecorderStopped.connect(self.recordingIcon_statusBarLabel.hide)
		signals.newWeather.connect(self.updateWeatherIfPrimary)
		signals.kbdPTT.connect(self.setKbdPttState)
		signals.sessionStarted.connect(self.sessionHasStarted)
		signals.sessionEnded.connect(self.sessionHasEnded)
		signals.sessionPaused.connect(self.sessionHasPaused)
		signals.sessionResumed.connect(self.sessionHasResumed)
		signals.fastClockTick.connect(self.updateClockDisp)
		signals.fastClockTick.connect(env.cpdlc.checkForTimeOuts)
		signals.fastClockTick.connect(self.updateRdfInfo)
		signals.slowClockTick.connect(self.checkForClockTriggers)
		signals.towerViewToggled.connect(self.towerView_system_action.setChecked)
		signals.towerViewToggled.connect(self.cheat_towerView_menu.setEnabled)
		signals.towerViewToggled.connect(self.towerView_dock.setVisible)
		signals.stripInfoChanged.connect(env.strips.refreshViews)
		signals.stripEditRequest.connect(lambda strip: edit_strip(self, strip))
		signals.depClearanceDispRequest.connect(self.depClearanceDispRequested)
		signals.selectionChanged.connect(self.updateStripFplActions)
		signals.receiveStrip.connect(receive_strip)
		signals.cpdlcTransferRequest.connect(receive_CPDLC_transfer_request)
		signals.cpdlcTransferResponse.connect(receive_CPDLC_transfer_response)
		signals.handoverFailure.connect(self.recoverFailedHandover)
		signals.rackVisibilityLost.connect(self.collectClosedRacks)
		signals.locationSettingsChanged.connect(self.updateAfterLocationSettingsChanged)
		signals.mainStylesheetApplied.connect(lambda: FlightStripItem.setSizeFromTextFont(self.strip_panel.stripRacks_view.font()))
		
		## MISC GUI setup
		self.strip_panel.setViewRacks([default_rack_name]) # will be moved out if a rack panel's saved "visible_racks" claims it [*1]
		self.strip_panel.restoreState(settings.saved_strip_dock_state) # [*1]
		for ptype, ptitle, pstate in settings.saved_user_panels_states:
			panel = user_panels_save_state_kwd[ptype]()
			panel.setWindowTitle(self._unambiguousPanelTitle(ptitle))
			panel.restoreState(pstate) # [*1]
			panel.show()
			self._mkCentralPanelAction(panel, True) # adds an entry to the central panel menu
		try:
			self.centralPanelSelection_actionGroup.actions()[settings.saved_selected_docked_panel].trigger()
		except IndexError:
			pass
		self.rwyBox_panel.setVerticalLayout(settings.vertical_runway_box_layout)
		self.recordSessionForPlayback_system_action.setEnabled(False)
		self.recordingIcon_statusBarLabel.setVisible(False)
		self.atis_view_action.setEnabled(False)
		self.cheat_towerView_menu.setEnabled(False)
		self.cheat_solo_menu.setEnabled(False)
		self.updateClockDisp()
		self.updateWeatherIfPrimary(settings.primary_METAR_station, None)
		self.updateStripFplActions()
		self.RDF_statusBarLabel.setVisible(settings.radio_direction_finding)
		self.PTT_statusBarLabel.setVisible(False)
		
		self.subsecond_ticker = Ticker(self, signals.fastClockTick.emit)
		self.subminute_ticker = Ticker(self, signals.slowClockTick.emit)
		self.subsecond_ticker.startTicking(subsecond_tick_interval)
		self.subminute_ticker.startTicking(subminute_tick_interval)
		# Disable some base airport stuff if doing CTR
		if env.airport_data is None:
			self.towerView_system_action.setEnabled(False)
			self.fgViewersSettings_system_action.setEnabled(False)
			self.locationViewpointsSettings_system_action.setEnabled(False)
			self.adSurfacesUse_options_action.setEnabled(False)
			self.runwayOccupationWarnings_options_action.setEnabled(False)
		# Finish
		if speech_recognition_available:
			prepare_SR_language_files()
		self.applyStylesheet() # do this last to force strips and radar tags to resize appropriately on emitted signal

	# def showEvent(self, event):
	# 	QMainWindow.showEvent(self, event)
	# 	if settings.first_time_at_location:
	# 		dialog = LocationSettingsDialog(self)
	# 		dialog.exec()
	# 		if dialog.result() > 0:
	# 			if settings.SSR_mode_capability == '0':
	# 				self._mkCentralPanelAction(LooseStripPanel(), True).trigger() # unambiguous only panel title
	# 			else:
	# 				self._mkCentralPanelAction(ScopeFrame(), True).trigger() # unambiguous only panel title

	def _userPanelClosing(self, panel, associated_action):
		self.centralPanelSelection_actionGroup.removeAction(associated_action)
		self.view_centralPanel_menu.removeAction(associated_action)
		self.user_panels = [p for p in self.user_panels if p is not panel]

	def _mkCentralPanelAction(self, panel, is_user_panel):
		action = self.centralPanelSelection_actionGroup.addAction(panel.windowIcon(), panel.windowTitle())
		action.setCheckable(True)
		action.triggered.connect(lambda ignore_checked, p=panel: self.central_workspace.setCurrentPanel(p))
		self.view_centralPanel_menu.addAction(action)
		if is_user_panel:
			self.user_panels.append(panel)
			panel.closing.connect(lambda p=panel, a=action: self._userPanelClosing(p, a))
			panel.titleChanged.connect(lambda title, a=action: a.setText(title))
		return action

	def _unambiguousPanelTitle(self, base_name): # unambiguous for picking which one saved as docked
		new_title = base_name
		i = 2
		while new_title in [panel.windowTitle() for panel in self.user_panels + [self.CPDLC_panel, self.teaching_console]]:
			new_title = '%s (%i)' % (base_name, i)
			i += 1
		return new_title

	def quickStartTimer(self):
		timeout, ok = QInputDialog.getInt(self, 'New timer', 'Timeout in minutes:', value=suggested_alarm_clock_timeout, min=1, max=240)
		if ok:
			env.alarm_clocks.startNewTimer(timedelta(minutes=timeout))

	def flagUnflagSelection(self):
		if selection.acft is not None:
			selection.acft.flagged = not selection.acft.flagged
			signals.selectionChanged.emit()
	
	def goToURL(self, url):
		if not QDesktopServices.openUrl(QUrl(url)):
			QMessageBox.critical(self, 'Error opening web browser', 'Could not invoke desktop web browser.\nGo to: %s' % url)
	
	def applyStylesheet(self):
		try:
			self.setStyleSheet(open(stylesheet_file).read()) # NOTE apparently, we cannot catch syntax errors in stylesheet
		except FileNotFoundError:
			self.setStyleSheet('')
		signals.mainStylesheetApplied.emit()

	def recoverFailedHandover(self, strip, msg):
		recover_strip(strip)
		QMessageBox.critical(self, 'Handover failed', msg)
	
	def updateAfterLocationSettingsChanged(self):
		env.rdf.resetSignals()
		self.RDF_statusBarLabel.setVisible(settings.radio_direction_finding)
		settings.session_manager.weatherLookUpRequest(settings.primary_METAR_station)

	
	# ---------------------     GUI auto-update functions     ---------------------- #
	
	def updateWindowTitle(self):
		title = 'ATC-pie - '
		if settings.session_manager.isRunning():
			if settings.session_manager.session_type == SessionType.SOLO:
				title += 'Solo'
			elif settings.session_manager.session_type == SessionType.PLAYBACK:
				title += 'Playback'
			else:
				title += settings.my_callsign
			title += ' @ '
		title += 'Control centre' if env.airport_data is None else env.airport_data.navpoint.long_name
		title += ' (%s)' % settings.location_code
		self.setWindowTitle(title)
	
	def updateClockDisp(self):
		if settings.session_manager.isRunning():
			txt = 'UTC ' + timestr(settings.session_manager.clockTime(), seconds=True)
			if settings.session_paused:
				txt += ' (paused)'
			self.clock_statusBarLabel.setText(txt)
		else:
			self.clock_statusBarLabel.setText('No session running')
	
	def checkForClockTriggers(self):
		if settings.session_manager.isRunning():
			strip_auto_print_check()
			if settings.record_ATIS_reminder is not None and settings.session_manager.clockTime() > settings.record_ATIS_reminder:
				settings.record_ATIS_reminder = None
				self.notification_panel.notifyTimeForAtis()
	
	def releaseSessionStartTempLock(self):
		settings.session_start_temp_lock = False
	
	def updateWeatherIfPrimary(self, station, weather): # NOTE weather may be None here
		if station == settings.primary_METAR_station:
			# Update status bar info
			self.METAR_statusBarLabel.setText(None if weather is None else weather.METAR())
			self.wind_statusBarLabel.setText('Wind ' + ('---' if weather is None else weather.readWind()))
			qnh = None if weather is None else weather.QNH() # NOTE qnh may still be None
			self.QNH_statusBarLabel.setText('QNH ' + ('---' if qnh is None else ('%d / %.2f' % (qnh, hPa2inHg * qnh))))
			# Update tower view
			if weather is not None and not settings.TWR_view_clear_weather_cheat:
				settings.controlled_tower_viewer.setWeather(weather)

	def setKbdPttState(self, toggle):
		settings.keyboard_PTT_pressed = toggle
		self.updatePTT()

	def updatePTT(self):
		self.PTT_statusBarLabel.setText('PTT' if settings.keyboard_PTT_pressed else ' - - - ')
	
	def updateRdfInfo(self):
		if settings.radio_direction_finding:
			self.RDF_statusBarLabel.updateDisp(env.rdf.strongestSignal())
	
	def updateSessionStartStopActions(self):
		running = settings.session_manager.isRunning()
		for gt, ma in {
					SessionType.SOLO: self.soloSession_system_action,
					SessionType.FLIGHTGEAR: self.flightGearSession_system_action,
					SessionType.FSD: self.fsdConnection_system_action,
					SessionType.STUDENT: self.studentSession_system_action,
					SessionType.TEACHER: self.teacherSession_system_action,
					SessionType.PLAYBACK: self.playbackSession_system_action
				}.items():
			if gt == settings.session_manager.session_type:
				ma.setEnabled(True)
				ma.setChecked(running)
			else:
				ma.setEnabled(not running)
				ma.setChecked(False)
	
	def updateStripFplActions(self):
		self.newLinkedStrip_action.setEnabled(selection.strip is None and not selection.acft == selection.fpl is None)
		self.newLinkedFPL_action.setEnabled(selection.strip is not None and selection.strip.linkedFPL() is None)
	
	def sessionHasStarted(self, session_type):
		self.updateWindowTitle()
		self.session_start_temp_lock_timer.start(session_start_temp_lock_duration)
		self.updateSessionStartStopActions()
		self.recordSessionForPlayback_system_action.setEnabled(session_type != SessionType.PLAYBACK and session_type != SessionType.TEACHER) # TODO teacher records student's session through wire?
		self.atis_view_action.setEnabled(env.airport_data is not None)
		self.cheat_solo_menu.setEnabled(session_type == SessionType.SOLO)
		if session_type == SessionType.STUDENT:
			for toggle_action in self.radarCheatMode_cheat_action, self.showAcftCheatToggles_cheat_action:
				toggle_action.setChecked(False)
				toggle_action.setEnabled(False)
		self.playbackCtrl_dock.setVisible(session_type == SessionType.PLAYBACK)
		self.updatePTT()
		self.PTT_statusBarLabel.setVisible(True)
		if session_type != SessionType.PLAYBACK:
			env.radar.startSweeping()
		
	def sessionHasEnded(self, session_type):
		env.alarm_clocks.clearAllTimers()
		settings.session_recorder.stopIfRecording()
		self.recordSessionForPlayback_system_action.setChecked(False)
		if session_type != SessionType.PLAYBACK:
			env.radar.stopSweeping()
		env.radar.resetContacts()
		env.strips.removeAllStrips()
		env.FPLs.clearFPLs()
		env.rdf.resetSignals()
		env.cpdlc.clearHistory()
		env.weather_information.clear()
		self.updateWindowTitle()
		self.updateSessionStartStopActions()
		self.recordSessionForPlayback_system_action.setEnabled(False)
		self.atis_view_action.setEnabled(False)
		self.pauseSimulation_cheat_action.setChecked(False)
		self.cheat_solo_menu.setEnabled(False)
		for toggle_action in self.radarCheatMode_cheat_action, self.showAcftCheatToggles_cheat_action:
			toggle_action.setEnabled(True)
		self.playbackCtrl_dock.setVisible(False)
		self.PTT_statusBarLabel.setVisible(False)
		selection.deselect()
		settings.last_recorded_ATIS = None
		settings.record_ATIS_reminder = None
		print('Session ended.')
	
	def sessionHasPaused(self):
		settings.session_paused = True
		if settings.session_manager.session_type != SessionType.PLAYBACK:
			env.radar.stopSweeping()
	
	def sessionHasResumed(self):
		settings.session_paused = False
		if settings.session_manager.session_type != SessionType.PLAYBACK:
			env.radar.startSweeping()
	
	def aircraftHasDisappeared(self, acft):
		strip = env.linkedStrip(acft)
		if strip is not None:
			signals.linkedContactLost.emit(strip, acft.coords())
			strip.linkAircraft(None)
		if selection.acft is acft:
			if strip is None:
				selection.deselect()
			else: # was linked when lost
				selection.selectStrip(strip)
	
	def collectClosedRacks(self, racks):
		self.strip_panel.setViewRacks(self.strip_panel.getViewRacks() + racks)

	
	
	# ---------------------     Session start functions     ---------------------- #

	def start_solo(self):
		dialog = StartSoloDialog_CTR(self) if env.airport_data is None else StartSoloDialog_AD(self)
		if dialog.exec():
			init_traffic = dialog.chosenInitialTrafficCount()
			settings.my_callsign = settings.location_code
			settings.session_manager = SoloSessionManager_CTR(self, init_traffic) if env.airport_data is None else SoloSessionManager_AD(self, init_traffic)
			settings.session_manager.start()
	
	def start_FlightGearSession(self):
		dialog = StartFgSessionDialog(self)
		if dialog.exec():
			settings.my_callsign = dialog.chosenCallsign()
			settings.session_manager = FlightGearSessionManager(self)
			settings.session_manager.start()
	
	def start_FSD(self):
		dialog = StartFsdDialog(self)
		if dialog.exec():
			settings.my_callsign = dialog.chosenCallsign()
			settings.session_manager = FsdSessionManager(self)
			settings.session_manager.start()

	def start_learning(self):
		if StartStudentSessionDialog(self).exec():
			settings.my_callsign = student_callsign
			settings.session_manager = StudentSessionManager(self)
			settings.session_manager.start()
	
	def start_teaching(self):
		if StartTeacherSessionDialog(self).exec():
			settings.my_callsign = teacher_callsign
			settings.session_manager = TeacherSessionManager(self)
			settings.session_manager.start()

	def start_playback(self):
		dialog = StartPlaybackDialog(self)
		dialog.browseForSourceData()
		if dialog.sourcedTimeline() and dialog.exec():
			settings.my_callsign = settings.location_code
			settings.session_manager = PlaybackSessionManager(self, dialog.sourcedTimeline())
			settings.session_manager.start()


	
	# ---------------------     GUI menu actions     ---------------------- #
	
	## SYSTEM MENU ##
	
	def startStopSession(self, start_func):
		settings.session_paused = False
		if settings.session_manager.isRunning(): # Stop session
			selection.deselect()
			settings.session_manager.stop()
		else: # Start session
			settings.session_start_temp_lock = True
			start_func()
		self.updateSessionStartStopActions()
		if not settings.session_manager.isRunning():
			settings.session_start_temp_lock = False

	def toggleTowerWindow(self):
		if self.towerView_system_action.isChecked():
			settings.controlled_tower_viewer.start()
		else:
			settings.controlled_tower_viewer.stop()

	def configureViewpoints(self):
		if ViewpointDialog(self).exec():
			settings.tower_height_cheat_offset = 0
			if settings.controlled_tower_viewer.isRunning():
				settings.controlled_tower_viewer.updateTowerPosition()
			signals.indicatePoint.emit(env.viewpoint()[0])

	def configureFgViewers(self):
		FgfsViewersDialog(self).exec()

	def reloadBackgroundImages(self):
		print('Reload: background images')
		settings.radar_background_images, settings.loose_strip_bay_backgrounds = read_bg_img(settings.location_code, env.navpoints)
		signals.backgroundImagesReloaded.emit()
		QMessageBox.information(self, 'Done reloading', 'Background images reloaded. Check for console error messages.')

	def reloadFgAcftModels(self):
		print('Reload: FG aircraft models')
		make_FGFS_models_liveries()
		QMessageBox.information(self, 'Done reloading', 'FG aircraft models reloaded. Check for console error messages.')
	
	def reloadStylesheetAndColours(self):
		print('Reload: stylesheet and colours')
		self.applyStylesheet() # emits its own signal
		settings.loadColourSettings()
		signals.colourConfigReloaded.emit()
		QMessageBox.information(self, 'Done reloading', 'Stylesheet and colour configuration reloaded. Check for console error messages.')
	
	def reloadRoutePresetsAndEntryExitPoints(self):
		print('Reload: route presets and AD entry/exit points')
		settings.route_presets = read_route_presets(stderr)
		world_routing_db.clearEntryExitPoints()
		import_entry_exit_data(stderr)
		QMessageBox.information(self, 'Done reloading', 'Route presets and entry/exit points reloaded. Check for console error messages.')
	
	def switchMeasuringCoordsLog(self, toggle):
		settings.measuring_tool_logs_coordinates = toggle
		self.radar_measurement_log.setVisible(toggle)

	def switchRecordSession(self, toggle):
		if toggle and not settings.session_recorder.isRecording():
			dialog = RecordPlaybackDialog(self)
			if dialog.exec():
				settings.session_recorder.startRecording(dialog.dataFileName())
		elif not toggle and settings.session_recorder.isRecording() and QMessageBox.question(self, 'Stop recording session', 'Stop recording session?') == QMessageBox.Yes:
			try:
				settings.session_recorder.stopIfRecording()
			except OSError as err:
				QMessageBox.critical(self, 'Stop recording session', 'Error while closing data file: %s' % err)
		self.recordSessionForPlayback_system_action.setChecked(settings.session_recorder.isRecording())
	
	def extractSectorFile(self):
		txt, ignore = QFileDialog.getOpenFileName(self, caption='Select sector file to extract from')
		if txt != '':
			extract_sector(txt, env.radarPos(), settings.map_range)
			QMessageBox.information(self, 'Done extracting',
				'Background drawings extracted.\nSee console for summary and files created in the "OUTPUT" directory.')
	
	def repositionRadarBgImages(self):
		w = self.central_workspace.currentPanel()
		if isinstance(w, ScopeFrame):
			w.positionVisibleBgImages()
		else:
			QMessageBox.critical(self, 'Image positioning error', 'This requires a radar panel docked in the central area.')

	def openLocationSettings(self):
		dialog = LocationSettingsDialog(self)
		dialog.exec()
		if dialog.result() > 0 and settings.session_manager.isRunning() and settings.session_manager.session_type != SessionType.PLAYBACK:
			env.radar.startSweeping() # in case sweep period has changed for example
	
	def openSoloRuntimeSettings(self):
		SoloRuntimeSettingsDialog(self).exec()
	
	def changeLocation(self):
		if QMessageBox.question(self, 'Change location', 'This will close the current session. Are you sure?') == QMessageBox.Yes:
			self.launcher.show()
			self.close()
	
	
	## VIEW MENU ##

	def recallWindowState(self):
		try:
			with open(dock_layout_file, 'rb') as f:
				self.restoreState(f.read())
		except FileNotFoundError:
			QMessageBox.critical(self, 'Recall dock layout', 'No saved layout to recall.')

	def saveDockLayout(self): # STYLE catch file write error
		with open(dock_layout_file, 'wb') as f:
			f.write(self.saveState())
		QMessageBox.information(self, 'Save dock layout', 'Current dock layout saved.')

	def newUserPanel(self, panel, prompt_title):
		panel.setWindowTitle(self._unambiguousPanelTitle(panel.windowTitle()))
		txt, ok = QInputDialog.getText(self, prompt_title, 'Panel title:', text=panel.windowTitle())
		if ok:
			if txt == '':
				txt = panel.defaultTitle()
			panel.setWindowTitle(self._unambiguousPanelTitle(txt))
			panel.show()
			action = self._mkCentralPanelAction(panel, True)
			if self.central_workspace.currentPanel() is None:
				action.trigger()
		else:
			panel.close()

	def showRaisePanel(self, panel):
		if self.central_workspace.currentPanel() is panel:
			self.raise_()
		elif panel.isVisible(): # panel is popped out
			panel.raise_()
		else: # panel is closed
			panel.show()
		flash_widget(panel, panel.flashStyleSheet())
		panel.setFocus()

	def depClearanceDispRequested(self, strip):
		self.DEP_clearance_view.updateView(strip)
		open_raise_window(self.DEP_clearance_view)

	def openSelectedStrip(self):
		if selection.strip is None:
			QMessageBox.critical(self, 'Strip detail sheet', 'No strip in selection.')
		else:
			signals.stripEditRequest.emit(selection.strip)

	def showLastCpdlcDialogueForSelection(self):
		cs = selection.selectedCallsign()
		if cs is None:
			QMessageBox.critical(self, 'Last CPDLC dialogue', 'No callsign in selection.')
		else:
			signals.cpdlcDialogueRequest.emit(cs, False)

	def showDepClearanceForSelection(self):
		if selection.strip is None:
			QMessageBox.critical(self, 'Departure clearance', 'No strip in selection.')
		elif selection.strip.lookup(departure_clearance_detail):
			signals.depClearanceDispRequest.emit(selection.strip)
		elif QMessageBox.question(self, 'Departure clearance', 'No departure clearance registered on strip.\nPrepare one now?') == QMessageBox.Yes:
			DepartureClearanceEditDialog(self, selection.strip).exec()

	def openAtisDialog(self):
		if settings.session_manager.isRunning() and env.airport_data is not None:
			AtisDialog(self).exec()
	
	
	## OPTIONS MENU ##
	
	def configureAdSfcUse(self):
		AdSfcUseDialog(self).exec()
	
	def muteNotificationSounds(self, toggle):
		settings.mute_notifications = toggle
	
	def switchPrimaryRadar(self, toggle):
		settings.primary_radar_active = toggle
		env.radar.instantSweep()
	
	def switchConflictWarnings(self, toggle):
		settings.route_conflict_warnings = toggle
		env.radar.checkPositionRouteConflicts()
	
	def switchTrafficIdentification(self, toggle):
		settings.traffic_identification_assistant = toggle
		if not toggle:
			for strip in env.strips.listAll():
				strip.writeDetail(soft_link_detail, None)
			signals.stripInfoChanged.emit() # to trigger refreshViews and global radar checks
	
	def switchRwyOccupationIndications(self, toggle):
		settings.monitor_runway_occupation = toggle
	
	def switchApproachSpacingHints(self, toggle):
		settings.APP_spacing_hints = toggle
		signals.stripInfoChanged.emit()
	
	def openGeneralSettings(self):
		GeneralSettingsDialog(self).exec()
	
	
	## CHEAT MENU ##
	
	def pauseResumeSession(self, toggle):
		if toggle:
			settings.session_manager.pause()
		else:
			settings.session_manager.resume()

	def skipTimeForwardOnce(self):
		if settings.session_manager.session_type in (SessionType.SOLO, SessionType.TEACHER, SessionType.PLAYBACK):
			settings.session_manager.skipTimeForward(forward_time_skip)
	
	def spawnAircraft(self):
		n, ok = QInputDialog.getInt(self, 'Spawn new aircraft', 'Try to spawn:', value=1, min=1, max=99)
		if ok:
			for i in range(n): # WARNING: session should be running
				settings.session_manager.spawnNewControlledAircraft()
	
	def killSelectedAircraft(self):
		to_kill = selection.acft
		if to_kill is None:
			QMessageBox.critical(self, 'Cheat error', 'No aircraft selected.')
		else:
			kill_aircraft(to_kill)
	
	def setRejectedInstrPopUp(self, toggle):
		settings.solo_erroneous_instruction_warning = toggle
	
	def ensureClearWeather(self, toggle):
		settings.TWR_view_clear_weather_cheat = toggle
		if toggle:
			weather = mkWeather(settings.location_code, settings.session_manager.clockTime()) # clear weather with location code as station
			settings.controlled_tower_viewer.setWeather(weather)
		else:
			weather = env.primaryWeather()
			if weather is not None:
				settings.controlled_tower_viewer.setWeather(weather)
	
	def setShowRecognisedVoiceStrings(self, toggle):
		settings.show_recognised_voice_strings = toggle
	
	def changeTowerHeight(self):
		current_height = env.viewpoint(asfc=True)[1] # applies current TWR height cheat
		if settings.selected_viewpoint < len(env.airport_data.viewpoints) + len(settings.custom_viewpoints):
			original_info = 'original value is %d' % (current_height - settings.tower_height_cheat_offset)
		else:
			original_info = 'no original value'
		new_height, ok = QInputDialog.getInt(self, 'Cheat tower height', 'New height in feet (%s):' % original_info, value=(int(current_height)), min=10, max=999)
		if ok:
			settings.tower_height_cheat_offset = new_height - (current_height - settings.tower_height_cheat_offset)
			settings.controlled_tower_viewer.updateTowerPosition()
	
	def setRadarCheatMode(self, toggle):
		settings.radar_cheat = toggle
		env.radar.instantSweep()
	
	def showAcftCheatToggles(self, toggle):
		self.selection_info_panel.showCheatToggle(toggle)
		self.selectionInfo_toolbarWidget.showCheatToggle(toggle)

	
	# -----------------     Internal GUI events      ------------------ #
	
	def closeEvent(self, event):
		env.radar.stopSweeping()
		if settings.session_manager.isRunning():
			settings.session_manager.stop()
		if settings.controlled_tower_viewer.isRunning():
			settings.controlled_tower_viewer.stop(wait=True)
		if speech_recognition_available:
			cleanup_SR_language_files()
		print('Closing main window.')
		settings.saved_strip_racks = env.strips.rackNames()
		settings.saved_strip_dock_state = self.strip_panel.stateSave()
		settings.saved_user_panels_states = [(stateSaveKwd(p), p.windowTitle(), p.stateSave()) for p in self.user_panels]
		settings.saved_selected_docked_panel = next((i for i, action in enumerate(self.centralPanelSelection_actionGroup.actions()) if action.isChecked()), 0)
		signals.mainWindowClosing.emit()
		signals.disconnect()
		settings.saveGlobalSettings()
		settings.saveLocationSettings(env.airport_data)
		env.resetEnv()
		settings.resetForNewWindow()
		EarthCoords.clearRadarPos()
		QMainWindow.closeEvent(self, event)
