
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
from datetime import datetime, timedelta, timezone

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QTcpSocket

from ai.aircraft import pitch_factor

from base.acft import Aircraft, Xpdr
from base.fpl import FPL
from base.params import Heading, AltFlSpec, Speed, distance_travelled
from base.util import some, rounded, m2NM

from ext.fgfs import FGFS_model_position
from ext.fgms import mk_fgms_position_packet, FGMS_prop_XPDR_capability, FGMS_prop_XPDR_code, \
		FGMS_prop_XPDR_ident, FGMS_prop_XPDR_alt, FGMS_prop_XPDR_gnd, FGMS_prop_XPDR_ias, FGMS_prop_XPDR_mach

from session.config import settings
from session.env import env


# ---------- Constants ----------

protocol_version = '9' # expected by https://github.com/kuroneko/fsd commit bc7d43b6 (latest available in April 2020)
init_connection_timeout = 3000 # ms
min_dist_for_hdg_update = m2NM * .1
max_time_for_pos_update = timedelta(seconds=5)
min_height_for_neg_pitch = 100 # ft
speed_estimation_factor_airborne = .9  # underestimate speed to limit backtrack effects on real update...
speed_estimation_factor_onGround = .75 # ...especially on ground where ACFT are slow and stop often
min_height_for_airborne = 50 # ft
allowed_FPL_DEP_time_delay = timedelta(hours=5) # set DEP tomorrow if FPL time is longer ago today (no DEP date in FSD)

# -------------------------------


# received prefix -> number of fields to split from left
# CAUTION: prefixed packets have a different format when sent
recv_prefixes_fmt = {
	'#AA': 6,  # Add an ATC client
	'#AP': 7,  # Add a pilot client
	'#DA': 2,  # Remove an ATC client
	'#DL': 4,  # Server heart beat
	'#DP': 2,  # Remove a pilot client
	'#TM': 3,  # "Text message" (last field might contain ':')
	'$AR': 4,  # METAR received
	'$CQ': 3,  # Request (last field might contain ':')
	'$CR': 4,  # Answer to request (last field might contain ':')
	'$ER': 5,  # Error message from server (last field might contain ':')
	'$FP': 17, # FPL filed
	'$HO': 3,  # Handover
	'%':   8,  # ATC position update
	'@':   10  # Pilot position update
}

# ERROR CODES:
#  0  No error
#  1  Callsign in use
#  2  Callsign invalid
#  3  Already registered
#  4  Syntax error
#  5  Invalid source in packet
#  6  Invalid CID/password
#  7  No such callsign
#  8  No flightplan
#  9  No such weather profile
# 10  Invalid protocol revision
# 11  Requested level too high
# 12  No more clients
# 13  CID/PID suspended



def secure_field(s):
	return s.replace(':', ' ').replace('\n', ' ')




def FPL_16_fields(fpl):
	spd = fpl[FPL.TAS]
	eet = fpl[FPL.EET]
	cr_alt = fpl[FPL.CRUISE_ALT]
	if eet is None:
		eetH = eetM = ''
	else:
		minutes = rounded(eet.total_seconds() / 60)
		full_hours = int(minutes / 60) # floor int
		eetH = str(full_hours)
		eetM = str(minutes - 60 * full_hours)
	dep_time = ''
	fpldep = fpl[FPL.TIME_OF_DEP]
	if fpldep is not None: # only if more or less today (FSD does not allow dates in FPLs)
		tnow = settings.session_manager.clockTime()
		if tnow < fpldep + allowed_FPL_DEP_time_delay < tnow + timedelta(days=1):
			dep_time = '%02d%02d' % (fpldep.hour, fpldep.minute)
	return [
		some(fpl[FPL.CALLSIGN], ''),
		{'IFR': 'I', 'VFR': 'V'}.get(fpl[FPL.FLIGHT_RULES], ''),
		some(fpl[FPL.ACFT_TYPE], ''),
		('' if spd is None else '%d' % spd.kt()),
		some(fpl[FPL.ICAO_DEP], ''),
		dep_time, # DEP1
		'', # DEP2
		('' if cr_alt is None else cr_alt.toStr()),
		some(fpl[FPL.ICAO_ARR], ''),
		eetH,
		eetM,
		'', # FOB1
		'', # FOB2
		some(fpl[FPL.ICAO_ALT], ''),
		some(fpl[FPL.COMMENTS], ''),
		some(fpl[FPL.ROUTE], '')
	]




