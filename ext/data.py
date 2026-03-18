
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
from os import path
from sys import stderr

from PyQt5.QtGui import QPixmap

from base.coords import EarthCoords
from base.db import acft_db, acft_registration_formats, phon_airlines, phon_navpoints
from base.elev import ElevationMap
from base.nav import Airfield, NavpointError, world_navpoint_db, world_routing_db
from base.params import Speed

from ext.fgfs import FGFS_ACFT_recogniser, FGFS_ATC_recogniser, FGFS_model_chooser, FGFS_model_liveries
from ext.xplane import extract_world_AD_positions, extracted_ad_pos_file

from session.config import strNoHash_to_QColor


# ---------- Constants ----------

aircraft_db_spec_file = 'CONFIG/acft/acft-db'
ICAO_types_to_FGFS_models_file = 'CONFIG/acft/icao2fgfs'
FGFS_models_to_ICAO_types_file = 'CONFIG/acft/fgfs2icao'
aircraft_reg_spec_file = 'CONFIG/acft/tail-numbers'
background_images_dir = 'CONFIG/bg'
custom_ad_pos_file = 'CONFIG/nav/AD-positions'
airport_entry_exit_file = 'CONFIG/nav/AD-entry-exit'
route_presets_file = 'CONFIG/nav/route-presets'
elev_map_file_fmt = 'CONFIG/elev/%s.elev'
airlines_speech_file = 'CONFIG/phon/airline-callsigns.phon'
navpoint_speech_file_fmt = 'CONFIG/phon/navpoints-%s.phon'

pixmap_corner_sep = ':'
FG_ATC_model_token = ':ATC'
unavailable_acft_info_token = '-'

model_gnd_height_spec_token = ':height'
model_lat_offset_spec_token = ':latoffset'
model_fwd_offset_spec_token = ':fwdoffset'
model_airline_livery_spec_token = ':airline'

# -------------------------------


##------------------------------------##
##                                    ##
##          BACKGROUND IMAGES         ##
##                                    ##
##------------------------------------##

def read_text_drawing(file_name, navpointdb):
	try:
		with open(file_name, encoding='utf8') as f:
			draw_sections = []
			section_number = 0
			fline = f.readline()
			while fline != '': # looking for colour line until EOF
				line = fline.split('#', maxsplit=1)[0].strip()
				if line != '': # New drawing block; should start with a colour spec
					section_number += 1
					try:
						colour = strNoHash_to_QColor(line)
						points = []
						point_labels = []
						line_labels = []
						fline = f.readline()
						while fline.strip() != '': # now looking for points until EOF or empty line
							split = fline.split('#', maxsplit=1)[0].rstrip().split(maxsplit=1)
							if len(split) > 0: # ignore full comment lines
								if split[0] == ':label' and len(split) == 2 and len(line_labels) == len(point_labels) - 1:
									line_labels.append(split[1])
								else: # read new point
									if len(line_labels) < len(point_labels): # missing a line label spec
										line_labels.append(None)
									points.append(navpointdb.coordsFromPointSpec(split[0]))
									point_labels.append(split[1] if len(split) == 2 else None)
							fline = f.readline()
						if len(points) == 0:
							raise ValueError('empty point sequence')
						if len(line_labels) != len(point_labels) - 1:
							raise ValueError('trailing line spec')
						draw_sections.append((colour, points, point_labels, line_labels))
					except (NavpointError, ValueError) as err: # error on line
						print('ERROR in %s section %d: %s' % (file_name, section_number, err), file=stderr)
						while line != '': # skip until next empty line or EOF
							line = f.readline().strip()
				fline = f.readline()
		return draw_sections
	except FileNotFoundError:
		raise ValueError('Drawing file not found')


