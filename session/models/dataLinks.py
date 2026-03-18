from datetime import timedelta
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
from PyQt5.QtCore import Qt, pyqtSignal, QAbstractTableModel, QSortFilterProxyModel, QModelIndex

from base.utc import rel_session_datetime_str
from base.util import pop_all

from gui.misc import signals
from gui.graphics.miscGraphics import coloured_square_icon

from session.config import settings
from session.manager import SessionType


# ---------- Constants ----------

# -------------------------------


class ConnectionStatus:
	OK, EXPECTING, PROBLEM = range(3)

	qt_colours = {
		OK: Qt.darkGreen,
		PROBLEM: Qt.red,
		EXPECTING: Qt.yellow
	}




# =============================================== #

#            SINGLE DATA LINK DIALOGUE            #

#================================================ #

class CpdlcDialogueModel(QAbstractTableModel):
	statusChanged = pyqtSignal()
	
	def __init__(self, parent, acft_callsign, transfer_from):
		QAbstractTableModel.__init__(self, parent)
		self.acft_callsign = acft_callsign
		self.initiator = transfer_from # Transferring ATC, or None if initiated by ACFT
		self.messages = []
		self.connected_at = settings.session_manager.clockTime() if transfer_from is None else None # if None: value given when XFR accepted
		self.terminated_at = None # value given when no longer live
		self.transfer_to = None # transferring or transferred
		self.marked_problem = None
		self.terminated_by_data_auth = False # True for ATC disconnect or cancelled incoming XFR; False for ACFT disconnect or rejected incoming XFR; N/A if ended with accepted XFR
	
	def markProblem(self, pbstr):
		self.marked_problem = settings.session_manager.clockTime(), pbstr
		signals.cpdlcProblem.emit(self.acftCallsign(), pbstr)
		self.statusChanged.emit()
	
	
	## ACCESS
	
	def msgCount(self): # NOTE: this excludes any added connection/XFR row (thus usually different to rowCount)
		return len(self.messages)
	
	def acftCallsign(self):
		return self.acft_callsign
	
	def isLive(self):
		return self.connected_at is not None and self.terminated_at is None
	
	def isTerminated(self):
		return self.terminated_at is not None
	
	def pendingTransferTo(self):
		return self.transfer_to if self.isLive() else None
	
	def expectingMsg(self): # from either me or them
		return self.isLive() and self.msgCount() > 0 and self.messages[-1].expectsAnswer() # from either side
	
	def pendingTransferFrom(self):
		return self.initiator if not self.isLive() and not self.isTerminated() else None
	
	def markedProblemTime(self):
		return None if self.marked_problem is None else self.marked_problem[0]
	
	def pendingInstrMsg(self, uplink):
		try:
			msg = next(msg for msg in reversed(self.messages) if not msg.isStandby() or msg.isUplink() == uplink)
			if msg.isUplink() == uplink and msg.recognisedInstructions() is not None:
				return msg
			else:
				return None
		except StopIteration:
			return None
	
	def statusColour(self):
		if self.marked_problem is not None:
			return ConnectionStatus.PROBLEM
		elif self.expectingMsg() or self.pendingTransferFrom() is not None or self.pendingTransferTo() is not None:
			return ConnectionStatus.EXPECTING
		else:
			return ConnectionStatus.OK
	
	def statusStr(self):
		if self.marked_problem is not None:
			return '!!  ' + self.marked_problem[1]
		if self.isTerminated():
			if self.connected_at is None:
				return 'Aborted transfer' if self.terminated_by_data_auth else 'Rejected transfer'
			else:
				return 'Disconnected' if self.transfer_to is None else 'Transferred'
		elif self.isLive():
			if self.transfer_to is not None:
				return 'Transferring to %s...' % self.transfer_to
			elif self.expectingMsg(): # implies message list not empty
				last = self.messages[-1]
				return 'Waiting for msg...' if last.isFromMe() != last.isStandby() else 'Please answer/acknowledge...'
			else:
				return 'Connected'
		else: # never connected
			return 'Transfer from %s...' % self.initiator
	
	
	## MODIFICATION
	
	def setTransferTo(self, atc): # NOTE: None to cancel proposal
		if self.isLive():
			self.transfer_to = atc
			self.statusChanged.emit()
		else:
			print('WARNING: Ignored setTransferTo call for %s.' % self.acftCallsign(), file=stderr)
	
	def acceptIncomingTransfer(self):
		if self.pendingTransferFrom() is None:
			print('WARNING: Ignored acceptIncomingTransfer call for %s.' % self.acftCallsign(), file=stderr)
		else:
			self.connected_at = settings.session_manager.clockTime()
			self.beginInsertRows(QModelIndex(), 0, 0)
			self.endInsertRows()
			self.statusChanged.emit()
			settings.session_recorder.proposeCpdlcSys(self.connected_at, self.acftCallsign(), connectFlag=True, xfr=self.pendingTransferFrom())
	
	def appendMessage(self, msg):
		if self.isLive():
			was_expecting = self.expectingMsg() # test before message is appended
			n = self.rowCount()
			self.beginInsertRows(QModelIndex(), n, n)
			self.messages.append(msg)
			self.endInsertRows()
			if not msg.isFromMe(): # receiving; needs a signal
				if msg.containsUnable():
					self.markProblem('UNABLE received')
				elif msg.isAcknowledgement() and not was_expecting:
					self.markProblem('Unexpected acknowledgement')
				else:
					signals.cpdlcMessageReceived.emit(self.acftCallsign(), msg)
			self.statusChanged.emit()
			settings.session_recorder.proposeCpdlcMsg(self.acftCallsign(), msg)
		else:
			print('WARNING: Ignored appendMessage call for %s.' % self.acftCallsign(), file=stderr)
	
	def terminate(self, by_data_auth):
		"""
		by_data_auth values:
		- for an incoming transfer: True = XFR cancelled by initiator; False = rejected XFR
		- for a live link: True = accepted XFR if outgoing XFR pending else ATC disconnect; False = ACFT disconnect
		"""
		if self.isTerminated():
			print('ERROR: CPDLC dialogue already terminated.', file=stderr)
		else:
			pending_to = self.pendingTransferTo()
			pending_from = self.pendingTransferFrom()
			n = self.rowCount()
			self.beginInsertRows(QModelIndex(), n, n)
			if not by_data_auth and pending_to is not None: # implies live; ACFT disconnecting while XFR pending
				self.markProblem('Terminated while transferring to ' + self.transfer_to)
				self.transfer_to = None
			elif self.expectingMsg(): # implies live
				self.markProblem('Ended before expected answer')
			elif self.isLive() and not by_data_auth: # ACFT disconnecting
				self.markProblem('ACFT disconnected')
			self.terminated_at = settings.session_manager.clockTime()
			self.terminated_by_data_auth = by_data_auth
			self.endInsertRows()
			self.statusChanged.emit()
			if pending_from is None:
				if by_data_auth:
					if pending_to is None: # ATC disconnect
						settings.session_recorder.proposeCpdlcSys(self.terminated_at, self.acftCallsign(), connectFlag=False)
					else: # accepted XFR
						settings.session_recorder.proposeCpdlcSys(self.terminated_at, self.acftCallsign(), connectFlag=True, xfr=pending_to)
				else: # ACFT disconnect
					settings.session_recorder.proposeCpdlcSys(self.terminated_at, self.acftCallsign())
			else: # pending incoming XFR
				if by_data_auth: # XFR cancelled
					settings.session_recorder.proposeCpdlcSys(self.terminated_at, self.acftCallsign(), xfr=pending_from)
				else: # XFR rejected
					settings.session_recorder.proposeCpdlcSys(self.terminated_at, self.acftCallsign(), connectFlag=False, xfr=pending_from)
	
	def resolveProblems(self):
		self.marked_problem = None
		self.statusChanged.emit()
	
	def checkForTimeOut(self):
		if self.expectingMsg(): # implies nessage list not empty
			last = self.messages[-1]
			if last.isFromMe() != last.isStandby() and settings.session_manager.clockTime() - last.timeStamp() >= settings.CPDLC_ACK_timeout:
				self.markProblem('Message timed out')
	
	
	## MODEL STUFF
	
	def rowCount(self, parent=QModelIndex()):
		return self.msgCount() + int(self.connected_at is not None) + int(self.isTerminated())

	def columnCount(self, parent=QModelIndex()):
		return 3  # normal message row: time stamp, message type, contents

	def data(self, index, role):
		row = index.row()
		col = index.column()
		if role == Qt.DisplayRole:
			## First row
			if row == 0:
				if settings.session_manager.session_type == SessionType.PLAYBACK and \
						self.connected_at is not None and self.connected_at <= settings.session_manager.timeline.startTime():
					if col == 2:
						return 'connected prior to recorded time'
				elif col == 0:
					if self.connected_at is None: # was never live (unique row of a rejected/aborted transfer)
						return rel_session_datetime_str(self.terminated_at, seconds=True)
					else: # regular case of a once or still live dialog, displaying connection time
						return rel_session_datetime_str(self.connected_at, seconds=True)
				elif col == 1:
					return 'LOGON' if self.initiator is None else 'XFR'
				elif col == 2:
					if self.initiator is not None:
						if self.connected_at is None: # unique row of a terminated transfer, rejected by us or cancelled by them
							s = 'aborted' if self.terminated_by_data_auth else 'rejected'
						else:
							s = 'accepted'
						return 'from %s (%s)' % (self.initiator, s)
			
			## Last (but non-unique) row of a terminated connection that was once live
			elif self.isTerminated() and row == self.rowCount() - 1:
				if col == 0:
					return rel_session_datetime_str(self.terminated_at, seconds=True)
				elif col == 1:
					return 'DISCONNECT' if self.transfer_to is None else 'XFR'
				elif col == 2:
					if self.transfer_to is None:
						return 'by ATC' if self.terminated_by_data_auth else 'by ACFT'
					else:
						return 'accepted by %s' % self.transfer_to
			
			## Regular message row
			else:
				msg = self.messages[row - 1]
				if col == 0:
					return rel_session_datetime_str(msg.timeStamp(), seconds=True)
				elif col == 1:
					return '↓↑'[msg.isUplink()]
				elif col == 2:
					return msg.displayText(sepStr=', ')
		
		elif role == Qt.ToolTipRole:
			if 1 <= row <= self.msgCount():
				if col == 2:
					return 'Element types: ' + ', '.join(elt.split(' ', maxsplit=1)[0] for elt in self.messages[row - 1].elements())





