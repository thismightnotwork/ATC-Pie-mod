
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

import string
import re
from random import random, randint, choice

from base.coords import EarthCoords
from base.db import acft_cat, acft_registration_formats, commercial_prob
from base.fpl import FPL
from base.nav import world_navpoint_db, NavpointError
from base.params import AltFlSpec, PressureAlt
from base.strip import rack_detail
from base.utc import timestr
from base.util import pop_all, some, rounded

from session.config import settings


# ---------- Constants ----------

default_tower_height = 100 # ft

rnd_callsign_max_attempts = 5
tail_number_letter_placeholder = '@'
tail_number_digit_placeholder = '%'
tail_number_alphanum_placeholder = '*'

# -------------------------------


class Environment:
	"""
	Things that are updated during the running session
	"""
	def __init__(self):
		# To set manually before a main window session
		self.airport_data = None       # remains None in CTR mode
		self.elevation_map = None      # optionally set
		self.navpoints = None          # Navpoints in range
		self.rdf = None                # set once and persistent
		self.weather_information = {}  # str station -> Weather
		# Below: Qt objects emitting/connecting signals to disconnect before being replaced between sessions:
		self.radar = None              # set once and persistent
		self.cpdlc = None              # CPDLC message history model
		self.strips = None             # Full strip list model
		self.discarded_strips = None   # Discarded strip model
		self.FPLs = None               # FPL model
		self.ATCs = None               # ATCs available in handover range
		self.alarm_clocks = None       # user-started timers, tied to session clock time (not real time)
	
	def resetEnv(self):
		self.airport_data = None
		self.elevation_map = None
		self.navpoints = None
		self.rdf = None
		self.weather_information.clear()
		for qtobj in self.radar, self.cpdlc, self.strips, self.discarded_strips, self.FPLs, self.ATCs, self.alarm_clocks:
			qtobj.disconnect()
		self.radar = None
		self.cpdlc = None
		self.strips = None
		self.discarded_strips = None
		self.FPLs = None
		self.ATCs = None
		self.alarm_clocks = None
	
	def elevation(self, coords):
		if self.elevation_map is not None:
			try:
				return self.elevation_map.elev(coords.toRadarCoords())
			except ValueError:
				pass
		return 0 if self.airport_data is None else self.airport_data.field_elevation
	
	def radarPos(self):
		return EarthCoords.getRadarPos()
	
	def viewpoint(self, asfc=False):
		"""
		returns EarthCoords, float ft AMSL (or ASFC if arg is set) pair specifying current viewpoint's position
		CAUTION: should not be called in CTR mode.
		"""
		try:
			pos, height, name = self.airport_data.viewpoints[settings.selected_viewpoint]
		except IndexError: # not an apt.dat-defined viewpoint
			try:
				pos_spec, height, name = settings.custom_viewpoints[settings.selected_viewpoint - len(self.airport_data.viewpoints)]
				pos = world_navpoint_db.coordsFromPointSpec(pos_spec)
			except (IndexError, NavpointError, ValueError): # safeguarding NavpointError & ValueError from world_navpoint_db.coordsFromPointSpec
				pos = self.airport_data.navpoint.coordinates
				height = default_tower_height
		return pos, (height if asfc else height + self.elevation(pos)) + settings.tower_height_cheat_offset
	
	def pointInRadarRange(self, coords):
		return self.radarPos().distanceTo(coords) <= settings.radar_range
	
	def pointOnMap(self, coords):
		return self.radarPos().distanceTo(coords) <= settings.map_range
	
	def mapLocStr(self, pos):
		if self.pointOnMap(pos):
			return 'near %s' % self.navpoints.findClosest(pos)
		else:
			return 'off map to the %s' % self.radarPos().headingTo(pos).approxCardinal(True)
	
	def linkedStrip(self, item): # item must be FPL or Aircraft
		try:
			if isinstance(item, FPL):
				return self.strips.findStrip(lambda s: s.linkedFPL() is item)
			else: # Aircraft
				return self.strips.findStrip(lambda s: s.linkedAircraft() is item)
		except StopIteration:
			return None
	
	def frequencies(self):
		if self.airport_data is None:
			return []
		else:
			return sorted(self.airport_data.frequencies, key=(lambda frqdata: str(frqdata[0])))
	
	def knownAcftCallsigns(self, strips=True, xpdr=True, cpdlc=True, sessionMgr=False): # default is all known sim-relevant callsigns
		callsigns = set() # avoid repetitions
		if strips:
			for strip in self.strips.listAll():
				callsigns.add(strip.callsign())
		if xpdr:
			for acft in self.radar.contacts():
				callsigns.add(acft.xpdrCallsign())
		callsigns.discard(None)
		if cpdlc:
			for dlnk in self.cpdlc.dataLinks(lambda dl: not dl.isTerminated()):
				callsigns.add(dlnk.acftCallsign())
		if sessionMgr:
			for acft in settings.session_manager.getAircraft():
				callsigns.add(acft.identifier)
		return list(callsigns)
	
	def radarContactByCallsign(self, callsign):
		candidates = [acft for acft in self.radar.contacts() if acft.xpdrCallsign() is not None and acft.xpdrCallsign().upper() == callsign.upper()]
		for strip in env.strips.listAll():
			if strip.callsign() is not None and strip.callsign().upper() == callsign:
				lnk = strip.linkedAircraft()
				if lnk is not None and all(lnk is not acft for acft in candidates):
					candidates.append(lnk)
		return candidates[0] if len(candidates) == 1 else None

	def shouldAnswerWhoHas(self, callsign):
		return self.strips.count(lambda s: s.callsign() is not None and s.callsign().upper() == callsign.upper()
			and s.lookup(rack_detail) not in settings.private_racks) > 0
	
	def weatherInformation(self, station):
		return self.weather_information.get(station)
	
	def primaryWeather(self):
		return self.weatherInformation(settings.primary_METAR_station)
	
	def readDeclination(self):
		txt = '%.1f°' % abs(settings.magnetic_declination)
		if settings.magnetic_declination != 0:
			txt += ' ' + 'EW'[settings.magnetic_declination < 0]
		return txt
	
	def transitionAltitude(self):
		if self.airport_data is not None and self.airport_data.transition_altitude is not None:
			return self.airport_data.transition_altitude
		else:
			return settings.transition_altitude
	
	def transitionLevel(self):
		"""
		Returns the lowest FL above the TA.
		This is NOT the lowest assignable, which takes more vertical separation
		"""
		return PressureAlt.fromAMSL(self.transitionAltitude(), self.QNH()).FL() + 1
	
	def QNH(self, noneSafe=True):
		w = self.primaryWeather()
		qnh = None if w is None else w.QNH()
		return some(qnh, 1013.25) if noneSafe else qnh
	
	def QFE(self, qnh):
		"""
		in AD mode, returns the ground level pressure (QFE), given MSL pressure
		"""
		return None if self.airport_data is None else qnh - self.airport_data.field_elevation / 28
	
	def groundPressureAlt(self, coords):
		return PressureAlt.fromAMSL(self.elevation(coords), self.QNH())
	
	def pressureAlt(self, alt_fl_spec):
		return alt_fl_spec.toPressureAlt(self.QNH())
	
	def specifyAltFl(self, pressure_alt, step=1):
		"""
		returns an AltFlSpec for the pressure altitude w.r.t. transition altitude and current pressure,
		i.e. a reading in feet AMSL if under the transition level, a flight level otherwise.
		Altitudes are rounded to closest "step hundred"; FLs are rounded with given step
		(use step=None for exact values even in feet).
		"""
		fl = rounded(pressure_alt.FL(), some(step, 1))
		if fl >= self.transitionLevel():
			return AltFlSpec(True, fl)
		else:
			amsl = pressure_alt.ftAMSL(self.QNH())
			return AltFlSpec(False, (amsl if step is None else rounded(amsl, 100 * step)))
	
	def RWD(self, hdg):
		"""
		relative wind direction for given heading
		"""
		w = self.primaryWeather()
		if w is not None:
			wind = w.mainWind()
			if wind is not None and wind[0] is not None:
				return wind[0].opposite().diff(hdg)
		return None
	
	def suggestedATIS(self, letter, appendix=''):
		if self.airport_data is None:
			return ''
		atis = 'This is %s information %s recorded at %s' % \
				((settings.location_radio_name if settings.location_radio_name else self.airport_data.navpoint.long_name),
				letter, timestr(settings.session_manager.clockTime(), z=True))
		if any(rwy.use_for_departures or rwy.use_for_arrivals for rwy in env.airport_data.directionalRunways()):
			atis += '\nRunway(s) in use: %s' % self.readRunwaysInUse()
		w = self.primaryWeather()
		if w is None:
			atis += '\nNo weather available'
		else:
			atis += '\nWind %s' % w.readWind()
			atis += '\nVisibility %s' % w.readVisibility()
			temperatures = w.temperatures()
			if temperatures is not None:
				atis += '\nTemp. %d °C, dew point %d °C' % temperatures
			qnh = w.QNH()
			atis += '\nQNH N/A' if qnh is None else '\nQNH %d, QFE %d' % (qnh, self.QFE(qnh))
		if appendix:
			atis += '\n\n' + appendix
		atis += '\n\nAdvise %s on initial contact that you have received information %s' \
			% ((settings.location_radio_name if settings.location_radio_name else 'ATC'), letter)
		return atis
	
	def readRunwaysInUse(self):
		if self.airport_data is None:
			return 'N/A'
		dep = [rwy.name for rwy in self.airport_data.directionalRunways() if rwy.use_for_departures]
		arr = [rwy.name for rwy in self.airport_data.directionalRunways() if rwy.use_for_arrivals]
		if dep + arr == []:
			return 'N/A'
		both = pop_all(dep, lambda rwy: rwy in arr)
		pop_all(arr, lambda rwy: rwy in both)
		res = '' if both == [] else '/'.join(both) + ' for dep+arr'
		if len(dep) > 0:
			if res != '':
				res += ', '
			res += '%s for departures' % '/'.join(dep)
		if len(arr) > 0:
			if res != '':
				res += ', '
			res += '%s for arrivals' % '/'.join(arr)
		return res