def read_bg_img(icao, navpointdb):
	try:
		with open(path.join(background_images_dir, '%s.lst' % icao), encoding='utf8') as f:
			radar_background_layers = []
			loose_strip_bay_backgrounds = []
			for line in f:
				tokens = line.split('#', maxsplit=1)[0].rstrip().split(maxsplit=2)
				if len(tokens) == 3:
					try:
						image_file = path.join(background_images_dir, tokens[0])
						if tokens[1] == 'DRAW': # DRAWING SPEC, no corners given
							radar_background_layers.append((False, tokens[0], tokens[2], read_text_drawing(image_file, navpointdb)))
						else:
							pixmap = QPixmap(image_file)
							if pixmap.isNull():
								raise ValueError('Not found or unrecognised format')
							if tokens[1] == 'LOOSE': # LOOSE STRIP BAY BACKGROUND
								new_tokens = tokens[2].split(maxsplit=1)
								if len(new_tokens) != 2:
									raise ValueError('Bad LOOSE spec (missing scale or title)')
								loose_strip_bay_backgrounds.append((tokens[0], pixmap, float(new_tokens[0]), new_tokens[1]))
							elif pixmap_corner_sep in tokens[1]: # PIXMAP, two corners given
								nw, se = tokens[1].split(pixmap_corner_sep, maxsplit=1)
								nw_coords = navpointdb.coordsFromPointSpec(nw)
								se_coords = navpointdb.coordsFromPointSpec(se)
								radar_background_layers.append((True, tokens[0], tokens[2], (pixmap, nw_coords, se_coords)))
							else:
								raise ValueError('Bad image spec (should be NW:SE or "DRAW")' + tokens[1])
					except NavpointError as err:
						print('%s: navpoint %s unknown or not unique (consider `~\' operator)' % (tokens[0], err), file=stderr)
					except ValueError as err:
						print('%s: %s' % (tokens[0], err), file=stderr)
				elif len(tokens) != 0:
					print('Bad syntax in background drawing spec line: ' + line.rstrip('\n'), file=stderr)
		return radar_background_layers, loose_strip_bay_backgrounds
	except FileNotFoundError:
		print('No background image list found.')
		return [], []




##-----------------------------------##
##                                   ##
##       GROUND ELEVATION MAPS       ##
##                                   ##
##-----------------------------------##


def get_ground_elevation_map(location_code):
	try:
		with open(elev_map_file_fmt % location_code, encoding='utf8') as f:
			nw = se = None
			line = f.readline()
			while nw is None and line != '':
				tokens = line.split('#', maxsplit=1)[0].split()
				if len(tokens) == 0:
					line = f.readline()
				elif len(tokens) == 2:
					nw = EarthCoords.fromString(tokens[0])
					se = EarthCoords.fromString(tokens[1])
				else:
					raise ValueError('invalid header line')
			if nw is None:
				raise ValueError('missing header line')
			matrix = []
			xprec = None
			line = f.readline()
			while line.strip() != '':
				values = [float(token) for token in line.split('#', maxsplit=1)[0].split()]
				if xprec is None:
					xprec = len(values)
				elif len(values) != xprec:
					raise ValueError('expected %d values in row %d' % (xprec, len(matrix) + 1))
				matrix.append(values) # add row
				line = f.readline()
		# Finished reading file.
		result = ElevationMap(nw.toRadarCoords(), se.toRadarCoords(), len(matrix), xprec)
		for i, row in enumerate(matrix):
			for j, elev in enumerate(row):
				result.setElevation(i, j, elev)
		return result
	except ValueError as err:
		print('Error in elevation map: %s' % err, file=stderr)





##-----------------------------------------##
##                                         ##
##   AIRCRAFT DATA BASE + FGFS RENDERING   ##
##                                         ##
##-----------------------------------------##


def load_aircraft_db():
	"""
	loads the dict: ICAO desig -> (category, WTC, cruise speed)
	where category is either of those used in X-plane, e.g. for parking positions
	any of tuple elements can use the "unavailable_acft_info_token" to signify unknown info
	"""
	try:
		with open(aircraft_db_spec_file, encoding='utf8') as f:
			for line in f:
				tokens = line.split('#', maxsplit=1)[0].rstrip().split(maxsplit=4)
				if len(tokens) == 4:
					desig, xplane_cat, wtc, cruise = tokens
					if xplane_cat == unavailable_acft_info_token:
						xplane_cat = None
					if wtc == unavailable_acft_info_token:
						wtc = None
					acft_db[desig] = xplane_cat, wtc, (Speed(float(cruise)) if cruise != unavailable_acft_info_token else None)
				elif len(tokens) != 0:
					print('Error on ACFT spec line: %s' % line.strip(), file=stderr)
	except FileNotFoundError:
		print('Aircraft data base file not found: %s' % aircraft_db_spec_file, file=stderr)


