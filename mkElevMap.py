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

import sys
from subprocess import Popen, PIPE

from base.coords import EarthCoords, RadarCoords
from base.elev import ElevationMap
from base.util import m2NM, m2ft


# ---------- Constants ----------

output_file = 'OUTPUT/auto.elev'
default_fgelev_cmd = 'fgelev' # no default options

# -------------------------------


if __name__ == "__main__":
	args = sys.argv[1:]
	if len(args) != 3 and not (len(args) >= 5 and args[3] == '--'):
		sys.exit('Usage: %s <nw> <se> <prec_metres> [-- <fgelev_cmd>]' % sys.argv[0])
	nw = EarthCoords.fromString(args[0])
	se = EarthCoords.fromString(args[1])
	prec_NM = m2NM * float(args[2])
	fgelev_cmd = default_fgelev_cmd if len(args) < 5 else args[4]
	fgelev_opts = args[5:]
	
	EarthCoords.setRadarPos(nw)
	rnw = nw.toRadarCoords() # 0,0
	rse = se.toRadarCoords() # lon_diff_NM, lat_diff_NM
	lon_diff_NM = rse.x()
	lat_diff_NM = rse.y()
	n_rows = int(lat_diff_NM / prec_NM + .5) + 1
	n_cols = int(lon_diff_NM / prec_NM + .5) + 1
	elev = ElevationMap(rnw, rse, n_rows, n_cols) # checks dimensions and creates store table
	print('Map has %d rows and %d columns.' % (n_rows, n_cols))
	
	with Popen([fgelev_cmd] + fgelev_opts, stdin=PIPE, stdout=PIPE, bufsize=1, universal_newlines=True) as fgelev:
		print('Reading elevations...')
		count = 0
		for i in range(n_rows):
			for j in range(n_cols):
				print('%d%%' % (100 * count / n_rows / n_cols), end='\r')
				coords = EarthCoords.fromRadarCoords(RadarCoords(j * lon_diff_NM / (n_cols - 1), i * lat_diff_NM / (n_rows - 1)))
				print('%d,%d %f %f' % (i, j, coords.lon, coords.lat), file=fgelev.stdin)
				line = fgelev.stdout.readline()
				while ':' not in line:
					print('Ignoring unexpected line from fgelev:', line.rstrip('\n'), file=sys.stderr)
					line = fgelev.stdout.readline()
				ptid, ptelev = (tok.strip() for tok in line.split(':', maxsplit=1))
				row, col = (int(tok) for tok in ptid.split(','))
				if row == i and col == j:
					elev.setElevation(int(row), int(col), m2ft * float(ptelev))
				else:
					print('Unexpected response from fgelev for row/col %d,%d: %s' % (i, j, line.rstrip('\n')), file=sys.stderr)
				count += 1
		print('Done.')
	
	with open(output_file, 'w', encoding='utf8') as fout:
		print('#', file=fout)
		print('# ATC-pie elevation map generated with mkElevMap.py', file=fout)
		print('# Arguments used:', 'NW=%s' % args[0], 'SE=%s' % args[1], 'prec=%s' % args[2], file=fout)
		print('#', file=fout)
		print(file=fout)
		print('%s  %s' % (nw.toString(), se.toString()), file=fout)
		elev.printElevations(f=fout, indent=True)
	
	print('Created file: %s' % output_file)

