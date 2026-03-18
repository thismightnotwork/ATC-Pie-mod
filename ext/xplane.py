
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
from math import tan, radians

from PyQt5.QtGui import QPainterPath

from base.ad import AirportData, DirRunway, Helipad
from base.coords import EarthCoords
from base.params import Heading
from base.radio import CommFrequency
from base.nav import Navpoint, VOR, NDB, Fix, Rnav, NavpointError, world_navpoint_db, world_routing_db

from session.config import version_string


# ---------- Constants ----------

custom_navaid_file = 'CONFIG/nav/navaid.dat'
custom_navfix_file = 'CONFIG/nav/fix.dat'
custom_airway_file = 'CONFIG/nav/awy.dat'
custom_airport_file_fmt = 'CONFIG/ad/%s.dat'

xplane_file_encoding = 'iso-8859-15'
fallback_navaid_file = 'resources/x-plane/earth_nav.dat'
fallback_navfix_file = 'resources/x-plane/earth_fix.dat'
fallback_airway_file = 'resources/x-plane/earth_awy.dat'
fallback_world_apt_dat_file = 'resources/x-plane/apt.dat'

extracted_ad_pos_file = 'OUTPUT/AD-positions.extract'
extracted_airport_file_fmt = 'OUTPUT/%s.extract'
aptdat_extracted_file_header_line = 'Extracted by ATC-pie %s from the old world-wide "apt.dat" file' % version_string

navpoint_coords_max_dist = 15 # maximum distance at which to accept a waypoint name, in NM from its specified position
ad_ref_point_max_dist = .001 # NM

# -------------------------------


ad_data_files_read = set()


# ============================================== #

#            X-PLANE HELPER FUNCTIONS            #

# ============================================== #

def line_code(line):
	try:
		return int(line.split(maxsplit=1)[0])
	except (IndexError, ValueError):
		return None


def surface_type_str(surface_code):
	if surface_code == 1 or 20 <= surface_code <= 38:
		return 'Asphalt'
	elif surface_code == 2 or 50 <= surface_code <= 57:
		return 'Concrete'
	else:
		return {
			3: 'Turf/grass',
			4: 'Dirt',
			5: 'Gravel',
			12: 'Dry lake bed',
			13: 'Water',
			14: 'Snow/ice',
			#15: 'Transparent'
		}.get(surface_code, 'Unknown')


def is_paved_surface(surface_code):
	return surface_code == 1 or surface_code == 2 or 20 <= surface_code <= 38 or 50 <= surface_code <= 57

def is_xplane_airport_header(line, icao=None):
	return line_code(line) in [1, 16, 17] and (icao is None or line.split(maxsplit=5)[4] == icao)

def is_xplane_node_line(line):
	return line_code(line) in range(111, 117)



def extend_path(path, end_point, prev_bezier, this_bezier):
	if this_bezier is None:
		if prev_bezier is None: # straight line
			path.lineTo(end_point)
		else:                   # bezier curve from last ctrl point
			path.quadTo(prev_bezier, end_point)
	else:
		mirror_ctrl = 2 * end_point - this_bezier
		if prev_bezier is None: # bezier curve to point with ctrl point
			path.quadTo(mirror_ctrl, end_point)
		else:                   # cubic bezier curve using ctrl points on either side
			path.cubicTo(prev_bezier, mirror_ctrl, end_point)



def parse_xplane_node_line(line):
	"""
	returns a 5-value tuple:
	- node position
	- bezier ctrl point if not None
	- int paint type if not None
	- int light type if not None
	- bool if ending node (True if closes path), or None if path goes on
	"""
	if not is_xplane_node_line(line):
		raise ValueError('Not a node line: %s' % line)
	tokens = line.split()
	row_code = tokens[0]
	node_coords = EarthCoords(float(tokens[1]), float(tokens[2])).toQPointF()
	bezier_ctrl = EarthCoords(float(tokens[3]), float(tokens[4])).toQPointF() if row_code in ['112', '114', '116'] else None
	ending_spec = None if row_code in ['111', '112'] else row_code in ['113', '114']
	paint_lights = [int(tk) for tk in tokens[3 if bezier_ctrl is None else 5:]]
	paint_type = next((t for t in paint_lights if t < 100), None)
	light_type = next((t for t in paint_lights if t >= 100), None)
	return node_coords, bezier_ctrl, paint_type, light_type, ending_spec
	


