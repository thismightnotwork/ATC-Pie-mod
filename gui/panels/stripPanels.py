
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

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMessageBox, QMenu, QAction, QActionGroup, QGraphicsView
from ui.stripRackPanel import Ui_stripRackPanel
from ui.looseStripPanel import Ui_looseStripPanel

from base.strip import recycled_detail

from gui.misc import signals, IconFile
from gui.dialogs.racks import RackVisibilityDialog
from gui.graphics.flightStrips import LooseStripBayScene, FlightStripItem
from gui.widgets.stripView import RackedStripsFilterModel, RunwayBoxesView
from gui.workspace import WorkspaceDockablePanel

from session.env import env
from session.config import settings
from session.models.liveStrips import default_rack_name


# ---------- Constants ----------

# -------------------------------


class StripRackPanel(WorkspaceDockablePanel, Ui_stripRackPanel): # is a QWidget
	view_modes = DIVIDE, SCROLL, TABBED = range(3) # NB: order matters for menu action descriptions
	
	def __init__(self):
		WorkspaceDockablePanel.__init__(self, defaultTitle='Strip racks')
		self.setupUi(self)
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.setWindowIcon(QIcon(IconFile.panel_racks))
		self.rack_filter_model = RackedStripsFilterModel(self)
		self.stripRacks_view.setModel(self.rack_filter_model)
		self.current_view_mode = StripRackPanel.DIVIDE
		self.updateViewFromMode()
		# OPTS menu
		createNewRack_action = QAction('New rack...', self)
		createNewRack_action.setIcon(QIcon(IconFile.action_newRack))
		createNewRack_action.triggered.connect(self.createNewRack)
		moveRacks_action = QAction('Bring racks to this view...', self)
		moveRacks_action.triggered.connect(self.moveRacksToView)
		self.view_mode_action_group = QActionGroup(self)
		for mode, txt in zip(StripRackPanel.view_modes, ['Divided width', 'Horizontal scroll', 'Tabbed racks']):
			view_action = QAction(txt, self)
			view_action.setCheckable(True)
			view_action.triggered.connect(lambda toggle, m=mode: self.selectViewMode(m))
			self.view_mode_action_group.addAction(view_action)
			if mode == self.current_view_mode:
				view_action.setChecked(True)
		opts_menu = QMenu(self)
		opts_menu.addAction(createNewRack_action)
		opts_menu.addAction(moveRacks_action)
		opts_menu.addSeparator()
		opts_menu.addActions(self.view_mode_action_group.actions())
		self.view_menuButton.setMenu(opts_menu)
		# External signals below. CAUTION: these must all be disconnected on widget deletion
		env.strips.columnsRemoved.connect(self.updateAfterRackDeletion)
		signals.rackEdited.connect(self.updateAfterRackEdit)
		signals.rackVisibilityTaken.connect(self.hideRacks)
		signals.selectionChanged.connect(self.updateSelections)
		signals.selectionChanged.connect(self.strip_menuButton.updateButtonsAndActions)
		signals.stripInfoChanged.connect(self.strip_menuButton.updateButtonsAndActions)
		self.strip_menuButton.updateButtonsAndActions()
	
	def getViewRacks(self):
		"""
		returns the racks currently shown in the panel, in visible order (whether tabbed or in columns)
		"""
		if self.stacked_view_widget.currentWidget() is self.tableView_page:
			hh = self.stripRacks_view.horizontalHeader()
			return [self.rack_filter_model.rackName(hh.logicalIndex(i)) for i in range(hh.count())]
		else:
			return [w.singleRackFilter() for w in self.stripRacks_tabs.rackTabs()]
	
	def setViewRacks(self, racks):
		self.rack_filter_model.setRackFilter(racks)
		hh = self.stripRacks_view.horizontalHeader()
		for vis, rack in enumerate(racks):
			try:
				curr_vis = next(i for i in range(vis + 1, hh.count()) if self.rack_filter_model.rackName(hh.logicalIndex(i)) == rack)
				hh.moveSection(curr_vis, vis)
			except StopIteration:
				pass
		self.stripRacks_tabs.setTabs(racks)
		self.updateViewFromMode()
	
	
	## GUI UPDATES
	
	def updateAfterRackEdit(self, old_name, new_name):
		if new_name != old_name:
			self.rack_filter_model.updateRackFilter({old_name: new_name})
			self.stripRacks_tabs.updateTabName(old_name, new_name)
		self.stripRacks_tabs.updateTabIcons()
		self.updateSelections()
	
	def updateAfterRackDeletion(self):
		self.rack_filter_model.updateRackFilter({})
		still_existing = env.strips.rackNames()
		self.stripRacks_tabs.setTabs([r for r in self.getViewRacks() if r in still_existing])
		self.updateViewFromMode()
		self.updateSelections()
	
	def updateSelections(self):
		self.stripRacks_view.updateSelection()
		self.stripRacks_tabs.updateSelection()
	
	def updateViewFromMode(self):
		if self.current_view_mode == StripRackPanel.TABBED:
			self.stacked_view_widget.setCurrentWidget(self.tabView_page)
			self.stripRacks_tabs.updateTabIcons()
		else:
			self.stacked_view_widget.setCurrentWidget(self.tableView_page)
			self.stripRacks_view.setDivideHorizWidth(self.current_view_mode == StripRackPanel.DIVIDE)
	
	def hideRacks(self, racks):
		self.setViewRacks([r for r in self.getViewRacks() if r not in racks])
	
	
	## ACTIONS
	
	def createNewRack(self):
		i = 1
		new_rack_name = 'Rack 1'
		while not env.strips.validNewRackName(new_rack_name):
			i += 1
			new_rack_name = 'Rack %d' % i
		env.strips.addRack(new_rack_name)
		self.setViewRacks(self.getViewRacks() + [new_rack_name])
	
	def moveRacksToView(self):
		available_racks = [r for r in env.strips.rackNames() if r not in self.getViewRacks()]
		dialog = RackVisibilityDialog(available_racks, parent=self)
		dialog.exec()
		if dialog.result() > 0:
			new_rack_visibility = self.getViewRacks() + dialog.getSelection()
			signals.rackVisibilityTaken.emit(new_rack_visibility)
			self.setViewRacks(new_rack_visibility)
	
	def selectViewMode(self, view_mode):
		rack_order_to_replicate = self.getViewRacks() # views not necessarily in sync if sections/tabs were moved
		self.current_view_mode = view_mode
		self.updateViewFromMode()
		self.setViewRacks(rack_order_to_replicate)
	
	
	## SAVED STATES
	
	def stateSave(self):
		return {
			'view_mode': str(self.current_view_mode),
			'visible_racks': ','.join(str(env.strips.rackIndex(r)) for r in self.getViewRacks())
		}
	
	def restoreState(self, saved_state):
		try:
			view_mode = int(saved_state['view_mode'])
			view_mode_action = self.view_mode_action_group.actions()[view_mode]
			view_mode_action.setChecked(True)
			view_mode_action.trigger()
		except (KeyError, IndexError, ValueError):
			pass # missing or invalid view mode state attr
		try:
			racks = [env.strips.rackName(int(ir)) for ir in saved_state['visible_racks'].split(',')]
			signals.rackVisibilityTaken.emit(racks)
			self.setViewRacks(racks)
		except KeyError:
			pass # no visible racks saved
		except (IndexError, ValueError):
			pass # bad int list value
	
	
	## CLOSING
	
	def closeEvent(self, event): # not triggered when used as main window dock
		env.strips.columnsRemoved.disconnect(self.updateAfterRackDeletion)
		signals.selectionChanged.disconnect(self.strip_menuButton.updateButtonsAndActions)
		signals.stripInfoChanged.disconnect(self.strip_menuButton.updateButtonsAndActions)
		signals.selectionChanged.disconnect(self.updateSelections)
		signals.rackEdited.disconnect(self.updateAfterRackEdit)
		signals.rackVisibilityTaken.disconnect(self.hideRacks)
		event.accept()
		signals.rackVisibilityLost.emit(self.getViewRacks())
		WorkspaceDockablePanel.closeEvent(self, event)





