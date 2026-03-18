
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
from random import randint
from sys import stderr
from socket import timeout
from urllib.error import URLError
from urllib.parse import urlencode
from PyQt5.QtCore import QThread, QTimer, pyqtSignal

from base.cpdlc import CpdlcMessage, CPDLC_element_formats
from base.util import some

from session.config import settings, open_URL
from session.env import env
from session.manager import SessionType


# ---------- Constants ----------

Hoppie_base_URL = 'http://www.hoppie.nl/acars/system/connect.html'
Hoppie_account_URL = 'https://www.hoppie.nl/acars/system/account.html'
normal_poll_min_interval = 40  # seconds
normal_poll_max_interval = 60  # seconds
short_poll_interval = 20  # seconds
short_poll_max_count = 5
poll_response_section_regexp = re.compile(r'\{([^ ]+) +(\w+) +\{([^{}]*)}}')

# -------------------------------


def Hoppie_request(recipient, msg_type, payload):
	qdict = {
		'logon': settings.FSD_Hoppie_logon,
		'from': settings.my_callsign,
		'to': recipient,
		'type': msg_type,
		'packet': payload
	}
	try:
		#DEBUGprint('** Sending Hoppie:', recipient, msg_type, payload)
		response = open_URL(Hoppie_base_URL, postData=bytes(urlencode(qdict), encoding='utf8')).decode()
		#DEBUGprint('** Received from Hoppie:', response)
		if response.startswith('ok'):
			return response[2:].strip()
		elif response.startswith('error'):
			print('Error response from Hoppie network:', response[5:].strip().lstrip('{').rstrip('}'), file=stderr)
		else:
			print('Could not interpret Hoppie response:', response, file=stderr)
	except (URLError, timeout) as error:
		print('Hoppie service URL error or request timed out: %s' % error, file=stderr)



class HoppieRequester(QThread):
	cpdlcDataReceived = pyqtSignal(str, str) # sender, data

	def __init__(self, parent):
		QThread.__init__(self, parent)
		self.request_queue = []

	def doCpdlcRequest(self, recipient, msgMin, msgMrn, msgRa, txt): # MIN is an int; MRN is None if msg is not a response
		self.request_queue.append((recipient, 'cpdlc', '/data2/%i/%s/%s/%s' % (msgMin, some(msgMrn, ''), msgRa, txt)))
		self.start()

	def doPollRequest(self):
		self.request_queue.append(('SERVER', 'poll', ''))
		self.start()

	def run(self):
		while len(self.request_queue) > 0:
			recipient, msg_type, data = self.request_queue.pop(0)
			response = Hoppie_request(recipient, msg_type, data)
			if response is not None:
				if msg_type == 'poll':
					bracketed_match = poll_response_section_regexp.match(response)
					while bracketed_match:
						if bracketed_match.group(2) == 'cpdlc':
							self.cpdlcDataReceived.emit(bracketed_match.group(1), bracketed_match.group(3))
						else:
							print('Ignoring Hoppie ACARS non-CPDLC data:', data, file=stderr)
						response = response[len(bracketed_match.group(0)):].lstrip()
						bracketed_match = poll_response_section_regexp.match(response)




def unmark_Hoppie_fmt(txt):
	return txt.replace('@_@', '').replace('@', '').strip()