def read_xplane_node_sequence(f, first_line=None):
	"""
	Returns a tuple of:
	 - QPainterPath containing node sequence
	 - paint_sequence (length is same as path if closed; one item shorter otherwise)
	 - bool path is closed
	 - int number of lines read
	"""
	path = QPainterPath()
	lines_read = 0
	line = first_line
	if line is None:
		line = f.readline()
		lines_read += 1
	node, bez, paint, light, end_mode = parse_xplane_node_line(line.strip())
	assert end_mode is None, 'First node of path shold not be an ending node'
	first_node = node
	first_bezier = bez
	paint_sequence = [paint]
	path.moveTo(node)
	prev_bezier = bez
	while line != '':
		node, bez, paint, light, end_mode = parse_xplane_node_line(line.strip())
		extend_path(path, node, prev_bezier, bez)
		prev_bezier = bez
		if end_mode is None: # not yet reached end or loop
			paint_sequence.append(paint)
			line = f.readline()
			lines_read += 1
		else: # end of path reached
			if end_mode: # close loop (back to first point)
				extend_path(path, first_node, bez, first_bezier)
				paint_sequence.append(paint)
			return path, paint_sequence, end_mode, lines_read
	else:
		print('End of file: missing ending node', file=stderr)





def extract_world_AD_positions():
	with open(fallback_world_apt_dat_file, encoding=xplane_file_encoding) as f:
		with open(extracted_ad_pos_file, 'w', encoding='utf8') as exf:
			print('#', aptdat_extracted_file_header_line, file=exf)
			line = f.readline()
			ad_count = 0
			while line != '': # not EOF
				if is_xplane_airport_header(line):
					row_code, ignore1, ignore2, ignore3, icao_code, long_name = line.split(maxsplit=5)
					if icao_code.isalpha(): # Ignoring airports with numbers in them---to many of them, hardly ever useful
						# we are inside the airport section looking for its coordinates
						coords = None
						line = f.readline()
						while line != '' and not is_xplane_airport_header(line):
							# old data; will not contain 1302 row codes with "datum" lat/lon
							if line_code(line) == 14: # X-plane viewpoint, unconditionally used as coords
								row_code, lat, lon, ignore_rest_of_line = line.split(maxsplit=3)
								coords = EarthCoords(float(lat), float(lon))
							elif coords is None and line_code(line) == 100: # falls back near a RWY end if no viewpoint for AD
								tokens = line.split()
								coords = EarthCoords(float(tokens[9]), float(tokens[10])).moved(Heading(360, True), .15)
							line = f.readline()
						if coords is not None: # Airfields with unknown world coordinates are ignored
							print('%s\t%s\t%s' % (icao_code, coords.toString(), long_name.rstrip()), file=exf)
							ad_count += 1
					else:
						line = f.readline()
				else:
					line = f.readline()
			# Terminate with the footer to mark the process as finished
			print(str(ad_count), file=exf)
		print('Extracted default world AD positions file:', extracted_ad_pos_file)


def extract_airport_file(ad_code):
	with open(fallback_world_apt_dat_file, encoding=xplane_file_encoding) as f:
		line = line1 = f.readline()
		while line != '' and not is_xplane_airport_header(line, icao=ad_code):
			line = f.readline()
		if line != '': # not EOF
			output_file_name = extracted_airport_file_fmt % ad_code
			with open(output_file_name, 'w', encoding='utf8') as out:
				out.write(line1)
				out.write(aptdat_extracted_file_header_line + '\n\n')
				out.write(line)
				line = f.readline()
				while line != '' and not is_xplane_airport_header(line):
					out.write(line)
					line = f.readline()
			print('Extracted default data file for %s:' % ad_code, output_file_name)





# =========================================== #

#          NAVIGATION & ROUTING DATA          #

# =========================================== #

