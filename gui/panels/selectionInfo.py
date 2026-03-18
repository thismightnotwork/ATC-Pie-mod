
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

from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QIcon
from ui.selectionInfoPanel import Ui_selectionInfoPanel
from ui.selectionInfoToolbarWidget import Ui_selectionInfoToolbarWidget

from base.strip import parsed_route_detail
from base.coords import dist_str
from base.params import TTF_str

from session.env import env
from session.config import settings

from gui.misc import signals, selection, IconFile
from gui.dialogs.routeInfo import RouteDialog


# ---------- Constants ----------

# -------------------------------




class AbstractSelectionInfoWidget:
	"""
	CAUTION, derived classes MUST:
	- inherit from QWidget
	- contain three two-state toggle widgets named "flag_toggle", "ignore_toggle" and "cheat_toggle"
	- define method "updateDisplay"
	"""
	
	def __init__(self):
		self.radar_contact = None
		self.cheat_toggle.setVisible(False)
		self.updateSelection()
		self.flag_toggle.clicked.connect(self.setContactFlag)
		self.ignore_toggle.clicked.connect(self.setContactIgnore)
		self.cheat_toggle.clicked.connect(self.setContactCheatMode)
		env.radar.acftBlip.connect(self.checkAcftBlip)
		signals.selectionChanged.connect(self.updateSelection)
		signals.stripInfoChanged.connect(self.updateDisplay)
		signals.locationSettingsChanged.connect(self.updateDisplay) # in case SSR capability changed
	
	def showCheatToggle(self, b):
		self.cheat_toggle.setVisible(b)

	def checkAcftBlip(self, acft):
		if acft is self.radar_contact:
			self.updateDisplay()

	def updateSelection(self):
		self.radar_contact = selection.acft
		if self.radar_contact is None:
			for toggle in self.flag_toggle, self.ignore_toggle, self.cheat_toggle:
				toggle.setEnabled(False)
				toggle.setChecked(False)
		else:
			self.flag_toggle.setEnabled(True)
			self.ignore_toggle.setEnabled(True)
			self.cheat_toggle.setEnabled(True)
			self.flag_toggle.setChecked(self.radar_contact.flagged)
			self.ignore_toggle.setChecked(self.radar_contact.ignored)
			self.cheat_toggle.setChecked(self.radar_contact.individual_cheat)
		self.updateDisplay()
	
	def setContactCheatMode(self, b):
		if self.radar_contact is not None:
			self.radar_contact.setIndividualCheat(b)
			self.radar_contact.saveRadarSnapshot() #NOTE does nothing in playback sessions (not to tamper with history)
			signals.selectionChanged.emit()
	
	def setContactFlag(self, b):
		if self.radar_contact is not None:
			self.radar_contact.flagged = b
			signals.selectionChanged.emit()
	
	def setContactIgnore(self, b):
		if self.radar_contact is not None:
			self.radar_contact.ignored = b
			signals.selectionChanged.emit()








class SelectionInfoToolbarWidget(QWidget, Ui_selectionInfoToolbarWidget, AbstractSelectionInfoWidget):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		AbstractSelectionInfoWidget.__init__(self)
	
	def updateDisplay(self):
		if self.radar_contact is None:
			self.setEnabled(False)
			hdg = alt = ias = mach = None
		else:
			self.setEnabled(True)
			hdg = self.radar_contact.heading()
			alt = self.radar_contact.xpdrAlt()
			ias = self.radar_contact.xpdrIAS()
			mach = self.radar_contact.xpdrMachNumber()
		txt = ['Track ' + ('---' if hdg is None else hdg.read())]
		if settings.SSR_mode_capability not in '0A' or alt is not None:
			txt.append('FL ' + ('---' if alt is None else '%03d' % alt.FL()))
		if settings.SSR_mode_capability == 'S' or ias is not None or mach is not None:
			txt.append('IAS ' + ('---' if ias is None else '%d' % ias.kt()))
			txt.append('M' + ('---' if mach is None else ('%.2f' % mach).lstrip('0')))
		self.selection_info.setText(' / '.join(txt))