def FPL_from_fields(callsign, destFSD, rules, acft, spd, depAD,
			dep1, dep2, cruise, destAD, eetH, eetM, fob1, fob2, altAD, rmk, route):
	# NOTE: FOB fields and dep2 ignored in ATC-pie; SOULS and WTC missing in FSD
	fpl = FPL()
	fpl[FPL.CALLSIGN] = callsign
	fpl[FPL.ICAO_DEP] = depAD
	fpl[FPL.ICAO_ARR] = destAD
	fpl[FPL.ICAO_ALT] = altAD
	try:
		fpl[FPL.CRUISE_ALT] = AltFlSpec.fromStr(cruise)
	except ValueError:
		pass
	fpl[FPL.ROUTE] = route
	fpl[FPL.COMMENTS] = rmk
	fpl[FPL.FLIGHT_RULES] = {'I': 'IFR', 'V': 'VFR'}.get(rules)
	filtered_acft_split = [s for s in acft.split('/', maxsplit=2) if len(s) > 1]
	if len(filtered_acft_split) == 1:
		fpl[FPL.ACFT_TYPE] = filtered_acft_split[0]
	tnow = settings.session_manager.clockTime()
	try:
		tdep = datetime(tnow.year, tnow.month, tnow.day,
							hour=int(dep1[:2]), minute=int(dep1[2:]), tzinfo=timezone.utc)
		if tnow - allowed_FPL_DEP_time_delay > tdep:
			tdep += timedelta(days=1)
		fpl[FPL.TIME_OF_DEP] = tdep
	except ValueError:
		pass
	try:
		hh = int(eetH)
		mm = int(eetM)
		if hh != 0 or mm != 0:
			fpl[FPL.EET] = timedelta(hours=hh, minutes=mm)
	except ValueError:
		pass
	try:
		fpl[FPL.TAS] = Speed(int(spd))
	except ValueError:
		pass
	return fpl





def freq_str(frq):
	return ''.join(c for c in str(frq)[1:] if c != '.')