class HoppieCommunicator:
	def __init__(self, gui):
		self.requester_thread = HoppieRequester(gui)
		self.poll_timer = QTimer(gui)
		self.poll_timer.setSingleShot(True)
		self.requester_thread.cpdlcDataReceived.connect(self.receiveCpdlcData)
		self.requester_thread.finished.connect(self.pollDone)
		self.poll_timer.timeout.connect(self.requester_thread.doPollRequest)
		self.short_poll_countdown = 0 # set when expecting answers to increase polling rate for a while
		self.my_next_MIN = 0
		self.MINs_expecting_response = {} # callsign -> last msg ID number (for MRNs in responses)

	def startPolling(self):
		self.poll_timer.start(1) # milliseconds

	def stopPolling(self):
		self.poll_timer.stop()
		self.my_next_MIN = 0
		self.MINs_expecting_response.clear()

	def pollDone(self):
		if self.short_poll_countdown > 0:
			self.poll_timer.start(1000 * short_poll_interval)
			self.short_poll_countdown -= 1
		else:
			self.poll_timer.start(1000 * randint(normal_poll_min_interval, normal_poll_max_interval))

	def receiveCpdlcData(self, sender, data):
		datasplit = data.split('/', maxsplit=5) # example data: /data2/4//NE/CURRENT ATC UNIT@_@SCOD@_@SCOTTISH CTL
		if len(datasplit) == 6:
			if datasplit[4] == 'N': # response attribute says no answer needed
				if sender in self.MINs_expecting_response:
					del self.MINs_expecting_response[sender]
			else: # presumably: response attribute is "Y", i.e. an answer is expected from us
				try:
					self.MINs_expecting_response[sender] = int(datasplit[2])
				except ValueError:
					pass # bad MIN format; keeping last value if any
			msgtxt = datasplit[5]
			if msgtxt == 'REQUEST LOGON': # Hoppie-specific message
				if settings.controller_pilot_data_link: # accept log-on (without filtering: request might come from an already accepted ACFT)
					env.cpdlc.beginDataLink(sender)
					self.sendCpdlcData(sender, 'LOGON ACCEPTED', 'NE')
			elif msgtxt == 'LOGOFF': # Hoppie-specific message
				link = env.cpdlc.liveDataLink(sender)
				if link is not None:
					link.terminate(False)
				try:
					del self.MINs_expecting_response[sender]
				except KeyError:
					pass
			else: # expect a regular message, spelt out formatted as in ICAO doc. 4444 (not including element identifiers)
				link = env.cpdlc.liveDataLink(sender)
				if link is None:
					print('Ignored CPDLC message sent from %s while not connected.' % sender, file=stderr)
				else:
					atc_pov = settings.session_manager.session_type == SessionType.TEACHER
					if '|' in msgtxt: # this has sometimes been observed, although not documented
						link.appendMessage(CpdlcMessage([parse_CPDLC_element(unmark_Hoppie_fmt(elt), atc_pov) for elt in msgtxt.split('|')]))
					else:
						link.appendMessage(parse_CPDLC_message(unmark_Hoppie_fmt(msgtxt), atc_pov))
		else:
			print('Ignored ill-formed CPDLC message:', data, file=stderr)

	def sendCpdlcData(self, dest, txtmsg, ra, incrPolling=False):
		self.requester_thread.doCpdlcRequest(dest, self.my_next_MIN, self.MINs_expecting_response.get(dest), ra,
				txtmsg.replace('{', '_').replace('}', '_'))
		self.my_next_MIN += 1
		if incrPolling: # increase polling rate temporarily
			self.short_poll_countdown = short_poll_max_count
			self.poll_timer.start(1000 * short_poll_interval)



