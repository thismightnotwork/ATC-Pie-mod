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

import os
import re
import sys
from socket import socket, AF_INET, SOCK_DGRAM, SOL_SOCKET, SO_REUSEADDR

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon

from ext.audio import pyaudio_available
from ext.data import import_ad_pos_data, import_entry_exit_data, read_route_presets, \
		load_aircraft_db, load_aircraft_registration_formats, load_airlines_db, \
		make_FGFS_model_recognisers, make_FGFS_models_liveries
from ext.irc import IRC_available
from ext.sr import speech_recognition_available
from ext.tts import speech_synthesis_available
from ext.xplane import import_navaid_data, import_navfix_data, import_airway_data

from gui.launcher import ATCpieLauncher, valid_location_code, min_map_range, max_map_range

from session.config import settings, app_icon_path, version_string


# ---------- Constants ----------

output_dir_name = 'OUTPUT'
nav_data_error_log_file = 'OUTPUT/nav-data-errors.log'

output_file_count_warning = 50

# -------------------------------


valued_option_regexp = re.compile('--([^=]+)=(.+)')



if __name__ == "__main__":
	print('ATC-pie version %s' % version_string)
	if len(os.listdir(output_dir_name)) >= output_file_count_warning:
		print('WARNING: There are many files in the "%s" directory. Consider running clean-up after moving relevant entries.' % output_dir_name)

	app = QApplication(sys.argv)
	app.setWindowIcon(QIcon(app_icon_path))
	
	# Parse arguments
	try:
		location_arg = map_range_arg = None
		args = sys.argv[1:]
		while len(args) > 0:
			arg = args.pop(0)
			match = valued_option_regexp.fullmatch(arg)
			if match:
				if match.group(1) == 'map-range':
					map_range_arg = int(match.group(2))
					if not min_map_range <= map_range_arg <= max_map_range:
						raise ValueError('Map range out of bounds [%d..%d]' % (min_map_range, max_map_range))
				elif match.group(1) == 'views-send-from':
					settings.FGFS_views_send_port = int(match.group(2))
				else:
					raise ValueError('Could not interpret argument: ' + arg)
			elif location_arg is None and valid_location_code(arg):
				location_arg = arg
			else:
				raise ValueError('Bad argument: ' + arg)
		if map_range_arg is not None and location_arg is None:
			raise ValueError('Map range set with no location.')
	except ValueError as err:
		sys.exit('ERROR: %s' % err)
	
	if not IRC_available:
		print('IRC library not found; ATC coordination and CPDLC disabled in FlightGear sessions.')
	if not pyaudio_available:
		print('PyAudio not found; ATC phone lines disabled in all sessions, and voice radio in teacher/student sessions.')
	if not speech_recognition_available:
		print('PocketShpinx or PyAudio not found; voice instruction recognition disabled in solo sessions.')
	if not speech_synthesis_available:
		print('Pyttsx library not found; AI read-back synthesis disabled in solo sessions.')
	
	# Load global DBs
	print('Loading aircraft & airline data...')
	load_aircraft_db()
	load_aircraft_registration_formats()
	load_airlines_db()
	make_FGFS_model_recognisers()
	make_FGFS_models_liveries()
	print('Reading world navigation & routing data...')
	with open(nav_data_error_log_file, 'w') as err_log_file:
		import_ad_pos_data(err_log_file)
		import_navaid_data(err_log_file)
		import_navfix_data(err_log_file)
		import_airway_data(err_log_file)
		import_entry_exit_data(err_log_file)
	print('Starting up...')
	try:
		settings.FGFS_views_send_socket = socket(AF_INET, SOCK_DGRAM)
		settings.FGFS_views_send_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
		settings.FGFS_views_send_socket.bind(('', settings.FGFS_views_send_port))
	except OSError as err:
		sys.exit('Socket creation error: %s' % err)
	
	settings.route_presets = read_route_presets(sys.stderr)
	settings.loadCtrRadarPositions()
	
	w = ATCpieLauncher()
	if location_arg is None:
		w.show()
	else:
		try:
			w.launch(location_arg, ctrPos=settings.CTR_radar_positions.get(location_arg), mapRange=map_range_arg)
		except ValueError as err:
			sys.exit('ERROR: %s' % err)
	
	exit_status = app.exec()
	settings.saveCtrRadarPositions()
	sys.exit(exit_status)