def import_navaid_data(err_log_file):
	try:
		f = open(custom_navaid_file, encoding='utf8')
	except FileNotFoundError:
		print('No navaid data provided (%s); falling back on old data.' % custom_navaid_file, file=stderr)
		f = open(fallback_navaid_file, encoding=xplane_file_encoding)
	with f:
		f.readline() # ignore first line
		tokens = f.readline().split() # second line should contain "XXX Version", where XXX < 1100 is old for us
		try:
			XP11_OK = int(tokens[tokens.index('Version') - 1]) >= 1100
		except (ValueError, IndexError):
			print('WARNING: Could not identify navaid data version.', file=err_log_file)
			XP11_OK = True # assume newer version
		dmelst = [] # list of DMEs to try to couple with NDBs/VOR(TAC)s
		for line in f:
			if line_code(line) in [2, 3]: # NDB or VOR
				if XP11_OK:
					row_code, lat, lon, elev, frq, rng, var, code, terminal, region, name = line.split(maxsplit=10)
				else: # pre-XP11 data
					row_code, lat, lon, elev, frq, rng, var, code, name = line.split(maxsplit=8)
					region = None
				long_name = name.rstrip()
				coords = EarthCoords(float(lat), float(lon))
				if row_code == '2': # NDB
					p = NDB(code, coords, region, frq, long_name)
				else: # VOR/VORTAC
					p = VOR(code, coords, region, '%s.%s' % (frq[:3], frq[3:]), long_name, tacan=('VORTAC' in long_name))
				world_navpoint_db.add(p)
			elif line_code(line) in [12, 13]: # DME: 12 = coupled with VOR/VORTAC; 13 = standalone or coupled with NDB
				tokens = line.split(maxsplit=11)
				if XP11_OK and len(tokens) == 12:
					row_code, lat, lon, elev, frq, rng, bias, code, terminal, reg = tokens[:10] # ignoring 2 values: rwy, name
				else: # pre-XP11 data (can be a line in an XP11 file)
					row_code, lat, lon, elev, frq, rng, bias, code = tokens[:8] # ignoring 3 values: terminal, rwy, name
					reg = None
				pos = EarthCoords(float(lat), float(lon))
				typ = Navpoint.VOR if row_code == '12' else Navpoint.NDB
				dmelst.append((code, pos, typ, reg))
		for name, pos, typ, reg in dmelst: # add DMEs after all other navaids have been sourced
			try:
				p = world_navpoint_db.findClosest(pos, code=name, types=[typ], region=reg, maxDist=navpoint_coords_max_dist)
				p.dme = True
			except NavpointError: # according to spec: VORs should exist; a non-existing NDB means standalone DME
				if typ == Navpoint.VOR:
					vorstr = name if reg is None else '%s@%s' % (name, reg)
					print('VOR "%s" not found for DME coupling in navaid data.' % vorstr, file=err_log_file)



# FIX/RNAV spec example line:
# 46.661100000 -112.437869444  KELTY ENRT K1 4606275
#    lat            lon        name  AD region type
# Old XP10 format:
# 49.137500  004.049167 DIKOL
#   lat        lon      name
#TODO? Newer XP12 format adds "waypoint name" field: https://developer.x-plane.com/wp-content/uploads/2021/09/XP-FIX1200-Spec.pdf

def import_navfix_data(err_log_file):
	try:
		f = open(custom_navfix_file, encoding='utf8')
	except FileNotFoundError:
		print('No fix/RNAV data provided (%s); falling back on old data.' % custom_navfix_file, file=stderr)
		f = open(fallback_navfix_file, encoding=xplane_file_encoding)
	with f:
		for line in f:
			tokens = line.split(maxsplit=6)
			name = None
			if len(tokens) == 3: # XP10 format
				lat, lon, name = tokens
				region = None
			elif 5 <= len(tokens) <= 6: # XP11 format
				lat, lon, name, terminal, region = tokens[:5]
			if name is not None:
				coordinates = EarthCoords(float(lat), float(lon))
				if name.isalpha() and len(name) == 5:
					world_navpoint_db.add(Fix(name, coordinates, region))
				else:
					world_navpoint_db.add(Rnav(name, coordinates, region))



