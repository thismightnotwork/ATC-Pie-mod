
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

import re
from sys import stderr
from datetime import datetime, date, time, timezone
from socket import timeout
from urllib.parse import urlencode
from urllib.error import URLError
from xml.etree import ElementTree

from base.util import some
from base.fpl import FPL
from base.params import AltFlSpec, Speed

from session.config import settings, open_URL


# ---------- Constants ----------

lenny64_base_location = 'http://flightgear-atc.alwaysdata.net/dev2017_04_28.php'
lenny64_query_timeout = 2 # seconds for timeout that is acceptable to wait on FPL operations (not all are threaded)
ATCpie_comment_element_tag = 'ATC_comment' # for a modifiable comment inside lenny64's <additionalInformation> FPL element
ATCpie_wakeTurb_element_tag = 'wake_turb_cat' # wake turbulence category (L, M, H, J)

# -------------------------------


lenny64_date_regexp = re.compile(r'(\d+)-(\d+)-(\d+)') # YYYY-MM-DD
lenny64_time_regexp = re.compile(r'(\d+):(\d+):(\d+)') # hh:mm:ss

def lenny64_time_string(native_datetime):
	return '%02d:%02d:%02d' % (native_datetime.hour, native_datetime.minute, native_datetime.second)

def lenny64_date_string(native_datetime):
	return '%d-%02d-%02d' % (native_datetime.year, native_datetime.month, native_datetime.day)


class Lenny64Error(Exception):
	def __init__(self, query, msg, srvResponse=None):
		"""
		Response is the unexpected Lenny64 response type. Typically <error> after a query.
		No response means a network error has occurred and nothing was received.
		"""
		Exception.__init__(self)
		self.msg = msg
		self.query = query
		self.server_response = srvResponse
	
	def __str__(self):
		return self.msg
	
	def query(self):
		return self.query
	
	def srvResponse(self):
		return self.server_response
		


def lenny64_query(query, expect):
	"""
	Returns the TreeElement response from the Lenny64 server, or raises Lenny64Error if an error occurred
	(XML parse error, socket/network problem) or if the received root tag is different to the expected
	"""
	url = '%s?%s' % (lenny64_base_location, query)
	try:
		#DEBUGprint('## Lenny64 query:', query)
		response = open_URL(url, timeout=lenny64_query_timeout)
		#DEBUGprint('## Response:', response)
	except (URLError, timeout) as error:
		raise Lenny64Error(query, 'Socket or network error: %s' % error)
	try:
		xml = ElementTree.fromstring(response)
		if xml.tag != expect:
			raise Lenny64Error(query, 'Unexpected response type from server: <%s>' % xml.tag, srvResponse=response)
		return xml
	except ElementTree.ParseError as parse_error:
		print('Parse error in Lenny64 response (dumped below) to query: %s' % url, file=stderr)
		print('Error: %s' % parse_error, file=stderr)
		print(str(response), file=stderr)
		raise Lenny64Error(query, 'Operation may have completed correctly but a bad response was received from Lenny64.'
									' Please report with console output.')



def post_session(session_datetime, end_time, frq=None, icao=None):
	params = {
		'email': settings.lenny64_account_email,
		'password': settings.lenny64_password_md5,
		'date': lenny64_date_string(session_datetime.date()),
		'beginTime': lenny64_time_string(session_datetime.time()),
		'endTime': lenny64_time_string(end_time),
		'airportICAO': some(icao, settings.location_code)
	}
	if frq is not None:
		params['fgcom'] = str(frq)
	query = 'newAtcSession&' + urlencode(params)
	lenny64_query(query, expect='event') # server response ignored



# ================================================ #
#                  FLIGHT PLANS                    #
# ================================================ #

