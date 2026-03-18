
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

from math import atan, degrees

from PyQt5.QtCore import Qt, QAbstractTableModel
from PyQt5.QtWidgets import QDialog

from ui.locInfoDialog import Ui_locInfoDialog

from base.util import some, m2NM
from ext.xplane import surface_type_str
from gui.misc import RadioKeyEventFilter
from session.env import env


# ---------- Constants ----------

# -------------------------------


class RwyInfoTableModel(QAbstractTableModel):
    """
    CAUTION: Do not build if no airport data
    """

    def __init__(self, parent):
        QAbstractTableModel.__init__(self, parent)
        self.column_headers = ['RWY', 'LOC freq.', 'GS', 'Surface', 'Orientation', 'Length', 'Width', 'DTHR', 'THR elev.']
        self.runways = env.airport_data.directionalRunways()

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self.column_headers[section]

    def rowCount(self, parent=None):
        return len(self.runways)

    def columnCount(self, parent=None):
        return len(self.column_headers)

    def data(self, index, role):
        if role == Qt.DisplayRole:
            rwy = self.runways[index.row()]
            col = index.column()
            width, surface = env.airport_data.physicalRunwayData(rwy.physicalRwyIndex())
            if col == 0:  # RWY
                return rwy.name
            elif col == 1:  # LOC freq.
                txt = some(rwy.LOC_freq, 'none')
                if rwy.ILS_cat is not None:
                    txt += ' (%s)' % rwy.ILS_cat
                return txt
            elif col == 2:  # GS
                if rwy.hasILS():
                    return '%.1f%% / %.1f°' % (rwy.param_FPA, degrees(atan(rwy.param_FPA / 100)))
                else:
                    return 'none'
            elif col == 3:  # Surface
                return surface_type_str(surface)
            elif col == 4:  # Orientation
                return '%s°' % rwy.orientation().read()
            elif col == 5:  # Length
                return '%d m' % (rwy.length(dthr=False) / m2NM)
            elif col == 6:  # Width
                return '%d m' % width
            elif col == 7:  # DTHR
                return 'none' if rwy.dthr == 0 else '%d m' % rwy.dthr
            elif col == 8:  # THR elev.
                return 'N/A' if env.elevation_map is None else '%.1f ft' % env.elevation(rwy.threshold())


class HelipadInfoTableModel(QAbstractTableModel):
    """
    CAUTION: Do not build if no airport data
    """

    def __init__(self, parent):
        QAbstractTableModel.__init__(self, parent)
        self.column_headers = ['Helipad', 'Surface', 'Width', 'Elev.']
        self.helipads = env.airport_data.helipads()

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self.column_headers[section]

    def rowCount(self, parent=None):
        return len(self.helipads)

    def columnCount(self, parent=None):
        return len(self.column_headers)

    def data(self, index, role):
        if role == Qt.DisplayRole:
            pad = self.helipads[index.row()]
            col = index.column()
            if col == 0:  # Helipad
                return pad.name
            elif col == 1:  # Surface
                return surface_type_str(pad.surface)
            elif col == 2:  # Width
                return '%d m' % min(pad.width, pad.length)
            elif col == 3:  # Elev.
                return 'N/A' if env.elevation_map is None else '%.1f ft' % env.elevation(pad.centre)



class LocationInfoDialog(QDialog, Ui_locInfoDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.installEventFilter(RadioKeyEventFilter(self))
        if env.airport_data is None: # CTR mode
            self.location_stack.setCurrentWidget(self.ctrLocation_page)
            self.ctrPosition_info.setText(str(env.radarPos()))
        else: # AD mode
            self.location_stack.setCurrentWidget(self.adLocation_page)
            self.adPosition_info.setText(str(env.radarPos()))
            self.adElevation_info.setText('%.1f ft' % env.airport_data.field_elevation)
            rwy_table_model = RwyInfoTableModel(self)
            if rwy_table_model.rowCount() == 0:
                self.runways_groupBox.setVisible(False)
            else:
                self.runways_view.setModel(rwy_table_model)
                for i in range(rwy_table_model.columnCount()):
                    self.runways_view.resizeColumnToContents(i)
            helipad_table_model = HelipadInfoTableModel(self)
            if helipad_table_model.rowCount() == 0:
                self.helipads_groupBox.setVisible(False)
            else:
                self.helipads_view.setModel(helipad_table_model)
                for i in range(helipad_table_model.columnCount()):
                    self.helipads_view.resizeColumnToContents(i)