# AWY spec example line:
# ARKUK UU  11   GUBAT UU  11    N   1     90    530   G719
#  p1  reg1 typ1  p2  reg2 typ2 dir hi/lo FLmin FLmax AWY_name
# Old XP10 format:
# DIKEN  65.053333  076.696667 INROS  65.403333  073.503333  1   282   397   G719
#  p1      lat1        lon1     p2      lat2       lon2   hi/lo FLmin FLmax AWY_name

xp_awy_point_types = {
	'2': [Navpoint.NDB],
	'3': [Navpoint.VOR],
	'11': [Navpoint.FIX, Navpoint.RNAV]
}

def import_airway_data(err_log_file):
	try:
		f = open(custom_airway_file, encoding='utf8')
	except FileNotFoundError:
		print('No airway data provided (%s); falling back on old data.' % custom_airway_file, file=stderr)
		f = open(fallback_airway_file, encoding=xplane_file_encoding)
	with f:
		for line in f:
			tokens = line.split(maxsplit=11)
			if len(tokens) == 10: # XP10 format
				p1, lat1, lon1, p2, lat2, lon2, hi_lo, fl_min, fl_max, name = tokens
				try:
					navpoint1 = world_navpoint_db.findClosest(EarthCoords(float(lat1), float(lon1)), code=p1, maxDist=navpoint_coords_max_dist)
					navpoint2 = world_navpoint_db.findClosest(EarthCoords(float(lat2), float(lon2)), code=p2, maxDist=navpoint_coords_max_dist)
					world_routing_db.addAwy(navpoint1, navpoint2, name, fl_min, fl_max)
					world_routing_db.addAwy(navpoint2, navpoint1, name, fl_min, fl_max) # all AWYs assumed bi-directional
				except (NavpointError, ValueError) as err:
					print('Ignoring XP10 AWY spec for %s: problem with token "%s"' % (name, err), file=err_log_file)
			elif len(tokens) == 11: # XP11 format
				p1, region1, ptype1, p2, region2, ptype2, dir_restriction, hi_lo, fl_min, fl_max, name = tokens
				try:
					navpoint1 = world_navpoint_db.findUnique(p1, types=xp_awy_point_types[ptype1], region=region1)
					navpoint2 = world_navpoint_db.findUnique(p2, types=xp_awy_point_types[ptype2], region=region2)
				except (NavpointError, KeyError) as err:
					print('Ignoring XP11 AWY spec for %s: problem with token "%s"' % (name, err), file=err_log_file)
				else:
					if dir_restriction in 'NF':
						world_routing_db.addAwy(navpoint1, navpoint2, name, fl_min, fl_max)
					if dir_restriction in 'NB':
						world_routing_db.addAwy(navpoint2, navpoint1, name, fl_min, fl_max)











# =============================================== #

#                  AIRPORT DATA                   #

# =============================================== #


def open_airport_file(ad_code):
	try_file_name = custom_airport_file_fmt % ad_code
	try:
		return open(try_file_name, encoding='utf8')
	except FileNotFoundError: # No custom airport file found; fall back on packaged X-plane data.
		if ad_code not in ad_data_files_read:
			print('No airport data file provided for %s (%s); falling back on old data.' % (ad_code, try_file_name), file=stderr)
		try:
			return open(extracted_airport_file_fmt % ad_code, encoding='utf8')
		except FileNotFoundError: # Airport never extracted yet; build simple file first.
			extract_airport_file(ad_code)
			return open(extracted_airport_file_fmt % ad_code, encoding='utf8')



frequency_types = {50: 'recorded', 51: 'A/A', 52: 'DEL', 53: 'GND', 54: 'TWR', 55: 'APP', 56: 'DEP'}