#############################

##     LOOSE STRIP BAY     ##

#############################


class LooseStripPanel(WorkspaceDockablePanel, Ui_looseStripPanel): # is a QWidget
	def __init__(self):
		WorkspaceDockablePanel.__init__(self, defaultTitle='Loose strip bay')
		self.setupUi(self)
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.setWindowIcon(QIcon(IconFile.panel_looseBay))
		self.force_on_close = False
		self.stripView.setDragMode(QGraphicsView.ScrollHandDrag)
		self.stripView.setResizeAnchor(QGraphicsView.AnchorViewCenter)
		self.scene = LooseStripBayScene(self)
		self.stripView.setScene(self.scene)
		self.clearBg_action = QAction('No background', self)
		self.clearBg_action.setCheckable(True)
		self.clearBg_action.triggered.connect(self.scene.clearBgImg)
		self.rebuildBgMenu()
		self.compactStrips_tickBox.toggled.connect(self.scene.setCompactStrips)
		signals.stripDeleted.connect(self.scene.deleteStripItem)
		signals.backgroundImagesReloaded.connect(self.rebuildBgMenu)
		signals.selectionChanged.connect(self.strip_menuButton.updateButtonsAndActions)
		signals.stripInfoChanged.connect(self.strip_menuButton.updateButtonsAndActions)
		signals.sessionEnded.connect(self.scene.deleteAllStripItems)
		self.strip_menuButton.updateButtonsAndActions()
	
	def stripsInBay(self):
		return self.scene.getStrips()
	
	
	## GUI UPDATES
	
	def rebuildBgMenu(self):
		self.scene.clearBgImg() # clears background
		bg_action_group = QActionGroup(self)
		bg_action_group.addAction(self.clearBg_action)
		for file_spec, pixmap, scale, title in settings.loose_strip_bay_backgrounds:
			action = QAction(title, self)
			action.setCheckable(True)
			action.triggered.connect(lambda b, px=pixmap, sc=scale: self.scene.setBgImg(px, sc))
			bg_action_group.addAction(action)
		bg_menu = QMenu(self)
		bg_menu.addAction(self.clearBg_action)
		bg_menu.addSeparator()
		bg_menu.addActions(bg_action_group.actions()[1:]) # index 0 is self.clearBg_action
		self.background_menuButton.setMenu(bg_menu)
		self.clearBg_action.setChecked(True)
		self.background_menuButton.setEnabled(settings.loose_strip_bay_backgrounds != [])
	
	
	## SAVED STATES
	
	def stateSave(self):
		res = {'compact_strips': str(int(self.compactStrips_tickBox.isChecked()))}
		try:
			res['bg_img'] = str(next(i for i, act in enumerate(self.background_menuButton.menu().actions()) if act.isChecked()))
		except StopIteration:
			pass
		return res
	
	def restoreState(self, saved_state):
		try:
			self.compactStrips_tickBox.setChecked(bool(int(saved_state['compact_strips'])))
		except KeyError:
			pass
		try:
			sel_bg = int(saved_state['bg_img'])
			action = self.background_menuButton.menu().actions()[sel_bg]
			action.setChecked(True)
			action.trigger()
		except (KeyError, IndexError):
			pass
	
	
	## CLOSING
	
	def forceClose(self):
		self.force_on_close = True
		self.close()
	
	def closeEvent(self, event):
		if not self.force_on_close:
			strips = self.stripsInBay()
			if len(strips) > 0:
				if QMessageBox.question(self, 'Strip bay not empty',
						'This strip bay is currently holding %d strip(s).\nRack strips and close?' % len(strips)) == QMessageBox.Yes:
					for strip in strips:
						strip.writeDetail(recycled_detail, True)
						env.strips.repositionStrip(strip, default_rack_name)
				else:
					event.ignore()
					return
		self.scene.disconnectAllSignals()
		signals.stripDeleted.disconnect(self.scene.deleteStripItem)
		signals.backgroundImagesReloaded.disconnect(self.rebuildBgMenu)
		signals.selectionChanged.disconnect(self.strip_menuButton.updateButtonsAndActions)
		signals.stripInfoChanged.disconnect(self.strip_menuButton.updateButtonsAndActions)
		signals.sessionEnded.disconnect(self.scene.deleteAllStripItems)
		event.accept()
		WorkspaceDockablePanel.closeEvent(self, event)






############################

##    RUNWAY BOX PANEL    ##

############################

class RunwayBoxPanel(RunwayBoxesView):
	def __init__(self, parent=None):
		RunwayBoxesView.__init__(self, parent)
		signals.generalSettingsChanged.connect(self.updateLayout)
	
	def updateLayout(self):
		self.setVerticalLayout(settings.vertical_runway_box_layout)