env = Environment()










class CallsignGenerationError(StopIteration):
	pass


tail_number_letter_regexp = re.compile(re.escape(tail_number_letter_placeholder))
tail_number_digit_regexp = re.compile(re.escape(tail_number_digit_placeholder))
tail_number_alphanum_regexp = re.compile(re.escape(tail_number_alphanum_placeholder))


def generate_unused_callsign(acft_type, available_airlines):
	cs = None
	attempts = 0
	while cs is None or cs in env.ATCs.knownAtcCallsigns() + env.knownAcftCallsigns(sessionMgr=True):
		if attempts >= rnd_callsign_max_attempts:
			raise CallsignGenerationError('Max attempts reached in looking to randomise callsign.')
		attempts += 1
		airline = None
		if len(available_airlines) > 0:
			cat = acft_cat(acft_type)
			if cat is not None and random() < commercial_prob.get(cat, 0):
				airline = choice(available_airlines)
		if airline is None:
			if len(acft_registration_formats) > 0:
				cs = choice(acft_registration_formats)
				cs = tail_number_letter_regexp.sub((lambda x: choice(string.ascii_uppercase)), cs)
				cs = tail_number_digit_regexp.sub((lambda x: choice(string.digits)), cs)
				cs = tail_number_alphanum_regexp.sub((lambda x: choice(string.ascii_uppercase + string.digits)), cs)
		else:
			cs = '%s%04d' % (airline, randint(1, 9999))
	return cs