def load_aircraft_registration_formats():
	try:
		with open(aircraft_reg_spec_file, encoding='utf8') as f:
			for line in f:
				tokens = line.split('#', maxsplit=1)[0].split()
				if len(tokens) == 1:
					acft_registration_formats.append(tokens[0])
				elif len(tokens) != 0:
					print('Error on ACFT tail number spec line: %s' % line.strip(), file=stderr)
	except FileNotFoundError:
		print('Aircraft tail number spec file not found: %s' % aircraft_reg_spec_file, file=stderr)




def make_FGFS_model_recognisers():
	try:
		with open(FGFS_models_to_ICAO_types_file, encoding='utf8') as f:
			FGFS_ACFT_recogniser.clear()
			FGFS_ATC_recogniser.clear()
			for line in f:
				tokens = line.split('#', maxsplit=1)[0].rsplit(maxsplit=1)
				if len(tokens) == 0: # empty line
					pass
				elif len(tokens) == 2: # new model recogniser
					try:
						regexp = re.compile(tokens[0], flags=re.IGNORECASE)
					except Exception as err: # CAUTION: greedy catch, but can only come from exceptions in re.compile
						print('Error in regexp for model %s: %s' % (tokens[0], err), file=stderr)
					else:
						if tokens[1] == FG_ATC_model_token:
							FGFS_ATC_recogniser.append(regexp)
						else:
							FGFS_ACFT_recogniser.append((regexp, tokens[1]))
				else:
					print('Error on FGFS model recognising spec line: %s' % line.strip(), file=stderr)
	except FileNotFoundError:
		print('FG model recognising spec file not found: %s' % FGFS_models_to_ICAO_types_file, file=stderr)



# CAUTION below: order in list determines the resulting ordering in offset tuples
model_offset_spec_tokens = [model_gnd_height_spec_token, model_lat_offset_spec_token, model_fwd_offset_spec_token]

def make_FGFS_models_liveries():
	try:
		with open(ICAO_types_to_FGFS_models_file, encoding='utf8') as f:
			models = {}   # str -> str
			offsets = {}  # str -> [float, float, float] ordered as model_offset_spec_tokens, should fit FGFS_model_chooser
			FGFS_model_chooser.clear()
			FGFS_model_liveries.clear()
			last_dez = None
			for line in f:
				tokens = line.split('#', maxsplit=1)[0].split()
				if len(tokens) == 0:
					continue
				if len(tokens) == 2 and tokens[0] in model_offset_spec_tokens and last_dez is not None:
					try:
						offsets[last_dez][model_offset_spec_tokens.index(tokens[0])] = float(tokens[1])
					except ValueError:
						print('Error on FGFS model height spec for %s: numerical expected.' % last_dez, file=stderr)
				elif len(tokens) == 3 and tokens[0] == model_airline_livery_spec_token and last_dez is not None:
					airline, livery = tokens[1:]
					if last_dez not in FGFS_model_liveries: # first key for this ACFT type
						FGFS_model_liveries[last_dez] = {}
					FGFS_model_liveries[last_dez][airline] = livery
				elif len(tokens) == 2: # new model chooser
					dez, model = tokens
					if dez in models:
						print('WARNING: Overwriting FGFS model choice with duplicate for %s.' % dez, file=stderr)
					models[dez] = model
					offsets[dez] = [0, 0, 0]
					last_dez = dez
				else:
					print('Error on FGFS model choice line: %s' % line.strip(), file=stderr)
					last_dez = None
			for dez, m in models.items():
				FGFS_model_chooser[dez] = m, tuple(offsets[dez])
	except FileNotFoundError:
		print('FG model chooser spec file not found: %s' % ICAO_types_to_FGFS_models_file, file=stderr)



##--------------------------------##
##                                ##
##          SPEECH STUFF          ##
##                                ##
##--------------------------------##