## My details	 ##  Lenny64's XML elements
# CALLSIGN      # callsign
# ACFT_TYPE     # aircraft
# WTC           # additionalInformation.ATCpie_wakeTurb_element_tag
# ICAO_DEP      # airportFrom
# ICAO_ARR      # airportTo
# ICAO_ALT      # alternateDestination
# CRUISE_ALT    # cruiseAltitude
# TAS           # trueAirspeed
# SOULS         # soulsOnBoard
# TIME_OF_DEP   # dateDeparture + departureTime
# EET           # --> dateArrival + arrivalTime
# FLIGHT_RULES  # category
# ROUTE         # waypoints
# COMMENTS      # additionalInformation.ATCpie_comment_element_tag
# (N/A)         # airline
# (N/A)         # flightNumber
# (N/A)         # fuelTime
# (N/A)         # pilotName

def FPLdetails_from_XMLelement(fpl_elt):
	fpl_id = None # tbd below
	online_status = FPL.FILED
	details = {}
	dep_date = dep_time = None
	arr_date = arr_time = None
	for elt in fpl_elt:
		if elt.tag == 'flightplanId' and elt.text is not None:
			try:
				fpl_id = int(elt.text)
			except ValueError:
				print('Unreadable FPL ID from Lenny64: %s' % elt.text, file=stderr) # fpl_id stays None
		elif elt.tag == 'status':
			try: # NOTE: dict keys truncated below because of possible messy spelling at Lenny64 (e.g. "close" vs. "closed")
				online_status = {'f': FPL.FILED, 'o': FPL.OPEN, 'c': FPL.CLOSED}[elt.text[0]]
			except (KeyError, IndexError):
				print('Unrecognised FPL status string from Lenny64: %s' % elt.text, file=stderr)
		elif elt.tag == 'callsign':
			details[FPL.CALLSIGN] = elt.text # can be None
		elif elt.tag == 'aircraft':
			details[FPL.ACFT_TYPE] = elt.text # can be None
		elif elt.tag == 'airportFrom':
			details[FPL.ICAO_DEP] = elt.text # can be None
		elif elt.tag == 'airportTo':
			details[FPL.ICAO_ARR] = elt.text # can be None
		elif elt.tag == 'alternateDestination':
			details[FPL.ICAO_ALT] = elt.text # can be None
		elif elt.tag == 'cruiseAltitude' and elt.text is not None:
			try:
				details[FPL.CRUISE_ALT] = AltFlSpec.fromStr(elt.text)
			except ValueError:
				pass # Ignore unreadable alt./FL spec string
		elif elt.tag == 'trueAirspeed' and elt.text is not None:
			try:
				details[FPL.TAS] = Speed(int(elt.text))
			except ValueError:
				pass # Ignore unreadable integer, check with Lenny for authorised string formats
		elif elt.tag == 'soulsOnBoard' and elt.text is not None:
			try:
				details[FPL.SOULS] = int(elt.text)
			except ValueError:
				pass # Ignore unreadable integer, check with Lenny for authorised string formats
		elif elt.tag == 'dateDeparture' and elt.text is not None:
			match = lenny64_date_regexp.fullmatch(elt.text)
			if match:
				try:
					dep_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
				except ValueError:
					pass
		elif elt.tag == 'departureTime' and elt.text is not None:
			match = lenny64_time_regexp.fullmatch(elt.text)
			if match:
				hh, mm, ss = int(match.group(1)), int(match.group(2)), int(match.group(3))
				dep_time = time(hh, mm, ss)
		elif elt.tag == 'dateArrival' and elt.text is not None:
			match = lenny64_date_regexp.fullmatch(elt.text)
			if match:
				try:
					arr_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
				except ValueError:
					pass
		elif elt.tag == 'arrivalTime' and elt.text is not None:
			match = lenny64_time_regexp.fullmatch(elt.text)
			if match:
				hh, mm, ss = int(match.group(1)), int(match.group(2)), int(match.group(3))
				arr_time = time(hh, mm, ss)
		elif elt.tag == 'category':
			details[FPL.FLIGHT_RULES] = elt.text # can be None
		elif elt.tag == 'waypoints':
			details[FPL.ROUTE] = elt.text
		elif elt.tag == 'additionalInformation':
			found = elt.find(ATCpie_comment_element_tag) # ATC comments
			if found is not None:
				details[FPL.COMMENTS] = found.text # can be None
			found = elt.find(ATCpie_wakeTurb_element_tag) # wake turbulence category
			if found is not None:
				details[FPL.WTC] = found.text # can be None
	if dep_date is not None and dep_time is not None:
		details[FPL.TIME_OF_DEP] = datetime(dep_date.year, dep_date.month, dep_date.day,
					hour=dep_time.hour, minute=dep_time.minute, second=dep_time.second, tzinfo=timezone.utc)
		if arr_date is not None and arr_time is not None: # makes no sense without a departure datetime
			eta = datetime(arr_date.year, arr_date.month, arr_date.day,
						hour=arr_time.hour, minute=arr_time.minute, second=arr_time.second, tzinfo=timezone.utc)
			details[FPL.EET] = eta - details[FPL.TIME_OF_DEP]
	if fpl_id is None:
		raise ValueError('Missing or unreadable FPL ID')
	return fpl_id, online_status, details


