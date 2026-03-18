
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
from time import sleep
from socket import timeout
from urllib.error import URLError
from urllib.parse import urlencode
from xml.etree import ElementTree

from PyQt5.QtCore import QThread

from base.util import some
from base.coords import EarthCoords
from base.params import AltFlSpec, Speed
from base.radio import CommFrequency
from base.fpl import FPL
from base.strip import Strip, received_from_detail, assigned_altitude_detail, assigned_SQ_detail, departure_clearance_detail

from gui.misc import signals
from gui.widgets.basicWidgets import Ticker

from session.config import settings, open_URL
from session.env import env
from session.models.atc import ATC


# ---------- Constants ----------

SX_update_interval = 3 * 1000 # milliseconds
ATCpie_hidden_string = '__ATC-pie__' # to recognise ATC-pie sender in <pilot> elements

ORSX_account_name = 'ATC-pie'
ORSX_account_password = ''

# -------------------------------


# NOTE: all calls to this function are threaded
def server_query(cmd, dict_data):
	qdict = {
		'user': ORSX_account_name,
		'password': ORSX_account_password,
		'atc': settings.my_callsign
	}
	if env.airport_data is not None:
		qdict['airport'] = settings.location_code
	qdict.update(dict_data)
	try:
		#DEBUGprint('\nPOST %s DATA: %s' % (cmd, bytes(urlencode(qdict), encoding='utf8')))
		response = open_URL('%s/%s' % (settings.ORSX_server_name, cmd), postData=bytes(urlencode(qdict), encoding='utf8'))
		#DEBUGprint('RESPONSE: %s\n' % response)
		return response
	except (URLError, timeout) as error:
		print('OpenRadar exchange service URL error or request timed out: %s' % error, file=stderr)



def send_update_msg(fgms_id, strip, owner, handover):
	xml = ElementTree.Element('flightplanlist')
	xml.set('version', '1.0')
	xml.append(make_WW_XML(fgms_id, strip, owner, handover))
	qdict = {'flightplans': ElementTree.tostring(xml)}
	return server_query('updateFlightplans', qdict) is not None # returns True if OK



def send_update(fgms_id, strip, handover=None): # propose outgoing: handover=recipient; acknowledge incoming: handover=None
	# 1st message is identical between handover and acknowledgement (us claiming ownership alone)
	if send_update_msg(fgms_id, strip, settings.my_callsign, ''): # message OK
		sleep(2)
		if handover is None: # send 2nd message for strip acknowledgement (strip released)
			if not send_update_msg(fgms_id, strip, '', ''):
				print('ERROR: ORSX ACK msg 2. Received strip now probably seen as yours by OpenRadar users.', file=stderr)
		else: # send 2nd message for strip handover (presenting the now owned callsign with the recipient's name)
			if not send_update_msg(fgms_id, strip, settings.my_callsign, handover):
				print('ERROR: ORSX H/O msg 2. Strip now probably seen as yours by OpenRadar users.', file=stderr)
				signals.handoverFailure.emit(strip, 'OpenRadar handover failed.')
	else: # 1st message failed
		if handover is None:
			print('ERROR: ORSX ACK msg 1. Handover now probably seen as pending by OpenRadar users.', file=stderr)
		else:
			print('ERROR: ORSX H/O msg 1. Could not claim ownership; callsign probably already claimed by an OpenRadar user.', file=stderr)
			signals.handoverFailure.emit(strip, 'OpenRadar handover failed. The callsign is probably already claimed by an OpenRadar user.')






## MAIN CLASS

class WwStripExchanger:
	def __init__(self, gui):
		self.updater = SxUpdater(gui)
		self.update_ticker = Ticker(gui, self.updater.start)
		self.gui = gui
		self.running = False
	
	def start(self):
		self.update_ticker.start(SX_update_interval)
		self.running = True
	
	def stopAndWait(self):
		if self.isRunning():
			self.update_ticker.stop()
			self.updater.wait()
			self.running = False
		self.updater.ATCs_on_last_run.clear()
		self.updater.current_contact_claims.clear()
	
	def isRunning(self):
		return self.running
	
	def connectedATCs(self):
		return self.updater.ATCs_on_last_run[:]
	
	def isConnected(self, atc_callsign):
		return any(atc.callsign == atc_callsign for atc in self.updater.ATCs_on_last_run)
	
	def claimingContact(self, callsign):
		return self.updater.current_contact_claims.get(callsign)
	
	def performHandover(self, acft_id, atc_id, strip):
		SxSender(self.gui, strip, acft_id, handover=atc_id).start()


# ------------------------------------------------------------------------------


class SxSender(QThread):
	def __init__(self, gui, strip, fgms_callsign, handover):
		QThread.__init__(self, parent=gui)
		self.fgms_id = fgms_callsign
		self.strip = strip
		self.handover = handover
	
	def run(self):
		send_update(self.fgms_id, self.strip, handover=self.handover)




