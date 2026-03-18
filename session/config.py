
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

from datetime import timedelta
from os import getpid, path
from sys import stderr
from urllib.request import Request, urlopen
from xml.dom import minidom
from xml.etree import ElementTree

from PyQt5.QtGui import QColor

from base.util import some


# ---------- Constants ----------

version_string = '1.10.0' # keep without spaces

app_icon_path = 'resources/pixmap/ATC-pie-logo.png'

global_settings_file = 'CONFIG/settings.conf'
colour_settings_file = 'CONFIG/colours.conf'
radio_msg_presets_file = 'CONFIG/text-radio-messages.conf'
CTR_radar_positions_file = 'CONFIG/CTR-positions.conf'
location_settings_filename_fmt = 'CONFIG/loc/%s.conf'
output_files_dir = 'OUTPUT'

default_map_range_AD = 100 # NM
default_map_range_CTR = 300 # NM

radar_save_state_keyword = 'radar'
loosebay_save_state_keyword = 'loosebay'
stripracks_save_state_keyword = 'racks'

default_radio_msg_presets = [
	'Please note that $icao is controlled. Contact ATC if any intentions.',
	'Go ahead.',
	'Stand by.',
	'QNH $qnh',
	'qnhg|QNH $qnhg',
	'Runways in use: $runways',
	'Wind $wind',
	'Squawk $sq',
	'Number $nseq, traffic ahead ',
	'delsid|Cleared to $dest via $wpsid departure, initial FL 100, squawk $sq, expect runway $rwydep.',
	'delvect|Cleared to $dest via vectors, initial FL 100, squawk $sq, expect runway $rwydep.',
	'rbc|Read back correct, report ready for start-up.',
	'Push-back and start-up approved, report ready to taxi.',
	'luw|Runway $rwy, line up and wait',
	'cto|Wind $wind, runway $rwy, cleared for take-off',
	'Intercept LOC, cleared ILS, report runway in sight.',
	'ctl|Wind $wind, runway $rwy, cleared to land',
	'lost|You are identified on a $qdm bearing to the airport, $dist out.',
	'?cp|Did you copy?',
	'?alt|Say altitude',
	'?pos|Say position',
	'?ias|Say indicated air speed',
	'?mach|Say Mach number',
	'?int|Say intentions',
	'?app|Say type of approach requested',
	'?acft|Say type of aircraft',
	'??radio|Are you able radio, FGCom $frq?',
	'??xpdr|Are you able transponder?',
	'??vor|Are you able VOR navigation?',
	'??taxi|Are you able to taxi?',
	'ATC service now closing at $icao. Fly safe, good bye.'
]

default_colour_specs = {
	'measuring_tool': 'white',
	'point_indicator': 'yellow',
	'RDF_line': 'yellow',
	'loose_strip_bay_background': '333311', # very dark yellow
	# Radar
	'radar_background': '050805',
	'radar_circle': '151515',
	'radar_range_limit': 'olive',
	# Navpoints
	'nav_fix': '009000',
	'nav_aid': '5555ff',
	'nav_airfield': 'darkred',
	'nav_RNAV': 'grey',
	# Strip backgrounds
	'strip_unlinked': 'white',
	'strip_unlinked_identified': 'b0b0ff', # ~blue
	'strip_linked_OK': 'b0ffb0', # ~green
	'strip_linked_warning': 'ffdf83', # ~orange
	'strip_linked_alert': 'ffa0a0', # ~red
	# FPL deco icons
	'FPL_filed': 'black',
	'FPL_filed_outdated': 'grey',
	'FPL_open': 'green',
	'FPL_open_noETA': 'yellow',
	'FPL_open_overdue': 'red',
	'FPL_closed': '808000',
	# Aircraft
	'ACFT_linked': 'white',
	'ACFT_unlinked': '707070',
	'ACFT_ignored': '505050',
	'ACFT_flagged': 'yellow',
	'XPDR_call': 'ff0000',
	'XPDR_identification': '2525ff',
	'selection_indicator': 'white',
	'assignment_OK': 'eeeeee',
	'assignment_bad': 'red',
	'route_followed': 'green',
	'route_overridden': 'aaaa00',
	'separation_ring_OK': '707070',
	'separation_ring_warning': '887700',
	'separation_ring_bad': 'ee3300',
	'radar_tag_line': '404040',
	# Airport
	'AD_tarmac': '252525',
	'AD_parking_position': 'cccc00',
	'AD_holding_lines': 'darkred',
	'AD_taxiway_lines': '555500',
	'AD_runway': 'aaaaaa',
	'AD_viewpoint': 'white',
	'RWY_reserved': 'ccff00',
	'RWY_incursion': 'ff0000',
	'LDG_guide_ILS': '3080d0',
	'LDG_guide_noILS': 'd03080',
	'GND_route_taxiway': 'cc5050',
	'GND_route_apron': '8844aa'
}

# -------------------------------


def open_URL(url, postData=None, timeout=5):
	"""
	May raise urllib.request.urlopen exceptions like URLError
	"""
	req = Request(url, data=postData, headers={'User-Agent': 'ATC-pie/%s' % version_string})
	return urlopen(req, timeout=timeout).read()


def strNoHash_to_QColor(colstr):
	qcol = QColor(colstr)
	if not qcol.isValid():
		qcol = QColor('#' + colstr)
	if qcol.isValid():
		return qcol
	else:
		raise ValueError(colstr)



class XpdrAssignmentRange:
	def __init__(self, name, lo, hi, col):
		if lo > hi:
			raise ValueError('Invalid XPDR range: %04o-%04o' % (lo, hi))
		self.name = name
		self.lo = lo
		self.hi = hi
		self.col = col



class SemiCircRule:
	rules = OFF, E_W, N_S = range(3)