def lenny64_str_details(fpl, details):
	dct = {}
	if FPL.CALLSIGN in details:
		dct['callsign'] = fpl[FPL.CALLSIGN]
	if FPL.ICAO_DEP in details:
		dct['departureAirport'] = fpl[FPL.ICAO_DEP]
	if FPL.ICAO_ARR in details:
		dct['arrivalAirport'] = fpl[FPL.ICAO_ARR]
	if FPL.ICAO_ALT in details:
		dct['alternateDestination'] = fpl[FPL.ICAO_ALT]
	if FPL.CRUISE_ALT in details:
		dct['cruiseAltitude'] = None if fpl[FPL.CRUISE_ALT] is None else fpl[FPL.CRUISE_ALT].toStr()
	if FPL.TAS in details:
		dct['trueAirspeed'] = None if fpl[FPL.TAS] is None else fpl[FPL.TAS].kt()
	if FPL.TIME_OF_DEP in details:
		dct['dateDeparture'] = None if fpl[FPL.TIME_OF_DEP] is None else lenny64_date_string(fpl[FPL.TIME_OF_DEP])
		dct['departureTime'] = None if fpl[FPL.TIME_OF_DEP] is None else lenny64_time_string(fpl[FPL.TIME_OF_DEP])
	if FPL.EET in details and fpl[FPL.TIME_OF_DEP] is not None: # makes no sense without a TIME_OF_DEP
		if fpl[FPL.EET] is None:
			dct['dateArrival'] = None
			dct['arrivalTime'] = None
		else:
			arr = fpl[FPL.TIME_OF_DEP] + fpl[FPL.EET]
			dct['dateArrival'] = lenny64_date_string(arr)
			dct['arrivalTime'] = lenny64_time_string(arr)
	if FPL.ACFT_TYPE in details:
		dct['aircraft'] = fpl[FPL.ACFT_TYPE]
	if FPL.SOULS in details:
		dct['soulsOnBoard'] = fpl[FPL.SOULS]
	if FPL.ROUTE in details:
		dct['waypoints'] = fpl[FPL.ROUTE]
	if FPL.FLIGHT_RULES in details:
		dct['category'] = fpl[FPL.FLIGHT_RULES]
	return {d: some(v, '') for d, v in dct.items()}



## PULLING QUERIES

def download_FPLs(when, where=None):
	"""
	when: date
	where: airport ICAO, any airport if None
	"""
	query = 'getFlightplans&date=%s' % lenny64_date_string(when)
	if where is not None:
		query += '&airport=%s' % where
	response = lenny64_query(query, expect='flightplans')
	res = []
	for fpl_elt in response.iter('flightplan'):
		try:
			fpl_id, status, details = FPLdetails_from_XMLelement(fpl_elt)
			fpl = FPL(details)
			fpl.markAsOnline(fpl_id)
			fpl.setOnlineStatus(status)
			res.append(fpl)
		except ValueError:
			pass # Ignore faulty FPL
	return res