def get_airport_data(icao):
	result = AirportData()
	result.navpoint = world_navpoint_db.findAirfield(icao)
	ad_lat = ad_lon = None
	gnd_net_source_edges = [] # NOTE: GroundNetwork pretty labelling breaks if we add duplicate edges
	legacy_25kHz_freqs = [] # spec says they should be ignored if 8.33 kHz-spaced freq's are specified
	
	with open_airport_file(result.navpoint.code) as f:
		for line in f:
			row_type = line_code(line)
			
			if row_type is None:
				continue
			
			elif is_xplane_airport_header(line): # HEADER LINE; get elevation
				tokens = line.split(maxsplit=2)
				result.field_elevation = float(tokens[1])
				
			elif row_type == 100: # RUNWAY
				tokens = line.split()
				width = float(tokens[1])
				surface = int(tokens[2])
				name, lat, lon, disp_thr = tokens[8:12]
				rwy1 = DirRunway(name, EarthCoords(float(lat), float(lon)), float(disp_thr), width)
				name, lat, lon, disp_thr = tokens[17:21]
				rwy2 = DirRunway(name, EarthCoords(float(lat), float(lon)), float(disp_thr), width)
				result.addPhysicalRunway(width, surface, rwy1, rwy2)
				
			elif row_type == 102: # HELIPAD
				tokens = line.split()
				row_code, name, lat, lon, ori, l, w, surface = tokens[:8]
				centre = EarthCoords(float(lat), float(lon))
				result.helicopter_pads.append(Helipad(name, centre, int(surface), float(l), float(w), Heading(float(ori), True)))
				
			elif row_type == 14: # VIEWPOINT (NOTE: ATC-pie allows for more than one, though X-plane specifies one or zero)
				row_code, lat, lon, height, ignore, name = line.split(maxsplit=5)
				result.viewpoints.append((EarthCoords(float(lat), float(lon)), float(height), name.rstrip()))
				
			elif row_type == 19: # WINDSOCK
				row_code, lat, lon, ignore_rest_of_line = line.split(maxsplit=3)
				result.windsocks.append(EarthCoords(float(lat), float(lon)))
				
			elif row_type == 1302: # METADATA RECORD
				tokens = line.split()
				if len(tokens) == 3 and tokens[1] == 'transition_alt':
					result.transition_altitude = int(tokens[2])
				elif len(tokens) == 3 and (tokens[1] == 'datum_lat' or tokens[1] == 'datum_lon'):
					if tokens[1] == 'datum_lat':
						ad_lat = float(tokens[2])
					else: # datum_lon
						ad_lon = float(tokens[2])
					if ad_lat is not None and ad_lon is not None:
						ad_ref_point = EarthCoords(ad_lat, ad_lon)
						if result.navpoint.coordinates.distanceTo(ad_ref_point) > ad_ref_point_max_dist:
							print('AD position update recommended for %s: source reference point is %s' % (result.navpoint.code, ad_ref_point.toString()), file=stderr)
				
			elif 50 <= row_type <= 56 or 1050 <= row_type <= 1056: # RADIO FREQUENCY
				tokens = line.split(maxsplit=2)
				try:
					freq = CommFrequency(tokens[1])
					freq_name = tokens[2].rstrip('\n')
					if row_type < 100: # "legacy" freq with 25 kHz spacing
						legacy_25kHz_freqs.append((freq, freq_name, frequency_types[row_type]))
					else: # 8.33 kHz spacing
						result.frequencies.append((freq, freq_name, frequency_types[row_type % 100]))
				except (ValueError, IndexError):
					print('WARNING: Ignoring invalid frequency spec line at %s.' % result.navpoint.code, file=stderr)
				
			elif row_type == 1201: # GROUND NETWORK: TWY node
				tokens = line.rstrip().split(maxsplit=5)
				lat, lon, ignore, nid = tokens[1:5]
				result.ground_net.addNode(nid, EarthCoords(float(lat), float(lon)))
			
			elif line_code(line) == 1202: # GROUND NETWORK: TWY edge
				tokens = line.rstrip().split(maxsplit=5)
				v1, v2 = tokens[1:3]
				twy_name = rwy_spec = None
				if len(tokens) == 6:
					if tokens[4] == 'runway':
						rwy_spec = tokens[5].rstrip()
					elif tokens[4].startswith('taxiway'): # can be suffixed with "_X" to specify wing span
						twy_name = tokens[5].rstrip()
				if {v1, v2} in gnd_net_source_edges:
					print('WARNING: Ignoring duplicate ground route edge (%s, %s) at %s.' % (v1, v2, result.navpoint.code), file=stderr)
				else:
					gnd_net_source_edges.append({v1, v2})
					try:
						result.ground_net.addEdge(v1, v2, rwy_spec, twy_name)
					except KeyError:
						print('Invalid node in ground route edge spec (%s, %s)' % (v1, v2), file=stderr)
			
			elif line_code(line) == 1300: # GROUND NETWORK: parking_position
				tokens = line.rstrip().split(maxsplit=6)
				if len(tokens) == 7:
					lat, lon, hdg, typ, who, pkid = tokens[1:7]
					if typ in ['gate', 'hangar', 'tie-down']:
						pos = EarthCoords(float(lat), float(lon))
						cats = [] if who == 'all' else who.split('|')
						result.ground_net.addParkingPosition(pkid, pos, Heading(float(hdg), True), typ, cats)
				else:
					print('Invalid parking position spec ending with %s' % tokens[-1], file=stderr)
	
	if len(result.frequencies) == 0:
		result.frequencies = legacy_25kHz_freqs
	ad_data_files_read.add(result.navpoint.code) # this is a global variable
	return result