# ================================================ #

#                  FULL  HISTORY                   #

# ================================================ #

class CpdlcHistoryModel(QAbstractTableModel):
	clearingFromHistory = pyqtSignal(CpdlcDialogueModel)
	
	def __init__(self, parent):
		QAbstractTableModel.__init__(self, parent)
		self.proposed_connections = [] # (str ACFT callsign, str/None ATC callsign) list
		self.connection_history = []  # CpdlcDialogueModel list
		self.gui = parent
	
	def _dataLinkStatusChanged(self, row):
		self.dataChanged.emit(self.index(row, 0), self.index(row, 0), [Qt.DecorationRole])
		self.dataChanged.emit(self.index(row, 1), self.index(row, 1))
		signals.cpdlcStatusChanged.emit(self.dataLinkOnRow(row).acftCallsign())
	
	def checkForTimeOuts(self):
		if settings.CPDLC_ACK_timeout is not None:
			for dm in self.connection_history:
				dm.checkForTimeOut()
	
	
	## ACCESS
	
	def dataLinkOnRow(self, row):
		try:
			return self.connection_history[row]
		except IndexError:
			return None
	
	def dataLinks(self, pred=None):
		return [dl for dl in self.connection_history if pred is None or pred(dl)]
	
	def lastDataLink(self, callsign): # raises StopIteration if none in history
		return next((dl for dl in reversed(self.connection_history) if dl.acftCallsign() == callsign), None)
	
	def liveDataLink(self, callsign):
		return next((dl for dl in reversed(self.connection_history) if dl.acftCallsign() == callsign and dl.isLive()), None)
	
	
	## MODIFICATION
	
	def beginDataLink(self, acft_callsign, transferFrom=None, autoAccept=False):
		latest = self.lastDataLink(acft_callsign)
		if latest is None or latest.isTerminated():
			conn_row = len(self.connection_history)
			self.beginInsertRows(QModelIndex(), conn_row, conn_row)
			dm = CpdlcDialogueModel(self.gui, acft_callsign, transferFrom)
			dm.statusChanged.connect(lambda row=conn_row: self._dataLinkStatusChanged(row))
			self.connection_history.append(dm)
			self.endInsertRows()
			if autoAccept:
				assert transferFrom is not None
				dm.acceptIncomingTransfer() # signals statusChanged
			else:
				dm.statusChanged.emit()
			signals.cpdlcInitLink.emit(acft_callsign)
			if transferFrom is None:
				settings.session_recorder.proposeCpdlcSys(dm.connected_at, acft_callsign, connectFlag=True)
			else:
				settings.session_recorder.proposeCpdlcSys(settings.session_manager.clockTime(), acft_callsign, xfr=transferFrom)
		else:
			print('ERROR: Ignored CPDLC init call; callsign %s already connected or pending.' % acft_callsign, file=stderr)
	
	def clearHistory(self, pred=(lambda x: True)):
		self.beginResetModel()
		for dialogue in pop_all(self.connection_history, pred):
			self.clearingFromHistory.emit(dialogue)
		self.endResetModel()
	
	
	## MODEL STUFF
	
	def rowCount(self, parent):
		return len(self.connection_history)

	def columnCount(self, parent):
		return 2

	def data(self, index, role):
		data_link = self.connection_history[index.row()]
		col = index.column()
		if role == Qt.DisplayRole:
			if col == 0: # callsign
				return data_link.acftCallsign()
			elif col == 1: # status
				return data_link.statusStr()
		elif role == Qt.DecorationRole:
			if col == 0:
				status = data_link.statusColour()
				if data_link.isLive() or status != ConnectionStatus.OK:
					return coloured_square_icon(ConnectionStatus.qt_colours[status])



class CpdlcHistoryFilterModel(QSortFilterProxyModel):
	def __init__(self, parent, src_model):
		QSortFilterProxyModel.__init__(self, parent)
		self.current_filter = lambda x: True
		self.setSourceModel(src_model)
	
	def filterAcceptsColumn(self, sourceCol, sourceParent):
		return True
	
	def filterAcceptsRow(self, sourceRow, sourceParent):
		return self.current_filter(self.sourceModel().dataLinkOnRow(sourceRow))

	def setFilter(self, pred):
		self.current_filter = pred
		self.invalidateFilter()
