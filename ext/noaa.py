
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

from PyQt5.QtCore import QThread

from sys import stderr
from socket import timeout
from urllib.parse import urlencode
from urllib.error import URLError
from xml.etree import ElementTree

from base.weather import Weather

from session.config import settings, open_URL


# ---------- Constants ----------

METAR_base_location = 'http://tgftp.nws.noaa.gov/data/observations/metar/stations'
decl_base_location = 'http://www.ngdc.noaa.gov/geomag-web/calculators/calculateDeclination'

# -------------------------------


def get_METAR(icao):
	try:
		response = open_URL('%s/%s.TXT' % (METAR_base_location, icao))
		return response.decode('ascii').split('\n')[1] + '='
	except URLError:
		print('Could not download METAR for station %s' % icao, file=stderr)
	except timeout:
		print('NOAA METAR request timed out.', file=stderr)


def get_declination(day, earth_location): # DEPRECATED: service no longer available, see https://sourceforge.net/p/atc-pie/tickets/25/
	try:
		q_items = {
			'startYear': day.year,
			'startMonth': day.month,
			'startDay': day.day,
			'resultFormat': 'xml',
			'lon1Hemisphere': 'EW'[earth_location.lon < 0],
			'lon1': abs(earth_location.lon),
			'lat1Hemisphere': 'NS'[earth_location.lat < 0],
			'lat1': abs(earth_location.lat),
			'browserRequest': 'false'
		}
		#DEBUG print('%s?%s' % (decl_base_location, urlencode(q_items)))
		response = open_URL('%s?%s' % (decl_base_location, urlencode(q_items)))
		xml = ElementTree.fromstring(response)
		if xml.tag == 'maggridresult':
			res_elt = xml.find('result')
			decl_elt = None if res_elt is None else res_elt.find('declination')
			decl_txt = None if decl_elt is None else decl_elt.text
			if decl_txt is None:
				print('Declination value missing in retrieved NOAA data.', file=stderr)
			else:
				return float(decl_txt)
	except URLError:
		print('Could not obtain declination from NOAA website.', file=stderr)
	except timeout:
		print('NOAA declination request timed out.', file=stderr)
	except (ElementTree.ParseError, ValueError):
		print('Parse/value error while reading NOAA data.', file=stderr)




class RealWeatherChecker(QThread):
	def __init__(self, parent, callback):
		QThread.__init__(self, parent)
		self.callback = callback
		self.look_up_queue = []
	
	def lookupStation(self, station):
		self.look_up_queue.append(station)
		self.start()
	
	def lookupSelectedStations(self):
		self.look_up_queue.append(settings.primary_METAR_station)
		self.look_up_queue.extend(settings.additional_METAR_stations)
		self.start()
		
	def run(self):
		while len(self.look_up_queue) > 0:
			metar = get_METAR(self.look_up_queue.pop(0))
			if metar is not None:
				self.callback(Weather(metar))