# X-PLANE runway line example:
# 100 29.87 1 1 0.00 0 2 1 07L 48.75115000 002.09846100 0.00 178.61 2 0 0 1 25R 48.75439400 002.11289900 0.00 0.00 2 1 0 0
#
# In order:
# 0: "100" for land RWY
# 1: width-metres
# 2: surface type
# 3-7: (ignore)
# 8-16 (RWY 1): name lat-end lon-end disp-thr-metres (ignore) (ignore) (ignore) (ignore) (ignore)
# 17-25 (RWY 2): (idem 8-16)


# X-PLANE helipad line example:
# 102 H1 47.53918248 -122.30722302 2.00 10.06 10.06 1 0 0 0.25 0
#
# In order:
# 0: "102" for helipad
# 1: name/designator
# 2-3: lat-lon of centre
# 4: true heading orientation
# 5-6: length-width (metres)
# 7: surface type
# 8-11: (ignore)


# X-PLANE viewpoint line example:
# 14   37.61714303 -122.38327660  200 0 Tower Viewpoint
#
# In order:
# 0: "14" for viewpoint
# 1-2: lat-lon coordinates
# 3: viewpoint height in ft
# 4: (ignored)
# 5: name


# X-PLANE windsock line example:
# 19  48.71901305  002.37906976 1 New Windsock 02
#
# In order:
# 0: "19" for windsock
# 1-2: lat-lon coordinates
# 3: has lighting
# 4: name


# X-PLANE frequency line example:
# 50 11885 ATIS
#
# In order:
# 0: freq type: 50=recorded (e.g. ATIS), 51=unicom, 52=DEL, 53=GND, 54=TWR, 55=APP, 56=DEP
# 1: integer frequency in 100*Hz
# 2: description





def get_airport_drawables(icao):
	"""
	Returns a tuple of:
	 - TWY and apron surfaces: (QPainterPath, surface int code) list
	 - TWY centre lines: QPainterPath list
	 - holding lines: QPainterPath list
	 - AD boundary lines: QPainterPath list
	"""
	twy_apron_surfaces = []
	twy_centre_lines = []
	holding_lines = []
	ad_boundaries = []
	with open_airport_file(icao) as f:
		line = f.readline()
		line_number = 1
		while line != '': # not EOF
			if line_code(line) == 110: # TWY/apron section; header can contain a name (ignored here)
				surface_type = int(line.split(maxsplit=2)[1])
				path, paint_sequence, closed, lines_read = read_xplane_node_sequence(f)
				line_number += lines_read
				if not closed:
					print('WARNING: %s taxiway/apron surface spec should end with a closing node on line %d' % (icao, line_number), file=stderr)
				# Read holes on this TWY:
				line = f.readline()
				line_number += 1
				while is_xplane_node_line(line):
					hole_path, _, closed, lines_read = read_xplane_node_sequence(f, first_line=line)
					line_number += lines_read
					if not closed:
						print('WARNING: %s taxiway/apron hole spec should end with a closing node on line %d' % (icao, line_number), file=stderr)
					path.addPath(hole_path)
					line = f.readline() # for new loop (more holes?)
					line_number += 1
				twy_apron_surfaces.append((path, surface_type))
				continue # avoid reading a new line because we already have a one-line look-ahead here
			
			if line_code(line) == 120: # Linear feature; header can contain a name (ignored here)
				path, paint_sequence, closed, lines_read = read_xplane_node_sequence(f)
				line_number += lines_read
				if any(t in [4, 5, 6, 54, 55, 56] for t in paint_sequence): # holding line
					holding_lines.append(path)
				elif any(t in [1, 7, 51, 57] for t in paint_sequence): # TWY centre line
					twy_centre_lines.append(path)
				#elif any(t in [2, 8, 9, 52, 58, 59] for t in paint_sequence): # other non TWY edge lines
				#	print(paint_sequence)
				#	.append(path)
			
			elif line_code(line) == 130: # Airport boundary line
				path, paint_sequence, closed, lines_read = read_xplane_node_sequence(f)
				line_number += lines_read
				if not closed:
					print('WARNING: %s boundary line spec should end with a closing node on line %d' % (icao, line_number), file=stderr)
				ad_boundaries.append(path)
			
			# code below not reached before next iteration if "continued" in loop (e.g. because of TWY holes)
			line = f.readline() # for more linear objects
			line_number += 1
	
	return twy_apron_surfaces, twy_centre_lines, holding_lines, ad_boundaries