class SxUpdater(QThread):
	def __init__(self, gui):
		QThread.__init__(self, parent=gui)
		self.ATCs_on_last_run = [] # list of ATC objects
		self.current_contact_claims = {} # claimed ACFT callsign -> claiming ATC callsign
	
	def run(self):
		## PREPARING QUERY
		pos = env.radarPos()
		qdict = {
			'username': settings.MP_social_name,
			'lon': pos.lon,
			'lat': pos.lat,
			'range': some(settings.ORSX_handover_range, settings.radar_range),
			'xmlVersion': '1.0',
			'contacts': ','.join(acft.identifier for acft in env.radar.contacts()) # should this be all FGMS connections?
		}
		if settings.publicised_frequency is not None:
			qdict['frequency'] = str(settings.publicised_frequency)
		server_response = server_query('getFlightplans', qdict)
		## USING RESPONSE
		if server_response is not None:
			try:
				ww_root = ElementTree.fromstring(server_response)
			except ElementTree.ParseError as parse_error:
				print('Parse error in SX server data: %s' % parse_error, file=stderr)
				return
			new_ATCs = []
			
			# ATCs first
			for ww_atc in ww_root.find('atcsInRange').iter('atc'): # NOTE the server sends the full list each time
				atc = ATC(ww_atc.find('callsign').text)
				atc.social_name = ww_atc.find('username').text
				atc.position = EarthCoords(float(ww_atc.find('lat').text), float(ww_atc.find('lon').text))
				ww_frq = ww_atc.find('frequency').text
				try:
					atc.frequency = CommFrequency(ww_frq)
				except ValueError:
					atc.frequency = None
				new_ATCs.append(atc)
			self.ATCs_on_last_run = new_ATCs
			
			# Then strip data (contact claims and handover)
			for ww_flightplan in ww_root.iter('flightplan'): # NOTE the server only sends those when something changes
				ww_header = ww_flightplan.find('header')
				ww_callsign = ww_header.find('callsign').text
				ww_owner = ww_header.find('owner').text
				if ww_owner is None:
					if ww_callsign in self.current_contact_claims:
						del self.current_contact_claims[ww_callsign]
				else:
					self.current_contact_claims[ww_callsign] = ww_owner
				
				if ww_header.find('handover').text == settings.my_callsign: # RECEIVE A STRIP!
					strip = Strip()
					strip.writeDetail(received_from_detail, ww_owner)
					strip.writeDetail(assigned_SQ_detail, ck_int(ww_header.find('squawk').text, base=8))
					strip.writeDetail(assigned_altitude_detail, ck_alt_spec(ww_header.find('assignedAlt').text))
					# Ignored from WW header above: <flags>, <assignedRunway>, <assignedRoute>, <status>, <flight>
					# Ignored from WW data below: <fuelTime>; used with ulterior motive: <pilot>
					ww_data = ww_flightplan.find('data')
					# ATC-pie hides a separator string in <pilot> element, to allow WTC, callsign, DEP clearance details be stored and passed through OpenRadar
					# e.g. <pilot>M__ATC-pie__X-FOO</pilot> for M turb. and X-FOO strip callsign
					# If the token is absent, we know the strip is from OpenRadar
					hidden_tokens = some(ww_data.find('pilot').text, '').split(ATCpie_hidden_string)
					if len(hidden_tokens) == 1: # hidden marker NOT present; previous strip editor was OpenRadar
						strip.writeDetail(FPL.CALLSIGN, ww_callsign)
					else: # recognise strip edited with ATC-pie
						strip.writeDetail(FPL.WTC, hidden_tokens[0])
						strip.writeDetail(FPL.CALLSIGN, hidden_tokens[1])
						if len(hidden_tokens) > 2 and hidden_tokens[2]: # older ATC-pie versions had no DEP clearances
							strip.writeDetail(departure_clearance_detail, hidden_tokens[2])
					strip.writeDetail(FPL.FLIGHT_RULES, ww_data.find('type').text)
					strip.writeDetail(FPL.ACFT_TYPE, ww_data.find('aircraft').text)
					strip.writeDetail(FPL.ICAO_DEP, ww_data.find('departure').text)
					strip.writeDetail(FPL.ICAO_ARR, ww_data.find('destination').text)
					strip.writeDetail(FPL.ROUTE, ww_data.find('route').text)
					strip.writeDetail(FPL.CRUISE_ALT, ck_alt_spec(ww_data.find('cruisingAlt').text))
					spd = ck_int(ww_data.find('trueAirspeed').text)
					if spd is not None:
						strip.writeDetail(FPL.TAS, Speed(spd))
					strip.writeDetail(FPL.COMMENTS, ww_data.find('remarks').text)
					# Possibly ignored details (OpenRadar confuses FPLs and strips): DEP time, EET, alt. AD, souls [*]
					signals.receiveStrip.emit(strip)
					send_update(ww_callsign, strip) # Acknowledge strip




def ck_int(spec_string, base=10):
	try:
		return int(spec_string, base)
	except (TypeError, ValueError):
		return None