def load_speech_data_file(src_file, fill_dict, clearDict=True):
	try:
		with open(src_file, encoding='utf8') as f:
			if clearDict:
				fill_dict.clear()
			for line in f:
				cols = [column.strip() for column in line.split('#', maxsplit=1)[0].split('|')]
				if cols == ['']:
					pass
				elif len(cols) == 3 and all(col != '' for col in cols):
					code, callsign, phonemes = cols
					fill_dict[code] = callsign, phonemes
				else:
					print('ERROR in pronunciation spec line: %s' % line.rstrip('\n'), file=stderr)
	except FileNotFoundError:
		pass


def load_airlines_db():
	load_speech_data_file(airlines_speech_file, phon_airlines)

def load_local_navpoint_speech_data(location):
	load_speech_data_file(navpoint_speech_file_fmt % location, phon_navpoints)






##-------------------------------------##
##                                     ##
##      AD POSITIONS & ROUTING DB      ##
##                                     ##
##-------------------------------------##

def import_ad_pos_data(err_log_file):
	try:
		f = open(custom_ad_pos_file, encoding='utf8')
	except FileNotFoundError: # No custom airfield position file found; fall back on extracted X-plane inventory.
		print('No world AD position data provided (%s); falling back on old data.' % custom_ad_pos_file, file=stderr)
		try:
			f = open(extracted_ad_pos_file, encoding='utf8')
		except FileNotFoundError: # Airport positions not extracted yet; build file from packaged X-plane world file.
			extract_world_AD_positions()
			f = open(extracted_ad_pos_file, encoding='utf8')
	footer_line_count = None
	ad_added = 0
	with f:
		for fline in f:
			split = fline.split('#', maxsplit=1)[0].rstrip().split(maxsplit=2)
			if len(split) == 3:
				icao_code, lat_lon, name = split
				coords = EarthCoords.fromString(lat_lon)
				world_navpoint_db.add(Airfield(icao_code, coords, name.rstrip()))
				ad_added += 1
			elif len(split) == 1 and footer_line_count is None:
				footer_line_count = int(split[0])
			elif len(split) != 0:
				print('Bad or illegal spec line in AD positions file: %s' % fline.rstrip('\n'), file=err_log_file)
	if footer_line_count is None or footer_line_count != ad_added:
		print('ERROR: inconsistencies in AD position data. This can be caused by an interrupted extraction process; '
				'try "cleanUp.sh" and try again.', file=stderr)
		raise ValueError('AD position data corrupt')


def import_entry_exit_data(err_log_file):
	try:
		with open(airport_entry_exit_file, encoding='utf8') as f:
			for line in f:
				tokens = line.split('#', maxsplit=1)[0].split()
				if len(tokens) >= 3: # AD "entry/exit" point_name
					try:
						ad = world_navpoint_db.findAirfield(tokens[0])
						p = world_navpoint_db.findClosest(ad.coordinates, code=tokens[2])
						if tokens[1] == 'entry':
							world_routing_db.addEntryPoint(ad, p, tokens[3:])
						elif tokens[1] == 'exit':
							world_routing_db.addExitPoint(ad, p, tokens[3:])
						else:
							print('Invalid entry/exit token: %s' % tokens[1], file=err_log_file)
					except NavpointError:
						print('Entry/exit navpoint %s not found: %s' % (tokens[0], tokens[2]), file=err_log_file)
				elif len(tokens) != 0: # ignore empty lines
					print('Bad entry/exit line: %s' % line.rstrip('\n'), file=err_log_file)
	except FileNotFoundError:
		pass


def read_route_presets(err_log_file):
	result = {}
	try:
		with open(route_presets_file, encoding='utf8') as f:
			for line in f:
				spl = line.split('#', maxsplit=1)[0].rstrip().split(maxsplit=2)
				if len(spl) == 3:
					end_points = spl[0], spl[1]
					try:
						result[end_points].append(spl[2])
					except KeyError:
						result[end_points] = [spl[2]]
				elif len(spl) != 0:
					print('Error on preset route line: %s' % line.rstrip('\n'), file=err_log_file)
	except FileNotFoundError:
		pass
	return result