## GROUND NETWORK

# Example of TAXIWAY NODE spec line
#   1201 47.53752190 -122.30826710 both 5416 A_start
# Columns:
#   1-2: lat-lon
#   4: ID

# Example of TAXIWAY EDGE spec line
#   1202 5416 5417 twoway taxiway A
# Columns:
#   1-2: vertices
#   4: "taxiway" or "runway" if on runway
#   5: TWY name

# Example of PARKING POSITION spec line
#   1300 47.43931757 -122.29806851 88.78 gate jets|turboprops A2
# Columns:
#   1-2: lat-lon
#   3: true heading when ACFT is parked
#   4: "gate", "hangar", "misc" or "tie-down" ("misc" not considered as parking)
#   5: pipe-deparated list heavy|jets|turboprops|props|helos or "all"
#   6: unique name of position


def import_ILS_capabilities(airport_data):
	try:
		f = open(custom_navaid_file, encoding='utf8')
	except FileNotFoundError:
		f = open(fallback_navaid_file, encoding=xplane_file_encoding)
	with f:
		for line in f:
			lc = line_code(line)
			if lc is not None and 4 <= lc <= 9: # all lines with ILS codes [4..9] have similar structure
				tokens = line.split() # no token can contain whitespace
				if len(tokens) == 11: # XP10 format
					row_code, lat, lon, elev, frq, rng, qdm, app_id, ad, rwy, cat = tokens
				else: # XP11 data
					row_code, lat, lon, elev, frq, rng, qdm, app_id, ad, region, rwy, cat = tokens
				if ad == airport_data.navpoint.code: # spec says "Markers must now use the parent localizer as ID"
					try:
						drwy = airport_data.runway(rwy)
						coords = EarthCoords(float(lat), float(lon))
					except KeyError: # unknown RWY
						print('Unknown RWY %s or bad LOC spec' % rwy, file=stderr)
					else: # we are interested in the line spec
						if row_code in ['4', '5']: # LOC
							drwy.ILS_cat = cat
							drwy.LOC_freq = '%s.%s' % (frq[:3], frq[3:])
							drwy.LOC_bearing = Heading(float(qdm), True)
							drwy.LOC_range = drwy.threshold().distanceTo(coords.moved(drwy.LOC_bearing.opposite(), float(rng)))
						elif row_code == '6': # GS (angle prefixes the bearing)
							try:
								iqdm = qdm.index('.') - 3
							except ValueError:
								iqdm = len(qdm) - 3
							fpa_degrees = int(qdm[:iqdm]) / 100
							drwy.param_FPA = 100 * tan(radians(fpa_degrees))
							drwy.GS_range = drwy.touchDownPoint().distanceTo(coords.moved(Heading(float(qdm[iqdm:]), True).opposite(), float(rng)))
						elif row_code == '7': # OM
							drwy.OM_pos = coords
						elif row_code == '8': # MM
							drwy.MM_pos = coords
						elif row_code == '9': # IM
							drwy.IM_pos = coords