class SelectionInfoPanel(QWidget, Ui_selectionInfoPanel, AbstractSelectionInfoWidget):
	def __init__(self, parent=None):
		QWidget.__init__(self, parent)
		self.setupUi(self)
		AbstractSelectionInfoWidget.__init__(self)
		self.viewRoute_button.setIcon(QIcon(IconFile.button_view))
		self.airport_box.setEnabled(env.airport_data is not None)
		self.viewRoute_button.clicked.connect(self.viewRoute)
	
	def viewRoute(self):
		if self._last_known_route is not None:
			spd = acft = None
			if self.radar_contact is not None:
				spd = self.radar_contact.groundSpeed()
				acft = self.radar_contact.xpdrAcftType()
			RouteDialog(self._last_known_route, speedHint=spd, acftHint=acft, parent=self).exec()
	
	def updateDisplay(self):
		if self.radar_contact is None:
			self.info_area.setEnabled(False)
			return
		else:
			self.info_area.setEnabled(True)
		
		# AIRCRAFT BOX
		# Heading
		hdg = self.radar_contact.heading()
		self.aircraftHeading_info.setText('?' if hdg is None else hdg.read() + '°')
		# Alt./FL
		alt = self.radar_contact.xpdrAlt()
		if alt is None:
			self.aircraftAltitude_info.setText('N/A' if settings.SSR_mode_capability in '0A' else '?')
		else:
			alt_spec = env.specifyAltFl(alt, step=None)
			alt_str = alt_spec.toStr()
			if not alt_spec.isFL() and env.QNH(noneSafe=False) is None:
				alt_str += '  !!QNH'
			self.aircraftAltitude_info.setText(alt_str)
		# Vertical speed
		vs = self.radar_contact.verticalSpeed()
		if vs is None:
			self.aircraftVerticalSpeed_info.setText('N/A' if settings.SSR_mode_capability in '0A' else '?')
		else:
			self.aircraftVerticalSpeed_info.setText('%+d ft/min' % vs)
		# Ground speed
		groundSpeed = self.radar_contact.groundSpeed()
		if groundSpeed is None:
			self.aircraftGroundSpeed_info.setText('?')
		else:
			self.aircraftGroundSpeed_info.setText(str(groundSpeed))
		# Indicated airspeed speed
		ias = self.radar_contact.IAS()
		if ias is None:
			self.aircraftIndicatedAirSpeed_info.setText('?' if settings.SSR_mode_capability == 'S' else 'N/A')
		else:
			s = str(ias)
			if self.radar_contact.xpdrIAS() is None:
				s += ' (estimated)'
			self.aircraftIndicatedAirSpeed_info.setText(s)
		# Mach number
		mach = self.radar_contact.xpdrMachNumber()
		if mach is None:
			self.aircraftMachNumber_info.setText('?' if settings.SSR_mode_capability == 'S' else 'N/A')
		else:
			self.aircraftMachNumber_info.setText(('%.2f' % mach).lstrip('0'))
		
		# ROUTE BOX
		coords = self.radar_contact.coords()
		strip = env.linkedStrip(self.radar_contact)
		route = None if strip is None else strip.lookup(parsed_route_detail)
		self._last_known_route = route
		if route is None:
			self.route_box.setEnabled(False)
		else:
			self.route_box.setEnabled(True)
			i_leg = route.currentLegIndex(coords)
			wpdist = coords.distanceTo(route.waypoint(i_leg).coordinates)
			self.legCount_info.setText('%d of %d' % (i_leg + 1, route.legCount()))
			self.legSpec_info.setText(route.legStr(i_leg))
			self.waypointAt_info.setText(dist_str(wpdist))
			try: # TTF
				if groundSpeed is None:
					raise ValueError('No ground speed info')
				self.waypointTTF_info.setText(TTF_str(wpdist, groundSpeed))
			except ValueError:
				self.waypointTTF_info.setText('?')
		
		# AIRPORT BOX
		if env.airport_data is not None:
			airport_dist = coords.distanceTo(env.radarPos())
			self.airportBearing_info.setText(coords.headingTo(env.radarPos()).read())
			self.airportDistance_info.setText(dist_str(airport_dist))
			try: # TTF
				if groundSpeed is None:
					raise ValueError('No ground speed info')
				self.airportTTF_info.setText(TTF_str(airport_dist, groundSpeed))
			except ValueError:
				self.airportTTF_info.setText('?')