class Settings:
	def __init__(self):
		self.run_count = 0
		self.colours = {k: strNoHash_to_QColor(v) for k, v in default_colour_specs.items()}
		self.radio_msg_presets = []
		self.route_presets = []
		self.CTR_radar_positions = {}
		self.session_manager = None
		self.session_recorder = None
		
		self.loadPresetRadioMessages()
		self.loadColourSettings()
		
		# Permanent between locations; only modifiable from command line
		self.FGFS_views_send_port = 5009
		self.FGFS_views_send_socket = None # not changeable from GUI
		
		# Modifiable defaults
		self._setDefaults_unsavedSettings() # to reset between locations
		self._setDefaults_globalSettings()
		self._setDefaults_locationSettings()   # to reset between locations
		
		
	## ===== UNSAVED SETTINGS ===== ##
	
	def _setDefaults_unsavedSettings(self):
		# Window init.
		self.location_code = ''
		self.map_range = None
		self.first_time_at_location = True
		
		# Internal settings
		self.my_callsign = 'DUMMY'
		self.session_paused = False
		self.keyboard_PTT_pressed = False
		self.last_recorded_ATIS = None # str info letter, datetime recorded, CommFrequency, str notepad
		self.record_ATIS_reminder = None # next datetime to trigger reminder
		self.session_start_temp_lock = False
		self.controlled_tower_viewer = None
		self.radar_background_images = None
		self.loose_strip_bay_backgrounds = None
		self.prepared_lexicon_file = None
		self.prepared_grammar_file = None
		
		# Run-time user options
		self.measuring_tool_logs_coordinates = False
		self.activated_additional_viewers = set() # set of indices in self.additional_viewers
		self.radar_cheat = False
		self.tower_height_cheat_offset = 0
		self.TWR_view_clear_weather_cheat = False
		self.publicised_frequency = None
		self.radios = [] # AbstractRadio list
		self.radios_silenced = False
		self.show_recognised_voice_strings = False
		self.taxi_instructions_avoid_runways = True
		self.solo_erroneous_instruction_warning = False
		self.teacher_ACFT_touch_down_without_clearance = False
		self.text_radio_senders_blacklist = set()
		
		# Modifiable on solo AD start only
		self.solo_role_GND = False
		self.solo_role_TWR = False
		self.solo_role_APP = False
		self.solo_role_DEP = False
	
	
	## ===== SAVED GLOBAL SETTINGS ===== ##
	
	def _setDefaults_globalSettings(self):
		self.MP_social_name = ''         # shared between FG and FSD system settings
		self.FGCom_enabled = False       # shared between FG and FSD start dialogs
		self.phone_lines_enabled = False # shared between FG and FSD start dialogs

		# Modifiable from solo session start/settings dialogs
		self.solo_aircraft_types = ['C172', 'AT43', 'A320', 'A346', 'A388', 'B744', 'B737', 'B772', 'B773']
		self.solo_restrict_to_available_liveries = False
		self.solo_prefer_entry_exit_ADs = False
		self.sphinx_acoustic_model_dir = '' # empty string for Sphinx's default model

		# Modifiable from FG session start/settings dialogs
		self.FGMS_client_port = 5000
		self.FG_IRC_enabled = True   # subsystem tick box
		self.FG_ORSX_enabled = False # subsystem tick box
		self.FGMS_server_host = 'mpserver01.flightgear.org'
		self.FGMS_server_port = 5000
		self.FG_IRC_channel = '#atc'
		self.ORSX_server_name = 'http://h2281805.stratoserver.net/FgFpServer'
		self.ORSX_handover_range = None # None = use radar range; int otherwise
		self.lenny64_account_email = ''
		self.lenny64_password_md5 = ''
		self.FG_FPL_update_interval = timedelta(minutes=5)   # None for manual checks only
		self.FG_METAR_update_interval = timedelta(minutes=2) # None for manual checks only

		# Modifiable from FSD session start/settings dialogs
		self.FSD_visibility_range = 100
		self.FSD_voice_system_port = 16661
		self.FSD_Hoppie_enabled = False # subsystem tick box
		self.FSD_server_host = 'localhost'
		self.FSD_server_port = 6809
		self.FSD_cid = ''
		self.FSD_rating = 2
		self.FSD_password = ''
		self.FSD_Hoppie_logon = ''
		self.FSD_weather_from_server = True
		self.FSD_METAR_update_interval = timedelta(minutes=5) # None for manual checks only

		# Modifiable from teacher/student session start dialogs
		self.teaching_service_host = '' # student only
		self.teaching_service_port = 5000 # teacher & student

		# Modifiable from FGFS viewer settings dialogs
		self.external_tower_viewer_process = False
		self.FGFS_executable = 'fgfs'
		self.FGFS_root_dir = '' # empty string for FlightGear default directory
		self.FGFS_aircraft_dir = '' # empty string for FlightGear default directory
		self.FGFS_scenery_dir = '' # empty string for FlightGear default directory
		self.external_tower_viewer_host = 'localhost'
		self.tower_viewer_UDP_port = 5010
		self.tower_viewer_telnet_port = 5010
		self.additional_viewers = []   # modifiable from its own dialog (host+port tuple list)

		# Modifiable from FG/FSD voice settings dialogs
		self.FGCom_mumble_host = 'localhost'
		self.FGCom_mumble_port = 16661
		self.FGCom_mumble_sound_effects = True
		self.reachable_phone_IP = ''

		# Modifiable from menus/panels
		self.mute_notifications = False
		self.primary_radar_active = False
		self.route_conflict_warnings = True
		self.traffic_identification_assistant = True
		self.APP_spacing_hints = False
		self.monitor_runway_occupation = False
		self.general_notes = ''
		self.phone_line_squelch = .006   # modifiable from GUI outside of dialog
		
		# Modifiable from general settings dialog
		self.strip_route_vect_warnings = True
		self.strip_CPDLC_integration = True
		self.vertical_runway_box_layout = False
		self.confirm_handovers = False
		self.confirm_lossy_strip_releases = False
		self.confirm_linked_strip_deletions = True
		self.strip_autofill_on_ACFT_link = False
		self.strip_autofill_on_FPL_link = True
		self.strip_autofill_before_handovers = True
		self.strip_autolink_mode_S = False
		self.strip_autolink_open_FPL = False

		self.use_known_aircraft = True
		self.known_aircraft = {} # callsign -> ACFT type

		self.radar_sweeping_display = True
		self.radar_contact_trace_time = timedelta(minutes=1) # zero timedelta is fine
		self.invisible_blips_before_contact_lost = 5
		self.radar_tag_FL_at_bottom = False
		self.radar_tag_speed_tens = False
		self.radar_tag_WTC_position = 0 # 0: not shown; 1: follows ACFT type; 2: follows speed
		self.radar_tag_interpret_XPDR_FL = False
		
		self.heading_tolerance = 10 # degrees
		self.altitude_tolerance = 100 # ft
		self.speed_tolerance = 15 # kt
		self.route_conflict_anticipation = timedelta(minutes=5) # zero timedelta is fine
		self.route_conflict_traffic = 0 # 0: exclude VFR; 1: marked IFR only; 2: all controlled traffic
		self.seq_opt_min_combo_gain = timedelta(minutes=1) # zero timedelta is fine
		self.seq_opt_max_acft_loss = timedelta(minutes=1)

		self.CPDLC_ACK_timeout = timedelta(seconds=60) # None for no timeout
		self.CPDLC_send_COMU9_to_accepted_transfers = False
		self.CPDLC_send_strips_on_accepted_transfers = False
		self.CPDLC_raises_windows = True
		self.CPDLC_closes_windows = False
		
		self.private_ATC_msg_auto_raise = False
		self.ATC_chatroom_msg_notifications = False
		self.text_radio_history_time = None # timedelta, or None for no limit
		
		self.sound_notifications = None # int set (meaning depends on order of Notification.types) or None to be filled later
		self.PTT_mutes_notifications = False
		
		# Modifiable from solo session options dialog
		self.solo_max_aircraft_count = 6
		self.solo_min_spawn_delay = timedelta(seconds=30) # minimum is 1 s in settings
		self.solo_max_spawn_delay = timedelta(minutes=5)  # minimum is 2 min in settings
		self.solo_distracting_traffic_count = 0
		self.solo_CPDLC_balance = 0
		self.solo_ARRvsDEP_balance = .33
		self.solo_ILSvsVisual_balance = 0
		self.solo_helos_request_ILS = True
		self.solo_MISAP_probability = 0
		self.solo_weather_change_interval = timedelta(minutes=15) # None for no change
		self.solo_voice_instructions = False
		self.solo_wilco_beeps = True
		self.solo_voice_readback = False
	
	
	## ===== SAVED LOCATION-SPECIFIC SETTINGS ===== ##
	
	def _setDefaults_locationSettings(self):
		# User-modifiable from GUI menus and panels
		self.custom_viewpoints = []
		self.selected_viewpoint = 0
		self.additional_METAR_stations = []
		self.rack_colours = {}     # for racks with an assigned colour: str -> QColor
		self.ATC_collecting_racks = {} # for ATCs with an assigned receiving rack: str callsign -> str rack name
		self.auto_print_collecting_rack = None # if non-default rack collects the auto-printed strips
		self.private_racks = set() # racks excluded from who-has answers
		self.local_notes = ''
		
		# User-modifiable from location settings dialog
		self.radio_direction_finding = True
		self.controller_pilot_data_link = False
		self.SSR_mode_capability = 'C' # possible values are '0' if no SSR, otherwise 'A', 'C' or 'S'
		self.radar_range = 80 # NM
		self.radar_signal_floor_level = 0 # ft ASFC (real, not pressure-dependant)
		self.radar_sweep_interval = timedelta(seconds=5) # minimum is 1 s in settings
		self.auto_print_strips_include_DEP = True
		self.auto_print_strips_include_ARR = False
		self.auto_print_strips_IFR_only = False
		self.auto_print_strips_anticipation = timedelta(minutes=15) # zero timedelta is fine
		
		self.horizontal_separation = 5 # NM
		self.vertical_separation = 500 # ft
		self.conflict_warning_floor_FL = 80
		self.transition_altitude = 5000 # ft (useless if a TA is set in apt.dat)
		self.uncontrolled_VFR_XPDR_code = 0o7000
		self.primary_METAR_station = ''
		self.location_radio_name = ''
		self.magnetic_declination = 0
		
		self.XPDR_assignment_ranges = []
		
		self.solo_APP_ceiling_FL_min = 80
		self.solo_APP_ceiling_FL_max = 120
		self.solo_TWR_ceiling_FL = 20
		self.solo_TWR_range_dist = 10
		self.solo_CTR_floor_FL = 200
		self.solo_CTR_ceiling_FL = 300
		self.solo_CTR_range_dist = 60
		self.solo_CTR_routing_points = [] # str list, normally of fix or navaid names
		self.solo_CTR_semi_circular_rule = SemiCircRule.E_W
		self.ATIS_custom_appendix = ''
		
		# Set once when restoring from settings; used then before closing; not always in sync in between
		self.saved_strip_racks = []
		self.saved_strip_dock_state = {}
		self.saved_user_panels_states = [] # (str type, str title, dict state save) list
		self.saved_selected_docked_panel = 0 # action index in central panel selection menu
	
	
	## ===== WINDOW IDs, RESETTING FOR NEW START-UP ===== ##
	def resetForNewWindow(self):
		self._setDefaults_unsavedSettings()
		self._setDefaults_locationSettings()
		self.run_count += 1
	
	def windowID(self):
		return '%d-%d' % (getpid(), self.run_count)

	def outputFileName(self, base_name, windowID=True, ext=None):
		name = 'window-%s.' % self.windowID() if windowID else ''
		name += base_name
		if ext is not None:
			name += '.%s' % ext
		return path.join(output_files_dir, name)
	
	
	## ===== CTR RADAR POSITIONS ===== ##
	
	def loadCtrRadarPositions(self):
		try:
			with open(CTR_radar_positions_file, encoding='utf8') as f:
				for line in f:
					tokens = line.split('#', maxsplit=1)[0].split()
					if len(tokens) == 0:
						pass
					elif len(tokens) == 2:
						self.CTR_radar_positions[tokens[0]] = tokens[1]
					else:
						print('Error on CTR position spec line: %s' % line.rstrip('\n'), file=stderr)
		except FileNotFoundError:
			pass
	
	def saveCtrRadarPositions(self):
		with open(CTR_radar_positions_file, 'w', encoding='utf8') as f:
			for code, pos in self.CTR_radar_positions.items():
				print('%s\t%s' % (code, pos), file=f)
	
	
	## ===== PRESET TEXT MESSAGES ===== ##
	
	def loadPresetRadioMessages(self):
		try:
			with open(radio_msg_presets_file, encoding='utf8') as f:
				self.radio_msg_presets = [line.strip() for line in f.readlines() if line.strip() != '']
		except FileNotFoundError:
			self.radio_msg_presets = default_radio_msg_presets[:]
	
	def savePresetRadioMessages(self):
		with open(radio_msg_presets_file, 'w', encoding='utf8') as f:
			for msg in self.radio_msg_presets:
				print(msg, file=f)


	## ===== COLOUR SETTINGS ===== ##

	def loadColourSettings(self):
		try:
			with open(colour_settings_file, encoding='utf8') as f:
				expected_colours = set(default_colour_specs)
				for line in f:
					tokens = line.split('#', maxsplit=1)[0].split()
					if len(tokens) == 2:
						if tokens[0] in self.colours:
							expected_colours.remove(tokens[0])
							try:
								self.colours[tokens[0]] = strNoHash_to_QColor(tokens[1])
							except ValueError as err:
								print('Invalid colour specification "%s"' % err, file=stderr)
						else:
							print('Unknown colour specification "%s"' % tokens[0], file=stderr)
					elif len(tokens) != 0:
						print('Invalid colour spec line: %s' % line.rstrip('\n'), file=stderr)
			if len(expected_colours) > 0:
				print('Missing colour specification(s): %s' % ', '.join(expected_colours), file=stderr)
		except FileNotFoundError:
			with open(colour_settings_file, 'w', encoding='utf8') as f:
				for k in sorted(default_colour_specs):
					print('%s\t%s' % (k, default_colour_specs[k]), file=f)
			print('Created default colour configuration file.')


	## ===== SAVING SETTINGS ===== ##

	def saveGlobalSettings(self):
		root = ElementTree.Element('settings')

		root.append(xmllstelt('solo_aircraft_types', self.solo_aircraft_types, lambda t: xmlelt('aircraft_type', t)))
		root.append(xmlelt('solo_restrict_to_available_liveries', str(int(self.solo_restrict_to_available_liveries))))
		root.append(xmlelt('solo_prefer_entry_exit_ADs', str(int(self.solo_prefer_entry_exit_ADs))))
		root.append(xmlelt('sphinx_acoustic_model_dir', self.sphinx_acoustic_model_dir))

		root.append(xmlelt('FGMS_server_host', self.FGMS_server_host))
		root.append(xmlelt('FGMS_server_port', str(self.FGMS_server_port)))
		root.append(xmlelt('MP_social_name', self.MP_social_name))
		root.append(xmlelt('FG_IRC_channel', self.FG_IRC_channel))
		root.append(xmlelt('ORSX_server_name', self.ORSX_server_name))
		if self.ORSX_handover_range is not None:
			root.append(xmlelt('ORSX_handover_range', str(self.ORSX_handover_range)))
		root.append(xmlelt('lenny64_account_email', self.lenny64_account_email))
		root.append(xmlelt('lenny64_password_md5', self.lenny64_password_md5))
		root.append(xmlelt('FG_FPL_update_interval', str(0 if self.FG_FPL_update_interval is None else int(self.FG_FPL_update_interval.total_seconds() / 60))))
		root.append(xmlelt('FG_METAR_update_interval', str(0 if self.FG_METAR_update_interval is None else int(self.FG_METAR_update_interval.total_seconds() / 60))))

		root.append(xmlelt('FSD_server_host', self.FSD_server_host))
		root.append(xmlelt('FSD_server_port', str(self.FSD_server_port)))
		root.append(xmlelt('FSD_cid', self.FSD_cid))
		root.append(xmlelt('FSD_rating', str(self.FSD_rating)))
		root.append(xmlelt('FSD_password', self.FSD_password))
		root.append(xmlelt('FSD_Hoppie_logon', self.FSD_Hoppie_logon))
		root.append(xmlelt('FSD_weather_from_server', str(int(self.FSD_weather_from_server))))
		root.append(xmlelt('FSD_METAR_update_interval', str(0 if self.FSD_METAR_update_interval is None else int(self.FSD_METAR_update_interval.total_seconds() / 60))))

		root.append(xmlelt('FGCom_mumble_host', self.FGCom_mumble_host))
		root.append(xmlelt('FGCom_mumble_port', str(self.FGCom_mumble_port)))
		root.append(xmlelt('FGCom_mumble_sound_effects', str(int(self.FGCom_mumble_sound_effects))))
		root.append(xmlelt('reachable_phone_IP', self.reachable_phone_IP))

		root.append(xmlelt('external_tower_viewer_process', str(int(self.external_tower_viewer_process))))
		root.append(xmlelt('FGFS_executable', self.FGFS_executable))
		root.append(xmlelt('FGFS_root_dir', self.FGFS_root_dir))
		root.append(xmlelt('FGFS_aircraft_dir', self.FGFS_aircraft_dir))
		root.append(xmlelt('FGFS_scenery_dir', self.FGFS_scenery_dir))
		root.append(xmlelt('external_tower_viewer_host', self.external_tower_viewer_host))
		root.append(xmlelt('tower_viewer_UDP_port', str(self.tower_viewer_UDP_port)))
		root.append(xmlelt('tower_viewer_telnet_port', str(self.tower_viewer_telnet_port)))

		root.append(xmllstelt('additional_viewers', self.additional_viewers,
				lambda inet: xmlelt('viewer', None, attrib={'host': inet[0], 'port': str(inet[1])})))
		root.append(xmlelt('phone_line_squelch', str(self.phone_line_squelch)))
		root.append(xmlelt('FGCom_enabled', str(int(self.FGCom_enabled))))
		root.append(xmlelt('phone_lines_enabled', str(int(self.phone_lines_enabled))))
		root.append(xmlelt('FGMS_client_port', str(self.FGMS_client_port)))
		root.append(xmlelt('FG_IRC_enabled', str(int(self.FG_IRC_enabled))))
		root.append(xmlelt('FG_ORSX_enabled', str(int(self.FG_ORSX_enabled))))
		root.append(xmlelt('FSD_visibility_range', str(self.FSD_visibility_range)))
		root.append(xmlelt('FSD_voice_system_port', str(self.FSD_voice_system_port)))
		root.append(xmlelt('FSD_Hoppie_enabled', str(int(self.FSD_Hoppie_enabled))))
		root.append(xmlelt('teaching_service_host', self.teaching_service_host))
		root.append(xmlelt('teaching_service_port', str(self.teaching_service_port)))

		root.append(xmlelt('mute_notifications', str(int(self.mute_notifications))))
		root.append(xmlelt('primary_radar_active', str(int(self.primary_radar_active))))
		root.append(xmlelt('traffic_identification_assistant', str(int(self.traffic_identification_assistant))))
		root.append(xmlelt('route_conflict_warnings', str(int(self.route_conflict_warnings))))
		root.append(xmlelt('APP_spacing_hints', str(int(self.APP_spacing_hints))))
		root.append(xmlelt('monitor_runway_occupation', str(int(self.monitor_runway_occupation))))
		root.append(xmlelt('general_notes', self.general_notes))

		root.append(xmlelt('strip_route_vect_warnings', str(int(self.strip_route_vect_warnings))))
		root.append(xmlelt('strip_CPDLC_integration', str(int(self.strip_CPDLC_integration))))
		root.append(xmlelt('vertical_runway_box_layout', str(int(self.vertical_runway_box_layout))))
		root.append(xmlelt('confirm_handovers', str(int(self.confirm_handovers))))
		root.append(xmlelt('confirm_lossy_strip_releases', str(int(self.confirm_lossy_strip_releases))))
		root.append(xmlelt('confirm_linked_strip_deletions', str(int(self.confirm_linked_strip_deletions))))
		root.append(xmlelt('strip_autofill_on_ACFT_link', str(int(self.strip_autofill_on_ACFT_link))))
		root.append(xmlelt('strip_autofill_on_FPL_link', str(int(self.strip_autofill_on_FPL_link))))
		root.append(xmlelt('strip_autofill_before_handovers', str(int(self.strip_autofill_before_handovers))))
		root.append(xmlelt('strip_autolink_mode_S', str(int(self.strip_autolink_mode_S))))
		root.append(xmlelt('strip_autolink_open_FPL', str(int(self.strip_autolink_open_FPL))))
		root.append(xmlelt('use_known_aircraft', str(int(self.use_known_aircraft))))
		root.append(xmllstelt('known_aircraft', self.known_aircraft.items(),
				lambda acft_type_pair: xmlelt('known_acft', None, attrib={'callsign': acft_type_pair[0], 'type': acft_type_pair[1]})))
		root.append(xmlelt('radar_sweeping_display', str(int(self.radar_sweeping_display))))
		root.append(xmlelt('radar_contact_trace_time', str(int(self.radar_contact_trace_time.total_seconds() / 60))))
		root.append(xmlelt('invisible_blips_before_contact_lost', str(int(self.invisible_blips_before_contact_lost))))
		root.append(xmlelt('radar_tag_FL_at_bottom', str(int(self.radar_tag_FL_at_bottom))))
		root.append(xmlelt('radar_tag_speed_tens', str(int(self.radar_tag_speed_tens))))
		root.append(xmlelt('radar_tag_WTC_position', str(self.radar_tag_WTC_position)))
		root.append(xmlelt('radar_tag_interpret_XPDR_FL', str(int(self.radar_tag_interpret_XPDR_FL))))
		root.append(xmlelt('heading_tolerance', str(self.heading_tolerance)))
		root.append(xmlelt('altitude_tolerance', str(self.altitude_tolerance)))
		root.append(xmlelt('speed_tolerance', str(self.speed_tolerance)))
		root.append(xmlelt('route_conflict_anticipation', str(int(self.route_conflict_anticipation.total_seconds() / 60))))
		root.append(xmlelt('route_conflict_traffic', str(self.route_conflict_traffic)))
		root.append(xmlelt('seq_opt_min_combo_gain', str(int(self.seq_opt_min_combo_gain.total_seconds() / 60))))
		root.append(xmlelt('seq_opt_max_acft_loss', str(int(self.seq_opt_max_acft_loss.total_seconds() / 60))))
		root.append(xmlelt('CPDLC_ACK_timeout', str(0 if self.CPDLC_ACK_timeout is None else int(self.CPDLC_ACK_timeout.total_seconds()))))
		root.append(xmlelt('CPDLC_send_COMU9_to_accepted_transfers', str(int(self.CPDLC_send_COMU9_to_accepted_transfers))))
		root.append(xmlelt('CPDLC_send_strips_on_accepted_transfers', str(int(self.CPDLC_send_strips_on_accepted_transfers))))
		root.append(xmlelt('CPDLC_raises_windows', str(int(self.CPDLC_raises_windows))))
		root.append(xmlelt('CPDLC_closes_windows', str(int(self.CPDLC_closes_windows))))
		root.append(xmlelt('private_ATC_msg_auto_raise', str(int(self.private_ATC_msg_auto_raise))))
		root.append(xmlelt('ATC_chatroom_msg_notifications', str(int(self.ATC_chatroom_msg_notifications))))
		root.append(xmlelt('text_radio_history_time', str(0 if self.text_radio_history_time is None else int(self.text_radio_history_time.total_seconds() / 60))))
		root.append(xmlelt('PTT_mutes_notifications', str(int(self.PTT_mutes_notifications))))
		root.append(xmlelt('sound_notifications', ','.join(str(n) for n in self.sound_notifications)))

		root.append(xmlelt('solo_max_aircraft_count', str(self.solo_max_aircraft_count)))
		root.append(xmlelt('solo_min_spawn_delay', str(int(self.solo_min_spawn_delay.total_seconds()))))
		root.append(xmlelt('solo_max_spawn_delay', str(int(self.solo_max_spawn_delay.total_seconds()))))
		root.append(xmlelt('solo_distracting_traffic_count', str(self.solo_distracting_traffic_count)))
		root.append(xmlelt('solo_CPDLC_balance', str(self.solo_CPDLC_balance)))
		root.append(xmlelt('solo_ARRvsDEP_balance', str(self.solo_ARRvsDEP_balance)))
		root.append(xmlelt('solo_ILSvsVisual_balance', str(self.solo_ILSvsVisual_balance)))
		root.append(xmlelt('solo_helos_request_ILS', str(int(self.solo_helos_request_ILS))))
		root.append(xmlelt('solo_MISAP_probability', str(self.solo_MISAP_probability)))
		root.append(xmlelt('solo_weather_change_interval', str(0 if self.solo_weather_change_interval is None else int(self.solo_weather_change_interval.total_seconds() / 60))))
		root.append(xmlelt('solo_voice_instructions', str(int(self.solo_voice_instructions))))
		root.append(xmlelt('solo_wilco_beeps', str(int(self.solo_wilco_beeps))))
		root.append(xmlelt('solo_voice_readback', str(int(self.solo_voice_readback))))

		with open(global_settings_file, 'w', encoding='utf8') as f:
			f.write(minidom.parseString(ElementTree.tostring(root)).toprettyxml()) # STYLE: generating and reparsing before writing
		self.savePresetRadioMessages() # saves in separate file
	
	# Location settings
	def saveLocationSettings(self, airportData):
		"""
		airportData=None for CTR mode
		"""
		root = ElementTree.Element('settings')
		filename = location_settings_filename_fmt % self.location_code
		
		if airportData is None:
			root.append(xmlelt('solo_CTR_floor_FL', str(self.solo_CTR_floor_FL)))
			root.append(xmlelt('solo_CTR_ceiling_FL', str(self.solo_CTR_ceiling_FL)))
			root.append(xmlelt('solo_CTR_range_dist', str(self.solo_CTR_range_dist)))
			root.append(xmlelt('solo_CTR_routing_points', ' '.join(self.solo_CTR_routing_points)))
			root.append(xmlelt('solo_CTR_semi_circular_rule', str(self.solo_CTR_semi_circular_rule)))
		else:
			root.append(xmllstelt('surface_parameters', airportData.directionalRunways() + airportData.helipads(), mk_sfc_param_elt))
			root.append(xmllstelt('custom_viewpoints', self.custom_viewpoints, mk_custom_viewpoint_elt))
			root.append(xmlelt('selected_viewpoint', str(self.selected_viewpoint)))
			
			root.append(xmlelt('solo_TWR_range_dist', str(self.solo_TWR_range_dist)))
			root.append(xmlelt('solo_TWR_ceiling_FL', str(self.solo_TWR_ceiling_FL)))
			root.append(xmlelt('solo_APP_ceiling_FL_min', str(self.solo_APP_ceiling_FL_min)))
			root.append(xmlelt('solo_APP_ceiling_FL_max', str(self.solo_APP_ceiling_FL_max)))
		
		root.append(xmlelt('radio_direction_finding', str(int(self.radio_direction_finding))))
		root.append(xmlelt('controller_pilot_data_link', str(int(self.controller_pilot_data_link))))
		root.append(xmlelt('SSR_mode_capability', self.SSR_mode_capability))
		root.append(xmlelt('radar_range', str(self.radar_range)))
		root.append(xmlelt('radar_signal_floor_level', str(self.radar_signal_floor_level)))
		root.append(xmlelt('radar_sweep_interval', str(int(self.radar_sweep_interval.total_seconds()))))
		root.append(xmlelt('auto_print_strips_include_DEP', str(int(self.auto_print_strips_include_DEP))))
		root.append(xmlelt('auto_print_strips_include_ARR', str(int(self.auto_print_strips_include_ARR))))
		root.append(xmlelt('auto_print_strips_IFR_only', str(int(self.auto_print_strips_IFR_only))))
		root.append(xmlelt('auto_print_strips_anticipation', str(int(self.auto_print_strips_anticipation.total_seconds() / 60))))
		
		root.append(xmlelt('horizontal_separation', str(self.horizontal_separation)))
		root.append(xmlelt('vertical_separation', str(self.vertical_separation)))
		root.append(xmlelt('conflict_warning_floor_FL', str(self.conflict_warning_floor_FL)))
		if airportData is None or airportData.transition_altitude is None:
			root.append(xmlelt('transition_altitude', str(self.transition_altitude)))
		root.append(xmlelt('uncontrolled_VFR_XPDR_code', '%04o' % self.uncontrolled_VFR_XPDR_code))
		root.append(xmlelt('primary_METAR_station', self.primary_METAR_station))
		root.append(xmlelt('location_radio_name', self.location_radio_name))
		root.append(xmlelt('magnetic_declination', str(self.magnetic_declination)))
		
		root.append(xmllstelt('XPDR_ranges', self.XPDR_assignment_ranges, mk_xpdr_range_elt))
		root.append(xmlelt('ATIS_custom_appendix', self.ATIS_custom_appendix))

		root.append(xmllstelt('additional_METAR_stations', self.additional_METAR_stations, lambda s: xmlelt('additional_METAR_station', s)))
		root.append(xmlelt('local_notes', self.local_notes))
		root.append(xmllstelt('strip_racks', self.saved_strip_racks, lambda rack:
				mk_rack_elt(rack, [atc for atc, collector in self.ATC_collecting_racks.items() if collector == rack], self.rack_colours.get(rack), rack in self.private_racks)))
		root.append(mk_panels_state_elt(self.saved_strip_dock_state, self.saved_user_panels_states, self.saved_selected_docked_panel))
		if self.auto_print_collecting_rack is not None:
			root.append(xmlelt('auto_print_collecting_rack', self.auto_print_collecting_rack))
		with open(filename, 'w', encoding='utf8') as f:
			f.write(minidom.parseString(ElementTree.tostring(root)).toprettyxml()) # STYLE: generating and reparsing before writing
		
		
	## ===== RESTORING SETTINGS ===== ##
	
	def restoreGlobalSettings(self):
		root = ElementTree.parse(global_settings_file).getroot()

		solo_aircraft_types = root.find('solo_aircraft_types')
		if solo_aircraft_types is not None:
			self.solo_aircraft_types = [elt.text for elt in solo_aircraft_types.iter('aircraft_type') if elt.text is not None]
		solo_restrict_to_available_liveries = root.find('solo_restrict_to_available_liveries')
		if solo_restrict_to_available_liveries is not None:
			self.solo_restrict_to_available_liveries = bool(int(solo_restrict_to_available_liveries.text)) # 0/1
		solo_prefer_entry_exit_ADs = root.find('solo_prefer_entry_exit_ADs')
		if solo_prefer_entry_exit_ADs is not None:
			self.solo_prefer_entry_exit_ADs = bool(int(solo_prefer_entry_exit_ADs.text)) # 0/1
		sphinx_acoustic_model_dir = root.find('sphinx_acoustic_model_dir')
		if sphinx_acoustic_model_dir is not None:
			self.sphinx_acoustic_model_dir = get_text(sphinx_acoustic_model_dir)
		
		FGMS_server_host = root.find('FGMS_server_host')
		if FGMS_server_host is not None:
			self.FGMS_server_host = get_text(FGMS_server_host)
		FGMS_server_port = root.find('FGMS_server_port')
		if FGMS_server_port is not None:
			self.FGMS_server_port = int(FGMS_server_port.text)
		MP_social_name = root.find('MP_social_name')
		if MP_social_name is not None:
			self.MP_social_name = get_text(MP_social_name)
		FG_IRC_channel = root.find('FG_IRC_channel')
		if FG_IRC_channel is not None:
			self.FG_IRC_channel = get_text(FG_IRC_channel)
		ORSX_server_name = root.find('ORSX_server_name')
		if ORSX_server_name is not None:
			self.ORSX_server_name = get_text(ORSX_server_name)
		ORSX_handover_range = root.find('ORSX_handover_range')
		if ORSX_handover_range is not None:
			self.ORSX_handover_range = int(ORSX_handover_range.text)
		lenny64_account_email = root.find('lenny64_account_email')
		if lenny64_account_email is not None:
			self.lenny64_account_email = get_text(lenny64_account_email)
		lenny64_password_md5 = root.find('lenny64_password_md5')
		if lenny64_password_md5 is not None:
			self.lenny64_password_md5 = get_text(lenny64_password_md5)
		FG_FPL_update_interval = root.find('FG_FPL_update_interval')
		if FG_FPL_update_interval is not None:
			value = int(FG_FPL_update_interval.text)
			self.FG_FPL_update_interval = None if value == 0 else timedelta(minutes=value)
		FG_METAR_update_interval = root.find('FG_METAR_update_interval')
		if FG_METAR_update_interval is not None:
			value = int(FG_METAR_update_interval.text)
			self.FG_METAR_update_interval = None if value == 0 else timedelta(minutes=value)
		
		FSD_server_host = root.find('FSD_server_host')
		if FSD_server_host is not None:
			self.FSD_server_host = get_text(FSD_server_host)
		FSD_server_port = root.find('FSD_server_port')
		if FSD_server_port is not None:
			self.FSD_server_port = int(FSD_server_port.text)
		FSD_cid = root.find('FSD_cid')
		if FSD_cid is not None:
			self.FSD_cid = get_text(FSD_cid)
		FSD_rating = root.find('FSD_rating')
		if FSD_rating is not None:
			self.FSD_rating = int(FSD_rating.text)
		FSD_password = root.find('FSD_password')
		if FSD_password is not None:
			self.FSD_password = get_text(FSD_password)
		FSD_Hoppie_logon = root.find('FSD_Hoppie_logon')
		if FSD_Hoppie_logon is not None:
			self.FSD_Hoppie_logon = get_text(FSD_Hoppie_logon)
		FSD_weather_from_server = root.find('FSD_weather_from_server')
		if FSD_weather_from_server is not None:
			self.FSD_weather_from_server = bool(int(FSD_weather_from_server.text)) # 0/1
		FSD_METAR_update_interval = root.find('FSD_METAR_update_interval')
		if FSD_METAR_update_interval is not None:
			value = int(FSD_METAR_update_interval.text)
			self.FSD_METAR_update_interval = None if value == 0 else timedelta(minutes=value)

		FGCom_mumble_host = root.find('FGCom_mumble_host')
		if FGCom_mumble_host is not None:
			self.FGCom_mumble_host = get_text(FGCom_mumble_host)
		FGCom_mumble_port = root.find('FGCom_mumble_port')
		if FGCom_mumble_port is not None:
			self.FGCom_mumble_port = int(FGCom_mumble_port.text)
		FGCom_mumble_sound_effects = root.find('FGCom_mumble_sound_effects')
		if FGCom_mumble_sound_effects is not None:
			self.FGCom_mumble_sound_effects = bool(int(FGCom_mumble_sound_effects.text)) # 0/1
		reachable_phone_IP = root.find('reachable_phone_IP')
		if reachable_phone_IP is not None:
			self.reachable_phone_IP = get_text(reachable_phone_IP)
		
		external_tower_viewer_process = root.find('external_tower_viewer_process')
		if external_tower_viewer_process is not None:
			self.external_tower_viewer_process = bool(int(external_tower_viewer_process.text))
		FGFS_executable = root.find('FGFS_executable')
		if FGFS_executable is not None:
			self.FGFS_executable = get_text(FGFS_executable)
		FGFS_root_dir = root.find('FGFS_root_dir')
		if FGFS_root_dir is not None:
			self.FGFS_root_dir = get_text(FGFS_root_dir)
		FGFS_aircraft_dir = root.find('FGFS_aircraft_dir')
		if FGFS_aircraft_dir is not None:
			self.FGFS_aircraft_dir = get_text(FGFS_aircraft_dir)
		FGFS_scenery_dir = root.find('FGFS_scenery_dir')
		if FGFS_scenery_dir is not None:
			self.FGFS_scenery_dir = get_text(FGFS_scenery_dir)
		external_tower_viewer_host = root.find('external_tower_viewer_host')
		if external_tower_viewer_host is not None:
			self.external_tower_viewer_host = get_text(external_tower_viewer_host)
		tower_viewer_UDP_port = root.find('tower_viewer_UDP_port')
		if tower_viewer_UDP_port is not None:
			self.tower_viewer_UDP_port = int(tower_viewer_UDP_port.text)
		tower_viewer_telnet_port = root.find('tower_viewer_telnet_port')
		if tower_viewer_telnet_port is not None:
			self.tower_viewer_telnet_port = int(tower_viewer_telnet_port.text)

		additional_viewers = root.find('additional_viewers')
		if additional_viewers is not None:
			for viewer_elt in additional_viewers.iter('viewer'):
				try:
					self.additional_viewers.append((viewer_elt.attrib['host'], int(viewer_elt.attrib['port'])))
				except (KeyError, IndexError):
					print('Invalid viewer specification.', file=stderr)
		phone_line_squelch = root.find('phone_line_squelch')
		if phone_line_squelch is not None:
			self.phone_line_squelch = float(phone_line_squelch.text)
		FGCom_enabled = root.find('FGCom_enabled')
		if FGCom_enabled is not None:
			self.FGCom_enabled = bool(int(FGCom_enabled.text)) # 0/1
		phone_lines_enabled = root.find('phone_lines_enabled')
		if phone_lines_enabled is not None:
			self.phone_lines_enabled = bool(int(phone_lines_enabled.text)) # 0/1
		FGMS_client_port = root.find('FGMS_client_port')
		if FGMS_client_port is not None:
			self.FGMS_client_port = int(FGMS_client_port.text)
		FG_IRC_enabled = root.find('FG_IRC_enabled')
		if FG_IRC_enabled is not None:
			self.FG_IRC_enabled = bool(int(FG_IRC_enabled.text)) # 0/1
		FG_ORSX_enabled = root.find('FG_ORSX_enabled')
		if FG_ORSX_enabled is not None:
			self.FG_ORSX_enabled = bool(int(FG_ORSX_enabled.text)) # 0/1
		FSD_visibility_range = root.find('FSD_visibility_range')
		if FSD_visibility_range is not None:
			self.FSD_visibility_range = int(FSD_visibility_range.text)
		FSD_voice_system_port = root.find('FSD_voice_system_port')
		if FSD_voice_system_port is not None:
			self.FSD_voice_system_port = int(FSD_voice_system_port.text)
		FSD_Hoppie_enabled = root.find('FSD_Hoppie_enabled')
		if FSD_Hoppie_enabled is not None:
			self.FSD_Hoppie_enabled = bool(int(FSD_Hoppie_enabled.text)) # 0/1
		teaching_service_host = root.find('teaching_service_host')
		if teaching_service_host is not None:
			self.teaching_service_host = get_text(teaching_service_host)
		teaching_service_port = root.find('teaching_service_port')
		if teaching_service_port is not None:
			self.teaching_service_port = int(teaching_service_port.text)

		strip_route_vect_warnings = root.find('strip_route_vect_warnings')
		if strip_route_vect_warnings is not None:
			self.strip_route_vect_warnings = bool(int(strip_route_vect_warnings.text)) # 0/1
		strip_CPDLC_integration = root.find('strip_CPDLC_integration')
		if strip_CPDLC_integration is not None:
			self.strip_CPDLC_integration = bool(int(strip_CPDLC_integration.text)) # 0/1
		vertical_runway_box_layout = root.find('vertical_runway_box_layout')
		if vertical_runway_box_layout is not None:
			self.vertical_runway_box_layout = bool(int(vertical_runway_box_layout.text)) # 0/1
		confirm_handovers = root.find('confirm_handovers')
		if confirm_handovers is not None:
			self.confirm_handovers = bool(int(confirm_handovers.text)) # 0/1
		confirm_lossy_strip_releases = root.find('confirm_lossy_strip_releases')
		if confirm_lossy_strip_releases is not None:
			self.confirm_lossy_strip_releases = bool(int(confirm_lossy_strip_releases.text)) # 0/1
		confirm_linked_strip_deletions = root.find('confirm_linked_strip_deletions')
		if confirm_linked_strip_deletions is not None:
			self.confirm_linked_strip_deletions = bool(int(confirm_linked_strip_deletions.text)) # 0/1
		strip_autofill_on_ACFT_link = root.find('strip_autofill_on_ACFT_link')
		if strip_autofill_on_ACFT_link is not None:
			self.strip_autofill_on_ACFT_link = bool(int(strip_autofill_on_ACFT_link.text)) # 0/1
		strip_autofill_on_FPL_link = root.find('strip_autofill_on_FPL_link')
		if strip_autofill_on_FPL_link is not None:
			self.strip_autofill_on_FPL_link = bool(int(strip_autofill_on_FPL_link.text)) # 0/1
		strip_autofill_before_handovers = root.find('strip_autofill_before_handovers')
		if strip_autofill_before_handovers is not None:
			self.strip_autofill_before_handovers = bool(int(strip_autofill_before_handovers.text)) # 0/1
		strip_autolink_mode_S = root.find('strip_autolink_mode_S')
		if strip_autolink_mode_S is not None:
			self.strip_autolink_mode_S = bool(int(strip_autolink_mode_S.text)) # 0/1
		strip_autolink_open_FPL = root.find('strip_autolink_open_FPL')
		if strip_autolink_open_FPL is not None:
			self.strip_autolink_open_FPL = bool(int(strip_autolink_open_FPL.text)) # 0/1

		use_known_aircraft = root.find('use_known_aircraft')
		if use_known_aircraft is not None:
			self.use_known_aircraft = bool(int(use_known_aircraft.text)) # 0/1
		known_aircraft = root.find('known_aircraft')
		if known_aircraft is not None:
			for known_acft_elt in known_aircraft.iter('known_acft'):
				cs = known_acft_elt.attrib['callsign']
				atd = known_acft_elt.attrib['type']
				if cs and atd:
					self.known_aircraft[cs] = atd

		radar_sweeping_display = root.find('radar_sweeping_display')
		if radar_sweeping_display is not None:
			self.radar_sweeping_display = bool(int(radar_sweeping_display.text)) # 0/1
		radar_contact_trace_time = root.find('radar_contact_trace_time')
		if radar_contact_trace_time is not None:
			self.radar_contact_trace_time = timedelta(minutes=int(radar_contact_trace_time.text))
		invisible_blips_before_contact_lost = root.find('invisible_blips_before_contact_lost')
		if invisible_blips_before_contact_lost is not None:
			self.invisible_blips_before_contact_lost = int(invisible_blips_before_contact_lost.text)
		radar_tag_FL_at_bottom = root.find('radar_tag_FL_at_bottom')
		if radar_tag_FL_at_bottom is not None:
			self.radar_tag_FL_at_bottom = bool(int(radar_tag_FL_at_bottom.text)) # 0/1
		radar_tag_speed_tens = root.find('radar_tag_speed_tens')
		if radar_tag_speed_tens is not None:
			self.radar_tag_speed_tens = bool(int(radar_tag_speed_tens.text)) # 0/1
		radar_tag_WTC_position = root.find('radar_tag_WTC_position')
		if radar_tag_WTC_position is not None:
			self.radar_tag_WTC_position = int(radar_tag_WTC_position.text)
		radar_tag_interpret_XPDR_FL = root.find('radar_tag_interpret_XPDR_FL')
		if radar_tag_interpret_XPDR_FL is not None:
			self.radar_tag_interpret_XPDR_FL = bool(int(radar_tag_interpret_XPDR_FL.text)) # 0/1
		heading_tolerance = root.find('heading_tolerance')
		if heading_tolerance is not None:
			self.heading_tolerance = int(heading_tolerance.text)
		altitude_tolerance = root.find('altitude_tolerance')
		if altitude_tolerance is not None:
			self.altitude_tolerance = int(altitude_tolerance.text)
		speed_tolerance = root.find('speed_tolerance')
		if speed_tolerance is not None:
			self.speed_tolerance = int(speed_tolerance.text)
		route_conflict_anticipation = root.find('route_conflict_anticipation')
		if route_conflict_anticipation is not None:
			self.route_conflict_anticipation = timedelta(minutes=int(route_conflict_anticipation.text))
		route_conflict_traffic = root.find('route_conflict_traffic')
		if route_conflict_traffic is not None:
			self.route_conflict_traffic = int(route_conflict_traffic.text)
		seq_opt_min_combo_gain = root.find('seq_opt_min_combo_gain')
		if seq_opt_min_combo_gain is not None:
			self.seq_opt_min_combo_gain = timedelta(minutes=int(seq_opt_min_combo_gain.text))
		seq_opt_max_acft_loss = root.find('seq_opt_max_acft_loss')
		if seq_opt_max_acft_loss is not None:
			self.seq_opt_max_acft_loss = timedelta(minutes=int(seq_opt_max_acft_loss.text))

		CPDLC_ACK_timeout = root.find('CPDLC_ACK_timeout')
		if CPDLC_ACK_timeout is not None:
			value = int(CPDLC_ACK_timeout.text)
			self.CPDLC_ACK_timeout = None if value == 0 else timedelta(seconds=value)
		CPDLC_send_COMU9_to_accepted_transfers = root.find('CPDLC_send_COMU9_to_accepted_transfers')
		if CPDLC_send_COMU9_to_accepted_transfers is not None:
			self.CPDLC_send_COMU9_to_accepted_transfers = bool(int(CPDLC_send_COMU9_to_accepted_transfers.text)) # 0/1
		CPDLC_send_strips_on_accepted_transfers = root.find('CPDLC_send_strips_on_accepted_transfers')
		if CPDLC_send_strips_on_accepted_transfers is not None:
			self.CPDLC_send_strips_on_accepted_transfers = bool(int(CPDLC_send_strips_on_accepted_transfers.text)) # 0/1
		CPDLC_raises_windows = root.find('CPDLC_raises_windows')
		if CPDLC_raises_windows is not None:
			self.CPDLC_raises_windows = bool(int(CPDLC_raises_windows.text)) # 0/1
		CPDLC_closes_windows = root.find('CPDLC_closes_windows')
		if CPDLC_closes_windows is not None:
			self.CPDLC_closes_windows = bool(int(CPDLC_closes_windows.text)) # 0/1

		private_ATC_msg_auto_raise = root.find('private_ATC_msg_auto_raise')
		if private_ATC_msg_auto_raise is not None:
			self.private_ATC_msg_auto_raise = bool(int(private_ATC_msg_auto_raise.text)) # 0/1
		ATC_chatroom_msg_notifications = root.find('ATC_chatroom_msg_notifications')
		if ATC_chatroom_msg_notifications is not None:
			self.ATC_chatroom_msg_notifications = bool(int(ATC_chatroom_msg_notifications.text)) # 0/1
		text_radio_history_time = root.find('text_radio_history_time')
		if text_radio_history_time is not None:
			value = int(text_radio_history_time.text)
			self.text_radio_history_time = None if value == 0 else timedelta(minutes=value)
		
		sound_notifications = root.find('sound_notifications')
		if sound_notifications is not None:
			try:
				self.sound_notifications = {int(n) for n in get_text(sound_notifications).split(',')}
			except ValueError:
				print('Could not interpret "sound_notifications" in settings.', file=stderr)
		PTT_mutes_notifications = root.find('PTT_mutes_notifications')
		if PTT_mutes_notifications is not None:
			self.PTT_mutes_notifications = bool(int(PTT_mutes_notifications.text)) # 0/1
		
		solo_max_aircraft_count = root.find('solo_max_aircraft_count')
		if solo_max_aircraft_count is not None:
			self.solo_max_aircraft_count = int(solo_max_aircraft_count.text)
		solo_min_spawn_delay = root.find('solo_min_spawn_delay')
		if solo_min_spawn_delay is not None:
			self.solo_min_spawn_delay = timedelta(seconds=int(solo_min_spawn_delay.text))
		solo_max_spawn_delay = root.find('solo_max_spawn_delay')
		if solo_max_spawn_delay is not None:
			self.solo_max_spawn_delay = timedelta(seconds=int(solo_max_spawn_delay.text))
		solo_distracting_traffic_count = root.find('solo_distracting_traffic_count')
		if solo_distracting_traffic_count is not None:
			self.solo_distracting_traffic_count = int(solo_distracting_traffic_count.text)
		solo_CPDLC_balance = root.find('solo_CPDLC_balance')
		if solo_CPDLC_balance is not None:
			self.solo_CPDLC_balance = float(solo_CPDLC_balance.text)
		solo_ARRvsDEP_balance = root.find('solo_ARRvsDEP_balance')
		if solo_ARRvsDEP_balance is not None:
			self.solo_ARRvsDEP_balance = float(solo_ARRvsDEP_balance.text)
		solo_ILSvsVisual_balance = root.find('solo_ILSvsVisual_balance')
		if solo_ILSvsVisual_balance is not None:
			self.solo_ILSvsVisual_balance = float(solo_ILSvsVisual_balance.text)
		solo_helos_request_ILS = root.find('solo_helos_request_ILS')
		if solo_helos_request_ILS is not None:
			self.solo_helos_request_ILS = bool(int(solo_helos_request_ILS.text)) # 0/1
		solo_MISAP_probability = root.find('solo_MISAP_probability')
		if solo_MISAP_probability is not None:
			self.solo_MISAP_probability = float(solo_MISAP_probability.text)
		solo_weather_change_interval = root.find('solo_weather_change_interval')
		if solo_weather_change_interval is not None:
			value = int(solo_weather_change_interval.text)
			self.solo_weather_change_interval = None if value == 0 else timedelta(minutes=value)
		solo_voice_instructions = root.find('solo_voice_instructions')
		if solo_voice_instructions is not None:
			self.solo_voice_instructions = bool(int(solo_voice_instructions.text)) # 0/1
		solo_wilco_beeps = root.find('solo_wilco_beeps')
		if solo_wilco_beeps is not None:
			self.solo_wilco_beeps = bool(int(solo_wilco_beeps.text)) # 0/1
		solo_voice_readback = root.find('solo_voice_readback')
		if solo_voice_readback is not None:
			self.solo_voice_readback = bool(int(solo_voice_readback.text)) # 0/1

		general_notes = root.find('general_notes')
		if general_notes is not None:
			self.general_notes = get_text(general_notes)
		mute_notifications = root.find('mute_notifications')
		if mute_notifications is not None:
			self.mute_notifications = bool(int(mute_notifications.text)) # 0/1
		primary_radar_active = root.find('primary_radar_active')
		if primary_radar_active is not None:
			self.primary_radar_active = bool(int(primary_radar_active.text)) # 0/1
		traffic_identification_assistant = root.find('traffic_identification_assistant')
		if traffic_identification_assistant is not None:
			self.traffic_identification_assistant = bool(int(traffic_identification_assistant.text)) # 0/1
		route_conflict_warnings = root.find('route_conflict_warnings')
		if route_conflict_warnings is not None:
			self.route_conflict_warnings = bool(int(route_conflict_warnings.text)) # 0/1
		APP_spacing_hints = root.find('APP_spacing_hints')
		if APP_spacing_hints is not None:
			self.APP_spacing_hints = bool(int(APP_spacing_hints.text)) # 0/1
		monitor_runway_occupation = root.find('monitor_runway_occupation')
		if monitor_runway_occupation is not None:
			self.monitor_runway_occupation = bool(int(monitor_runway_occupation.text)) # 0/1
	

	def restoreLocationSettings_AD(self, airportData):
		self.location_code = airportData.navpoint.code
		root = ElementTree.parse(location_settings_filename_fmt % self.location_code).getroot()
		self._restoreLocationSettings_shared(root)
		surface_parameters = root.find('surface_parameters')
		if surface_parameters is not None:
			for rwy_elt in surface_parameters.iter('runway'):
				try:
					runway = airportData.runway(rwy_elt.attrib['name'])
				except KeyError:
					print('Ignored unnamed runway in settings file.', file=stderr)
				else:
					for param_elt in rwy_elt.iter('param'):
						param = param_elt.attrib['name']
						if param == 'fpa':
							runway.param_FPA = float(param_elt.text)
						elif param == 'line':
							runway.param_disp_line_length = int(param_elt.text)
						elif param == 'props':
							runway.param_acceptProps = bool(int(param_elt.text))
						elif param == 'turboprops':
							runway.param_acceptTurboprops = bool(int(param_elt.text))
						elif param == 'jets':
							runway.param_acceptJets = bool(int(param_elt.text))
						elif param == 'heavy':
							runway.param_acceptHeavy = bool(int(param_elt.text))
						else:
							print('Bad parameter spec "%s" for RWY %s' % (param, runway.name), file=stderr)
			for hpad_elt in surface_parameters.iter('helipad'):
				try:
					hpad = next(hpad for hpad in airportData.helipads() if hpad.name == hpad_elt.attrib['name'])
				except StopIteration:
					print('Ignored unnamed helipad in settings file.', file=stderr)
				else:
					for param_elt in hpad_elt.iter('param'):
						param = param_elt.attrib['name']
						if param == 'depcourse':
							hpad.setDepCourse(int(param_elt.text))

		custom_viewpoints = root.find('custom_viewpoints')
		if custom_viewpoints is not None:
			for custom_viewpoint in custom_viewpoints.iter('custom_viewpoint'):
				pos_spec = custom_viewpoint.attrib['position']
				height = float(custom_viewpoint.attrib['height'])
				name = custom_viewpoint.text
				self.custom_viewpoints.append((pos_spec, height, name))
		selected_viewpoint = root.find('selected_viewpoint')
		if selected_viewpoint is not None:
			self.selected_viewpoint = int(selected_viewpoint.text)
	
		solo_TWR_range_dist = root.find('solo_TWR_range_dist')
		if solo_TWR_range_dist is not None:
			self.solo_TWR_range_dist = int(solo_TWR_range_dist.text)
		solo_TWR_ceiling_FL = root.find('solo_TWR_ceiling_FL')
		if solo_TWR_ceiling_FL is not None:
			self.solo_TWR_ceiling_FL = int(solo_TWR_ceiling_FL.text)
		solo_APP_ceiling_FL_min = root.find('solo_APP_ceiling_FL_min')
		if solo_APP_ceiling_FL_min is not None:
			self.solo_APP_ceiling_FL_min = int(solo_APP_ceiling_FL_min.text)
		solo_APP_ceiling_FL_max = root.find('solo_APP_ceiling_FL_max')
		if solo_APP_ceiling_FL_max is not None:
			self.solo_APP_ceiling_FL_max = int(solo_APP_ceiling_FL_max.text)

	def restoreLocationSettings_CTR(self, location_code):
		self.location_code = location_code
		root = ElementTree.parse(location_settings_filename_fmt % location_code).getroot()
		self._restoreLocationSettings_shared(root)
	
		solo_CTR_floor_FL = root.find('solo_CTR_floor_FL')
		if solo_CTR_floor_FL is not None:
			self.solo_CTR_floor_FL = int(solo_CTR_floor_FL.text)
		solo_CTR_ceiling_FL = root.find('solo_CTR_ceiling_FL')
		if solo_CTR_ceiling_FL is not None:
			self.solo_CTR_ceiling_FL = int(solo_CTR_ceiling_FL.text)
		solo_CTR_range_dist = root.find('solo_CTR_range_dist')
		if solo_CTR_range_dist is not None:
			self.solo_CTR_range_dist = int(solo_CTR_range_dist.text)
		solo_CTR_routing_points = root.find('solo_CTR_routing_points')
		if solo_CTR_routing_points is not None:
			self.solo_CTR_routing_points = get_text(solo_CTR_routing_points).split()
		solo_CTR_semi_circular_rule = root.find('solo_CTR_semi_circular_rule')
		if solo_CTR_semi_circular_rule is not None:
			self.solo_CTR_semi_circular_rule = int(solo_CTR_semi_circular_rule.text)
	
	def _restoreLocationSettings_shared(self, root):
		radio_direction_finding = root.find('radio_direction_finding')
		if radio_direction_finding is not None:
			self.radio_direction_finding = bool(int(radio_direction_finding.text)) # 0/1
		controller_pilot_data_link = root.find('controller_pilot_data_link')
		if controller_pilot_data_link is not None:
			self.controller_pilot_data_link = bool(int(controller_pilot_data_link.text)) # 0/1
		SSR_mode_capability = root.find('SSR_mode_capability')
		if SSR_mode_capability is not None:
			self.SSR_mode_capability = get_text(SSR_mode_capability)
		radar_range = root.find('radar_range')
		if radar_range is not None:
			self.radar_range = int(radar_range.text)
		radar_signal_floor_level = root.find('radar_signal_floor_level')
		if radar_signal_floor_level is not None:
			self.radar_signal_floor_level = int(radar_signal_floor_level.text)
		radar_sweep_interval = root.find('radar_sweep_interval')
		if radar_sweep_interval is not None:
			self.radar_sweep_interval = timedelta(seconds=int(radar_sweep_interval.text))
		auto_print_strips_include_DEP = root.find('auto_print_strips_include_DEP')
		if auto_print_strips_include_DEP is not None:
			self.auto_print_strips_include_DEP = bool(int(auto_print_strips_include_DEP.text))
		auto_print_strips_include_ARR = root.find('auto_print_strips_include_ARR')
		if auto_print_strips_include_ARR is not None:
			self.auto_print_strips_include_ARR = bool(int(auto_print_strips_include_ARR.text))
		auto_print_strips_IFR_only = root.find('auto_print_strips_IFR_only')
		if auto_print_strips_IFR_only is not None:
			self.auto_print_strips_IFR_only = bool(int(auto_print_strips_IFR_only.text))
		auto_print_strips_anticipation = root.find('auto_print_strips_anticipation')
		if auto_print_strips_anticipation is not None:
			self.auto_print_strips_anticipation = timedelta(minutes=int(auto_print_strips_anticipation.text))

		XPDR_ranges = root.find('XPDR_ranges')
		if XPDR_ranges is not None:
			for XPDR_range in XPDR_ranges.iter('XPDR_range'):
				try:
					lo = int(XPDR_range.attrib['lo'], base=8)
					hi = int(XPDR_range.attrib['hi'], base=8)
					col = XPDR_range.attrib.get('colour')
					colour = None if col is None else QColor(col)
					self.XPDR_assignment_ranges.append(XpdrAssignmentRange(get_text(XPDR_range), lo, hi, colour))
				except (ValueError, KeyError):
					print('Error in assignment range specification', file=stderr)
		
		horizontal_separation = root.find('horizontal_separation')
		if horizontal_separation is not None:
			self.horizontal_separation = float(horizontal_separation.text)
		vertical_separation = root.find('vertical_separation')
		if vertical_separation is not None:
			self.vertical_separation = int(vertical_separation.text)
		conflict_warning_floor_FL = root.find('conflict_warning_floor_FL')
		if conflict_warning_floor_FL is not None:
			self.conflict_warning_floor_FL = int(conflict_warning_floor_FL.text)
		transition_altitude = root.find('transition_altitude')
		if transition_altitude is not None:
			self.transition_altitude = int(transition_altitude.text)
		uncontrolled_VFR_XPDR_code = root.find('uncontrolled_VFR_XPDR_code')
		if uncontrolled_VFR_XPDR_code is not None:
			self.uncontrolled_VFR_XPDR_code = int(uncontrolled_VFR_XPDR_code.text, base=8)
		primary_METAR_station = root.find('primary_METAR_station')
		if primary_METAR_station is not None:
			self.primary_METAR_station = get_text(primary_METAR_station)
		location_radio_name = root.find('location_radio_name')
		if location_radio_name is not None:
			self.location_radio_name = get_text(location_radio_name)
		magnetic_declination = root.find('magnetic_declination')
		if magnetic_declination is not None:
			self.magnetic_declination = float(magnetic_declination.text)

		ATIS_custom_appendix = root.find('ATIS_custom_appendix')
		if ATIS_custom_appendix is not None:
			self.ATIS_custom_appendix = get_text(ATIS_custom_appendix)

		additional_METAR_stations = root.find('additional_METAR_stations')
		if additional_METAR_stations is not None:
			for additional_METAR_station in additional_METAR_stations.iter('additional_METAR_station'):
				self.additional_METAR_stations.append(get_text(additional_METAR_station))
		local_notes = root.find('local_notes')
		if local_notes is not None:
			self.local_notes = get_text(local_notes)
		strip_racks = root.find('strip_racks')
		if strip_racks is not None:
			for strip_rack in strip_racks.iter('strip_rack'):
				try:
					rack_name = strip_rack.attrib['name']
					if rack_name in self.saved_strip_racks:
						raise KeyError # duplicate name
				except KeyError:
					pass # No name save for this rack; ignore.
				else: # New rack to restore
					self.saved_strip_racks.append(rack_name)
					try: # COLOUR
						self.rack_colours[rack_name] = QColor(strip_rack.attrib['colour'])
					except KeyError:
						pass # No colour saved for this rack
					try: # PRIVATE?
						if bool(int(strip_rack.attrib['private'])):
							self.private_racks.add(rack_name)
					except KeyError:
						pass # Missing "private" attrib for this rack
					# COLLECTING FROM...
					for collects_from in strip_rack.iter('collects_from'):
						if collects_from.text is not None and collects_from.text != '':
							self.ATC_collecting_racks[collects_from.text] = rack_name
		auto_print_collecting_rack = root.find('auto_print_collecting_rack')
		if auto_print_collecting_rack is not None:
			self.auto_print_collecting_rack = auto_print_collecting_rack.text
		
		panels_state = root.find('panels_state')
		if panels_state is not None:
			try:
				central_panel = panels_state.find('central_panel')
				if central_panel is not None:
					settings.saved_selected_docked_panel = int(central_panel.attrib['menu_index'])
				strip_dock = panels_state.find('strip_dock')
				if strip_dock is not None:
					self.saved_strip_dock_state = get_panel_state_dict(strip_dock)
				for user_panel in panels_state.iter('user_panel'):
					w_type = user_panel.attrib['type']
					title = user_panel.attrib['title']
					state = get_panel_state_dict(user_panel)
					self.saved_user_panels_states.append((w_type, title, state))
			except KeyError:
				print('Missing data or attributes in saved panels state.', file=stderr)


