
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

from PyQt5.QtWidgets import QWidget, QMessageBox
from ui.launcherDialog import Ui_launcher

from base.util import some
from base.coords import EarthCoords
from base.nav import world_navpoint_db, Navpoint, NavpointError
from base.radar import Radar
from base.radio import RadioDirectionFinder

from session.config import settings, default_map_range_AD, default_map_range_CTR, version_string, app_icon_path
from session.env import env
from session.models.alarmClocks import AlarmClocksModel
from session.models.atc import AtcTableModel
from session.models.dataLinks import CpdlcHistoryModel
from session.models.discardedStrips import DiscardedStripModel
from session.models.flightPlans import FlightPlanModel
from session.models.liveStrips import LiveStripModel

from ext.data import read_bg_img, get_ground_elevation_map, load_local_navpoint_speech_data
from ext.xplane import get_airport_data, import_ILS_capabilities

from gui.main import MainWindow


# ---------- Constants ----------

min_map_range = 20    # keep int
max_map_range = 1000  # keep int

point_spec_help_message = 'Valid point specifications:' \
	'\n - decimal coordinates, e.g. 35.8765,-90.567' \
	'\n - deg-min-sec coordinate format, e.g. 48°51\'24\'\'N,2°21\'03\'\'E' \
	'\n - named point, e.g. LANUX' \
	'\n\nAdditional operators:' \
	'\n - displacement: point>radial,distance' \
	'\n - "nearest to" disambiguation: point~refpoint' \
	'\n - type disambiguation: (TYPE)point' \
	'\n - ICAO region filter: point@region' \
	'\n\nFor more detail, refer to "point specification" in the quick reference.'

# -------------------------------



def valid_location_code(code):
	return code.isalnum()



