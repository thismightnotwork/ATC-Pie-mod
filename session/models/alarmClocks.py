
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
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex

from gui.misc import signals

from session.config import settings


# ---------- Constants ----------

# -------------------------------


class AlarmClocksModel(QAbstractTableModel):
    columns = ['Remaining', 'Timeout message']

    def __init__(self, parent):
        QAbstractTableModel.__init__(self, parent)
        self.timeout_times = []    # datetime list; should be of same length as self.timeout_messages
        self.timeout_messages = [] # str list; empty string means no message
        signals.fastClockTick.connect(self._updatesAndTimeouts)
        signals.sessionStarted.connect(self.clearAllTimers)
        signals.sessionEnded.connect(self.clearAllTimers)

    def _updatesAndTimeouts(self):
        i = 0
        while i < len(self.timeout_times):
            if self.timeout_times[i] <= settings.session_manager.clockTime():
                signals.alarmClockTimedOut.emit(self.timeout_messages[i])
                self.removeTimer(i)
            else:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)
                i += 1

    def rowCount(self, parent=None):
        return len(self.timeout_times)

    def columnCount(self, parent):
        return len(AlarmClocksModel.columns)

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 1:
            flags |= Qt.ItemIsEditable
        return flags

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return AlarmClocksModel.columns[section]

    def data(self, index, role):
        row = index.row()
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                secs = max(0, int((self.timeout_times[row] - settings.session_manager.clockTime()).total_seconds()))
                return '%d:%02d' % (secs // 60, secs % 60)
            elif col == 1:
                return self.timeout_messages[row]

    def setData(self, index, value, role=Qt.EditRole):
        if index.column() == 1:
            self.timeout_messages[index.row()] = value
            self.dataChanged.emit(index, index)
            return True
        return False

    # Non-overriding methods
    def timeUntilFirstTimeout(self):
        if self.timeout_times:
            return max(timedelta(), min(self.timeout_times) - settings.session_manager.clockTime())
        else:
            return None

    def startNewTimer(self, time_delta, timeoutMsg=''):
        position = self.rowCount()
        self.beginInsertRows(QModelIndex(), position, position)
        self.timeout_times.append(settings.session_manager.clockTime() + time_delta)
        self.timeout_messages.append(timeoutMsg)
        self.endInsertRows()

    def removeTimer(self, row):
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.timeout_times[row]
        del self.timeout_messages[row]
        self.endRemoveRows()

    def clearAllTimers(self):
        self.beginResetModel()
        self.timeout_times.clear()
        self.timeout_messages.clear()
        self.endResetModel()