settings = Settings()





def xmlelt(tag, text, attrib=None):
	elt = ElementTree.Element(tag)
	if text is not None:
		elt.text = text
	if attrib is not None:
		elt.attrib.update(attrib)
	return elt

def xmllstelt(list_tag, item_list, element_generator):
	elt = ElementTree.Element(list_tag)
	for item in item_list:
		elt.append(element_generator(item))
	return elt

def get_text(xml_element):
	return some(xml_element.text, '')

def get_panel_state_dict(window_elt): # CAUTION this can raise KeyError
	res = {}
	for state in window_elt.iter('state'):
		if 'attr' in state.attrib: # single value state attribute
			res[state.attrib['attr']] = state.attrib['value']
		else:
			list_name = state.attrib['list']
			item_value = state.attrib['item']
			try:
				res[list_name].append(item_value)
			except KeyError:
				res[list_name] = [item_value]
	return res


# ------------------------------------------

def mk_rack_elt(rack_name, collects_from, opt_colour, is_private):
	elt = ElementTree.Element('strip_rack')
	attr = {'name': rack_name}
	if opt_colour is not None:
		attr['colour'] = opt_colour.name()
	attr['private'] = str(int(is_private))
	elt.attrib.update(attr)
	for atc in collects_from:
		elt.append(xmlelt('collects_from', atc))
	return elt

