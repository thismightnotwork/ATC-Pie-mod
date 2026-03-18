
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

from PyQt5.QtWidgets import QWidget, QInputDialog
from ui.weatherPanel import Ui_weatherPanel

from base.weather import hPa2inHg

from session.config import settings
from session.env import env

from gui.misc import signals
from gui.widgets.miscWidgets import WeatherDispWidget


# ---------- Constants ----------

# -------------------------------

class WeatherPanel(QWidget, Ui_weatherPanel):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		self.selectedStationWeather_groupBox.setTitle(settings.primary_METAR_station)
		for station in settings.additional_METAR_stations:
			self.additionalStations_tabs.addTab(WeatherDispWidget(), station)
		self.checkNow_button.clicked.connect(self.requestAllDisplayedWeather)
		self.addStation_button.clicked.connect(self.addWeatherStationTab)
		self.additionalStations_tabs.tabCloseRequested.connect(self.removeWeatherStationTab)
		signals.locationSettingsChanged.connect(self.updateLocalAnalysis) # in case transition alt. changed
		signals.locationSettingsChanged.connect(self.updatePrimaryStation) # in case prim. METAR station changed
		signals.newWeather.connect(self.updateWeatherDispFromNewInfo)
		signals.sessionStarted.connect(self.sessionStarts) # will reset all displays: all weathers are None
		signals.sessionEnded.connect(lambda: self.checkNow_button.setEnabled(False))
	
	def sessionStarts(self):
		self.selectedStation_widget.updateDisp(env.primaryWeather()) # normally resets display: weather is None
		self.updateLocalAnalysis()
		for i, ams in enumerate(settings.additional_METAR_stations): # normally resets displays: weathers are None
			self.additionalStations_tabs.widget(i).updateDisp(env.weatherInformation(ams))
		self.requestAllDisplayedWeather()
		self.checkNow_button.setEnabled(True)
	
	def updateWeatherDispFromNewInfo(self, station, weather):
		if station == settings.primary_METAR_station:
			self.selectedStation_widget.updateDisp(weather)
			self.updateLocalAnalysis()
		for i, ams in enumerate(settings.additional_METAR_stations):
			if ams == station:
				self.additionalStations_tabs.widget(i).updateDisp(weather)

	def updatePrimaryStation(self):
		self.selectedStationWeather_groupBox.setTitle(settings.primary_METAR_station)
		self.selectedStation_widget.updateDisp(env.weatherInformation(settings.primary_METAR_station))
		self.updateLocalAnalysis()

	def updateLocalAnalysis(self):
		qnh = env.QNH(noneSafe=False)
		if qnh is None:
			self.transitionLevel_info.setText('N/A')
			self.QFE_info.setText('N/A')
		else:
			self.transitionLevel_info.setText('FL%03d' % env.transitionLevel())
			if env.airport_data is None:
				self.QFE_info.setText('N/A')
			else:
				qfe = env.QFE(qnh)
				self.QFE_info.setText('%d hPa, %.2f inHg' % (qfe, hPa2inHg * qfe))
		w = env.primaryWeather()
		main_wind = None if w is None else w.mainWind()
		if env.airport_data is None or main_wind is None: # no runways or wind info
			self.rwyPref_info.setText('N/A')
		elif main_wind[0] is None: # no predominant heading
			self.rwyPref_info.setText('any')
		else:
			difflst = [(rwy.name, abs(env.RWD(rwy.orientation().opposite()))) for rwy in env.airport_data.directionalRunways()]
			preflst = sorted([pair for pair in difflst if pair[1] <= 90], key=(lambda pair: pair[1]))
			self.rwyPref_info.setText(', '.join(pair[0] for pair in preflst))
	
	def requestAllDisplayedWeather(self):
		settings.session_manager.weatherLookUpRequest(settings.primary_METAR_station)
		for station in settings.additional_METAR_stations:
			settings.session_manager.weatherLookUpRequest(station)
	
	def addWeatherStationTab(self):
		station, ok = QInputDialog.getText(self, 'Add a weather station', 'Station name:')
		if ok:
			station = station.upper()
			try:
				index = settings.additional_METAR_stations.index(station)
			except ValueError: # new tab needed
				widget = WeatherDispWidget()
				widget.updateDisp(env.weatherInformation(station))
				index = self.additionalStations_tabs.addTab(widget, station)
				settings.additional_METAR_stations.append(station)
				settings.session_manager.weatherLookUpRequest(station)
			self.additionalStations_tabs.setCurrentIndex(index)
	
	def removeWeatherStationTab(self, index):
		if 0 <= index < self.additionalStations_tabs.count():
			self.additionalStations_tabs.removeTab(index)
			del settings.additional_METAR_stations[index]
