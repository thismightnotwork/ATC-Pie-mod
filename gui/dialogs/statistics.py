
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

from PyQt5.QtWidgets import QDialog

from ui.statsDialog import Ui_statisticsDialog

from base.fpl import FPL
from base.strip import rack_detail, runway_box_detail, shelved_detail, sent_to_detail
from gui.misc import RadioKeyEventFilter
from session.env import env


# ---------- Constants ----------

# -------------------------------

class StatisticsDialog(QDialog, Ui_statisticsDialog): # TODO: more perf. indicators, timed stats, make non-modal or show times...
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.installEventFilter(RadioKeyEventFilter(self))

    def showEvent(self, event):
        racked = env.strips.count(lambda s: s.lookup(rack_detail) is not None)
        boxed = env.strips.count(lambda s: s.lookup(runway_box_detail) is not None)
        total = env.strips.count()
        sent = env.discarded_strips.count(lambda s: s.lookup(sent_to_detail) is not None)
        shelved = env.discarded_strips.count(lambda s: s.lookup(shelved_detail))
        self.rackedStrips_info.setText(str(racked))
        self.looseStrips_info.setText(str(total - racked - boxed))
        self.boxedStrips_info.setText(str(boxed))
        self.activeStrips_info.setText(str(total))
        self.sentStrips_info.setText(str(sent))
        self.shelvedStrips_info.setText(str(shelved))
        self.releasedStrips_info.setText(str(sent + shelved))
        self.xpdrLinkedStrips_info.setText(str(env.strips.count(lambda s: s.linkedAircraft() is not None)))
        self.fplLinkedStrips_info.setText(str(env.strips.count(lambda s: s.linkedFPL() is not None)))
        self.vfrStrips_info.setText(str(env.strips.count(lambda s: s.lookup(FPL.FLIGHT_RULES) == 'VFR')))
        self.ifrStrips_info.setText(str(env.strips.count(lambda s: s.lookup(FPL.FLIGHT_RULES) == 'IFR')))
