#!/usr/bin/env python

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

from base.coords import EarthCoords
from base.nav import NavpointError

from session.config import settings
from session.env import env


# ---------- Constants ----------

sct_file_encoding = 'iso-8859-15'
fmt_dms = r'(\d{1,3})\.(\d{1,2})\.(\d{1,2})\.(\d{,3})' # for multiple use in line below
re_point = re.compile(r'(?P<lat>[NSns]%s) +(?P<lon>[EWew]%s)|(?P<named>\w+) +(?P=named)' % (fmt_dms, fmt_dms))

# -------------------------------


def bg_basename(file_key):
	return 'bg-%s-%s' % (settings.location_code, file_key)



def read_point(s):
	match = re_point.fullmatch(s)
	if match:
		if match.group('named') is None: # lat/lon coordinates in SCT format
			lat, lon = s.split()
			lat_d, lat_m, lat_s = lat[1:].split('.', maxsplit=2)
			lon_d, lon_m, lon_s = lon[1:].split('.', maxsplit=2)
			return EarthCoords.fromString('%sd%sm%ss%s,%sd%sm%ss%s' \
				% (lat_d, lat_m, lat_s, lat[0].upper(), lon_d, lon_m, lon_s, lon[0].upper()))
		else: # named point
			try:
				return env.navpoints.findUnique(match.group('named')).coordinates
			except NavpointError:
				raise ValueError('Named point out of range or not unique: %s' % s)
	else:
		raise ValueError('Not a valid point spec: %s' % s)


def get_segment(txt):
	tokens = txt.split(maxsplit=4)
	if len(tokens) < 4: # len should be 4 or 5
		raise ValueError('Missing tokens')
	p1 = read_point(' '.join(tokens[0:2]))
	p2 = read_point(' '.join(tokens[2:4]))
	return (p1, p2, tokens[:4]), (tokens[4] if len(tokens) > 4 else '')
	


def repl_spaces(txt, repl='_'):
	return re.sub(' ', repl, txt)


def point_to_string(p):
	if isinstance(p, EarthCoords):
		return p.toString()
	else: # named point
		return p




def extract_sector(sector_file, centre_point, range_limit):
	with open(settings.outputFileName('bg-extract', windowID=False, ext='err'), 'w', encoding='utf8') as ferr:
		with open(sector_file, encoding=sct_file_encoding) as fin:
			print('Extracting from sector file "%s"... ' % sector_file)
			in_section = last_drawing_block = last_coord_spec = None
			src_line_number = 0
			files = {} # file key -> file
			object_counters = {} # file name -> int
			for src_line in fin:
				src_line_number += 1
				line = src_line.split(';', maxsplit=1)[0].rstrip()
				
				# --- Interpret spec line --- #
				got_segment = None # if set below, must also set: output_file, drawing_block, block_colour
				
				if line == '':
					continue
				
				elif line.startswith('[') and line.endswith(']'):
					in_section = line[1:-1]
				
				# --------- GEO --------- #
				elif in_section == 'GEO':
					try:
						got_segment, drawing_block = get_segment(line)
						if drawing_block == '':
							drawing_block = 'unnamed'
						output_file = 'geo-' + repl_spaces(drawing_block)
						block_colour = 'yellow'
					except ValueError as err:
						print('Line %d: %s' % (src_line_number, err), file=ferr)
				
				# ---- ARTCC (HI/LO), SID, STAR ---- #
				elif in_section in ['SID', 'STAR'] or in_section is not None and in_section.startswith('ARTCC'):
					if line.startswith(' '): # indented sequal to prev. line
						if last_drawing_block is None:
							print('Isolated %s segment on line %d; is header commented out?' % (in_section, src_line_number), file=ferr)
						else:
							drawing_block = last_drawing_block
							try:
								got_segment, rest_of_line = get_segment(line)
							except ValueError as err:
								print('Line %d: %s' % (src_line_number, err), file=ferr)
					else: # not on an indented line
						if in_section in ['SID', 'STAR']:
							drawing_block = line[:26].strip()
							try:
								got_segment, rest_of_line = get_segment(line[26:])
							except ValueError as err:
								print('Line %d: %s' % (src_line_number, err), file=ferr)
						else: # in an ARTCC section
							line_split = [s.strip() for s in line.split(' ', maxsplit=1)] # min len is 1
							drawing_block = line_split[0]
							try:
								got_segment, rest_of_line = get_segment(line_split[1])
							except IndexError:
								print('Missing point specifications on line %d' % src_line_number, file=ferr)
							except ValueError as err:
								print('Line %d: %s' % (src_line_number, err), file=ferr)
					
					if got_segment: # still on boundary or proc section line
						if in_section in ['SID', 'STAR']:
							output_file = 'proc-%s' % in_section
							block_colour = {'SID':'%02X%02XFF', 'STAR':'FF%02X%02X'}[in_section] % (randint(0, 0xDD), randint(0, 0xDD))
						else: # ARTCC
							output_file = 'boundaries-%s' % {'ARTCC': 'main', 'ARTCC HIGH': 'high', 'ARTCC LOW': 'low'}.get(in_section, 'unknown')
							block_colour = 'cyan'
					
				# ---- Write if necessary ---- #
				# must set: last_output_file, last_drawing_block, last_coord_spec
				
				if got_segment:
					point1, point2, coords_spec = got_segment
				if got_segment and all(p.distanceTo(centre_point) <= range_limit for p in (point1, point2)):
					try:
						fout = files[output_file]
					except KeyError:
						new_file = settings.outputFileName(bg_basename(output_file), windowID=False, ext='extract')
						fout = files[output_file] = open(new_file, 'w', encoding='utf8')
						print('#', file=fout)
						print('# Created by ATC-pie extracting from sector file %s' % sector_file, file=fout)
						print('#', file=fout)
						object_counters[output_file] = 0
					if output_file == last_output_file and drawing_block == last_drawing_block \
								and coords_spec[0] == last_coord_spec[0] and coords_spec[1] == last_coord_spec[1]:
						print('%s' % point_to_string(point2), file=fout)
					else:
						print('\n%s  # %s' % (block_colour, drawing_block), file=fout)
						print('%s  @%d' % (point_to_string(point1), src_line_number), file=fout)
						print('%s' % point_to_string(point2), file=fout)
						object_counters[output_file] += 1
					last_output_file = output_file
					last_drawing_block = drawing_block
					last_coord_spec = coords_spec[2:4]
				else:
					last_output_file = last_drawing_block = last_coord_spec = None
	extract_lst_file = settings.outputFileName('%s.lst' % settings.location_code, windowID=False, ext='extract')
	with open(extract_lst_file, 'w', encoding='utf8') as flst:
		for fkey in sorted(files):
			print('%s\tDRAW\t%s: %d object(s)' % (bg_basename(fkey), fkey, object_counters[fkey]), file=flst)
			files[fkey].close()
	print('Wrote ".lst" menu and %d background drawing file(s).' % len(files))



