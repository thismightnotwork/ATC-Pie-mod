
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

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QDialog, QInputDialog, QFileDialog, QMessageBox, QVBoxLayout, QLabel, QPlainTextEdit, QDialogButtonBox

from ui.aboutDialog import Ui_aboutDialog
from ui.cpdlcXfrOptionsDialog import Ui_cpdlcXfrOptionsDialog
from ui.discardedStripsDialog import Ui_discardedStripsDialog
from ui.recordTimelineDialog import Ui_recordTimelineDialog
from ui.routeSpecsLostDialog import Ui_routeSpecsLostDialog

from base.cpdlc import CPDLC_element_display_text

from gui.misc import signals, IconFile, RadioKeyEventFilter

from session.config import version_string, output_files_dir, settings
from session.env import env


# ---------- Constants ----------

version_string_placeholder = '##version##'
default_timeline_data_file_name = 'recorded-timeline'

# -------------------------------

def select_ATC_callsign(parent_widget, title, prompt='Select ATC:'):
	res = None
	items = env.ATCs.knownAtcCallsigns()
	if len(items) == 0:
		QMessageBox.critical(parent_widget, 'ATC selection error', 'No available ATC callsigns.')
	else:
		item, ok = QInputDialog.getItem(parent_widget, title, prompt, env.ATCs.knownAtcCallsigns(), editable=False)
		if ok:
			res = item
	return res


class TextInputDialog(QDialog):
	def __init__(self, parent, title, label, suggestion=''):
		QDialog.__init__(self, parent)
		self.setWindowTitle(title)
		self._result = None
		self.prompt_label = QLabel(label, self)
		self.txt_edit = QPlainTextEdit(suggestion, self)
		self.txt_edit.setTabChangesFocus(True)
		self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
		self.layout = QVBoxLayout(self)
		self.layout.addWidget(self.prompt_label)
		self.layout.addWidget(self.txt_edit)
		self.layout.addWidget(self.button_box)
		self.button_box.accepted.connect(self.doAccept)
		self.button_box.rejected.connect(self.doReject)

	def doAccept(self):
		self._result = self.txt_edit.toPlainText()
		self.accept()

	def doReject(self):
		self._result = None
		self.reject()

	def textResult(self):
		return self._result



class AboutDialog(QDialog, Ui_aboutDialog):
	def __init__(self, parent=None):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.text_browser.setHtml(re.sub(version_string_placeholder, version_string, self.text_browser.toHtml()))



class RadarMeasurementLog(QPlainTextEdit):
	def __init__(self, parent=None, visibilityAction=None):
		QPlainTextEdit.__init__(self, parent)
		self.setWindowTitle('Radar measurements log')
		self.setWindowFlags(Qt.Window)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.hide()
		self.visibility_action = visibilityAction
		signals.measuringLogEntry.connect(self.appendEntry)
		signals.closeNonDockableWindows.connect(self.close)

	def appendEntry(self, log_entry):
		txt = self.toPlainText()
		self.setPlainText(txt + '\n' + log_entry if txt else log_entry)
		self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

	def showEvent(self, event):
		QPlainTextEdit.showEvent(self, event)
		self.visibility_action.setChecked(True)

	def hideEvent(self, event):
		QPlainTextEdit.hideEvent(self, event)
		self.visibility_action.setChecked(False)



class CpdlcXfrOptionsDialog(QDialog, Ui_cpdlcXfrOptionsDialog):
	def __init__(self, parent, handover_msg_elt):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.contactInstruction_info.setText(CPDLC_element_display_text(handover_msg_elt))

	def transferOptionSelected(self):
		return self.cpdlcTransfer_option.isChecked()

	def instructionOptionSelected(self):
		return self.contactInstruction_option.isChecked()



class RouteSpecsLostDialog(QDialog, Ui_routeSpecsLostDialog):
	def __init__(self, parent, title, lost_specs_text):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.installEventFilter(RadioKeyEventFilter(self))
		self.setWindowTitle(title)
		self.lostSpecs_box.setText(lost_specs_text)
	
	def mustOpenStripDetails(self):
		return self.openStripDetailSheet_tickBox.isChecked()



class DiscardedStripsDialog(QDialog, Ui_discardedStripsDialog):
	def __init__(self, parent, view_model, dialog_title):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.clear_button.setIcon(QIcon(IconFile.button_clear))
		self.installEventFilter(RadioKeyEventFilter(self))
		self.setWindowTitle(dialog_title)
		self.model = view_model
		self.strip_view.setModel(view_model)
		self.clear_button.clicked.connect(self.model.forgetStrips)
		self.recall_button.clicked.connect(self.recallSelectedStrips)
		self.close_button.clicked.connect(self.accept)
	
	def recallSelectedStrips(self):
		for index in self.strip_view.selectedIndexes():
			signals.stripRecall.emit(self.model.stripAt(index))



class RecordPlaybackDialog(QDialog, Ui_recordTimelineDialog):
	def __init__(self, parent):
		QDialog.__init__(self, parent)
		self.setupUi(self)
		self.dataFile_edit.textChanged.connect(lambda txt: self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(txt != ''))
		self.browse_button.clicked.connect(self.browseForDataFile)
		self.buttonBox.accepted.connect(self.doOK) # UI connects buttonBox accept/reject

	def showEvent(self, event):
		a, c, w, o = settings.session_recorder.recordedEventsFlags()
		self.recordTraffic_tickBox.setChecked(a)
		self.recordComms_tickBox.setChecked(c)
		self.recordWeather_tickBox.setChecked(w)
		self.recordOther_tickBox.setChecked(o)
		self.dataFile_edit.setText(path.join(output_files_dir, default_timeline_data_file_name))

	def browseForDataFile(self):
		txt, filt = QFileDialog.getSaveFileName(self, caption='Select output timeline file name')
		if txt != '':
			self.dataFile_edit.setText(txt)

	def dataFileName(self):
		return self.dataFile_edit.text()

	def doOK(self):
		if not path.isfile(self.dataFile_edit.text()) or QMessageBox.question(self, 'File exists', 'File exists. Overwrite?') == QMessageBox.Yes:
			settings.session_recorder.setRecordedEvents(
				self.recordTraffic_tickBox.isChecked(), self.recordComms_tickBox.isChecked(),
				self.recordWeather_tickBox.isChecked(), self.recordOther_tickBox.isChecked()
			)
			self.accept()