def ck_alt_spec(spec_string):
	try:
		return AltFlSpec.fromStr(spec_string)
	except (TypeError, ValueError):
		return None


####################################

# CODE TO GET STRINGS FOR THE NON-STRIP DETAILS, IN CASE RECYCLED

## DEP time
#nsd_dep = ck_int(ww_data.find('departureTime').text)
#if nsd_dep is not None:
#	dep_h = nsd_dep // 100
#	dep_min = nsd_dep % 100
#	if 0 <= dep_h < 24 and 0 <= dep_min < 60:
#		t = now().replace(hour=dep_h, minute=dep_min, second=0, microsecond=0)
#		non_strip_details.append((FPL.TIME_OF_DEP, '%s, %s' % (datestr(t), timestr(t))))

## EET
#nsd_eet = ww_data.find('estFlightTime').text
#if nsd_eet is not None and ':' in nsd_eet:
#	hours, minutes = nsd_eet.split(':', maxsplit=1)
#	try:
#		non_strip_details.append((FPL.EET, '%d h %d min' % (int(hours), int(minutes))))
#	except ValueError:
#		pass

## Alternate AD
#nsd_alt = ww_data.find('alternateDest').text
#if nsd_alt:
#	non_strip_details.append((FPL.ICAO_ALT, nsd_alt))

## Soul count
#nsd_souls = ck_int(ww_data.find('soulsOnBoard').text)
#if nsd_souls:
#	non_strip_details.append((FPL.SOULS, nsd_souls))



def make_simple_element(tag, contents):
	elt = ElementTree.Element(tag)
	if contents is not None:
		elt.text = str(contents)
	return elt


def make_WW_XML(fgms_id, strip, owner, handover):
	header = ElementTree.Element('header')
	data = ElementTree.Element('data')
	# Header
	header.append(make_simple_element('callsign', fgms_id))
	header.append(make_simple_element('owner', owner))
	header.append(make_simple_element('handover', handover))
	sq = strip.lookup(assigned_SQ_detail)
	header.append(make_simple_element('squawk', (None if sq is None else int('%o' % sq, base=10))))
	assAlt = strip.lookup(assigned_altitude_detail) # AltFlSpec or None
	header.append(make_simple_element('assignedAlt', (None if assAlt is None else assAlt.toStr())))
	# Ignored header
	header.append(make_simple_element('status', 'ACTIVE'))
	header.append(make_simple_element('fgcom', 'false'))
	header.append(make_simple_element('flight', None)) # WW says: element must not be empty
	header.append(make_simple_element('assignedRunway', None))
	header.append(make_simple_element('assignedRoute', None))
	# Data
	data.append(make_simple_element('type', some(strip.lookup(FPL.FLIGHT_RULES), 'VFR')))
	data.append(make_simple_element('aircraft', strip.lookup(FPL.ACFT_TYPE)))
	spd = strip.lookup(FPL.TAS)
	data.append(make_simple_element('trueAirspeed', (None if spd is None else spd.kt())))
	data.append(make_simple_element('departure', strip.lookup(FPL.ICAO_DEP)))
	cr_alt = strip.lookup(FPL.CRUISE_ALT)
	data.append(make_simple_element('cruisingAlt', (None if cr_alt is None else cr_alt.toStr())))
	data.append(make_simple_element('route', strip.lookup(FPL.ROUTE)))
	data.append(make_simple_element('destination', strip.lookup(FPL.ICAO_ARR)))
	data.append(make_simple_element('remarks', strip.lookup(FPL.COMMENTS)))
	# Hidden data (ulterior motive: recognise data generated by ATC-pie)
	hidden_wake_turb = some(strip.lookup(FPL.WTC), '')
	hidden_callsign = some(strip.callsign(), '')
	hidden_dep_clr = some(strip.lookup(departure_clearance_detail), '')
	data.append(make_simple_element('pilot', '%s%s%s%s%s' % (hidden_wake_turb, ATCpie_hidden_string, hidden_callsign, ATCpie_hidden_string, hidden_dep_clr)))
	# Non-strip data for ATC-pie, but possibly given in flight plan
	# dep = strip.lookup(FPL.TIME_OF_DEP, fpl=True)
	# data.append(make_simple_element('departureTime', (None if dep is None else '%02d%02d' % (dep.hour, dep.minute))))
	# eet = strip.lookup(FPL.EET, fpl=True)
	# eet = None if eet is None else int(eet.total_seconds() + .5) // 60
	# data.append(make_simple_element('estFlightTime', (None if eet is None else '%d:%02d' % (eet // 60, eet % 60))))
	# data.append(make_simple_element('alternateDest', strip.lookup(FPL.ICAO_ALT, fpl=True)))
	# data.append(make_simple_element('soulsOnBoard', strip.lookup(FPL.SOULS, fpl=True)))
	# Ignored data
	data.append(make_simple_element('fuelTime', None))
	# Wrap up
	root = ElementTree.Element('flightplan')
	root.append(header)
	root.append(data)
	return root