class FsdAircraft(Aircraft):
	def __init__(self, callsign, acft_type, pd_pos, pd_alt, pd_speed, pd_xpdr):
		Aircraft.__init__(self, callsign, acft_type, pd_pos, pd_alt)
		self.last_PD_time = settings.session_manager.clockTime()
		self.last_PD_coords = pd_pos
		self.last_PD_alt = pd_alt
		self.last_PD_speed = pd_speed
		self.last_PD_xpdr = pd_xpdr
		self.last_vs_ftpsec = 0 # unit here is ft/s
		self.last_heading = None
		self.prior_heading = None
	
	def updateLiveStatusWithEstimate(self):
		if self.last_heading is None:
			return
		dt = min(settings.session_manager.clockTime() - self.last_PD_time, max_time_for_pos_update)
		deg_offset = 0 if self.prior_heading is None else self.last_heading.diff(self.prior_heading) / 2
		spd_fact = speed_estimation_factor_airborne if self.last_PD_alt >= env.elevation(self.last_PD_coords) + min_height_for_airborne else speed_estimation_factor_onGround
		est_pos = self.last_PD_coords.moved(self.last_heading + deg_offset, distance_travelled(dt, self.last_PD_speed * spd_fact))
		est_alt = max(self.last_PD_alt + dt.total_seconds() * self.last_vs_ftpsec / 2, env.elevation(est_pos))
		self.updateLiveStatus(est_pos, est_alt, self.last_PD_xpdr)
	
	def updatePdStatus(self, pd_pos, pd_alt, pd_speed, pd_xpdr):
		tnow = settings.session_manager.clockTime()
		self.last_vs_ftpsec = (pd_alt - self.last_PD_alt) / (tnow - self.last_PD_time).total_seconds() # ft/s
		if self.last_PD_coords.distanceTo(pd_pos) >= min_dist_for_hdg_update:
			self.prior_heading = self.last_heading
			self.last_heading = self.last_PD_coords.headingTo(pd_pos)
		else: # Stopped for too long; reset prior heading
			self.prior_heading = None
		self.updateLiveStatus(pd_pos, pd_alt, pd_xpdr)
		self.last_PD_time = tnow
		self.last_PD_coords = pd_pos
		self.last_PD_alt = pd_alt
		self.last_PD_speed = pd_speed
		self.last_PD_xpdr = pd_xpdr
	
	def fgmsPositionPacket(self):
		pdct = {FGMS_prop_XPDR_capability: 1} # no mode S in FSD
		try:
			pdct[FGMS_prop_XPDR_code] = self.last_PD_xpdr[Xpdr.CODE]
		except KeyError:
			pass
		try:
			pdct[FGMS_prop_XPDR_ident] = self.last_PD_xpdr[Xpdr.IDENT]
		except KeyError:
			pass
		try:
			pdct[FGMS_prop_XPDR_alt] = int(self.last_PD_xpdr[Xpdr.ALT].ft1013())
		except KeyError:
			pass
		try:
			pdct[FGMS_prop_XPDR_gnd] = self.last_PD_xpdr[Xpdr.GND]
		except KeyError:
			pass
		try:
			pdct[FGMS_prop_XPDR_ias] = int(self.last_PD_xpdr[Xpdr.IAS].kt())
		except KeyError:
			pass
		try:
			pdct[FGMS_prop_XPDR_mach] = self.last_PD_xpdr[Xpdr.MACH]
		except KeyError:
			pass
		acft_coords = self.liveCoords()
		acft_amsl = self.liveRealAlt()
		acft_hdg = some(self.last_heading, Heading(0, True))
		model, coords, amsl = FGFS_model_position(self.aircraft_type, acft_coords, acft_amsl, acft_hdg)
		deg_pitch = 0 if self.last_vs_ftpsec < 0 and acft_amsl < env.elevation(acft_coords) + min_height_for_neg_pitch \
				else pitch_factor * 60 * self.last_vs_ftpsec
		return mk_fgms_position_packet(self.identifier, model, coords, amsl,
				hdg=acft_hdg.trueAngle(), pitch=deg_pitch, roll=0, properties=pdct)