class ATCpieLauncher(QWidget, Ui_launcher):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.mapRange_edit.setMinimum(min_map_range)
		self.mapRange_edit.setMaximum(max_map_range)
		self.logo_widget.setStyleSheet('border-image: url(%s) 0 0 0 0 stretch stretch' % app_icon_path)
		self.version_info.setText('Version: %s' % version_string)
		self.last_selected_ICAO = None
		self.updateCtrLocationsList()
		self.AD_radioButton.toggled.connect(self.switchMode)
		self.airport_select.recognised.connect(self.recogniseAD)
		self.airport_select.unrecognised.connect(self.unrecogniseAD)
		self.airport_select.airport_edit.returnPressed.connect(self.start_button.click)
		self.ctrLocationCode_edit.activated.connect(self.selectListedCtrLocation)
		self.ctrLocationCode_edit.lineEdit().textChanged.connect(self.updateStartButton)
		self.ctrRadarPos_edit.textChanged.connect(self.updateStartButton)
		self.ctrRadarPos_edit.returnPressed.connect(self.start_button.click)
		self.radarPosHelp_button.clicked.connect(self.showRadarPosHelp)
		self.start_button.clicked.connect(self.launchWithWindowInput)
		self.exit_button.clicked.connect(self.close)
		self.AD_radioButton.setChecked(True)
	
	def switchMode(self, ad_mode):
		self.mapRange_edit.setValue(default_map_range_AD if ad_mode else default_map_range_CTR)
		self.updateStartButton()
	
	def selectListedCtrLocation(self, index):
		try:
			self.ctrRadarPos_edit.setText(settings.CTR_radar_positions[self.ctrLocationCode_edit.itemText(index)])
		except KeyError:
			self.ctrRadarPos_edit.clear()
	
	def updateStartButton(self):
		if self.AD_radioButton.isChecked():
			self.start_button.setEnabled(self.last_selected_ICAO is not None)
		else:
			self.start_button.setEnabled(valid_location_code(self.ctrLocationCode_edit.currentText()) and self.ctrRadarPos_edit.text() != '')
	
	def updateCtrLocationsList(self):
		self.ctrLocationCode_edit.clear()
		self.ctrLocationCode_edit.addItems(sorted(settings.CTR_radar_positions.keys()))
		self.ctrLocationCode_edit.clearEditText()
	
	def recogniseAD(self, ad):
		self.last_selected_ICAO = ad.code
		self.selectedAD_info.setText(ad.long_name)
		self.start_button.setEnabled(True)
	
	def unrecogniseAD(self):
		self.last_selected_ICAO = None
		self.selectedAD_info.clear()
		self.start_button.setEnabled(False)
	
	def showRadarPosHelp(self):
		QMessageBox.information(self, 'Help on point specification', point_spec_help_message)
	
	def launchWithWindowInput(self):
		self.close()
		try:
			if self.AD_radioButton.isChecked(): # Airport mode
				self.launch(self.last_selected_ICAO, mapRange=self.mapRange_edit.value())
			else: # CTR mode
				self.launch(self.ctrLocationCode_edit.currentText(), ctrPos=self.ctrRadarPos_edit.text(), mapRange=self.mapRange_edit.value())
		except ValueError as err:
			QMessageBox.critical(self, 'Start-up error', str(err))
			self.show()
	
	def launch(self, location_code, mapRange=None, ctrPos=None):
		"""
		Raise ValueError with error message if launch fails.
		"""
		settings.map_range = some(mapRange, (default_map_range_AD if ctrPos is None else default_map_range_CTR))
		print('Setting up window %s in %s mode at location %s...'
				% (settings.windowID(), ('AD' if ctrPos is None else 'CTR'), location_code))
		try:
			if ctrPos is None: # Airport mode
				env.airport_data = get_airport_data(location_code)
				import_ILS_capabilities(env.airport_data)
				EarthCoords.setRadarPos(env.airport_data.navpoint.coordinates)
				try:
					settings.restoreLocationSettings_AD(env.airport_data)
					settings.first_time_at_location = False
				except FileNotFoundError:
					print('No airport settings file found; using defaults.')
					settings.primary_METAR_station = location_code # guess on first run; AD may have a weather station
				try:
					env.elevation_map = get_ground_elevation_map(location_code)
				except FileNotFoundError:
					print('No elevation map found; using field elevation.')
			else: # CTR mode
				if world_navpoint_db.findAll(code=location_code, types=[Navpoint.AD]):
					raise ValueError('CTR location code "%s" also listed as AD.' % location_code)
				EarthCoords.setRadarPos(world_navpoint_db.coordsFromPointSpec(ctrPos))
				try:
					if settings.CTR_radar_positions[location_code] != ctrPos:
						print('Overriding previously saved radar position: ' + ctrPos)
				except KeyError:
					print('Creating new CTR position.')
				settings.CTR_radar_positions[location_code] = ctrPos
				try:
					settings.restoreLocationSettings_CTR(location_code)
					settings.first_time_at_location = False
				except FileNotFoundError:
					print('No CTR settings file found; using defaults.')
				self.updateCtrLocationsList()
		except NavpointError as err:
			raise ValueError('Navpoint error: %s' % err)
		else:
			print('Radar position is: %s' % env.radarPos())
			env.navpoints = world_navpoint_db.subDB(lambda p: env.pointOnMap(p.coordinates))
			env.radar = Radar(self) # CAUTION: uses airport data; make sure it is already in env
			env.rdf = RadioDirectionFinder()
			env.cpdlc = CpdlcHistoryModel(self)
			env.strips = LiveStripModel(self)
			env.FPLs = FlightPlanModel(self)
			env.ATCs = AtcTableModel(self)
			env.discarded_strips = DiscardedStripModel(self)
			env.alarm_clocks = AlarmClocksModel(self)
			try:
				settings.restoreGlobalSettings()
			except FileNotFoundError:
				print('No global settings file found; using defaults.')
			settings.radar_background_images, settings.loose_strip_bay_backgrounds = read_bg_img(location_code, env.navpoints)
			load_local_navpoint_speech_data(location_code)
			session_window = MainWindow(self)
			session_window.show()
