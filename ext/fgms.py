
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

import struct
from os import path
from sys import stderr
from math import radians, pi, cos, sin, acos
from datetime import timedelta

from base.util import some
from base.utc import realTime, program_started_at
from base.coords import cartesian_metres_to_WGS84_geodetic, WGS84_geodetic_to_cartesian_metres
from base.params import PressureAlt, Speed
from base.acft import Aircraft, Xpdr
from base.radio import CommFrequency
from base.text import TextMessage

from ext.fgfs import ICAO_aircraft_type, is_ATC_model, ATCpie_model_string

from gui.misc import signals

from session.config import settings, version_string
from session.env import env


# ---------- Constants ----------

fgms_string_encoding = 'utf8'
minimum_chat_message_send_count = 8
dodgy_character_substitute = '_'
minimum_FGMS_visibility_range = 100 # NM
FGMS_live_ACFT_time = timedelta(seconds=2) # after which ACFT is considered disconnected (to appear as "?" on next sweep)
FGMS_connection_timeout = timedelta(seconds=60) # after which ACFT is considered a disconnected zombie (to be removed)
timestamp_ignore_maxdiff = 10 # s (as specified in FGMS packets)

los_min_dist = 20 # NM (minimum line-of-sight radio propagation)

# FGMS packet type codes
position_message_type_code = 7

v2_magic_padding = bytes.fromhex('1face002')
v2_version_prop_value = 2

# -------------------------------


def FGMS_prop_code_by_name(name):
	return next(code for code, data in FGMS_properties.items() if data[0] == name)



def scaled_float(nv, scale):
	nv *= scale
	if nv >= 32767:
		return 32767
	if nv <= -32767:
		return -32767
	return int(nv)


class FgmsType:
	all_types = V1_Bool, V1_Int, V1_Float, V1_String, V2_NoSend, V2_LikeV1, V2_ShortInt, \
			V2_ShortFloatNorm, V2_ShortFloat1, V2_ShortFloat2, V2_ShortFloat3, V2_ShortFloat4, V2_BoolArray = range(13)
	v2_tightly_packed_types = [V1_Bool, V1_String, V2_ShortInt,
			V2_ShortFloatNorm, V2_ShortFloat1, V2_ShortFloat2, V2_ShortFloat3, V2_ShortFloat4]