arg_regexp_str = { # CAUTION assuming case-insensitive use
	'ATIS':      '[A-Z]',
	'CALLSIGN': r'\w+',
	'CLRTYPE':   'APPROACH|DEPARTURE|FURTHER|OCEANIC|PUSHBACK|STARTUP|TAXI',
	'DEGREES':  r'\d{1,3}',
	'DEVTYPE':   'LATERAL|LEVEL|SPEED',
	'DIRECTION': 'LEFT|RIGHT',
	'FL_ALT':   r'FL\d{1,3}|\d+( ?ft?)',
	'FREQ':     r'\d{3}(\.\d{1,3})?( ?MHz)?',
	'FUEL':     r'\d+', # allows spaces
	'HDIST':    r'\d+(NM|km)?', # does NOT allow spaces because of SPCD-3..5
	'LEGTYPE':   '.+', # allows spaces
	'MINUTES':  r'\d+', # allows spaces
	'NDEG':     r'\d+',
	'POB':      r'\d+',
	'POINT':    r'\w+',
	'PRESSURE': r'\d+(\.\d+)?( ?(hPa|in ?Hg))?',
	'PROCEDURE': r'[A-Z]{5}\d.',
	'REASON':    '.+', # allows spaces
	'ROUTE':     '.+', # allows spaces
	'SPDTYPE':   'GROUND|INDICATED|MACH|TRUE',
	'SPEED':    r'\d+( ?(kt|knots|mph|km/?h))?',
	'TEXT':      '.+', # allows spaces
	'TIME':     r'\d{2}:?\d{2}(Z| ?UTC)?',
	'VSPEED':   r'\d{1,3}( ?ft/min)?', # allows spaces
	'XPDR':      '[0-7]{4}'
}

def element_fmt_regexp(msg_id):
	i = 0
	def next_arg_regexp(arg_key):
		nonlocal i
		res = '(?P<arg%i>%s)' % (i, arg_regexp_str[arg_key])
		i += 1
		return res
	return re.compile(re.sub(r'\{(\w+)}', (lambda m: next_arg_regexp(m.group(1))), CPDLC_element_formats[msg_id], flags=re.IGNORECASE))

element_fmt_regexps = {elt_id: element_fmt_regexp(elt_id) for elt_id in CPDLC_element_formats}

def match_CPDLC_element(txt, uplink, allowSys, startPos):
	candidates = []
	for msg_id, fmt_regexp in element_fmt_regexps.items():
		if uplink == (msg_id[3] == 'U') and (allowSys or not msg_id.startswith('SYS')) \
				and not (msg_id.startswith('TXT') or msg_id == 'RTEU-1' or msg_id == 'RTED-2'):
			# not considering TXT nor RTEU-1/D-2 because they are greedy candidates that shadow more useful matches
			match = fmt_regexp.match(txt, startPos)
			if match:
				#DEBUGprint('** MATCH', fmt_regexp)
				candidate = msg_id + ' ' + ' '.join(match['arg%i' % i] for i in range(len(match.groupdict())))
				candidates.append((candidate, match.end()))
	return candidates


def parse_CPDLC_element(txt, uplink, allowSys=False):
	candidates = match_CPDLC_element(txt, uplink, allowSys, 0)
	if len(candidates) == 1 and candidates[0][1] >= len(txt):
		return candidates[0][0]
	else:
		#DEBUGprint('** No single element full match for txt. Candidates:', str(candidates))
		return 'TXT%s-%i %s' % ('DU'[uplink], 1, txt.replace('@', '')) # TXTU-1 resp. attr. "R", TXTD-1 "Y"


def parse_CPDLC_message(txt, uplink, allowSys=False):
	candidates = [] # str list list
	building = [([fstelt], endpos) for fstelt, endpos in match_CPDLC_element(txt, uplink, allowSys, 0)]
	while building:
		#DEBUGprint('** ', str(building))
		eltlst, endpos = building.pop()
		while endpos < len(txt) and txt[endpos] in ' ,/': # NOTE: sep chars here only considered as such if after non-greedy prior match
			endpos += 1
		if endpos >= len(txt):
			candidates.append(eltlst)
		else:
			for nextelt, nextpos in match_CPDLC_element(txt, uplink, allowSys, endpos):
				building.append((eltlst + [nextelt], nextpos))
	if len(candidates) == 1:
		return CpdlcMessage(candidates[0])
	else:
		#DEBUGprint('** No single message match for txt. Candidates:', str(candidates))
		return CpdlcMessage('TXT%s-%i %s' % ('DU'[uplink], 1, txt.replace('@', ''))) # TXTU-1 resp. attr. "R", TXTD-1 "Y"