class FsdConnection(QObject):
	cmdReceived = pyqtSignal(str, list)
	connectionDropped = pyqtSignal()
	
	def __init__(self, parent):
		QObject.__init__(self, parent)
		self.socket = None
		self.strinbuf = ''
	
	def initOK(self):
		self.socket = QTcpSocket(self)
		self.socket.disconnected.connect(self.socketDisconnected)
		self.socket.readyRead.connect(self.receiveBytes)
		self.socket.connectToHost(settings.FSD_server_host, settings.FSD_server_port)
		if self.socket.waitForConnected(init_connection_timeout):
			coords = env.radarPos()
			self.sendLinePacket('#AA' + settings.my_callsign, 'SERVER', settings.MP_social_name,
					settings.FSD_cid, settings.FSD_password, str(settings.FSD_rating), protocol_version,
					'1', '0', '%f' % coords.lat, '%f' % coords.lon, '100')
		else:
			self.socket = None
		return self.isConnected()
	
	def socketDisconnected(self):
		self.socket = None
		self.connectionDropped.emit()
	
	def isConnected(self):
		return self.socket is not None and self.socket.state() == QAbstractSocket.ConnectedState
	
	def shutdown(self):
		self.sendLinePacket('#DA' + settings.my_callsign, 'SERVER')
		self.socket.disconnectFromHost() #NOTE: emits self.socket.disconnected
	
	
	## Low-level FSD send/receive methods
	
	def sendLinePacket(self, *fields, lastVerbatim=False):
		safe_fields = [secure_field(s) for s in fields[:-1]]
		if len(fields) > 0: # last field still missing
			safe_fields.append(fields[-1] if lastVerbatim else secure_field(fields[-1]))
		self.socket.write(bytes(':'.join(safe_fields) + '\r\n', encoding='utf8'))
		#DEBUGprint('[CLI]', ':'.join(safe_fields))

	def receiveBytes(self):
		self.strinbuf += bytes(self.socket.readAll()).decode('utf8')
		while '\n' in self.strinbuf:
			fsd_line, self.strinbuf = self.strinbuf.split('\n', maxsplit=1)
			fsd_line = fsd_line.rstrip('\r') # spec line sep is '\r\n', but '\r' seen missing
			#DEBUGprint('[SRV]', fsd_line)
			try:
				cmd, reqlen = next((prefix, nf) for prefix, nf in recv_prefixes_fmt.items() if fsd_line.startswith(prefix))
				self.cmdReceived.emit(cmd, fsd_line[len(cmd):].split(':', maxsplit=(reqlen - 1)))
			except StopIteration: # Unrecognised command
				print('Unhandled packet:', fsd_line, file=stderr)
	
	
	## Higher-level sending methods
	
	def sendPositionUpdate(self):
		coords = env.radarPos()
		frq_str = '' if settings.publicised_frequency is None else freq_str(settings.publicised_frequency)
		self.sendLinePacket('%' + settings.my_callsign, frq_str, protocol_version,
				str(settings.FSD_visibility_range), str(settings.FSD_rating), '%f' % coords.lat, '%f' % coords.lon, '0')
	
	def sendMetarRequest(self, station):
		self.sendLinePacket('$AX' + settings.my_callsign, 'SERVER', 'METAR', station)
	
	def sendTextMsg(self, msg, frq=None):
		if msg.isPrivate():
			self.sendLinePacket('#TM' + msg.sender(), msg.recipient(), msg.txtOnly(), lastVerbatim=True)
		elif frq is None: # Message for public ATC channel
			self.sendLinePacket('#TM' + msg.sender(), '*A', msg.txtOnly(), lastVerbatim=True)
		else: # Public text radio message on given frequency
			self.sendLinePacket('#TM' + msg.sender(), '@' + freq_str(frq), msg.txtMsg(), lastVerbatim=True)
	
	def sendQuery(self, requestee, query):
		self.sendLinePacket('$CQ' + settings.my_callsign, requestee, query, lastVerbatim=True)
	
	def sendQueryResponse(self, requester, query, response):
		self.sendLinePacket('$CR' + settings.my_callsign, requester, query, response, lastVerbatim=True)
	
	#NOTE: cannot send as other than own callsign
	#def sendFpl(self, fpl):
	#	# example: (17 fields total) $FPKLM002:SERVER:I:B738:100:EHAM:1226:0:FL120:EGLL:0:0:0:0::/V/:XAMAN
	#	fields = FPL_16_fields(fpl)
	#	callsign = fields.pop(0)
	#	self.sendLinePacket('$FP' + callsign, 'SERVER', *fields) # 17 fields
	
	#NOTE: this seems to be VATSIM only ($AM absent in FSD sources)
	#def sendFplAmendment(self, fpl):
	#	# example (18 fields total): $AMEKDK_APP:SERVER:ATCFSX:I:B738:389:EKCH:1325:0:FL260:EHAM:3:33:4:33::HHASDJKA:DOBEL MICHAEL4 PAM
	#	self.sendLinePacket('$AM' + settings.my_callsign, 'SERVER', *FPL_16_fields(fpl))
	
	def sendNonAtcPieHandover(self, recipient, callsign):
		self.sendLinePacket('$HO' + settings.my_callsign, recipient, callsign)