def mk_custom_viewpoint_elt(viewpoint_tuple):
	pos_spec, height, name = viewpoint_tuple
	return xmlelt('custom_viewpoint', name, attrib={'position': pos_spec, 'height': str(height)})

def mk_sfc_param_elt(sfc):
	if sfc.isRunway():
		params_elt = xmlelt('runway', None, attrib={'name': sfc.name})
		if not sfc.hasILS():
			params_elt.append(xmlelt('param', str(sfc.param_FPA), attrib={'name': 'fpa'}))
		params_elt.append(xmlelt('param', str(sfc.param_disp_line_length), attrib={'name': 'line'}))
		params_elt.append(xmlelt('param', str(int(sfc.param_acceptProps)), attrib={'name': 'props'}))
		params_elt.append(xmlelt('param', str(int(sfc.param_acceptTurboprops)), attrib={'name': 'turboprops'}))
		params_elt.append(xmlelt('param', str(int(sfc.param_acceptJets)), attrib={'name': 'jets'}))
		params_elt.append(xmlelt('param', str(int(sfc.param_acceptHeavy)), attrib={'name': 'heavy'}))
	else:
		params_elt = xmlelt('helipad', None, attrib={'name': sfc.name})
		params_elt.append(xmlelt('param', sfc.param_preferred_DEP_course.read(), attrib={'name': 'depcourse'}))
	return params_elt

def mk_xpdr_range_elt(rng):
	dct = {'lo': '%04o' % rng.lo, 'hi': '%04o' % rng.hi}
	if rng.col is not None:
		dct['colour'] = rng.col.name()
	return xmlelt('XPDR_range', rng.name, attrib=dct)

def mk_panels_state_elt(strip_dock_state, user_panels_states, docked_panel_index):
	res = xmlelt('panels_state', None)
	res.append(xmlelt('central_panel', None, {'menu_index': str(docked_panel_index)}))
	elt = xmlelt('strip_dock', None)
	_append_panel_state_elements(elt, strip_dock_state)
	res.append(elt)
	for ptype, ptitle, pstate in user_panels_states:
		elt = xmlelt('user_panel', None, attrib={'type': ptype, 'title': ptitle})
		_append_panel_state_elements(elt, pstate)
		res.append(elt)
	return res

def _append_panel_state_elements(elt, window_state):
	for attr, str_or_lst in window_state.items():
		if isinstance(str_or_lst, list):
			for value in str_or_lst:
				elt.append(xmlelt('state', None, attrib={'list': attr, 'item': value}))
		else:
			elt.append(xmlelt('state', None, attrib={'attr': attr, 'value': str_or_lst}))