## PUSHING QUERIES

def file_new_FPL(fpl):
	"""
	Files the given FPL which is assumed local only (non existant online)
	and sets the internal online ID to the one assigned by Lenny,
	thereby turning it into an "online-aware" flight plan.
	"""
	if fpl.isOnline():
		print('FPL already exists online: %s' % fpl, file=stderr)
		return
	query = 'fileFlightplan&email=%s&password=%s' % (settings.lenny64_account_email, settings.lenny64_password_md5)
	query += '&' + urlencode(lenny64_str_details(fpl, FPL.details))
	response = lenny64_query(query, expect='flightplan')
	try:
		fpl.markAsOnline(int(response.find('flightplanId').text))
	except (ValueError, TypeError, AttributeError): # resp. int(str), int(None), None.text
		raise Lenny64Error(query, 'Could not get a valid ID for newly filed FPL.', srvResponse=response)
	comments_value = fpl[FPL.COMMENTS]
	if comments_value is not None:
		try:
			push_FPL_custom_var(fpl.online_id, ATCpie_comment_element_tag, comments_value) # server response ignored
		except Lenny64Error: # a problem occurred with the comments (only)
			fpl.modified_details[FPL.COMMENTS] = comments_value # consider as a local modification
	wtc_value = fpl[FPL.WTC]
	if wtc_value is not None:
		try:
			push_FPL_custom_var(fpl.online_id, ATCpie_wakeTurb_element_tag, wtc_value) # server response ignored
		except Lenny64Error: # a problem occurred with the wake turb. cat. (only)
			fpl.modified_details[FPL.WTC] = wtc_value # consider as a local modification


def upload_FPL_updates(fpl):
	"""
	Uploads local updates made to the FPL since last pull, overriding online values.
	This method assumes the FPL exists online.
	"""
	assert fpl.isOnline()
	details_for_lenny = list(fpl.modified_details)
	if FPL.TIME_OF_DEP in details_for_lenny:
		details_for_lenny.append(FPL.EET)
	query = 'editFlightplan&email=%s&password=%s' % (settings.lenny64_account_email, settings.lenny64_password_md5)
	query += '&flightplanId=%d' % fpl.online_id
	query += '&' + urlencode(lenny64_str_details(fpl, details_for_lenny))
	lenny64_query(query, expect='flightplan') # server response ignored
	for d in list(fpl.modified_details):
		if d != FPL.COMMENTS and d != FPL.WTC:
			del fpl.modified_details[d]
	if FPL.COMMENTS in fpl.modified_details:
		try:
			push_FPL_custom_var(fpl.online_id, ATCpie_comment_element_tag, some(fpl[FPL.COMMENTS], ''))
			del fpl.modified_details[FPL.COMMENTS]
		except Lenny64Error:
			pass
	if FPL.WTC in fpl.modified_details:
		try:
			push_FPL_custom_var(fpl.online_id, ATCpie_wakeTurb_element_tag, some(fpl[FPL.WTC], ''))
			del fpl.modified_details[FPL.WTC]
		except Lenny64Error:
			pass


def push_FPL_custom_var(fpl_id, var_name, value):
	query = 'setVar&email=%s&password=%s' % (settings.lenny64_account_email, settings.lenny64_password_md5)
	query += '&flightplanId=%d' % fpl_id
	query += '&' + urlencode({'variable': var_name, 'value': value})
	return lenny64_query(query, expect='flightplan')



## OPEN/CLOSE QUERIES

def set_FPL_status(fpl, status):
	assert fpl.isOnline()
	qcmd = {FPL.OPEN: 'openFlightplan', FPL.CLOSED: 'closeFlightplan'}[status]
	query = '%s&email=%s&password=%s' % (qcmd, settings.lenny64_account_email, settings.lenny64_password_md5)
	query += '&flightplanId=%d' % fpl.online_id
	lenny64_query(query, expect='flightplan') # Lenny64Error raised or server response ignored
	fpl.setOnlineStatus(status) # not executed if previous line was not successful