class PacketData:
	"""
	Data packer/unpacker for FGMS data packets.
	Includes funny FGFS behaviour like little endian ints and big endian doubles,
	the unefficient V1 strings encoded with int sequences, etc.
	"""
	def __init__(self, data=None):
		self.data = some(data, bytes(0))
	
	def __len__(self):
		return len(self.data)
	
	def allData(self):
		return self.data

	def peek_bytes(self, nbytes):
		return self.data[:nbytes]

	def pop_bytes(self, nbytes):
		popped = self.data[:nbytes]
		self.data = self.data[nbytes:]
		if len(popped) < nbytes:
			print('WARNING: Truncated packet detected. Expected %d bytes; only %d could be read.' % (nbytes, len(popped)), file=stderr)
			return bytes(nbytes)
		return popped
	
	def append_bytes(self, raw_data):
		self.data += raw_data
	
	def append_packed(self, data):
		self.data += data.allData()
	
	def pad(self, block_multiple):
		pad = block_multiple - (len(self) % block_multiple)
		self.append_bytes(bytes(pad % block_multiple))
	
	## Low-level packing
	
	def pack_int(self, i):
		self.data += struct.pack('!i', i)
	def pack_float(self, f):
		self.data += struct.pack('!f', f)
	def pack_double(self, d):
		self.data += struct.pack('!d', d)
	def pack_padded_string(self, size, string): # For padded null-terminated string
		self.data += struct.pack('%ds' % size, bytes(string, encoding=fgms_string_encoding)[:size-1])
	
	## Low-level unpacking
	def unpack_int(self):
		return struct.unpack('!i', self.pop_bytes(4))[0]
	def unpack_unsigned_int(self):
		return struct.unpack('!I', self.pop_bytes(4))[0]
	def unpack_float(self):
		return struct.unpack('!f', self.pop_bytes(4))[0]
	def unpack_double(self):
		return struct.unpack('!d', self.pop_bytes(8))[0]
	def unpack_padded_string(self, size):
		return self.pop_bytes(size).split(b'\x00', 1)[0].decode(encoding=fgms_string_encoding)
	
	## High-level property packing
	
	def pack_property(self, prop_code, prop_value, legacy_protocol):
		prop_name, prop_type_v1, prop_type_v2 = FGMS_properties[prop_code]
		if legacy_protocol or prop_type_v2 == FgmsType.V2_LikeV1:
			prop_type = prop_type_v1
		else: # use v2 encoding
			prop_type = prop_type_v2
		buf = PacketData()
		if not legacy_protocol and prop_type in FgmsType.v2_tightly_packed_types: # TIGHT: pack code and value in same 4-byte int
			if prop_type == FgmsType.V2_ShortInt or prop_type == FgmsType.V1_Bool:
				if prop_type == FgmsType.V2_ShortInt:
					if prop_value > 0xffff:
						raise ValueError('Short int v2 prop %d overflow: %d; discarded.' % (prop_code, prop_value))
					right_value = prop_value
				else: # prop_value is a bool
					right_value = int(prop_value)
			elif prop_type == FgmsType.V2_ShortFloatNorm:
				right_value = scaled_float(prop_value, 32767)
			elif prop_type == FgmsType.V2_ShortFloat1:
				right_value = scaled_float(prop_value, 10)
			elif prop_type == FgmsType.V2_ShortFloat2:
				right_value = scaled_float(prop_value, 100)
			elif prop_type == FgmsType.V2_ShortFloat3:
				right_value = scaled_float(prop_value, 1000)
			elif prop_type == FgmsType.V2_ShortFloat4:
				right_value = scaled_float(prop_value, 10000)
			elif prop_type == FgmsType.V1_String:
				right_value = len(prop_value)
			else:
				raise ValueError('Unhandled tight packing of prop %d' % prop_code)
			buf.pack_int(prop_code << 16 | right_value)
			if prop_type == FgmsType.V1_String: # v2 string contents still to pack
				buf.append_bytes(bytes(prop_value, encoding=fgms_string_encoding))
		else: # LEGACY: pack property code first, then its value separately
			buf.pack_int(prop_code)
			if prop_type == FgmsType.V1_Bool:
				buf.pack_int(int(prop_value))
			elif prop_type == FgmsType.V1_Float:
				buf.pack_float(prop_value)
			elif prop_type == FgmsType.V1_Int:
				buf.pack_int(prop_value)
			elif prop_type == FgmsType.V1_String:
				strbuf = PacketData()
				for c in prop_value:
					strbuf.pack_int(ord(c))
				strbuf.pad(16)
				buf.pack_int(len(prop_value))
				buf.append_packed(strbuf)
			else: # ATC-pie should not need to send: V2_NoSend, V2_BoolArray
				raise ValueError('Unhandled legacy-style packing of prop %d' % prop_code)
		self.append_packed(buf)
	
	## High-level property unpacking
	
	def unpack_property(self, is_protocol_version_2):
		"""
		This method returns either:
		- a (code, value) pair when a unique FG property is unpacked from the data;
		- or (-1, assoc_dict) when an array of properties is unpacked, e.g. a v2 "bool array"
		  (the dict in this case associates prop code keys to their respective values).
		"""
		unpacked_first = self.unpack_int()
		#DEBUGprint('Unpacking int %d ' % unpacked_first, end='')
		right_value = None
		try:
			left_value = unpacked_first >> 16
			if left_value == 0:  # recognise legacy encoding of property
				prop_code = unpacked_first
				if is_protocol_version_2 and FGMS_properties[prop_code][2] != FgmsType.V2_LikeV1:
					prop_type = FGMS_properties[prop_code][2]
				else:
					prop_type = FGMS_properties[prop_code][1]
			else:  # recognising v2 tight encoding (code on the first two bytes, value in the low half)
				prop_code = left_value
				prop_type = FGMS_properties[prop_code][2]
				if prop_type == FgmsType.V2_LikeV1:
					prop_type = FGMS_properties[prop_code][1]
				if prop_type not in FgmsType.v2_tightly_packed_types:
					raise ValueError('Unrecognised property in 4-byte value %d' % unpacked_first)
				right_value = unpacked_first & 0xffff
				if right_value & 1 << 15 != 0:  # right-value is negative
					right_value |= ~0xffff
		except KeyError:
			raise ValueError('Unknown property code %d' % prop_code)
		#DEBUGprint('(code %d, type %d)' % (prop_code, prop_type), end='')
		if right_value is None:  # LEGACY: property value still to unpack
			if prop_type == FgmsType.V1_Bool:
				prop_value = bool(self.unpack_int())
			elif prop_type == FgmsType.V1_Float:
				prop_value = self.unpack_float()
			elif prop_type == FgmsType.V1_Int:
				prop_value = self.unpack_int()
			elif prop_type == FgmsType.V1_String:
				nchars = self.unpack_int()
				intbytes = PacketData(self.pop_bytes((((4 * nchars - 1) // 16) + 1) * 16))
				chrlst = []
				for i in range(nchars):
					try:
						chrlst.append(chr(intbytes.unpack_int()))
					except ValueError:
						chrlst.append(dodgy_character_substitute)
				prop_value = ''.join(chrlst)
			elif prop_type == FgmsType.V2_BoolArray and (BOOLARRAY_START_ID <= prop_code <= BOOLARRAY_END_ID):
				prop_value = {}
				bitvect = self.unpack_unsigned_int()
				for i in range(0, 31):
					if prop_code + i in FGMS_properties:
						prop_value[prop_code + i] = bool(bitvect & 1 << i)
				prop_code = -1 # this case returns multiple property values, their codes are the prop_value dict keys
			else:
				raise ValueError('Could not unpack property %d' % prop_code)
		else: # TIGHT: value already unpacked (or its length if type string)
			if prop_type == FgmsType.V1_Bool:
				prop_value = bool(right_value)
			elif prop_type == FgmsType.V1_String:
				prop_value = self.pop_bytes(right_value).decode(encoding=fgms_string_encoding)
			elif prop_type == FgmsType.V2_ShortInt:
				prop_value = right_value
			elif prop_type == FgmsType.V2_ShortFloatNorm:
				prop_value = right_value / 32767
			elif prop_type == FgmsType.V2_ShortFloat1:
				prop_value = right_value / 10
			elif prop_type == FgmsType.V2_ShortFloat2:
				prop_value = right_value / 100
			elif prop_type == FgmsType.V2_ShortFloat3:
				prop_value = right_value / 1000
			elif prop_type == FgmsType.V2_ShortFloat4:
				prop_value = right_value / 10000
			else: # should never be needed
				prop_value = NotImplemented
		#DEBUGprint(' %s style %s = %s' % (('legacy' if right_value is None else 'tight'), FGMS_properties[prop_code][0], prop_value))
		return prop_code, prop_value























# ==============================================================================================

#                                       SENDING & ENCODING

# ==============================================================================================


def mk_fgms_packet(sender_callsign, packet_type, content_data):
	buf = PacketData()
	# Header first (32 bytes)
	buf.append_bytes(b'FGFS') # Magic
	buf.append_bytes(bytes.fromhex('00 01 00 01')) # Protocol version 1.1
	buf.pack_int(packet_type) # Msg type, e.g. position message
	buf.pack_int(32 + len(content_data)) # Length of data
	buf.pack_int(max(settings.radar_range, minimum_FGMS_visibility_range)) # ex-ReplyAddress; see FG devel list msg 35687340
	buf.append_bytes(bytes(4)) # ReplyPort: ignored
	buf.pack_padded_string(8, sender_callsign) # Callsign
	# Append the data
	buf.append_packed(content_data)
	return buf.allData()



def mk_fgms_position_packet(callsign, acft_model, pos_coords, pos_amsl, hdg=0, pitch=0, roll=0, properties=None, legacy=False):
	"""
	pos_coords: EarthCoords
	pos_amsl should be real alt. in feet (not pressure-alt.)
	"""
	buf = PacketData()
	buf.pack_padded_string(96, acft_model) # Aircraft model
	buf.pack_double((realTime() - program_started_at).total_seconds()) # Time
	buf.pack_double(.1) # Lag # WARNING zero value can make some FG clients crash (see SF tickets 1927 and 1942)
	posX, posY, posZ = WGS84_geodetic_to_cartesian_metres(pos_coords, pos_amsl)
	buf.pack_double(posX) # PosX
	buf.pack_double(posY) # PosY
	buf.pack_double(posZ) # PosZ
	oriX, oriY, oriZ = FG_orientation_XYZ(pos_coords, hdg, pitch, roll)
	buf.pack_float(oriX) # OriX
	buf.pack_float(oriY) # OriY
	buf.pack_float(oriZ) # OriZ
	buf.pack_float(0) # VelX
	buf.pack_float(0) # VelY
	buf.pack_float(0) # VelZ
	buf.pack_float(0) # AV1
	buf.pack_float(0) # AV2
	buf.pack_float(0) # AV3
	buf.pack_float(0) # LA1
	buf.pack_float(0) # LA2
	buf.pack_float(0) # LA3
	buf.pack_float(0) # AA1
	buf.pack_float(0) # AA2
	buf.pack_float(0) # AA3
	buf.append_bytes(bytes(4) if legacy else v2_magic_padding) # pad
	# finished position data; now packing properties
	if not legacy:
		buf.pack_property(FGMS_v2_virtual_prop, v2_version_prop_value, False)
	if properties is not None:
		for prop_code, prop_value in properties.items():
			try:
				buf.pack_property(prop_code, prop_value, legacy)
			except ValueError as err:
				print('Error packing property: %s' % err, file=stderr)
	return mk_fgms_packet(callsign, position_message_type_code, buf)








class FgmsSender:
	def __init__(self, socket, srv_address, callsign):
		self.socket = socket
		self.server_address = srv_address
		self.callsign = callsign
		self.current_chat_msg = '' # out of msg queue below
		self.chat_msg_queue = [] # pop first, enqueue at end
		self.chat_msg_send_count = 0
	
	def enqueueTextMsg(self, txt):
		if txt == (self.current_chat_msg if self.chat_msg_queue == [] else self.chat_msg_queue[-1]):
			raise ValueError('FGMS ignores a text message if it is identical to the previous.')
		else:
			self.chat_msg_queue.append(txt)
	
	def sendPositionPacket(self):
		if self.chat_msg_send_count >= minimum_chat_message_send_count and len(self.chat_msg_queue) > 0:
			self.current_chat_msg = self.chat_msg_queue.pop(0)
			self.chat_msg_send_count = 0
		pdct = {
			FGMS_prop_chat_msg: self.current_chat_msg,
			FGMS_prop_ATCpie_version_string: version_string,
			FGMS_prop_ATCpie_social_name: settings.MP_social_name
		}
		freqs = [r.frequency() for r in settings.radios if r.isTransmitting()]
		if settings.publicised_frequency is not None and any(frq.inTune(settings.publicised_frequency) for frq in freqs):
			frq = settings.publicised_frequency # prefer the publicised one if in current transmission
		elif len(freqs) > 0:
			frq = freqs[0]
		else:
			frq = None
		pdct[FGMS_prop_comm_freq_hz] = 0 if frq is None else int(1000000 * frq.MHz())
		if settings.publicised_frequency is not None:
			pdct[FGMS_prop_ATCpie_publicised_freq] = str(settings.publicised_frequency)
		pos = env.radarPos()
		packet = mk_fgms_position_packet(self.callsign, ATCpie_model_string, pos, env.elevation(pos), properties=pdct)
		#DEBUG print('Sending packet with size %d=0x%x bytes. Optional data is: %s' % (len(packet), len(packet), packet.data[228:]))
		try:
			self.socket.sendto(packet, self.server_address)
			self.chat_msg_send_count += 1
		except OSError as error:
			print('Could not send FGMS packet to server. System says: %s' % error, file=stderr)








# ==============================================================================================

#                                      RECEIVING & DECODING

# ==============================================================================================


def decode_FGMS_position_message(packet):
	"""
	Returns a tuple of 8 values decoded from the argument FGMS packet:
	- callsign (FGMS unique identifier)
	- packet header time stamp
	- model string as recognised by current settings
	- position received in header: (EarthCoords, real altitude AMSL in ft)
	- transponder status dict of squawked values
	- the packed text message line if any
	- current radio transmission: None or CommFrequency (pilot keyed in and transmitting)
	- ATC-pie tuple if model recognised (client version, social name, publicised freq), otherwise None
	"""
	buf = PacketData(packet)
	# Header
	got_magic = buf.pop_bytes(4)
	if got_magic != b'FGFS':
		raise ValueError('Bad magic byte sequence: %s' % got_magic)
	got_protocol_version = buf.pop_bytes(4)
	if got_protocol_version != bytes.fromhex('00 01 00 01'):
		raise ValueError('Bad protocol version: %s' % got_protocol_version)
	got_msg_type = buf.pop_bytes(4)
	if got_msg_type != bytes.fromhex('00 00 00 07'):
		raise ValueError('Bad message type: %s' % got_msg_type)
	got_packet_size = buf.unpack_int()
	ignored = buf.unpack_int()
	ignored = buf.unpack_int()
	got_callsign = buf.unpack_padded_string(8)
	
	# Done header; now obligatory data...
	got_model = buf.unpack_padded_string(96)
	got_time = buf.unpack_double()
	got_lag = buf.unpack_double()
	got_posX = buf.unpack_double()
	got_posY = buf.unpack_double()
	got_posZ = buf.unpack_double()
	ignored = buf.pop_bytes(15 * 4) # Ori, Vel, AV, LA, AA triplets
	# REMOVED: old backward compat. allowing for props to start here; now considering padding is padding.
	got_padding = buf.pop_bytes(4) # INFO: packet is a v2 packet if got_padding == v2_magic_padding
	
	fgfs_model = path.basename(got_model)
	if fgfs_model.endswith('.xml'):
		fgfs_model = fgfs_model[:-4]
	res_model = fgfs_model if is_ATC_model(fgfs_model) else ICAO_aircraft_type(fgfs_model)
	res_position = cartesian_metres_to_WGS84_geodetic(got_posX, got_posY, got_posZ)
	
	# Done obligatory data; now property data...
	got_chat_line = got_xpdr_capability = got_transmission_freq = None # from regular (non-generic) properties
	got_social_name = got_publicised_frq = got_version_string = None # specific to ATC-pie (packed in "generic" properties)
	res_xpdr_data = {} # from regular XPDR properties, digested into an XPDR data dict
	
	last_prop_OK = None
	v2_virtual_prop_found = False
	while len(buf) >= 4:
		try:
			prop_code, prop_value = buf.unpack_property(v2_virtual_prop_found)
			if prop_code == FGMS_v2_virtual_prop:
				if prop_value >= v2_version_prop_value:
					v2_virtual_prop_found = True
			elif prop_code == FGMS_prop_chat_msg:
				got_chat_line = prop_value
			elif prop_code == FGMS_prop_comm_freq_hz and prop_value != 0:
				got_transmission_freq = CommFrequency(prop_value / 1000000) # num constructor
			elif prop_code == FGMS_prop_XPDR_capability:
				got_xpdr_capability = prop_value
			elif prop_code == FGMS_prop_XPDR_ident:
				res_xpdr_data[Xpdr.IDENT] = bool(prop_value)
			elif prop_code == FGMS_prop_XPDR_code and prop_value >= 0:
				try: # convert to intended octal code
					res_xpdr_data[Xpdr.CODE] = int(str(prop_value), 8)
				except ValueError: # prop decimal value had an illegal 8 or 9 digit
					pass # ignore property
			elif prop_code == FGMS_prop_XPDR_alt and prop_value > -999:
				res_xpdr_data[Xpdr.ALT] = PressureAlt(prop_value)
			elif prop_code == FGMS_prop_XPDR_ias and prop_value >= 0:
				res_xpdr_data[Xpdr.IAS] = Speed(prop_value)
			elif prop_code == FGMS_prop_XPDR_mach and prop_value >= 0:
				res_xpdr_data[Xpdr.MACH] = prop_value
			elif prop_code == FGMS_prop_XPDR_gnd:
				res_xpdr_data[Xpdr.GND] = prop_value
			elif got_model == ATCpie_model_string: # Read "generic" properties used by ATC-pie
				if prop_code == FGMS_prop_ATCpie_social_name:
					got_social_name = prop_value
				elif prop_code == FGMS_prop_ATCpie_publicised_freq:
					got_publicised_frq = CommFrequency(prop_value) # str constructor
				elif prop_code == FGMS_prop_ATCpie_version_string:
					got_version_string = prop_value
			last_prop_OK = prop_code
		except ValueError as err:
			pass #DEBUGprint('Problem reading property from %s after %s: %s' % (got_callsign, last_prop_OK, err))
	#DEBUG if len(buf) != 0:
	#DEBUG 	print('Bytes left over in packet from %s: %s' % (got_callsign, buf.data))
	# Finish up transponder status...
	if got_xpdr_capability == 2:
		res_xpdr_data[Xpdr.CALLSIGN] = got_callsign
		res_xpdr_data[Xpdr.ACFT] = res_model
	if Xpdr.CODE not in res_xpdr_data:
		res_xpdr_data.clear() # otherwise will show on!
	# done.
	res_atcpie = (got_version_string, got_social_name, got_publicised_frq) if got_model == ATCpie_model_string else None
	return got_callsign, got_time, res_model, res_position, res_xpdr_data, got_chat_line, got_transmission_freq, res_atcpie


























# ==============================================================================================

class FgmsAircraft(Aircraft):
	def __init__(self, identifier, acft_type, init_time_stamp, coords, real_alt):
		Aircraft.__init__(self, identifier, acft_type, coords, real_alt)
		self.latest_time_stamp = init_time_stamp
		self.ATCpie_social_name = None
		self.ATCpie_publicised_frequency = None
		self.last_chat_message_read = None
		self.last_radio_transmit_freq = None
	
	def isRadarVisible(self): # overriding method
		return Aircraft.isRadarVisible(self) and settings.session_manager.clockTime() - self.lastLiveUpdateTime() <= FGMS_live_ACFT_time

	def isZombie(self):
		return settings.session_manager.clockTime() - self.lastLiveUpdateTime() > FGMS_connection_timeout
	
	def digestTextMsg(self, msg):
		if msg != self.last_chat_message_read:
			self.last_chat_message_read = msg
			signals.incomingTextRadioMsg.emit(TextMessage(self.identifier, msg))
	
	def digestRadioTransmission(self, frq):
		if frq is not None: # check for signal strength
			if env.rdf.antennaPos()[0].distanceTo(self.liveCoords()) > self.liveRealAlt() / 100 + los_min_dist:
				# FUTURE change condition to "signal too weak" (read FGMS_prop_comm_signal_power in packet)
				# NOTE though: this is all only in the fallback case of FGCom NOT enabled, so is it worth the effort?
				# For now: we have about as much NMs of radio propagation as FL units for the ACFT
				frq = None
		if frq is not None and (self.last_radio_transmit_freq is None or not frq.inTune(self.last_radio_transmit_freq)):
			self.setPtt(frq) # aircraft beginning transmission on (or switched to) a new frequency
		elif frq is None and self.last_radio_transmit_freq is not None: # aircraft stopped transmitting
			self.resetPtt()
		self.last_radio_transmit_freq = frq



def update_FgmsAircraft_list(ACFT_lst, udp_packet):
	try:
		fgms_identifier, time_stamp, model, position, xpdr_data, chat_msg, \
				radio_transmission, atcpie_specific = decode_FGMS_position_message(udp_packet)
		pos_coords, pos_alt = position
	except ValueError as err:
		print('Error decoding FGMS packet: %s' % err, file=stderr)
		return
	try: # Try finding connected aircraft
		fgms_acft = next(acft for acft in ACFT_lst if acft.identifier == fgms_identifier)
	except StopIteration: # Aircraft not found; create it
		fgms_acft = FgmsAircraft(fgms_identifier, model, time_stamp, pos_coords, pos_alt)
		ACFT_lst.append(fgms_acft)
	else: # ACFT was found and needs updating
		# Time stamp
		if fgms_acft.latest_time_stamp - timestamp_ignore_maxdiff < time_stamp < fgms_acft.latest_time_stamp:
			return # Drop unordered UDP packet
		else:
			fgms_acft.latest_time_stamp = time_stamp
		# Aircraft model (though change of model string is unlikely)
		fgms_acft.aircraft_type = model
	if atcpie_specific is not None:
		atcpie_version, social_name, pub_freq = atcpie_specific
		#DEBUGprint(fgms_identifier, atcpie_version)
		fgms_acft.ATCpie_social_name = social_name
		fgms_acft.ATCpie_publicised_frequency = pub_freq
	fgms_acft.updateLiveStatus(pos_coords, pos_alt, xpdr_data)
	if chat_msg is not None and chat_msg != '':
		fgms_acft.digestTextMsg(chat_msg)
	if not settings.FGCom_enabled:
		fgms_acft.digestRadioTransmission(radio_transmission) # salvage RDF from aircraft FGMS data












## ======= FGFS property code definitions =======

BOOLARRAY_BLOCKSIZE = 40
BOOLARRAY_BASE_1 = 11000
BOOLARRAY_BASE_2 = BOOLARRAY_BASE_1 + BOOLARRAY_BLOCKSIZE
BOOLARRAY_BASE_3 = BOOLARRAY_BASE_2 + BOOLARRAY_BLOCKSIZE
BOOLARRAY_START_ID = BOOLARRAY_BASE_1
BOOLARRAY_END_ID = BOOLARRAY_BASE_3

V2018_1_BASE = 11990
EMESARYBRIDGETYPE_BASE = 12200  # EMESARY_BRIDGE_TYPE_BASE
EMESARYBRIDGE_BASE = 12000  # EMESARY_BRIDGE_BASE
V2018_3_BASE = 13000
FALLBACK_MODEL_ID = 13000
V2019_3_BASE = 13001
V2020_4_BASE = 13003


FGMS_properties = { # FGMS property ID: (prop name, v1 type, v2 type)
	10: ('sim/multiplay/protocol-version', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	
	100: ('surface-positions/left-aileron-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	101: ('surface-positions/right-aileron-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	102: ('surface-positions/elevator-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	103: ('surface-positions/rudder-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	104: ('surface-positions/flap-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	105: ('surface-positions/speedbrake-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	106: ('gear/tailhook/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	107: ('gear/launchbar/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	108: ('gear/launchbar/state', FgmsType.V1_String, FgmsType.V2_LikeV1), # cf. property 120
	109: ('gear/launchbar/holdback-position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	110: ('canopy/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	111: ('surface-positions/wing-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	112: ('surface-positions/wing-fold-pos-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	
	120: ('gear/launchbar/state-value', FgmsType.V1_Int, FgmsType.V2_NoSend), # cf. property 108

	200: ('gear/gear[0]/compression-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	201: ('gear/gear[0]/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	210: ('gear/gear[1]/compression-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	211: ('gear/gear[1]/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	220: ('gear/gear[2]/compression-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	221: ('gear/gear[2]/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	230: ('gear/gear[3]/compression-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	231: ('gear/gear[3]/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	240: ('gear/gear[4]/compression-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),
	241: ('gear/gear[4]/position-norm', FgmsType.V1_Float, FgmsType.V2_ShortFloatNorm),

	300: ('engines/engine[0]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	301: ('engines/engine[0]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	302: ('engines/engine[0]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	310: ('engines/engine[1]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	311: ('engines/engine[1]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	312: ('engines/engine[1]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	320: ('engines/engine[2]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	321: ('engines/engine[2]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	322: ('engines/engine[2]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	330: ('engines/engine[3]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	331: ('engines/engine[3]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	332: ('engines/engine[3]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	340: ('engines/engine[4]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	341: ('engines/engine[4]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	342: ('engines/engine[4]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	350: ('engines/engine[5]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	351: ('engines/engine[5]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	352: ('engines/engine[5]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	360: ('engines/engine[6]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	361: ('engines/engine[6]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	362: ('engines/engine[6]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	370: ('engines/engine[7]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	371: ('engines/engine[7]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	372: ('engines/engine[7]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	380: ('engines/engine[8]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	381: ('engines/engine[8]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	382: ('engines/engine[8]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	390: ('engines/engine[9]/n1', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	391: ('engines/engine[9]/n2', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	392: ('engines/engine[9]/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),

	800: ('rotors/main/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	801: ('rotors/tail/rpm', FgmsType.V1_Float, FgmsType.V2_ShortFloat1),
	810: ('rotors/main/blade[0]/position-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	811: ('rotors/main/blade[1]/position-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	812: ('rotors/main/blade[2]/position-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	813: ('rotors/main/blade[3]/position-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	820: ('rotors/main/blade[0]/flap-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	821: ('rotors/main/blade[1]/flap-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	822: ('rotors/main/blade[2]/flap-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	823: ('rotors/main/blade[3]/flap-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	830: ('rotors/tail/blade[0]/position-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	831: ('rotors/tail/blade[1]/position-deg', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),

	900: ('sim/hitches/aerotow/tow/length', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	901: ('sim/hitches/aerotow/tow/elastic-constant', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	902: ('sim/hitches/aerotow/tow/weight-per-m-kg-m', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	903: ('sim/hitches/aerotow/tow/dist', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	904: ('sim/hitches/aerotow/tow/connected-to-property-node', FgmsType.V1_Bool, FgmsType.V2_LikeV1),
	905: ('sim/hitches/aerotow/tow/connected-to-ai-or-mp-callsign', FgmsType.V1_String, FgmsType.V2_LikeV1),
	906: ('sim/hitches/aerotow/tow/brake-force', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	907: ('sim/hitches/aerotow/tow/end-force-x', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	908: ('sim/hitches/aerotow/tow/end-force-y', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	909: ('sim/hitches/aerotow/tow/end-force-z', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	930: ('sim/hitches/aerotow/is-slave', FgmsType.V1_Bool, FgmsType.V2_LikeV1),
	931: ('sim/hitches/aerotow/speed-in-tow-direction', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	932: ('sim/hitches/aerotow/open', FgmsType.V1_Bool, FgmsType.V2_LikeV1),
	933: ('sim/hitches/aerotow/local-pos-x', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	934: ('sim/hitches/aerotow/local-pos-y', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	935: ('sim/hitches/aerotow/local-pos-z', FgmsType.V1_Float, FgmsType.V2_LikeV1),

	1001: ('controls/flight/slats', FgmsType.V1_Float, FgmsType.V2_ShortFloat4),
	1002: ('controls/flight/speedbrake', FgmsType.V1_Float, FgmsType.V2_ShortFloat4),
	1003: ('controls/flight/spoilers', FgmsType.V1_Float, FgmsType.V2_ShortFloat4),
	1004: ('controls/gear/gear-down', FgmsType.V1_Float, FgmsType.V2_ShortFloat4),
	1005: ('controls/lighting/nav-lights', FgmsType.V1_Float, FgmsType.V2_ShortFloat3),
	1006: ('controls/armament/station[0]/jettison-all', FgmsType.V1_Bool, FgmsType.V2_ShortInt),

	1100: ('sim/model/variant', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	1101: ('sim/model/livery/file', FgmsType.V1_String, FgmsType.V2_LikeV1),

	1200: ('environment/wildfire/data', FgmsType.V1_String, FgmsType.V2_LikeV1),
	1201: ('environment/contrail', FgmsType.V1_Int, FgmsType.V2_ShortInt),

	1300: ('tanker', FgmsType.V1_Int, FgmsType.V2_ShortInt),

	1400: ('scenery/events', FgmsType.V1_String, FgmsType.V2_LikeV1),

	1500: ('instrumentation/transponder/transmitted-id', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	1501: ('instrumentation/transponder/altitude', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	1502: ('instrumentation/transponder/ident', FgmsType.V1_Bool, FgmsType.V2_ShortInt),
	1503: ('instrumentation/transponder/inputs/mode', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	1504: ('instrumentation/transponder/ground-bit', FgmsType.V1_Bool, FgmsType.V2_ShortInt),
	1505: ('instrumentation/transponder/airspeed-kt', FgmsType.V1_Int, FgmsType.V2_ShortInt),

	10001: ('sim/multiplay/transmission-freq-hz', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10002: ('sim/multiplay/chat', FgmsType.V1_String, FgmsType.V2_LikeV1),

	10100: ('sim/multiplay/generic/string[0]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10101: ('sim/multiplay/generic/string[1]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10102: ('sim/multiplay/generic/string[2]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10103: ('sim/multiplay/generic/string[3]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10104: ('sim/multiplay/generic/string[4]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10105: ('sim/multiplay/generic/string[5]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10106: ('sim/multiplay/generic/string[6]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10107: ('sim/multiplay/generic/string[7]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10108: ('sim/multiplay/generic/string[8]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10109: ('sim/multiplay/generic/string[9]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10110: ('sim/multiplay/generic/string[10]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10111: ('sim/multiplay/generic/string[11]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10112: ('sim/multiplay/generic/string[12]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10113: ('sim/multiplay/generic/string[13]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10114: ('sim/multiplay/generic/string[14]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10115: ('sim/multiplay/generic/string[15]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10116: ('sim/multiplay/generic/string[16]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10117: ('sim/multiplay/generic/string[17]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10118: ('sim/multiplay/generic/string[18]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	10119: ('sim/multiplay/generic/string[19]', FgmsType.V1_String, FgmsType.V2_LikeV1),

	10200: ('sim/multiplay/generic/float[0]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10201: ('sim/multiplay/generic/float[1]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10202: ('sim/multiplay/generic/float[2]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10203: ('sim/multiplay/generic/float[3]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10204: ('sim/multiplay/generic/float[4]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10205: ('sim/multiplay/generic/float[5]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10206: ('sim/multiplay/generic/float[6]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10207: ('sim/multiplay/generic/float[7]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10208: ('sim/multiplay/generic/float[8]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10209: ('sim/multiplay/generic/float[9]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10210: ('sim/multiplay/generic/float[10]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10211: ('sim/multiplay/generic/float[11]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10212: ('sim/multiplay/generic/float[12]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10213: ('sim/multiplay/generic/float[13]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10214: ('sim/multiplay/generic/float[14]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10215: ('sim/multiplay/generic/float[15]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10216: ('sim/multiplay/generic/float[16]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10217: ('sim/multiplay/generic/float[17]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10218: ('sim/multiplay/generic/float[18]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10219: ('sim/multiplay/generic/float[19]', FgmsType.V1_Float, FgmsType.V2_LikeV1),

	10220: ('sim/multiplay/generic/float[20]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10221: ('sim/multiplay/generic/float[21]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10222: ('sim/multiplay/generic/float[22]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10223: ('sim/multiplay/generic/float[23]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10224: ('sim/multiplay/generic/float[24]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10225: ('sim/multiplay/generic/float[25]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10226: ('sim/multiplay/generic/float[26]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10227: ('sim/multiplay/generic/float[27]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10228: ('sim/multiplay/generic/float[28]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10229: ('sim/multiplay/generic/float[29]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10230: ('sim/multiplay/generic/float[30]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10231: ('sim/multiplay/generic/float[31]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10232: ('sim/multiplay/generic/float[32]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10233: ('sim/multiplay/generic/float[33]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10234: ('sim/multiplay/generic/float[34]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10235: ('sim/multiplay/generic/float[35]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10236: ('sim/multiplay/generic/float[36]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10237: ('sim/multiplay/generic/float[37]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10238: ('sim/multiplay/generic/float[38]', FgmsType.V1_Float, FgmsType.V2_LikeV1),
	10239: ('sim/multiplay/generic/float[39]', FgmsType.V1_Float, FgmsType.V2_LikeV1),

	10300: ('sim/multiplay/generic/int[0]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10301: ('sim/multiplay/generic/int[1]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10302: ('sim/multiplay/generic/int[2]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10303: ('sim/multiplay/generic/int[3]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10304: ('sim/multiplay/generic/int[4]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10305: ('sim/multiplay/generic/int[5]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10306: ('sim/multiplay/generic/int[6]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10307: ('sim/multiplay/generic/int[7]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10308: ('sim/multiplay/generic/int[8]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10309: ('sim/multiplay/generic/int[9]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10310: ('sim/multiplay/generic/int[10]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10311: ('sim/multiplay/generic/int[11]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10312: ('sim/multiplay/generic/int[12]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10313: ('sim/multiplay/generic/int[13]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10314: ('sim/multiplay/generic/int[14]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10315: ('sim/multiplay/generic/int[15]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10316: ('sim/multiplay/generic/int[16]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10317: ('sim/multiplay/generic/int[17]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10318: ('sim/multiplay/generic/int[18]', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	10319: ('sim/multiplay/generic/int[19]', FgmsType.V1_Int, FgmsType.V2_LikeV1),

	10500: ('sim/multiplay/generic/short[0]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10501: ('sim/multiplay/generic/short[1]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10502: ('sim/multiplay/generic/short[2]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10503: ('sim/multiplay/generic/short[3]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10504: ('sim/multiplay/generic/short[4]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10505: ('sim/multiplay/generic/short[5]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10506: ('sim/multiplay/generic/short[6]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10507: ('sim/multiplay/generic/short[7]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10508: ('sim/multiplay/generic/short[8]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10509: ('sim/multiplay/generic/short[9]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10510: ('sim/multiplay/generic/short[10]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10511: ('sim/multiplay/generic/short[11]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10512: ('sim/multiplay/generic/short[12]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10513: ('sim/multiplay/generic/short[13]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10514: ('sim/multiplay/generic/short[14]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10515: ('sim/multiplay/generic/short[15]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10516: ('sim/multiplay/generic/short[16]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10517: ('sim/multiplay/generic/short[17]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10518: ('sim/multiplay/generic/short[18]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10519: ('sim/multiplay/generic/short[19]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10520: ('sim/multiplay/generic/short[20]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10521: ('sim/multiplay/generic/short[21]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10522: ('sim/multiplay/generic/short[22]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10523: ('sim/multiplay/generic/short[23]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10524: ('sim/multiplay/generic/short[24]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10525: ('sim/multiplay/generic/short[25]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10526: ('sim/multiplay/generic/short[26]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10527: ('sim/multiplay/generic/short[27]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10528: ('sim/multiplay/generic/short[28]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10529: ('sim/multiplay/generic/short[29]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10530: ('sim/multiplay/generic/short[30]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10531: ('sim/multiplay/generic/short[31]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10532: ('sim/multiplay/generic/short[32]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10533: ('sim/multiplay/generic/short[33]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10534: ('sim/multiplay/generic/short[34]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10535: ('sim/multiplay/generic/short[35]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10536: ('sim/multiplay/generic/short[36]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10537: ('sim/multiplay/generic/short[37]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10538: ('sim/multiplay/generic/short[38]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10539: ('sim/multiplay/generic/short[39]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10540: ('sim/multiplay/generic/short[40]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10541: ('sim/multiplay/generic/short[41]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10542: ('sim/multiplay/generic/short[42]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10543: ('sim/multiplay/generic/short[43]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10544: ('sim/multiplay/generic/short[44]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10545: ('sim/multiplay/generic/short[45]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10546: ('sim/multiplay/generic/short[46]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10547: ('sim/multiplay/generic/short[47]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10548: ('sim/multiplay/generic/short[48]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10549: ('sim/multiplay/generic/short[49]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10550: ('sim/multiplay/generic/short[50]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10551: ('sim/multiplay/generic/short[51]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10552: ('sim/multiplay/generic/short[52]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10553: ('sim/multiplay/generic/short[53]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10554: ('sim/multiplay/generic/short[54]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10555: ('sim/multiplay/generic/short[55]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10556: ('sim/multiplay/generic/short[56]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10557: ('sim/multiplay/generic/short[57]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10558: ('sim/multiplay/generic/short[58]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10559: ('sim/multiplay/generic/short[59]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10560: ('sim/multiplay/generic/short[60]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10561: ('sim/multiplay/generic/short[61]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10562: ('sim/multiplay/generic/short[62]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10563: ('sim/multiplay/generic/short[63]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10564: ('sim/multiplay/generic/short[64]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10565: ('sim/multiplay/generic/short[65]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10566: ('sim/multiplay/generic/short[66]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10567: ('sim/multiplay/generic/short[67]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10568: ('sim/multiplay/generic/short[68]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10569: ('sim/multiplay/generic/short[69]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10570: ('sim/multiplay/generic/short[70]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10571: ('sim/multiplay/generic/short[71]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10572: ('sim/multiplay/generic/short[72]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10573: ('sim/multiplay/generic/short[73]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10574: ('sim/multiplay/generic/short[74]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10575: ('sim/multiplay/generic/short[75]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10576: ('sim/multiplay/generic/short[76]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10577: ('sim/multiplay/generic/short[77]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10578: ('sim/multiplay/generic/short[78]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	10579: ('sim/multiplay/generic/short[79]', FgmsType.V1_Int, FgmsType.V2_ShortInt),

	BOOLARRAY_BASE_1 +  0: ('sim/multiplay/generic/bool[0]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  1: ('sim/multiplay/generic/bool[1]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  2: ('sim/multiplay/generic/bool[2]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  3: ('sim/multiplay/generic/bool[3]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  4: ('sim/multiplay/generic/bool[4]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  5: ('sim/multiplay/generic/bool[5]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  6: ('sim/multiplay/generic/bool[6]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  7: ('sim/multiplay/generic/bool[7]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  8: ('sim/multiplay/generic/bool[8]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 +  9: ('sim/multiplay/generic/bool[9]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 10: ('sim/multiplay/generic/bool[10]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 11: ('sim/multiplay/generic/bool[11]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 12: ('sim/multiplay/generic/bool[12]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 13: ('sim/multiplay/generic/bool[13]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 14: ('sim/multiplay/generic/bool[14]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 15: ('sim/multiplay/generic/bool[15]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 16: ('sim/multiplay/generic/bool[16]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 17: ('sim/multiplay/generic/bool[17]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 18: ('sim/multiplay/generic/bool[18]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 19: ('sim/multiplay/generic/bool[19]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 20: ('sim/multiplay/generic/bool[20]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 21: ('sim/multiplay/generic/bool[21]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 22: ('sim/multiplay/generic/bool[22]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 23: ('sim/multiplay/generic/bool[23]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 24: ('sim/multiplay/generic/bool[24]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 25: ('sim/multiplay/generic/bool[25]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 26: ('sim/multiplay/generic/bool[26]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 27: ('sim/multiplay/generic/bool[27]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 28: ('sim/multiplay/generic/bool[28]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 29: ('sim/multiplay/generic/bool[29]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_1 + 30: ('sim/multiplay/generic/bool[30]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),

	BOOLARRAY_BASE_2 + 0: ('sim/multiplay/generic/bool[31]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 1: ('sim/multiplay/generic/bool[32]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 2: ('sim/multiplay/generic/bool[33]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 3: ('sim/multiplay/generic/bool[34]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 4: ('sim/multiplay/generic/bool[35]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 5: ('sim/multiplay/generic/bool[36]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 6: ('sim/multiplay/generic/bool[37]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 7: ('sim/multiplay/generic/bool[38]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 8: ('sim/multiplay/generic/bool[39]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 9: ('sim/multiplay/generic/bool[40]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 10: ('sim/multiplay/generic/bool[41]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 11: ('sim/multiplay/generic/bool[91]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 12: ('sim/multiplay/generic/bool[42]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 13: ('sim/multiplay/generic/bool[43]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 14: ('sim/multiplay/generic/bool[44]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 15: ('sim/multiplay/generic/bool[45]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 16: ('sim/multiplay/generic/bool[46]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 17: ('sim/multiplay/generic/bool[47]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 18: ('sim/multiplay/generic/bool[48]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 19: ('sim/multiplay/generic/bool[49]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 20: ('sim/multiplay/generic/bool[50]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 21: ('sim/multiplay/generic/bool[51]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 22: ('sim/multiplay/generic/bool[52]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 23: ('sim/multiplay/generic/bool[53]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 24: ('sim/multiplay/generic/bool[54]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 25: ('sim/multiplay/generic/bool[55]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 26: ('sim/multiplay/generic/bool[56]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 27: ('sim/multiplay/generic/bool[57]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 28: ('sim/multiplay/generic/bool[58]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 29: ('sim/multiplay/generic/bool[59]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_2 + 30: ('sim/multiplay/generic/bool[60]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),

	BOOLARRAY_BASE_3 + 0: ('sim/multiplay/generic/bool[61]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 1: ('sim/multiplay/generic/bool[62]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 2: ('sim/multiplay/generic/bool[63]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 3: ('sim/multiplay/generic/bool[64]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 4: ('sim/multiplay/generic/bool[65]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 5: ('sim/multiplay/generic/bool[66]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 6: ('sim/multiplay/generic/bool[67]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 7: ('sim/multiplay/generic/bool[68]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 8: ('sim/multiplay/generic/bool[69]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 9: ('sim/multiplay/generic/bool[70]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 10: ('sim/multiplay/generic/bool[71]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 11: ('sim/multiplay/generic/bool[92]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 12: ('sim/multiplay/generic/bool[72]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 13: ('sim/multiplay/generic/bool[73]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 14: ('sim/multiplay/generic/bool[74]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 15: ('sim/multiplay/generic/bool[75]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 16: ('sim/multiplay/generic/bool[76]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 17: ('sim/multiplay/generic/bool[77]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 18: ('sim/multiplay/generic/bool[78]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 19: ('sim/multiplay/generic/bool[79]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 20: ('sim/multiplay/generic/bool[80]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 21: ('sim/multiplay/generic/bool[81]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 22: ('sim/multiplay/generic/bool[82]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 23: ('sim/multiplay/generic/bool[83]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 24: ('sim/multiplay/generic/bool[84]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 25: ('sim/multiplay/generic/bool[85]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 26: ('sim/multiplay/generic/bool[86]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 27: ('sim/multiplay/generic/bool[87]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 28: ('sim/multiplay/generic/bool[88]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 29: ('sim/multiplay/generic/bool[89]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	BOOLARRAY_BASE_3 + 30: ('sim/multiplay/generic/bool[90]', FgmsType.V1_Bool, FgmsType.V2_BoolArray),
	
	V2018_1_BASE + 0: ('sim/multiplay/mp-clock-mode', FgmsType.V1_Int, FgmsType.V2_ShortInt),

	EMESARYBRIDGE_BASE + 0: ('sim/multiplay/emesary/bridge[0]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 1: ('sim/multiplay/emesary/bridge[1]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 2: ('sim/multiplay/emesary/bridge[2]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 3: ('sim/multiplay/emesary/bridge[3]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 4: ('sim/multiplay/emesary/bridge[4]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 5: ('sim/multiplay/emesary/bridge[5]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 6: ('sim/multiplay/emesary/bridge[6]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 7: ('sim/multiplay/emesary/bridge[7]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 8: ('sim/multiplay/emesary/bridge[8]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 9: ('sim/multiplay/emesary/bridge[9]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 10: ('sim/multiplay/emesary/bridge[10]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 11: ('sim/multiplay/emesary/bridge[11]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 12: ('sim/multiplay/emesary/bridge[12]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 13: ('sim/multiplay/emesary/bridge[13]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 14: ('sim/multiplay/emesary/bridge[14]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 15: ('sim/multiplay/emesary/bridge[15]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 16: ('sim/multiplay/emesary/bridge[16]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 17: ('sim/multiplay/emesary/bridge[17]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 18: ('sim/multiplay/emesary/bridge[18]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 19: ('sim/multiplay/emesary/bridge[19]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 20: ('sim/multiplay/emesary/bridge[20]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 21: ('sim/multiplay/emesary/bridge[21]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 22: ('sim/multiplay/emesary/bridge[22]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 23: ('sim/multiplay/emesary/bridge[23]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 24: ('sim/multiplay/emesary/bridge[24]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 25: ('sim/multiplay/emesary/bridge[25]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 26: ('sim/multiplay/emesary/bridge[26]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 27: ('sim/multiplay/emesary/bridge[27]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 28: ('sim/multiplay/emesary/bridge[28]', FgmsType.V1_String, FgmsType.V2_LikeV1),
	EMESARYBRIDGE_BASE + 29: ('sim/multiplay/emesary/bridge[29]', FgmsType.V1_String, FgmsType.V2_LikeV1),

	EMESARYBRIDGETYPE_BASE + 0: ('sim/multiplay/emesary/bridge-type[0]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 1: ('sim/multiplay/emesary/bridge-type[1]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 2: ('sim/multiplay/emesary/bridge-type[2]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 3: ('sim/multiplay/emesary/bridge-type[3]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 4: ('sim/multiplay/emesary/bridge-type[4]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 5: ('sim/multiplay/emesary/bridge-type[5]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 6: ('sim/multiplay/emesary/bridge-type[6]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 7: ('sim/multiplay/emesary/bridge-type[7]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 8: ('sim/multiplay/emesary/bridge-type[8]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 9: ('sim/multiplay/emesary/bridge-type[9]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 10: ('sim/multiplay/emesary/bridge-type[10]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 11: ('sim/multiplay/emesary/bridge-type[11]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 12: ('sim/multiplay/emesary/bridge-type[12]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 13: ('sim/multiplay/emesary/bridge-type[13]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 14: ('sim/multiplay/emesary/bridge-type[14]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 15: ('sim/multiplay/emesary/bridge-type[15]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 16: ('sim/multiplay/emesary/bridge-type[16]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 17: ('sim/multiplay/emesary/bridge-type[17]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 18: ('sim/multiplay/emesary/bridge-type[18]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 19: ('sim/multiplay/emesary/bridge-type[19]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 20: ('sim/multiplay/emesary/bridge-type[20]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 21: ('sim/multiplay/emesary/bridge-type[21]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 22: ('sim/multiplay/emesary/bridge-type[22]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 23: ('sim/multiplay/emesary/bridge-type[23]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 24: ('sim/multiplay/emesary/bridge-type[24]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 25: ('sim/multiplay/emesary/bridge-type[25]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 26: ('sim/multiplay/emesary/bridge-type[26]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 27: ('sim/multiplay/emesary/bridge-type[27]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 28: ('sim/multiplay/emesary/bridge-type[28]', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	EMESARYBRIDGETYPE_BASE + 29: ('sim/multiplay/emesary/bridge-type[29]', FgmsType.V1_Int, FgmsType.V2_ShortInt),

	FALLBACK_MODEL_ID: ('sim/model/fallback-model-index', FgmsType.V1_Int, FgmsType.V2_ShortInt),
	V2019_3_BASE: ('sim/multiplay/comm-transmit-frequency-hz', FgmsType.V1_Int, FgmsType.V2_LikeV1),
	V2019_3_BASE + 1: ('sim/multiplay/comm-transmit-power-norm', FgmsType.V1_Int, FgmsType.V2_ShortFloatNorm),
	V2020_4_BASE: ('instrumentation/transponder/mach-number', FgmsType.V1_Float, FgmsType.V2_ShortFloat4)
}

FGMS_v2_virtual_prop = FGMS_prop_code_by_name('sim/multiplay/protocol-version')

# Relevant properties from ATC's PoV
FGMS_prop_XPDR_capability = FGMS_prop_code_by_name('instrumentation/transponder/inputs/mode')
FGMS_prop_XPDR_code = FGMS_prop_code_by_name('instrumentation/transponder/transmitted-id')
FGMS_prop_XPDR_alt = FGMS_prop_code_by_name('instrumentation/transponder/altitude')
FGMS_prop_XPDR_gnd = FGMS_prop_code_by_name('instrumentation/transponder/ground-bit')
FGMS_prop_XPDR_ias = FGMS_prop_code_by_name('instrumentation/transponder/airspeed-kt')
FGMS_prop_XPDR_mach = FGMS_prop_code_by_name('instrumentation/transponder/mach-number')
FGMS_prop_XPDR_ident = FGMS_prop_code_by_name('instrumentation/transponder/ident')
FGMS_prop_chat_msg = FGMS_prop_code_by_name('sim/multiplay/chat')
FGMS_prop_comm_freq_hz = FGMS_prop_code_by_name('sim/multiplay/comm-transmit-frequency-hz')
FGMS_prop_comm_signal_power = FGMS_prop_code_by_name('sim/multiplay/comm-transmit-power-norm')
FGMS_prop_helo_main_rotor = FGMS_prop_code_by_name('rotors/main/rpm')
FGMS_prop_helo_tail_rotor = FGMS_prop_code_by_name('rotors/tail/rpm')

# Prop's specific to ATC-pie
FGMS_prop_ATCpie_version_string = FGMS_prop_code_by_name('sim/multiplay/generic/string[0]')
FGMS_prop_ATCpie_social_name = FGMS_prop_code_by_name('sim/multiplay/generic/string[1]')
FGMS_prop_ATCpie_publicised_freq = FGMS_prop_code_by_name('sim/multiplay/generic/string[2]')



## ======= FGFS orientation conversions =======

epsilon = 1e-8

def wxyz_quat_mult(q1, q2):
	w1, x1, y1, z1 = q1
	w2, x2, y2, z2 = q2
	w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
	x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
	y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2
	z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
	return w, x, y, z

def earth2quat(coords):
	zd2 = radians(coords.lon) / 2
	yd2 = -pi / 4 - radians(coords.lat) / 2
	Szd2 = sin(zd2)
	Syd2 = sin(yd2)
	Czd2 = cos(zd2)
	Cyd2 = cos(yd2)
	w = Czd2 * Cyd2
	x = -Szd2 * Syd2
	y = Czd2 * Syd2
	z = Szd2 * Cyd2
	return w, x, y, z

def euler2quat(z, y, x):
	zd2 = z / 2
	yd2 = y / 2
	xd2 = x / 2
	Szd2 = sin(zd2)
	Syd2 = sin(yd2)
	Sxd2 = sin(xd2)
	Czd2 = cos(zd2)
	Cyd2 = cos(yd2)
	Cxd2 = cos(xd2)
	Cxd2Czd2 = Cxd2 * Czd2
	Cxd2Szd2 = Cxd2 * Szd2
	Sxd2Szd2 = Sxd2 * Szd2
	Sxd2Czd2 = Sxd2 * Czd2
	w = Cxd2Czd2 * Cyd2 + Sxd2Szd2 * Syd2
	x = Sxd2Czd2 * Cyd2 - Cxd2Szd2 * Syd2
	y = Cxd2Czd2 * Syd2 + Sxd2Szd2 * Cyd2
	z = Cxd2Szd2 * Cyd2 - Sxd2Czd2 * Syd2
	return w, x, y, z

def FG_orientation_XYZ(coords, hdg, pitch, roll):
	local_rot = euler2quat(radians(hdg), radians(pitch), radians(roll))
	qw, qx, qy, qz = wxyz_quat_mult(earth2quat(coords), local_rot)
	acw = acos(qw)
	sa = sin(acw)
	if abs(sa) < epsilon:
		return 1, 0, 0 # no rotation
	else:
		angle = 2 * acw
		k = angle / sa
		return k*qx, k*qy, k*qz
