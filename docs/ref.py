import copy
import datetime
import gc
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import time
import traceback
import weakref
from collections import deque
from contextlib import contextmanager
from typing import Optional

import SimpleITK as sitk
import nibabel as nib
import numpy as np

import qt
import ctk
import vtk

import slicer
import sitkUtils
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleLogic,
    ScriptedLoadableModuleWidget,
)
from slicer.util import VTKObservationMixin
from SubjectHierarchyPlugins.AbstractScriptedSubjectHierarchyPlugin import *

import SlicerCustomAppUtilities
from plans.brachy_plan_v2 import brachy_plan, brachy_plan_rf
from plans.config import setting
from plans.dose_pre.model_loader import load_dose_model
from plans.utilizations_v2 import position_transform, direction_transform, compute_body_shell_and_ref_direction, ras_direction_to_voxel
from Resources import BrachyPlanResources  # noqa: F401


def _load_module_constants():
    config_path = os.path.join(os.path.dirname(__file__), "plans", "config.json")
    try:
        with open(config_path, "r") as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.warning(f"Failed to load module config from {config_path}: {e}")
        config_data = {}
    return config_data.get("module_constants", {})


_module_constants = _load_module_constants()

NEW_SLICES_ROUNDED = _module_constants.get("NEW_SLICES_ROUNDED", 64)
SEED_LENGTH = _module_constants.get("SEED_LENGTH", 3.7)
SEED_RADIUS = _module_constants.get("SEED_RADIUS", 0.4)
SEED_RESOLUTION = _module_constants.get("SEED_RESOLUTION", 60)
DIRECTION_EXTENSION = _module_constants.get("DIRECTION_EXTENSION", 100)

RESAMPLE_DEFAULT_SIZE = [128, 128, 128]
RESAMPLE_DEFAULT_SPACING = [1, 1, 1]
CAPSULE_CYLINDER_RESOLUTION = 24
CAPSULE_SPHERE_RADIUS_OFFSET = 0.01
DOSE_MODEL_IN_CHANNELS = 3
DOSE_MODEL_OUT_CHANNELS = 1
DIRECTION_REVERSAL_SIGN = -1
DOSE_SCALE_FACTOR = 120.0

LOG_LEVEL_COLORS = {
    "error": "red",
    "warning": "orange",
    "success": "green",
    "info": "#333333",
}


class BrachyPlan(ScriptedLoadableModule):
    """BrachyPlan module for intelligent brachytherapy treatment planning.

    Orchestrates the overall application workflow, customizes the UI,
    and coordinates between segmentation and planning sub-modules.

    Attributes:
        _module_config: Dictionary of module metadata (icon, title, categories, etc.).
        _ui_config: Dictionary of UI visibility settings.
    """

    _module_config = {
        "icon": ":Resources/Icons/BrachyPlan.png",
        "title": "BrachyPlan",
        "categories": [""],
        "dependencies": [],
        "contributors": [
            "Shanghai Jiao Tong University (SJTU)",
            "Ruijin Hospital, Shanghai Jiao Tong University School of Medicine (RJH-SJTU)",
            "3D Slicer community",
        ],
        "help_text": "This is an integrated software platform designed for intelligent brachytherapy.",
    }

    _ui_config = {
        "show_module_panel": True,
        "module_selection": True,
        "layout_selection": True,
    }

    def __init__(self, parent):
        """Initialize the BrachyPlan module.

        Args:
            parent: Parent widget for the module.
        """
        ScriptedLoadableModule.__init__(self, parent)
        self._setup_module_config()
        self._setup_acknowledgement_text()
        self._setup_startup_settings()

    def _setup_module_config(self):
        """Apply module configuration from the config dictionary to the parent."""
        config = self._module_config
        
        iconPath = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "BrachyPlan.png")
        iconPath = iconPath.replace('\\', '/')
        if os.path.exists(iconPath):
            self.parent.icon = qt.QIcon(iconPath)
        else:
            print(f"[BrachyPlan] ERROR: Cannot find icon at {iconPath}")
        
        self.parent.title = config["title"]
        self.parent.categories = config["categories"]
        self.parent.dependencies = config["dependencies"]
        self.parent.contributors = config["contributors"]
        self.parent.helpText = config["help_text"] + self.getDefaultModuleDocumentationLink()

    def _setup_acknowledgement_text(self):
        """Set the acknowledgement text with logo and contributor information."""
        logoPath = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "BrachyPlan.png")
        self.parent.acknowledgementText = (
            f'<div style="display: flex; align-items: center; gap: 20px;">'
            f'<img src="{logoPath}" width="80" height="80" style="flex-shrink: 0;">'
            f'<div style="flex: 1;">'
            f"Brachytherapy was developed by research teams at Shanghai Jiao Tong University "
            f"and Ruijin Hospital, Shanghai Jiao Tong University School of Medicine.<br>"
            f"</div>"
            f"</div>"
        )

    def _setup_startup_settings(self):
        """Configure the startup module and connect startup completion signals."""
        slicer.app.settings().setValue("Modules/HomeModule", "BrachyPlan")
        slicer.app.connect("startupCompleted()", self.setupDefault3DView)
        slicer.app.connect("startupCompleted()", self.setupSliceControllerStyle)
        slicer.app.connect("startupCompleted()", self.enableModuleSelection)

    def setup(self):
        """Register the subject hierarchy plugin and apply UI panel settings."""
        scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
        scriptedPlugin.setPythonSource(BrachyPlanSubjectHierarchyPlugin.filePath)
        slicer.app.settings().setValue("Modules/ShowModulePanel", self._ui_config["show_module_panel"])

    def setupDefault3DView(self):
        """Configure the default 3D view with white background and hidden orientation markers."""
        layoutManager = slicer.app.layoutManager()
        if not layoutManager:
            return
        for i in range(layoutManager.threeDViewCount):
            view = layoutManager.threeDWidget(i).threeDView()
            viewNode = view.mrmlViewNode()
            viewNode.SetBackgroundColor(1, 1, 1)
            viewNode.SetBackgroundColor2(1, 1, 1)
            viewNode.SetBoxVisible(False)
            viewNode.SetAxisLabelsVisible(False)
            view.forceRender()

    def setupSliceControllerStyle(self):
        """Apply custom stylesheet to all slice view controllers."""
        layoutManager = slicer.app.layoutManager()
        for name in layoutManager.sliceViewNames():
            controller = layoutManager.sliceWidget(name).sliceController()
            controller.setStyleSheet("""
                background-color: rgba(180, 210, 255, 120);
                border-radius: 6px;
            """)

    def enableModuleSelection(self):
        """Ensure module selection, module panel, and layout selection are enabled."""
        ui_config = self._ui_config
        slicer.app.settings().setValue("Modules/ModuleSelection", ui_config["module_selection"])
        slicer.app.settings().setValue("Modules/ShowModulePanel", ui_config["show_module_panel"])
        slicer.app.settings().setValue("Modules/LayoutSelection", ui_config["layout_selection"])
        slicer.app.settings().sync()


class BrachyPlanSubjectHierarchyPlugin(AbstractScriptedSubjectHierarchyPlugin):
    """Subject hierarchy plugin that adds a 'Reset to original position' action for line markups.

    Attributes:
        filePath: Path to the source file for plugin registration.
        resetAction: QAction for resetting line markup positions.
    """

    filePath = __file__

    def __init__(self, scriptedPlugin):
        """Initialize the subject hierarchy plugin.

        Args:
            scriptedPlugin: The scripted plugin instance.
        """
        AbstractScriptedSubjectHierarchyPlugin.__init__(self, scriptedPlugin)
        scriptedPlugin.name = "BrachyPlan"
        self.resetAction = qt.QAction("Reset to original position", scriptedPlugin)
        self.resetAction.connect("triggered()", self.onResetLine)

    def canOwnSubjectHierarchyItem(self, itemID):
        """Check if the plugin can own a subject hierarchy item.

        Args:
            itemID: The ID of the subject hierarchy item.

        Returns:
            float: 1.0 if the item is a vtkMRMLMarkupsLineNode, 0.0 otherwise.
        """
        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        associatedNode = shNode.GetItemDataNode(itemID)
        if associatedNode is not None and associatedNode.IsA("vtkMRMLMarkupsLineNode"):
            return 1.0
        return 0.0

    def itemContextMenuActions(self):
        """Return the context menu actions for the item.

        Returns:
            list: List containing the reset action.
        """
        return [self.resetAction]

    def showContextMenuActionsForItem(self, itemID):
        """Show or hide the reset action based on the item type.

        Args:
            itemID: The ID of the subject hierarchy item.
        """
        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        associatedNode = shNode.GetItemDataNode(itemID)
        if associatedNode is not None and associatedNode.IsA("vtkMRMLMarkupsLineNode"):
            self.resetAction.visible = True
        else:
            self.resetAction.visible = False

    def onResetLine(self):
        """Reset the selected line markup to its original stored position."""
        try:
            pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
            itemID = pluginHandlerSingleton.currentItem()
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            lineNode = shNode.GetItemDataNode(itemID)
            if lineNode is None:
                return
            originalStart = lineNode.GetAttribute("originalStart")
            originalEnd = lineNode.GetAttribute("originalEnd")
            if originalStart and originalEnd:
                start_coords = [float(x) for x in originalStart.split(",")]
                end_coords = [float(x) for x in originalEnd.split(",")]
                lineNode.SetNthControlPointPosition(0, start_coords[0], start_coords[1], start_coords[2])
                lineNode.SetNthControlPointPosition(1, end_coords[0], end_coords[1], end_coords[2])
        except Exception as e:
            logging.error(f"Error resetting line position: {str(e)}")


def registerSampleData():
    """Register sample data sets for the BrachyPlan module.

    Adds BrachyPlan1 and BrachyPlan2 sample data sources to the Sample Data module
    so users can easily try the module with example data.
    """
    import SampleData

    iconsPath = os.path.join(os.path.dirname(__file__), "Resources/Icons")

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="Surgical Plan",
        sampleName="BrachyPlan1",
        thumbnailFileName=os.path.join(iconsPath, "BrachyPlan.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        fileNames="BrachyPlan1.nrrd",
        checksums="SHA256:998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        nodeNames="BrachyPlan1",
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="Surgical Plan",
        sampleName="BrachyPlan2",
        thumbnailFileName=os.path.join(iconsPath, "BrachyPlan.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        fileNames="BrachyPlan2.nrrd",
        checksums="SHA256:1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        nodeNames="BrachyPlan2",
    )


class InstallError(Exception):
    """Custom exception for installation errors.

    Attributes:
        message: Error message string.
        restartRequired: Whether a restart is required after the error.
    """

    def __init__(self, message, restartRequired=False):
        """Initialize the InstallError.

        Args:
            message: Error message string.
            restartRequired: Whether a restart is required after the error.
        """
        super().__init__(message)
        self.message = message
        self.restartRequired = restartRequired

    def __str__(self):
        """Return the error message string.

        Returns:
            str: The error message.
        """
        return self.message


class AnimatedProgressDialog(qt.QProgressDialog):
    """Custom progress dialog with animated percentage label.

    Overrides setRange to prevent external code from breaking the busy state,
    and always appends the current percentage to the label text.

    Attributes:
        baseLabelText: The base label text without percentage.
    """

    def __init__(self, labelText, parent):
        """Initialize the animated progress dialog.

        Args:
            labelText: Base label text to display with percentage.
            parent: Parent widget for the dialog.
        """
        super().__init__(labelText, "Waiting", 0, 0, parent)
        self.baseLabelText = labelText
        self._currentValue = 0
        self.setWindowTitle("Progress")
        self.setWindowModality(qt.Qt.WindowModal)
        self.setMinimumDuration(0)
        self.setAutoClose(False)
        self.setCancelButton(None)
        self.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bbb;
                border-radius: 4px;
                background-color: #f0f0f0;
                text-align: center;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                                  stop: 0 #4CAF50, stop: 1 #81C784);
                width: 20px;
                margin: 1px;
            }
            QLabel {
                color: #333;
                font-weight: bold;
            }
        """)

    def setValue(self, value):
        """Update the progress value and refresh the label with percentage.

        Args:
            value: Progress value (0-100).
        """
        self._currentValue = value
        percent = max(0, min(100, value))
        qt.QProgressDialog.setLabelText(self, f"{self.baseLabelText} [{percent}%]")

    def value(self):
        """Return the stored current progress value.

        Returns:
            int: Current progress value.
        """
        return self._currentValue

    def setRange(self, minimum, maximum):
        """Override to prevent external code from breaking the busy state.

        Args:
            minimum: Minimum range value (ignored).
            maximum: Maximum range value (ignored).
        """
        pass

    def setLabelText(self, text):
        """Update the base label text while preserving the percentage display.

        Args:
            text: New base label text.
        """
        current_value = self.value()
        self.baseLabelText = text
        percent = max(0, min(100, current_value))
        qt.QProgressDialog.setLabelText(self, f"{self.baseLabelText} [{percent}%]")


def createProgressDialog(labelText="Processing..."):
    """Create and show an animated progress dialog compatible with setValue().

    Args:
        labelText: Label text to display in the progress dialog.

    Returns:
        AnimatedProgressDialog: Configured and visible progress dialog instance.
    """
    mainWindow = slicer.util.mainWindow()
    progressDialog = AnimatedProgressDialog(labelText, mainWindow)
    progressDialog.show()
    progressDialog.raise_()
    progressDialog.activateWindow()
    return progressDialog


class BrachyPlanWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Widget class for the BrachyPlan module.

    Manages the UI panel, parameter node synchronization, planning parameter
    controls, segmentation triggers, and custom application styling.

    Attributes:
        _toolbars: Dictionary mapping toolbar names to QToolBar instances.
        logic: The BrachyPlanLogic instance for backend operations.
        _parameterNode: The MRML parameter node for state persistence.
        _updatingGUIFromParameterNode: Flag to prevent recursive GUI updates.
        _planning_params: Current planning parameters namespace object.
    """

    _PARAM_BINDINGS = [
        ("seedRadiusSpinBox", "valueChanged", ("seed_info", "radius")),
        ("seedLengthSpinBox", "valueChanged", ("seed_info", "length")),
        ("seedCountMinSpinBox", "valueChanged", ("seed_info", "num_of_seeds", 0)),
        ("seedCountMaxSpinBox", "valueChanged", ("seed_info", "num_of_seeds", 1)),
        ("seedDoseSpinBox", "valueChanged", ("seed_info", "seed_avr_dose")),
        ("targetValueSpinBox", "valueChanged", ("radiation_array_params", "target_value")),
        ("obstacleValueSpinBox", "valueChanged", ("radiation_array_params", "obstacle_value")),
        ("backgroundValueSpinBox", "valueChanged", ("radiation_array_params", "background_value")),
        ("backlitAngleSpinBox", "valueChanged", ("radiation_array_params", "backlit_angle")),
        ("maxCandiTrajSpinBox", "valueChanged", ("radiation_array_params", "maximum_candidate_trajectories")),
        ("inLowestEnergySpinBox", "valueChanged", ("in_lowest_energy",)),
        ("outHighestEnergySpinBox", "valueChanged", ("out_highest_energy",)),
        ("dvhRateSpinBox", "valueChanged", ("DVH_rate",)),
        ("maxIterSpinBox", "valueChanged", ("max_iter",)),
        ("refDirecXSpinBox", "valueChanged", ("reference_direc", 0)),
        ("refDirecYSpinBox", "valueChanged", ("reference_direc", 1)),
        ("refDirecZSpinBox", "valueChanged", ("reference_direc", 2)),
        ("maxEpisodesSpinBox", "valueChanged", ("rf_params", "max_episodes")),
        ("bandwidthSpinBox", "valueChanged", ("rf_params", "bandwidth")),
    ]

    @property
    def toolbarNames(self):
        """Return the list of toolbar names managed by this widget.

        Returns:
            list[str]: List of toolbar name strings.
        """
        return [str(k) for k in self._toolbars]

    def __init__(self, parent=None):
        """Initialize the BrachyPlan widget.

        Args:
            parent: Parent widget for this widget.
        """
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False
        self._dragged_needle = None
        self._last_processed_ct_id = None
        self._segmentation_in_progress = False

    def setup(self):
        """Setup the widget and initialize all UI components.

        Loads the .ui file, creates the logic instance, connects signals,
        initializes planning parameters, and applies custom styling.
        """
        ScriptedLoadableModuleWidget.setup(self)

        self.uiWidget = slicer.util.loadUI(self.resourcePath("UI/BrachyPlan.ui"))
        self.ui = slicer.util.childWidgetVariables(self.uiWidget)

        treeView = slicer.qMRMLSubjectHierarchyTreeView()
        treeView.setObjectName("treeView")
        treeView.setMRMLScene(slicer.mrmlScene)
        treeView.setColumnHidden(2, True)
        treeView.visibilityColumnVisible = True

        self._convert_to_splitter_layout(treeView)

        self.uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = BrachyPlanLogic()
        self.logic._widget = self
        self.logic.logCallback = self.addLog
        self.ui.SegTaskSelector.addItems(self.logic.segTasks)

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.ui.imageSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.imageSelector.setMRMLScene(slicer.mrmlScene)
        self.ui.CTVImageSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.CTVImageSelector.setMRMLScene(slicer.mrmlScene)
        self.ui.OARImageSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.OARImageSelector.setMRMLScene(slicer.mrmlScene)
        self.ui.outputSegmentationSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.outputSegmentationSelector.setMRMLScene(slicer.mrmlScene)

        self.ui.segmentButton.connect("clicked(bool)", self.onSegmentButton)

        self.initializePlanningParameters()

        self.ui.planButton.connect("clicked(bool)", self.onPlanButton)

        # Unified height for standard widgets (excluding text browsers and collapsible buttons)
        self._setupUnifiedWidgetHeights()

        self.ui.doseOpacitySlider.connect("valueChanged(int)", self.onDoseOpacityChanged)

        self.ui.autoRefDirecButton.connect("clicked(bool)", self._auto_compute_reference_direction)
        self.ui.imageSelector.connect("currentNodeChanged(vtkMRMLNode*)", self._on_input_selection_changed)
        self.ui.CTVImageSelector.connect("currentNodeChanged(vtkMRMLNode*)", self._on_input_selection_changed)
        # OAR selection no longer triggers reference direction auto-computation
        # self.ui.OARImageSelector.connect("currentNodeChanged(vtkMRMLNode*)", self._on_input_selection_changed)

        # Note: spinbox signals are disconnected - arrow can only be adjusted by dragging control points
        # self.ui.refDirecXSpinBox.connect("valueChanged(double)", self._on_ref_direc_spinbox_changed)
        # self.ui.refDirecYSpinBox.connect("valueChanged(double)", self._on_ref_direc_spinbox_changed)
        # self.ui.refDirecZSpinBox.connect("valueChanged(double)", self._on_ref_direc_spinbox_changed)

        self._ref_direc_arrow_node = None
        self._ref_direc_interaction_node = None
        self._ref_direc_updating = False

        self._last_dose_node = None
        self._last_ct_node = None
        self._toolbars = {}

        self._geometry_cache = {}

        self._connect_param_signals()

        self.initializeParameterNode()

        self.modifyWindowUI()
        self.setCustomUIVisible()

        self.applyApplicationStyle()

    def _set_nested_param(self, params, path, value):
        """Set a nested attribute on the planning params namespace.

        Args:
            params: The namespace object.
            path: Tuple of keys/indices to traverse.
            value: The value to set.
        """
        try:
            obj = params
            for key in path[:-1]:
                if isinstance(obj, dict):
                    obj = obj[key]
                elif isinstance(obj, (list, np.ndarray)):
                    obj = obj[key]
                else:
                    obj = getattr(obj, key)
            last_key = path[-1]
            if isinstance(obj, dict):
                obj[last_key] = value
            elif isinstance(obj, (list, np.ndarray)):
                obj[last_key] = value
            else:
                setattr(obj, last_key, value)
        except Exception as e:
            logging.warning(f"Failed to set nested param {path}: {e}")

    def _connect_param_signals(self):
        """Connect all parameter UI controls using the declarative binding table."""
        try:
            for widget_name, signal_name, param_path in self._PARAM_BINDINGS:
                widget = getattr(self.ui, widget_name)
                signal = getattr(widget, signal_name)
                path = param_path

                def make_handler(p):
                    def handler(value):
                        self._set_nested_param(self._planning_params, p, value)
                    return handler

                signal.connect(make_handler(path))

            self.ui.useReinforceLearningCheckBox.toggled.connect(
                lambda checked: setattr(self._planning_params, "use_rf", checked)
            )
        except Exception as e:
            self.addLog(f"Error connecting parameter signals: {str(e)}", level="error")

    def cleanup(self):
        """Called when the application closes and the module widget is destroyed.

        Removes all VTK observers, disconnects Qt signals, and releases
        UI resources to prevent memory leaks on exit.
        """
        self.removeObservers()

        # 1. Clean up settings UI and signals
        try:
            if hasattr(self, "settingsUI") and self.settingsUI is not None:
                self.settingsUI.CustomUICheckBox.toggled.disconnect(self.setCustomUIVisible)
                self.settingsUI.CustomStyleCheckBox.toggled.disconnect(self.toggleStyle)
        except Exception:
            pass

        try:
            if hasattr(self, "settingsAction") and self.settingsAction is not None:
                # Disconnect and delete the action
                try:
                    self.settingsAction.triggered.disconnect(self.raiseSettings)
                except Exception:
                    pass
                self.settingsAction.deleteLater()
                self.settingsAction = None
        except Exception:
            pass

        try:
            if hasattr(self, "settingsDialog") and self.settingsDialog is not None:
                self.settingsDialog.close()
                self.settingsDialog.deleteLater()
                self.settingsDialog = None
        except Exception:
            pass

        # 2. Remove custom toolbars from Slicer main window (Fix for UI Leak)
        try:
            if hasattr(self, "_toolbars") and self._toolbars:
                mainWindow = slicer.util.mainWindow()
                for name, toolbar in self._toolbars.items():
                    if toolbar is not None:
                        mainWindow.removeToolBar(toolbar)
                        toolbar.deleteLater()
                self._toolbars.clear()
        except Exception as e:
            logging.error(f"Error removing toolbars during cleanup: {str(e)}")

        try:
            if hasattr(self, "_mainSplitter") and self._mainSplitter is not None:
                self._mainSplitter = None
        except Exception:
            pass

        # 3. Disconnect slicer.app startup signals
        try:
            slicer.app.disconnect("startupCompleted()", self.setupDefault3DView)
            slicer.app.disconnect("startupCompleted()", self.setupSliceControllerStyle)
            slicer.app.disconnect("startupCompleted()", self.enableModuleSelection)
        except Exception:
            pass

        # 4. Clean up reference direction arrow and interaction nodes
        try:
            if hasattr(self, '_ref_direc_arrow_node') and self._ref_direc_arrow_node is not None:
                if hasattr(self, '_ref_direc_arrow_tag') and self._ref_direc_arrow_tag:
                    self._ref_direc_arrow_node.RemoveObserver(self._ref_direc_arrow_tag)
                    self._ref_direc_arrow_tag = None
                if self._ref_direc_arrow_node.GetScene() == slicer.mrmlScene:
                    slicer.mrmlScene.RemoveNode(self._ref_direc_arrow_node)
                self._ref_direc_arrow_node = None
        except Exception:
            pass

        try:
            if hasattr(self, '_ref_direc_interaction_node') and self._ref_direc_interaction_node is not None:
                if self._ref_direc_interaction_node.GetScene() == slicer.mrmlScene:
                    slicer.mrmlScene.RemoveNode(self._ref_direc_interaction_node)
                self._ref_direc_interaction_node = None
        except Exception:
            pass

        # 5. Clean up any leftover RefDirectionArrow nodes in scene
        try:
            for name in ["RefDirectionArrow", "RefDirectionArrow_Interaction"]:
                nodes = slicer.mrmlScene.GetNodesByName(name)
                for i in range(nodes.GetNumberOfItems()):
                    node = nodes.GetItemAsObject(i)
                    if node and node.GetScene() == slicer.mrmlScene:
                        slicer.mrmlScene.RemoveNode(node)
        except Exception:
            pass

        # 6. Clean up MRML cache and references
        try:
            self._last_dose_node = None
            self._last_ct_node = None
            self._last_processed_ct_id = None
        except Exception:
            pass

        # 7. Clean up geometry cache
        try:
            if hasattr(self, '_geometry_cache') and self._geometry_cache is not None:
                self._geometry_cache.clear()
                self._geometry_cache = None
        except Exception:
            pass

        # 8. Clean up logic callback
        try:
            if hasattr(self, 'logic') and self.logic is not None:
                self.logic.logCallback = None
        except Exception:
            pass

    def _setupUnifiedWidgetHeights(self, base_height=20):
        """Set unified height for standard widgets.

        Only affects specific widget types, excluding text browsers,
        collapsible buttons, and other stretchable containers.

        Args:
            base_height: Target height in pixels (default 20).
        """
        try:
            # Widget names to set fixed height (excluding text browsers and containers)
            widget_names = [
                # Main section
                'label', 'imageSelector', 'CTVLabel', 'CTVImageSelector', 'OARLabel', 'OARImageSelector', 'planButton',
                # Segmentation section
                'label_task', 'SegTaskSelector', 'label_output', 'outputSegmentationSelector',
                'fastModeCheckBox', 'segmentButton',
                # Planning params section
                'label_seedRadius', 'seedRadiusSpinBox', 'label_seedLength', 'seedLengthSpinBox',
                'label_seedCountMin', 'seedCountMinSpinBox', 'label_seedCountMax', 'seedCountMaxSpinBox',
                'label_seedDose', 'seedDoseSpinBox', 'label_refDirecX', 'refDirecXSpinBox',
                'label_refDirecY', 'refDirecYSpinBox', 'label_refDirecZ', 'refDirecZSpinBox',
                'autoRefDirecButton', 'label_targetValue', 'targetValueSpinBox',
                'label_obstacleValue', 'obstacleValueSpinBox', 'label_backgroundValue', 'backgroundValueSpinBox',
                'label_backlitAngle', 'backlitAngleSpinBox', 'label_maxCandiTraj', 'maxCandiTrajSpinBox',
                'label_inLowestEnergy', 'inLowestEnergySpinBox', 'label_outHighestEnergy', 'outHighestEnergySpinBox',
                'label_dvhRate', 'dvhRateSpinBox', 'label_maxIter', 'maxIterSpinBox',
                'label_maxEpisodes', 'maxEpisodesSpinBox', 'label_bandwidth', 'bandwidthSpinBox',
                'useReinforceLearningCheckBox',
                # Dose viz section
                'label_doseOpacity', 'doseOpacitySlider', 'doseOpacityValueLabel',
                'label_dvhTitle',
            ]

            from qt import Qt

            for name in widget_names:
                try:
                    widget = getattr(self.ui, name, None)
                    if widget and hasattr(widget, 'setFixedHeight'):
                        widget.setFixedHeight(base_height)
                    # Set alignment: horizontal left, vertical center
                    if widget and hasattr(widget, 'setAlignment'):
                        widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                except Exception:
                    pass
                    
        except Exception as e:
            self.addLog(f"Error setting up unified widget heights: {str(e)}", level="warning")

    def enter(self):
        """Called each time the user opens this module."""
        self.initializeParameterNode()

    def exit(self):
        """Called each time the user opens a different module."""
        try:
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        except Exception:
            pass

    def onSceneStartClose(self, caller, event):
        """Handle scene close start by clearing the parameter node.

        Args:
            caller: The object that triggered the event.
            event: The event type.
        """
        self.setParameterNode(None)
        self._geometry_cache.clear()
        if self.logic:
            self.logic._cleanup_needle_observers()
            self.logic._trajectory_info.clear()
            self.logic._plan_counter = 0
            self.logic._current_plan_folder = None
            self.logic._current_plan_folder_name = None
            self.logic._all_plan_folders.clear()

    def onSceneEndClose(self, caller, event):
        """Handle scene close end by re-initializing the parameter node.

        Args:
            caller: The object that triggered the event.
            event: The event type.
        """
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self):
        """Ensure the parameter node exists and is observed.

        Selects default input nodes if nothing is selected yet, so that
        settings are restored when the scene is saved and reloaded.
        """
        try:
            self.setParameterNode(self.logic.getParameterNode())

            if not self._parameterNode.GetNodeReference("InputVolume"):
                firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
                if firstVolumeNode:
                    self._parameterNode.SetNodeReferenceID("InputVolume", firstVolumeNode.GetID())

            if not self._parameterNode.GetNodeReference("SegmentedVolume"):
                firstSegNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
                if firstSegNode:
                    self._parameterNode.SetNodeReferenceID("SegmentedVolume", firstSegNode.GetID())

            if not self._parameterNode.GetNodeReference("OutputSegmentVolume"):
                firstOutputSegNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
                if firstOutputSegNode:
                    self._parameterNode.SetNodeReferenceID("OutputSegmentVolume", firstOutputSegNode.GetID())
        except Exception:
            pass

    def setParameterNode(self, inputParameterNode):
        """Set and observe the parameter node for GUI synchronization.

        Args:
            inputParameterNode: The parameter node to set and observe.
        """
        try:
            if self._parameterNode is not None and self.hasObserver(
                self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode
            ):
                self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
            self._parameterNode = inputParameterNode
            if self._parameterNode is not None:
                self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
            self.updateGUIFromParameterNode()
        except Exception:
            pass

    def updateGUIFromParameterNode(self, caller=None, event=None):
        """Update the module GUI to reflect the current parameter node state.

        Called whenever the parameter node is modified. Uses a guard flag
        to prevent recursive updates.

        Args:
            caller: The object that triggered the event (optional).
            event: The event type (optional).
        """
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        self._updatingGUIFromParameterNode = True
        try:
            self.ui.imageSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputVolume"))
            self.ui.outputSegmentationSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputSegmentVolume"))
            self.ui.CTVImageSelector.setCurrentNode(self._parameterNode.GetNodeReference("SegmentedVolume"))
            self.ui.OARImageSelector.setCurrentNode(self._parameterNode.GetNodeReference("OARVolume"))

            if self._parameterNode.GetNodeReference("InputVolume") and self._parameterNode.GetNodeReference(
                "SegmentedVolume"
            ):
                self.ui.planButton.toolTip = "Generate brachyplan"
                self.ui.planButton.enabled = True
            else:
                self.ui.planButton.toolTip = "Select input and segmented volume nodes"
                self.ui.planButton.enabled = False

            if self._parameterNode.GetNodeReference("InputVolume") and self._parameterNode.GetNodeReference(
                "OutputSegmentVolume"
            ):
                self.ui.segmentButton.toolTip = "Run segmentation on the selected CT image"
                self.ui.segmentButton.enabled = True
            else:
                self.ui.segmentButton.toolTip = (
                    "Select an input CT image and a output segmentation node to enable segmentation"
                )
                self.ui.segmentButton.enabled = False
        except Exception:
            pass
        finally:
            self._updatingGUIFromParameterNode = False

    def updateParameterNodeFromGUI(self, caller=None, event=None):
        """Save GUI changes into the parameter node.

        Called when the user makes any change in the GUI so that settings
        are restored when the scene is saved and loaded.

        Args:
            caller: The object that triggered the event (optional).
            event: The event type (optional).
        """
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        try:
            wasModified = self._parameterNode.StartModify()
            self._parameterNode.SetNodeReferenceID("InputVolume", self.ui.imageSelector.currentNodeID)
            self._parameterNode.SetNodeReferenceID("OutputSegmentVolume", self.ui.outputSegmentationSelector.currentNodeID)
            self._parameterNode.SetNodeReferenceID("SegmentedVolume", self.ui.CTVImageSelector.currentNodeID)
            self._parameterNode.SetNodeReferenceID("OARVolume", self.ui.OARImageSelector.currentNodeID)
            self._parameterNode.EndModify(wasModified)
        except Exception:
            pass

    def addLog(self, text, level="info"):
        """Append a timestamped, formatted message to the log window.

        Args:
            text: Text to append to the log window.
            level: Log level - 'error', 'warning', 'success', or 'info'.
        """
        try:
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            color = LOG_LEVEL_COLORS.get(level, LOG_LEVEL_COLORS["info"])
            formatted_text = f"""
            <font color="{color}"><b> [{current_time}] {text}</b></font>
            """
            self.ui.statusTextBrowser.append(formatted_text)
            now = time.monotonic()
            if not hasattr(self, '_last_process_events_time'):
                self._last_process_events_time = 0
            if now - self._last_process_events_time > 0.2:
                slicer.app.processEvents()
                self._last_process_events_time = now
        except Exception:
            pass

    def _convert_to_splitter_layout(self, tree_view):
        """Replace the main QVBoxLayout with a QSplitter for resizable sections.

        Extracts all child widgets from the uiWidget's vertical layout,
        creates a QSplitter with vertical orientation, and reparents all
        widgets into the splitter. This allows users to drag splitter
        handles to resize sections like Data Tree, Planning Parameters,
        Dose Visualization, and Status.

        Args:
            tree_view: qMRMLSubjectHierarchyTreeView to insert at the top.
        """
        try:
            main_layout = self.uiWidget.layout()

            widgets = []
            while main_layout.count() > 0:
                item = main_layout.takeAt(0)
                if item.widget():
                    widgets.append(item.widget())
                elif item.layout():
                    pass

            splitter = qt.QSplitter(qt.Qt.Vertical)
            splitter.setObjectName("mainSplitter")

            # Wrap tree_view in a collapsible button
            data_tree_button = ctk.ctkCollapsibleButton()
            data_tree_button.setObjectName("dataTreeCollapsibleButton")
            data_tree_button.text = "Data Tree"
            data_tree_layout = qt.QVBoxLayout(data_tree_button)
            data_tree_layout.setContentsMargins(0, 0, 0, 0)
            data_tree_layout.addWidget(tree_view)

            data_tree_button.connect("toggled(bool)", lambda checked: self._on_splitter_section_toggled(splitter, data_tree_button))

            splitter.addWidget(data_tree_button)

            for w in widgets:
                splitter.addWidget(w)

            # Wrap splitter in QScrollArea so content can exceed viewport
            # Wrap splitter in a container QWidget.  The scroll area
            # manages the container's size; the container's sizeHint
            # returns the splitter's content height so the scrollbar
            # appears when content exceeds the viewport.
            _container = qt.QWidget()
            _container.setObjectName("splitterContainer")
            _container_layout = qt.QVBoxLayout(_container)
            _container_layout.setContentsMargins(0, 0, 0, 0)
            _container_layout.setAlignment(qt.Qt.AlignTop)
            _container_layout.addWidget(splitter)

            scroll_area = qt.QScrollArea()
            scroll_area.setObjectName("mainScrollArea")
            scroll_area.setWidget(_container)
            scroll_area.setWidgetResizable(False)
            scroll_area.setFrameShape(qt.QFrame.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
            scroll_area.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAsNeeded)
            scroll_area.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
            self._container = _container

            # Top-align when content is smaller than viewport
            self.layout.setAlignment(qt.Qt.AlignTop)
            self.layout.addWidget(scroll_area)

            self._scrollArea = scroll_area

            # Only the collapsible containers that hold log/data widgets get stretch.
            # Their internal stretchable children (treeView, statusTextBrowser,
            # dvhMetricsBrowser) absorb space within the container.
            stretchable = {
                "dataTreeCollapsibleButton",
                "CollapsibleButton",
            }

            # Widgets that must have FIXED height (input section)
            fixed_widgets = {
                "label",  # "Input Image:" label
                "imageSelector",
                "CTVLabel",  # "Input CTV:" label
                "CTVImageSelector",
                "OARLabel",  # "Input OAR:" label
                "OARImageSelector",
                "planButton",
            }

            # Collapsible buttons - they should expand when opened, collapse when closed
            # Internal controls will have fixed height
            collapsible_buttons = {
                "dataTreeCollapsibleButton",
                "segmentationCollapsibleButton",
                "planningParamsCollapsibleButton",
                "doseVisualizationCollapsibleButton",
                "CollapsibleButton",
            }

            for i in range(splitter.count()):
                w = splitter.widget(i)
                if w is None:
                    continue

                obj_name = w.objectName if hasattr(w, 'objectName') else 'unknown'

                # Check widget type
                is_stretchable = (obj_name in stretchable)
                is_fixed = obj_name in fixed_widgets
                is_collapsible = obj_name in collapsible_buttons

                # Connect all collapsible buttons to the toggled handler
                # so expanding/collapsing updates desired sizes and scrollbar.
                if obj_name in collapsible_buttons:
                    try:
                        w.connect("toggled(bool)", lambda checked, s=splitter, b=w: self._on_splitter_section_toggled(s, b))
                    except Exception: pass

                # Set stretch factor dynamically based on collapsed state
                if obj_name in ["dataTreeCollapsibleButton", "CollapsibleButton"]:
                    is_collapsed = not w.checked if hasattr(w, 'checked') else getattr(w, 'collapsed', False)
                    splitter.setStretchFactor(i, 0 if is_collapsed else 10)
                else:
                    splitter.setStretchFactor(i, 0)

                if is_fixed:
                    # Input section widgets - set minimum height but allow shrinking proportionally
                    # Use Minimum size policy so widgets can shrink but won't disappear completely
                    try:
                        min_h = 25
                        w.setMinimumHeight(min_h)
                        # Don't set maximum height - allow widgets to shrink proportionally
                        # Set size policy to Minimum so they can shrink but won't disappear
                        size_policy = qt.QSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)
                        size_policy.setRetainSizeWhenHidden(True)
                        w.setSizePolicy(size_policy)
                        w.updateGeometry()
                    except Exception:
                        pass
                elif is_collapsible:
                    # Collapsible buttons - let them expand/collapse naturally
                    try:
                        is_collapsed = not w.checked if hasattr(w, 'checked') else getattr(w, 'collapsed', False)
                        if is_collapsed:
                            # Do not give it exact_height if it's currently collapsed right on boot
                            w.setMinimumHeight(30)
                            w.setMaximumHeight(30)
                            w.updateGeometry()
                        else:
                            # Calculate minimum height based on child widget count
                            child_count = self._count_visible_widgets(w)
                            obj_name = w.objectName if hasattr(w, 'objectName') else ''

                            # Segmentation button
                            if obj_name == 'segmentationCollapsibleButton':
                                exact_height = 25 + child_count * 20
                                w.setMinimumHeight(exact_height)
                                w.setMaximumHeight(16777215)  # Allow expansion
                            # Planning Parameters button - height set precisely after layout fixes
                            elif obj_name == 'planningParamsCollapsibleButton':
                                pass  # Height managed by _apply_planning_params_height()
                            # Stretchable containers: low min (allows manual resize), high default via setSizes
                            elif obj_name == 'dataTreeCollapsibleButton':
                                w.setMinimumHeight(80)
                                w.setMaximumHeight(16777215)
                            elif obj_name == 'CollapsibleButton':
                                w.setMinimumHeight(80)
                                w.setMaximumHeight(16777215)
                            # Sub-collapsibles with 3 rows of controls
                            elif obj_name in ('seedInfoCollapsibleButton', 'radiationParamsCollapsibleButton'):
                                w.setMinimumHeight(150)
                                w.setMaximumHeight(16777215)
                            else:
                                min_height = min(max(30 + child_count * 25, 60), 150)
                                w.setMinimumHeight(min_height)
                                w.setMaximumHeight(16777215)  # Allow expansion
                            w.updateGeometry()
                    except Exception:
                        pass
                elif is_stretchable:
                    try:
                        if obj_name == 'treeView':
                            w.setMinimumHeight(150)
                        else:
                            w.setMinimumHeight(100)
                        w.setMaximumHeight(16777215)
                        w.updateGeometry()
                    except Exception:
                        pass
                else:
                    # Other widgets - set minimum height but allow proportional shrinking
                    try:
                        min_h = 25
                        w.setMinimumHeight(min_h)
                        # Don't set maximum height - allow widgets to shrink proportionally
                        size_policy = qt.QSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)
                        w.setSizePolicy(size_policy)
                        w.updateGeometry()
                    except Exception:
                        pass

            self._fix_all_collapsible_buttons_layout()

            # Unified height for all widgets (except text browsers) - Reduced for max compactness
            self._unify_widget_heights(self.uiWidget, base_height=20)

            # Fix all layout spacing to achieve maximum compression
            self._fix_all_layouts_spacing(self.uiWidget)

            # Measure and constrain planningParams to exact content height
            self._apply_planning_params_height()

            splitter.setHandleWidth(1) # Visible handle for adjustment
            splitter.setChildrenCollapsible(False)

            # Update minimum height when user drags a splitter handle so the
            # scroll area can detect when content exceeds the viewport.
            splitter.splitterMoved.connect(lambda: self._updateSplitterMinHeight())


            # Store desired sizes (user's intended layout) separately from
            # actual sizes (constrained by viewport).  _updateSplitterMinHeight
            # uses desired sizes to compute content height for scrollbar.
            self._desired_sizes = []

            # Resize container to fill viewport; height = max(content, viewport).
            class _ViewportResizer(qt.QObject):
                def __init__(self, widget_ref, scroll_ref, parent=None):
                    super().__init__(parent)
                    self._w = widget_ref
                    self._s = scroll_ref
                def eventFilter(self, obj, event):
                    if event.type() == qt.QEvent.Resize:
                        w = self._w()
                        s = self._s()
                        if w and s:
                            sp = w._mainSplitter
                            if sp:
                                # Update _desired_sizes from current splitter sizes
                                # so _updateSplitterMinHeight uses actual layout.
                                cur = sp.sizes()
                                if w._desired_sizes and len(w._desired_sizes) == len(cur):
                                    w._desired_sizes = list(cur)
                            vp = s.viewport()
                            vp_w = w._qt_val(vp, 'width')
                            vp_h = w._qt_val(vp, 'height')
                            content_h = getattr(w, '_splitter_content_height', 0)
                            h = max(content_h, vp_h) if content_h > 0 else vp_h
                            w._container.resize(vp_w, h)
                    return False
            self._vp_resizer = _ViewportResizer(
                weakref.ref(self), weakref.ref(scroll_area), scroll_area.viewport())
            scroll_area.viewport().installEventFilter(self._vp_resizer)

            # Detect total available height for proportional calculation
            try:
                parent = splitter.parent()
                if parent and hasattr(parent, 'height'):
                    total_height = parent.height() if callable(parent.height) else parent.height
                else:
                    total_height = 800
            except Exception:
                total_height = 800
            if total_height < 400: total_height = 800

            # Ideal proportional sizing: Top (Data Tree) and Bottom (Status) take equal shares
            sizes = []
            middle_height = 0

            # Pass 1: calculate height taken by compressed middle controls
            for i in range(splitter.count()):
                w = splitter.widget(i)
                if not w: continue
                obj_name = w.objectName if hasattr(w, 'objectName') else ''
                if obj_name not in ["treeView", "CollapsibleButton"]:
                    if obj_name in fixed_widgets:
                        middle_height += 25
                    elif obj_name in collapsible_buttons:
                        is_collapsed = not w.checked if hasattr(w, 'checked') else getattr(w, 'collapsed', False)
                        if is_collapsed:
                            middle_height += 30
                        else:
                            min_h_attr = getattr(w, 'minimumHeight', None)
                            if min_h_attr is not None:
                                if callable(min_h_attr):
                                    min_h = min_h_attr()
                                else:
                                    min_h = int(min_h_attr)
                                middle_height += min_h
                            else:
                                middle_height += w.sizeHint.height() if hasattr(w, 'sizeHint') else 150
                    else:
                        middle_height += 25

            # Check if Status section is collapsed
            status_widget = None
            for i in range(splitter.count()):
                w = splitter.widget(i)
                if w and hasattr(w, 'objectName') and w.objectName == "CollapsibleButton":
                    status_widget = w
                    break
            status_collapsed = False
            if status_widget:
                status_collapsed = not status_widget.checked if hasattr(status_widget, 'checked') else getattr(status_widget, 'collapsed', False)

            for i in range(splitter.count()):
                splitter.setCollapsible(i, False)
                w = splitter.widget(i)
                obj_name = w.objectName if hasattr(w, 'objectName') else ''

                if obj_name == "dataTreeCollapsibleButton":
                    # Stretchable: high default, low min (allows manual resize)
                    sizes.append(400)
                    w.setMinimumHeight(80)
                    splitter.setStretchFactor(i, 10)
                elif obj_name == "CollapsibleButton":
                    if status_collapsed:
                        w.setFixedHeight(30)
                        sizes.append(30)
                        splitter.setStretchFactor(i, 0)
                    else:
                        # Stretchable: high default, low min (allows manual resize)
                        sizes.append(300)
                        w.setMinimumHeight(80)
                        splitter.setStretchFactor(i, 5)
                elif obj_name in fixed_widgets:
                    sizes.append(25)
                    w.setFixedHeight(25)
                    splitter.setStretchFactor(i, 0)
                elif obj_name in collapsible_buttons:
                    is_collapsed = not w.checked if hasattr(w, 'checked') else getattr(w, 'collapsed', False)
                    if is_collapsed:
                        w.setFixedHeight(30)
                        sizes.append(30)
                        splitter.setStretchFactor(i, 0)
                    else:
                        # Height will be set precisely by _apply_planning_params_height()
                        # after layout fixes. Use sizeHint as placeholder for now.
                        sizes.append(w.sizeHint.height() if hasattr(w, 'sizeHint') else 150)
                        splitter.setStretchFactor(i, 0)
                else:
                    sizes.append(25)
                    splitter.setStretchFactor(i, 0)

            # Defer setSizes until Qt has laid out the widget tree.
            # Calling setSizes() before the widget is shown has no effect
            # because Qt hasn't computed actual geometry yet.
            self._mainSplitter = splitter
            self._mainScrollArea = scroll_area
            self._splitter_content_height = 0
            self._initialSplitterSizes = sizes

            def _apply_initial_sizes():
                try:
                    if hasattr(self, '_mainSplitter') and self._mainSplitter:
                        # Re-measure planningParams after Qt has laid out children
                        self._apply_planning_params_height()
                        self._mainSplitter.setSizes(self._initialSplitterSizes)
                        # Only set _desired_sizes on first call — subsequent
                        # calls should not overwrite viewport resizer updates.
                        if not self._desired_sizes:
                            self._desired_sizes = list(self._initialSplitterSizes)
                        # Set minimum height so scrollbar appears when content > viewport
                        self._updateSplitterMinHeight()
                        self._mainSplitter.updateGeometry()
                        self._mainSplitter.update()
                except Exception:
                    pass

            qt.QTimer.singleShot(0, _apply_initial_sizes)
            # Also apply after a short delay as a safety net
            qt.QTimer.singleShot(200, _apply_initial_sizes)
        except Exception as e:
            self.addLog(f"Error setting up splitter layout: {str(e)}", level="error")
            self.layout.addWidget(self.uiWidget)

    def _on_splitter_section_toggled(self, splitter, button):
        """Handle section expand/collapse.

        On expand: section grows, total content height increases → scrollbar.
        On collapse: freed space redistributed to stretchable containers.
        """
        try:
            obj_name = button.objectName if hasattr(button, 'objectName') else '?'
            is_collapsed = not button.checked if hasattr(button, 'checked') else getattr(button, 'collapsed', False)
            print(f"[SPLITTER DEBUG] toggled: {obj_name}, collapsed={is_collapsed}")
            current_sizes = list(splitter.sizes())
            print(f"[SPLITTER DEBUG] current_sizes={current_sizes}")
            if not self._desired_sizes:
                self._desired_sizes = list(current_sizes)

            stretchable_indices = []
            for i in range(splitter.count()):
                w = splitter.widget(i)
                if w and hasattr(w, 'objectName') and w.objectName in ["dataTreeCollapsibleButton", "CollapsibleButton", "doseVisualizationCollapsibleButton"]:
                    stretchable_indices.append(i)

            for i in range(splitter.count()):
                w = splitter.widget(i)
                if w == button:
                    is_collapsed = not button.checked if hasattr(button, 'checked') else getattr(button, 'collapsed', False)
                    obj_name = w.objectName if hasattr(w, 'objectName') else ''

                    is_stretchable_container = obj_name in ["dataTreeCollapsibleButton", "CollapsibleButton", "doseVisualizationCollapsibleButton"]
                    if is_stretchable_container:
                        factor = 10 if obj_name == "dataTreeCollapsibleButton" else (7 if obj_name == "doseVisualizationCollapsibleButton" else 5)
                        splitter.setStretchFactor(i, 0 if is_collapsed else factor)
                    else:
                        splitter.setStretchFactor(i, 0)

                    if is_collapsed:
                        freed = current_sizes[i] - 30
                        w.setMinimumHeight(30)
                        w.setMaximumHeight(30)
                        current_sizes[i] = 30
                        self._desired_sizes[i] = 30
                        # Return freed space to stretchable containers
                        for si in stretchable_indices:
                            if si != i and freed != 0:
                                current_sizes[si] = max(50, current_sizes[si] + freed)
                                self._desired_sizes[si] = current_sizes[si]
                                break
                    else:
                        if is_stretchable_container:
                            min_h = max(current_sizes[i], 100)
                            w.setMinimumHeight(min_h)
                            w.setMaximumHeight(16777215)
                            desired = max(current_sizes[i], min_h + 50)
                            current_sizes[i] = desired
                            self._desired_sizes[i] = desired
                        else:
                            # Non-stretchable: expand, total grows beyond viewport
                            if obj_name == 'planningParamsCollapsibleButton':
                                target_h = self._measure_content_height(w)
                            else:
                                sh = w.sizeHint
                                target_h = self._qt_val(sh, 'height') if sh else 150
                            w.setMinimumHeight(target_h)
                            w.setMaximumHeight(target_h)
                            current_sizes[i] = target_h
                            self._desired_sizes[i] = target_h
                            # Redistribute from stretchable only if total exceeds viewport
                            # (viewport resizer handles the scrollbar)
                    break

            splitter.setSizes(current_sizes)
            self._updateSplitterMinHeight()
            splitter.updateGeometry()
            splitter.update()
        except Exception as e:
            print(f"[SPLITTER DEBUG] toggle ERROR: {e}")

    def _count_visible_widgets(self, parent_widget):
        """Count the number of visible child widgets in a parent widget.

        Args:
            parent_widget: Parent widget to count children in.

        Returns:
            int: Number of visible child widgets.
        """
        try:
            count = 0
            # Count direct children in layout if exists
            layout = parent_widget.layout()
            if layout:
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    if item and item.widget():
                        child = item.widget()
                        # Count visible widgets (excluding hidden ones)
                        if child.isVisibleTo(parent_widget):
                            count += 1
                            # If child is a collapsible button, count its children too
                            if hasattr(child, 'objectName'):
                                child_name = child.objectName
                                if 'CollapsibleButton' in child_name or 'collapsibleButton' in child_name:
                                    count += self._count_visible_widgets(child)
            return max(count, 3)  # Return at least 3 to ensure minimum height
        except Exception:
            return 5  # Default to 5 if counting fails

    def _fix_all_collapsible_buttons_layout(self):
        """Fix internal layout of all collapsible buttons.

        All internal controls should have fixed height (20px) except text browsers
        which should be stretchable. Collapsible buttons themselves can expand.
        """
        try:
            # Define all collapsible buttons and their stretchable children
            # Include nested collapsible buttons inside planningParamsCollapsibleButton
            collapsible_configs = [
                ("segmentationCollapsibleButton", []),
                ("planningParamsCollapsibleButton", []),
                ("seedInfoCollapsibleButton", []),
                ("refDirecCollapsibleButton", []),
                ("radiationParamsCollapsibleButton", []),
                ("doseConstraintsCollapsibleButton", []),
                ("rlParamsCollapsibleButton", []),
                ("doseVisualizationCollapsibleButton", ["dvhMetricsBrowser"]),
                ("CollapsibleButton", ["statusTextBrowser"]),
            ]

            for button_name, stretchable_children in collapsible_configs:
                try:
                    button = getattr(self.ui, button_name, None)
                    if not button:
                        continue

                    self._fix_collapsible_button_internal_layout(
                        button, stretchable_children
                    )
                except Exception as e:
                    pass

        except Exception as e:
            self.addLog(f"DEBUG ERROR in _fix_all_collapsible_buttons_layout: {str(e)}")

    def _fix_collapsible_button_internal_layout(self, button, stretchable_children=None):
        """Fix internal layout of a single collapsible button.

        Args:
            button: The collapsible button widget
            stretchable_children: List of child widget names that should be stretchable
        """
        if stretchable_children is None:
            stretchable_children = []

        try:
            if not button:
                return

            inner_layout = button.layout()
            if not inner_layout:
                return

            # For segmentation and planningParams, set minimal spacing and fixed layout
            button_name = button.objectName if hasattr(button, 'objectName') else ''
            is_compact_mode = button_name in [
                'segmentationCollapsibleButton', 'planningParamsCollapsibleButton',
                'seedInfoCollapsibleButton', 'refDirecCollapsibleButton',
                'radiationParamsCollapsibleButton', 'doseConstraintsCollapsibleButton',
                'rlParamsCollapsibleButton',
            ]
            
            if is_compact_mode:
                # Set minimal spacing for compact mode
                self._set_minimal_spacing(inner_layout)

            # Recursively process all widgets inside the collapsible button
            self._process_collapsible_children(button, stretchable_children, is_compact_mode)

            button.updateGeometry()
        except Exception:
            pass
    
    def _set_minimal_spacing(self, layout):
        """Set minimal spacing for a layout and all its sub-layouts.

        Args:
            layout: The layout to set minimal spacing on.
        """
        try:
            if not layout:
                return
            # Set minimal spacing
            layout.setSpacing(0)
            if hasattr(layout, 'setVerticalSpacing'):
                layout.setVerticalSpacing(0)
            if hasattr(layout, 'setHorizontalSpacing'):
                layout.setHorizontalSpacing(2)
            layout.setContentsMargins(1, 0, 1, 0)

            # Recursively process sub-layouts
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.layout():
                    self._set_minimal_spacing(item.layout())
        except Exception:
            pass

    def _process_collapsible_children(self, parent_widget, stretchable_children, compact_mode=False):
        """Recursively process widgets inside a collapsible button.

        Args:
            parent_widget: Parent widget to process
            stretchable_children: List of widget names that should be stretchable
            compact_mode: If True, use minimal spacing and fixed heights
        """
        try:
            # Widget types that should have fixed height
            fixed_height_types = (
                qt.QLabel, qt.QSpinBox, qt.QDoubleSpinBox,
                qt.QComboBox, qt.QPushButton, qt.QCheckBox, qt.QSlider,
                qt.QLineEdit, qt.QGroupBox
            )

            # Widget types that should be stretchable
            stretchable_types = (
                qt.QTextBrowser, qt.QTextEdit, qt.QPlainTextEdit,
                qt.QListWidget, qt.QTableWidget, qt.QTreeWidget
            )

            children = parent_widget.findChildren(qt.QWidget)
            for child in children:
                try:
                    obj_name = child.objectName if hasattr(child, 'objectName') else ''

                    # Check if this child should be stretchable
                    is_stretchable = (
                        obj_name in stretchable_children or
                        isinstance(child, stretchable_types)
                    )

                    if is_stretchable:
                        # Let text browsers expand with larger default height
                        child.setMinimumHeight(100)
                        child.setMaximumHeight(16777215)
                    elif isinstance(child, fixed_height_types):
                        # Set minimum height for standard controls and prevent shrinking too much
                        if compact_mode:
                            # Use an explicitly taller minimum height (20px) so text never squishes flat
                            child.setMinimumHeight(20)
                        else:
                            child.setMinimumHeight(20)
                        # Set vertical policy to Fixed to absolutely prevent Qt from compressing the widget height
                        size_policy = qt.QSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
                        size_policy.setRetainSizeWhenHidden(True)
                        child.setSizePolicy(size_policy)

                        # Set alignment: horizontal left, vertical center
                        if hasattr(child, 'setAlignment'):
                            from qt import Qt
                            child.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

                    child.updateGeometry()
                except Exception:
                    pass

        except Exception:
            pass

    def _measure_content_height(self, widget):
        """Measure the exact content height of a widget based on its layout children.

        Sums sizeHint().height() of all visible children plus layout spacing and margins.
        This gives the precise height the widget needs — no more, no less.
        """
        try:
            layout = widget.layout()
            if not layout:
                return widget.sizeHint.height() if hasattr(widget, 'sizeHint') else 100

            total = 0
            visible_count = 0
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item:
                    child_w = item.widget()
                    if child_w and child_w.visible:
                        total += child_w.sizeHint.height() if hasattr(child_w, 'sizeHint') else 20
                        visible_count += 1
                    elif item.layout():
                        # Nested layout — measure its widgets
                        sub_layout = item.layout()
                        for j in range(sub_layout.count()):
                            sub_item = sub_layout.itemAt(j)
                            if sub_item and sub_item.widget() and sub_item.widget().visible:
                                sw = sub_item.widget()
                                total += sw.sizeHint.height() if hasattr(sw, 'sizeHint') else 20
                                visible_count += 1

            if visible_count > 1:
                spacing = layout.spacing()
                if hasattr(layout, 'verticalSpacing'):
                    vs = layout.verticalSpacing()
                    if vs >= 0:
                        spacing = vs
                total += spacing * (visible_count - 1)

            margins = layout.contentsMargins()
            total += margins.top() + margins.bottom()

            return max(total, 30)
        except Exception:
            return widget.sizeHint.height() if hasattr(widget, 'sizeHint') else 200

    def _apply_planning_params_height(self):
        """Measure and set planningParams height to exactly fit its content."""
        try:
            pp = getattr(self.ui, 'planningParamsCollapsibleButton', None)
            if not pp or not self._mainSplitter:
                return
            h = self._measure_content_height(pp)
            pp.setMinimumHeight(h)
            pp.setMaximumHeight(h)
            # Update splitter size to match
            sizes = list(self._mainSplitter.sizes())
            for i in range(self._mainSplitter.count()):
                w = self._mainSplitter.widget(i)
                if w and w.objectName == 'planningParamsCollapsibleButton':
                    if i < len(sizes):
                        sizes[i] = h
                    break
            self._mainSplitter.setSizes(sizes)
            self._desired_sizes = list(sizes)
            self._updateSplitterMinHeight()
        except Exception:
            pass

    @staticmethod
    def _qt_val(obj, attr):
        """Safely get an int from a PyQt object attribute.

        In Slicer's PyQt, some QWidget/QSplitter attributes are slots
        that return ints when called, while others are already ints.
        This helper handles both cases.
        """
        v = getattr(obj, attr)
        if isinstance(v, int):
            return v
        if callable(v):
            return v()
        # Slot descriptor — try calling via class
        cls_v = getattr(type(obj), attr)
        if callable(cls_v):
            return cls_v(obj)
        raise TypeError(f"Cannot get int from {type(obj).__name__}.{attr} = {v!r}")

    def _updateSplitterMinHeight(self):
        """Update container size so scrollbar appears when content exceeds viewport.

        Computes the TOTAL content height by summing all children's heights
        (using the larger of minimumHeight and desired size for each).
        When this total exceeds the viewport height, the container grows
        beyond the viewport and the scroll area shows a scrollbar.
        """
        try:
            if not self._mainSplitter:
                return
            sp = self._mainSplitter
            desired = getattr(self, '_desired_sizes', [])
            total = 0
            n = self._qt_val(sp, 'count')
            hw = self._qt_val(sp, 'handleWidth')
            for i in range(n):
                w = sp.widget(i)
                if w:
                    min_h = self._qt_val(w, 'minimumHeight')
                    des_h = desired[i] if i < len(desired) else 0
                    total += max(min_h, des_h)
            total += hw * max(0, n - 1)
            self._splitter_content_height = total

            if hasattr(self, '_container') and self._container:
                self._container.setMinimumHeight(total)
                vp_h = 0
                vp_w = self._qt_val(self._container, 'width')
                if hasattr(self, '_mainScrollArea') and self._mainScrollArea:
                    vp = self._mainScrollArea.viewport()
                    vp_h = self._qt_val(vp, 'height')
                    vp_w = self._qt_val(vp, 'width')
                h = max(total, vp_h) if vp_h > 0 else total
                self._container.resize(vp_w, h)
                print(f"[SPLITTER DEBUG] total={total}, vp={vp_w}x{vp_h}, container={vp_w}x{h}, desired={desired}")
        except Exception as e:
            print(f"[SPLITTER DEBUG] _updateSplitterMinHeight ERROR: {e}")

    def _fix_dose_viz_internal_layout(self):
        """Fix internal layout of Dose Visualization collapsible button (legacy)."""
        # Now handled by _fix_all_collapsible_buttons_layout
        pass

    def _fix_status_internal_layout(self):
        """Fix internal layout of Status collapsible button (legacy)."""
        # Now handled by _fix_all_collapsible_buttons_layout
        pass

    def _fix_all_layouts_spacing(self, parent_widget):
        """Set fixed spacing for all layouts to prevent vertical stretching.

        Skips layouts inside compact-mode collapsible buttons (Planning Parameters
        and its sub-sections, Segmentation) to preserve their tighter spacing.

        Args:
            parent_widget: The parent widget to start recursion from.
        """
        try:
            # Collect compact-mode collapsible button widgets — their layouts
            # were already set to spacing=0 by _set_minimal_spacing and must
            # not be overridden here.
            compact_names = {
                'segmentationCollapsibleButton', 'planningParamsCollapsibleButton',
                'seedInfoCollapsibleButton', 'refDirecCollapsibleButton',
                'radiationParamsCollapsibleButton', 'doseConstraintsCollapsibleButton',
                'rlParamsCollapsibleButton',
            }
            compact_widgets = set()
            for name in compact_names:
                w = getattr(self.ui, name, None)
                if w:
                    compact_widgets.add(w)

            def _is_inside_compact(layout):
                """Check if a layout belongs to a compact-mode collapsible button."""
                try:
                    widget = layout.parentWidget()
                    while widget:
                        if widget in compact_widgets:
                            return True
                        widget = widget.parentWidget()
                except Exception:
                    pass
                return False

            # Find all layouts recursively
            layouts = parent_widget.findChildren(qt.QLayout)
            for layout in layouts:
                try:
                    if _is_inside_compact(layout):
                        continue
                    # Set fixed spacing between widgets (no vertical stretch)
                    layout.setSpacing(1)
                    if hasattr(layout, 'setVerticalSpacing'):
                        layout.setVerticalSpacing(1)
                    if hasattr(layout, 'setHorizontalSpacing'):
                        layout.setHorizontalSpacing(4)
                    # Set fixed margins (left, top, right, bottom) - minimal margins
                    layout.setContentsMargins(2, 1, 2, 1)
                except Exception:
                    pass
        except Exception:
            pass

    def _unify_widget_heights(self, parent_widget, base_height=22):
        """Recursively unify heights of all widgets except text browsers.

        Sets a consistent base height for labels, spin boxes, combo boxes,
        buttons, checkboxes, and sliders. Text browsers and similar multi-line
        widgets are excluded and can expand.

        Widgets inside compact-mode collapsible buttons use Fixed vertical
        policy so they never stretch to fill extra space.

        Args:
            parent_widget: The parent widget to start recursion from.
            base_height: The target height for standard widgets (default 20px).
        """
        try:
            # Widget types that should have unified fixed height
            fixed_height_types = (
                qt.QLabel, qt.QSpinBox, qt.QDoubleSpinBox,
                qt.QComboBox, qt.QPushButton, qt.QCheckBox, qt.QSlider
            )

            # Widget types that should be stretchable (not fixed height)
            stretchable_types = (
                qt.QTextBrowser, qt.QTextEdit, qt.QPlainTextEdit,
                qt.QListWidget, qt.QTableWidget, qt.QTreeWidget
            )

            # Widget names that should be excluded from height unification
            excluded_names = {
                'dvhMetricsBrowser', 'statusTextBrowser',
                'treeView', 'mainSplitter',
                'segmentationCollapsibleButton', 'planningParamsCollapsibleButton',
                'seedInfoCollapsibleButton', 'refDirecCollapsibleButton',
                'radiationParamsCollapsibleButton', 'doseConstraintsCollapsibleButton',
                'rlParamsCollapsibleButton',
                'doseVisualizationCollapsibleButton', 'CollapsibleButton',
            }

            # Collect compact-mode widgets to determine Fixed vs Minimum policy
            compact_names = {
                'segmentationCollapsibleButton', 'planningParamsCollapsibleButton',
                'seedInfoCollapsibleButton', 'refDirecCollapsibleButton',
                'radiationParamsCollapsibleButton', 'doseConstraintsCollapsibleButton',
                'rlParamsCollapsibleButton',
            }
            compact_widgets = set()
            for name in compact_names:
                cw = getattr(self.ui, name, None)
                if cw:
                    compact_widgets.add(cw)

            def _is_inside_compact(widget):
                """Check if widget is a descendant of a compact-mode collapsible button."""
                try:
                    p = widget.parentWidget()
                    while p:
                        if p in compact_widgets:
                            return True
                        p = p.parentWidget()
                except Exception:
                    pass
                return False

            def process_widget(w):
                if w is None:
                    return

                obj_name = w.objectName if hasattr(w, 'objectName') else ''

                # Skip excluded widgets
                if obj_name in excluded_names:
                    return

                # Check if widget is a stretchable type
                is_stretchable = isinstance(w, stretchable_types)

                # Check if widget should have fixed height
                is_fixed_type = isinstance(w, fixed_height_types)

                if is_stretchable:
                    # Allow text browsers to expand
                    try:
                        w.setMinimumHeight(base_height)
                        w.setMaximumHeight(16777215)
                        w.updateGeometry()
                    except Exception:
                        pass
                elif is_fixed_type:
                    try:
                        w.setMinimumHeight(base_height)
                        if _is_inside_compact(w):
                            # Compact mode: Fixed policy prevents vertical stretching
                            size_policy = qt.QSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
                        else:
                            # Normal mode: Minimum policy allows proportional shrinking
                            size_policy = qt.QSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)
                        size_policy.setRetainSizeWhenHidden(True)
                        w.setSizePolicy(size_policy)
                        w.updateGeometry()
                    except Exception:
                        pass

                # Recursively process children
                try:
                    children = w.findChildren(qt.QWidget)
                    for child in children:
                        process_widget(child)
                except Exception:
                    pass

            process_widget(parent_widget)

        except Exception:
            pass

    def overlay_dose_on_ct(self, ct_node, dose_node, opacity=0.5):
        """Overlay the dose volume on the CT image in all slice views.

        Sets the CT as the background layer and the dose map as the
        foreground layer with the specified opacity, enabling fused
        visualization without hiding the CT.

        Args:
            ct_node: CT volume node to display as background.
            dose_node: Dose volume node to display as foreground overlay.
            opacity: Foreground opacity (0.0 to 1.0). Defaults to 0.5.
        """
        try:
            self._last_dose_node = dose_node
            self._last_ct_node = ct_node

            layoutManager = slicer.app.layoutManager()
            if not layoutManager:
                return

            for name in layoutManager.sliceViewNames():
                sliceWidget = layoutManager.sliceWidget(name)
                compositeNode = sliceWidget.mrmlSliceCompositeNode()
                compositeNode.SetBackgroundVolumeID(ct_node.GetID())
                compositeNode.SetForegroundVolumeID(dose_node.GetID())
                compositeNode.SetForegroundOpacity(opacity)

            self.ui.doseOpacitySlider.setValue(int(opacity * 100))
            self.ui.doseOpacityValueLabel.setText(f"{int(opacity * 100)}%")
        except Exception as e:
            self.addLog(f"Error overlaying dose on CT: {str(e)}", level="error")

    def _show_dose_legend(self, dose_node):
        """Ensure the color legend for the dose volume is visible in all views.

        Must be called AFTER overlay_dose_on_ct, because setting the foreground
        volume triggers a slice view rebuild that resets legend visibility.

        Args:
            dose_node: The dose volume node whose legend should be shown.
        """
        try:
            displayNode = dose_node.GetDisplayNode()
            colorLegendDisplayNode = None
            if displayNode and hasattr(displayNode, 'GetColorLegendDisplayNode'):
                colorLegendDisplayNode = displayNode.GetColorLegendDisplayNode()
            if colorLegendDisplayNode is None:
                colorLegendDisplayNode = slicer.modules.colors.logic().AddDefaultColorLegendDisplayNode(dose_node)
            if colorLegendDisplayNode:
                colorLegendDisplayNode.SetTitleText("Dose (Gy)")
                colorLegendDisplayNode.SetVisibility(True)
                colorLegendDisplayNode.SetVisibility2D(True)
                colorLegendDisplayNode.SetVisibility3D(True)
                # Trigger MRML observation to force displayable manager update
                colorLegendDisplayNode.Modified()
                slicer.app.processEvents()
                layoutManager = slicer.app.layoutManager()
                if layoutManager:
                    for sliceName in layoutManager.sliceViewNames():
                        layoutManager.sliceWidget(sliceName).sliceView().forceRender()
                    for viewIndex in range(layoutManager.threeDViewCount):
                        layoutManager.threeDWidget(viewIndex).threeDView().forceRender()
        except Exception as e:
            self.addLog(f"Error showing dose legend: {str(e)}", level="warning")

    def onDoseOpacityChanged(self, value):
        """Handle dose opacity slider value changes.

        Updates the foreground opacity in all slice views and the
        percentage label.

        Args:
            value: Slider value (0-100).
        """
        try:
            opacity = value / 100.0
            self.ui.doseOpacityValueLabel.setText(f"{value}%")

            if self._last_dose_node is None:
                return

            layoutManager = slicer.app.layoutManager()
            if not layoutManager:
                return

            for name in layoutManager.sliceViewNames():
                sliceWidget = layoutManager.sliceWidget(name)
                compositeNode = sliceWidget.mrmlSliceCompositeNode()
                if compositeNode.GetForegroundVolumeID() == self._last_dose_node.GetID():
                    compositeNode.SetForegroundOpacity(opacity)
        except Exception:
            pass

    def compute_and_save_dvh(self, ct_node, dose_node):
        """Compute DVH for all structures and save results to the data tree.

        Creates table nodes and plot series nodes in the MRML scene for
        each structure found. Results are organized under a DVH folder
        in the subject hierarchy. The plot is automatically shown.

        Args:
            ct_node: CT volume node (reference for geometry).
            dose_node: Dose volume node.
        """
        try:
            self.addLog("Computing DVH analysis...")
            slicer.app.processEvents()

            prescription_dose = self.ui.inLowestEnergySpinBox.value
            dose_array = slicer.util.arrayFromVolume(dose_node).astype(np.float64)  # Already in Gy units
            slicer.app.processEvents()
            
            dose_min_val = float(np.min(dose_array))
            dose_max_val = float(np.max(dose_array))
            dose_mean_val = float(np.mean(dose_array))
            self.addLog(
                f"Dose range: [{dose_min_val:.2f}, {dose_max_val:.2f}] Gy, "
                f"mean={dose_mean_val:.2f} Gy, Rx={prescription_dose:.1f} Gy, "
                f"shape={dose_array.shape}"
            )
            slicer.app.processEvents()

            structures = self._get_dvh_structures(dose_node, ct_node, dose_array)
            if not structures:
                self.addLog("No structures found for DVH analysis.", level="warning")
                return
            slicer.app.processEvents()

            # Structure dose info logging removed for cleaner output

            dvh_data = self.calculate_dvh(dose_array, structures, prescription_dose)
            del structures
            slicer.app.processEvents()

            self._save_dvh_to_scene(dvh_data, dose_node, prescription_dose)
            del dose_array
            slicer.app.processEvents()
            self.addLog("DVH calculation completed.", level="success")
        except Exception as e:
            self.addLog(f"Error computing DVH: {str(e)}", level="error")

    def _get_dvh_structures(self, dose_node, ct_node, dose_array):
        """Extract structure masks from the scene for DVH analysis.

        Args:
            dose_node: Dose volume node (reference for geometry).
            ct_node: CT volume node (reference for geometry).
            dose_array: Cached numpy array of dose values to avoid redundant reads.

        Returns:
            dict: Mapping of structure name to binary mask array.
        """
        structures = {}
        dose_shape = dose_array.shape

        seg_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode")
        try:
            for i in range(seg_nodes.GetNumberOfItems()):
                seg_node = seg_nodes.GetItemAsObject(i)
                if seg_node is None:
                    continue
                segment_ids = vtk.vtkStringArray()
                seg_node.GetSegmentation().GetSegmentIDs(segment_ids)
                for j in range(segment_ids.GetNumberOfValues()):
                    seg_id = segment_ids.GetValue(j)
                    segment = seg_node.GetSegmentation().GetSegment(seg_id)
                    seg_name = segment.GetName()
                    label_map = None
                    export_ids = None
                    try:
                        label_map = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                        label_map.SetName(f"_dvh_temp_{seg_name}")
                        export_ids = vtk.vtkStringArray()
                        export_ids.InsertNextValue(seg_id)
                        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                            seg_node, export_ids, label_map, ct_node
                        )
                        mask_array = slicer.util.arrayFromVolume(label_map)
                        if mask_array.shape == dose_shape:
                            structures[seg_name] = (mask_array > 0).astype(np.uint8)
                    except Exception:
                        pass
                    finally:
                        if label_map is not None:
                            slicer.mrmlScene.RemoveNode(label_map)
                    # Process events periodically to prevent UI freeze
                    if j % 5 == 0:
                        slicer.app.processEvents()
        finally:
            seg_nodes.UnRegister(None)

        label_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLLabelMapVolumeNode")
        try:
            for i in range(label_nodes.GetNumberOfItems()):
                label_node = label_nodes.GetItemAsObject(i)
                if label_node is None or "_dvh_temp_" in (label_node.GetName() or ""):
                    continue
                name = label_node.GetName()
                if name not in structures:
                    try:
                        mask_array = slicer.util.arrayFromVolume(label_node)
                        if mask_array.shape == dose_shape:
                            unique_labels = np.unique(mask_array)
                            for label_val in unique_labels:
                                if label_val == 0:
                                    continue
                                struct_name = f"{name}_label{label_val}" if len(unique_labels) > 2 else name
                                structures[struct_name] = (mask_array == label_val).astype(np.uint8)
                    except Exception:
                        pass
                # Process events periodically to prevent UI freeze
                if i % 5 == 0:
                    slicer.app.processEvents()
        finally:
            label_nodes.UnRegister(None)

        return structures

    @staticmethod
    def calculate_dvh(dose_array, structures, prescription_dose, num_bins=300):
        """Calculate cumulative DVH, differential DVH and dose metrics.

        Args:
            dose_array: 3D numpy array of dose values in Gy.
            structures: Dict mapping structure name to binary mask array.
            prescription_dose: Prescription dose in Gy.
            num_bins: Number of bins for DVH histogram.

        Returns:
            dict: DVH data per structure with cumulative_dvh, differential_dvh,
                  metrics, and name.
        """
        dvh_data = {}
        dose_max = float(np.max(dose_array))
        if dose_max <= 0:
            return dvh_data

        # Use full dose range for DVH calculation to preserve all data
        # Display range will be limited separately for initial view
        dose_max_full = float(np.max(dose_array)) * 1.1  # Include all dose data
        
        # For metrics calculation, use sufficient range
        dose_max_for_bins = max(prescription_dose * 3.0, 250.0, dose_max_full)
        
        dose_bins = np.linspace(0, dose_max_for_bins, num_bins + 1)
        dose_centers = (dose_bins[:-1] + dose_bins[1:]) / 2.0
        bin_width = dose_bins[1] - dose_bins[0]

        # Process events periodically to prevent UI freeze
        structure_count = len(structures)
        for idx, (name, mask) in enumerate(structures.items()):
            # Update UI every few structures to prevent freezing
            if idx % 2 == 0:
                slicer.app.processEvents()
            
            structure_mask = mask > 0
            total_voxels = float(np.sum(structure_mask))
            if total_voxels == 0:
                continue

            structure_doses = dose_array[structure_mask]

            # Calculate cDVH directly from sorted doses for accuracy
            # This ensures V100 and other metrics match exactly
            sorted_doses = np.sort(structure_doses)[::-1]  # Descending order
            n = len(sorted_doses)
            
            # Create dose points for cDVH curve with adaptive binning
            # Use full dose range to preserve all data
            dose_max_plot = max(np.max(structure_doses) * 1.1, prescription_dose * 3.0)
            
            # Adaptive binning: keep 1.0 Gy bins for low dose range (<1000 Gy)
            # For high dose range (>1000 Gy), use larger bins to prevent performance issues
            high_dose_threshold = 1000.0  # Threshold for adaptive binning
            
            if dose_max_plot <= high_dose_threshold:
                # Normal range: use 1.0 Gy bins
                dose_bins_plot = np.arange(0, dose_max_plot + 1.0, 1.0)
            else:
                # High dose range: use 1.0 Gy bins up to 1000 Gy, then larger bins
                # Calculate adaptive bin size for high dose region
                high_dose_range = dose_max_plot - high_dose_threshold
                # Target ~500 bins for high dose region to keep total bins reasonable
                high_dose_bin_size = max(high_dose_range / 500, 10.0)  # At least 10 Gy bins
                # Round to reasonable number (10, 20, 50, 100)
                if high_dose_bin_size <= 10:
                    high_dose_bin_size = 10
                elif high_dose_bin_size <= 20:
                    high_dose_bin_size = 20
                elif high_dose_bin_size <= 50:
                    high_dose_bin_size = 50
                else:
                    high_dose_bin_size = 100
                
                # Create bins: 1.0 Gy steps up to 1000 Gy, then adaptive steps
                low_dose_bins = np.arange(0, high_dose_threshold + 1.0, 1.0)
                high_dose_bins = np.arange(high_dose_threshold + high_dose_bin_size, 
                                           dose_max_plot + high_dose_bin_size, 
                                           high_dose_bin_size)
                dose_bins_plot = np.concatenate([low_dose_bins, high_dose_bins])
            
            # Calculate cumulative percentage at each dose value
            cumulative_pct_plot = []
            for i, dose_val in enumerate(dose_bins_plot):
                # Process events periodically during long calculations
                if i % 100 == 0:
                    slicer.app.processEvents()
                pct = np.sum(structure_doses >= dose_val) / total_voxels * 100.0
                cumulative_pct_plot.append(pct)
            cumulative_pct_plot = np.array(cumulative_pct_plot)
            
            # Calculate differential DVH using the same dose_bins_plot
            # Use np.histogram with the custom bins
            # Note: np.histogram returns hist array with length len(bins)-1
            hist, bin_edges = np.histogram(structure_doses, bins=dose_bins_plot)
            # Use bin centers for differential DVH x-axis (excluding the last bin edge)
            dose_bins_diff = bin_edges[:-1]  # Remove last edge to match hist length
            differential_pct_plot = (hist / total_voxels) * 100.0

            def dose_at_volume(volume_pct):
                idx = min(int(n * volume_pct / 100.0), n - 1)
                return float(sorted_doses[idx])

            def volume_at_dose(dose_threshold):
                return float(np.sum(structure_doses >= dose_threshold) / total_voxels * 100.0)

            d_max = float(np.max(structure_doses))
            d_mean = float(np.mean(structure_doses))
            d_min = float(np.min(structure_doses))
            d98 = dose_at_volume(98)
            d95 = dose_at_volume(95)
            d90 = dose_at_volume(90)
            d50 = dose_at_volume(50)
            d2 = dose_at_volume(2)

            v100 = volume_at_dose(prescription_dose)
            v150 = volume_at_dose(prescription_dose * 1.5)
            v200 = volume_at_dose(prescription_dose * 2.0)
            v50 = volume_at_dose(prescription_dose * 0.5)

            ci = (v100 / 100.0) ** 2 if v100 > 0 else 0.0
            hi_n = (d2 - d98) / prescription_dose if prescription_dose > 0 else 0.0
            hi = (d_max - prescription_dose) / prescription_dose if prescription_dose > 0 else 0.0
            cov = v100 / 100.0
            gi = v50 / v100 if v100 > 0 else 0.0

            metrics = {
                "Dmax": d_max, "Dmin": d_min, "Dmean": d_mean,
                "D98": d98, "D95": d95, "D90": d90, "D50": d50, "D2": d2,
                "V100": v100, "V150": v150, "V200": v200,
                "CI": ci, "HI": hi, "HI_n": hi_n, "COV": cov, "GI": gi,
            }

            dvh_data[name] = {
                "cumulative_dvh": (dose_bins_plot, cumulative_pct_plot),
                "differential_dvh": (dose_bins_diff, differential_pct_plot),
                "metrics": metrics,
                "name": name,
            }

        return dvh_data
    def _save_dvh_to_scene(self, dvh_data, dose_node, prescription_dose):
        """Save DVH results as MRML nodes in the data tree.

        Creates table nodes and plot series nodes for each structure.
        Generates three charts: Cumulative DVH, Differential DVH, and
        Dose Metrics bar chart. All are organized under a DVH subject
        hierarchy folder.

        Args:
            dvh_data: Dict of DVH data per structure.
            dose_node: Dose volume node for hierarchy placement.
            prescription_dose: Prescription dose in Gy.
        """
        DVH_COLORS = [
            (0.89, 0.10, 0.10), (0.22, 0.49, 0.72), (0.30, 0.69, 0.31),
            (0.60, 0.31, 0.64), (1.00, 0.49, 0.00), (0.00, 0.75, 0.75),
            (0.85, 0.65, 0.13), (0.55, 0.34, 0.29), (0.47, 0.67, 0.94),
            (0.80, 0.52, 0.25),
        ]

        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        doseItemID = shNode.GetItemByDataNode(dose_node) if dose_node else 0

        nodes_to_remove = []
        for node_class in ["vtkMRMLPlotChartNode", "vtkMRMLPlotSeriesNode", "vtkMRMLTableNode"]:
            collection = slicer.mrmlScene.GetNodesByClass(node_class)
            try:
                for i in range(collection.GetNumberOfItems()):
                    node = collection.GetItemAsObject(i)
                    if node and node.GetName() and node.GetName().startswith("DVH"):
                        nodes_to_remove.append(node)
            finally:
                collection.UnRegister(None)
        for node in nodes_to_remove:
            slicer.mrmlScene.RemoveNode(node)

        dvhFolderId = shNode.CreateFolderItem(shNode.GetSceneItemID(), "DVH Analysis")
        if doseItemID:
            shNode.SetItemParent(dvhFolderId, shNode.GetItemParent(doseItemID))

        def _apply_chart_style(chart, title, x_title, y_title):
            """Apply consistent professional styling to a plot chart node.

            Args:
                chart: vtkMRMLPlotChartNode to style.
                title: Chart title string.
                x_title: X-axis label.
                y_title: Y-axis label.
            """
            chart.SetTitle(title)
            chart.SetXAxisTitle(x_title)
            chart.SetYAxisTitle(y_title)
            chart.SetLegendVisibility(True)
            chart.SetTitleFontSize(16)
            chart.SetAxisTitleFontSize(13)
            chart.SetAxisLabelFontSize(11)
            chart.SetLegendFontSize(10)
            # Set default axis ranges: X 0-600 Gy, Y 0-100%
            # Disable auto-scale to ensure fixed range
            chart.SetXAxisRangeAuto(False)
            chart.SetYAxisRangeAuto(False)
            chart.SetXAxisRange(0, 600)
            chart.SetYAxisRange(0, 100)

        def _make_series(name_suffix, dose_arr, vol_arr, color, line_width=2, plot_type=None):
            """Create a plot series node and its associated table node.

            Args:
                name_suffix: Suffix for node names.
                dose_arr: vtkFloatArray for x-axis data.
                vol_arr: vtkFloatArray for y-axis data.
                color: RGB tuple for the series color.
                line_width: Line width for the series.
                plot_type: Plot type enum (defaults to Line).

            Returns:
                tuple: (series_node, table_node)
            """
            # Create table node for series data
            table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"DVH_Table_{name_suffix}")
            table_node.AddColumn(dose_arr)
            table_node.AddColumn(vol_arr)

            series_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", f"DVH_Series_{name_suffix}")
            series_node.SetAndObserveTableNodeID(table_node.GetID())
            series_node.SetXColumnName(dose_arr.GetName())
            series_node.SetYColumnName(vol_arr.GetName())
            if plot_type is not None:
                series_node.SetPlotType(plot_type)
            else:
                series_node.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeLine)
            series_node.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
            series_node.SetLineWidth(line_width)
            series_node.SetColor(color[0], color[1], color[2])

            return series_node, table_node

        # ---- Chart 1: Cumulative DVH ----
        cDVH_chart = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "DVH cDVH Chart")
        _apply_chart_style(cDVH_chart, "Cumulative Dose Volume Histogram", "Dose (Gy)", "Volume (%)")
        cDVH_chartItemId = shNode.CreateItem(dvhFolderId, cDVH_chart)

        # ---- Chart 2: Differential DVH ----
        dDVH_chart = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "DVH dDVH Chart")
        _apply_chart_style(dDVH_chart, "Differential Dose Volume Histogram", "Dose (Gy)", "Volume per bin (%)")
        dDVH_chartItemId = shNode.CreateItem(dvhFolderId, dDVH_chart)

        metrics_lines = [f"<b>Rx Dose = {prescription_dose:.1f} Gy</b><br>"]

        dose_metric_names = ["D98", "D95", "D90", "D50", "Dmean", "D2", "Dmax"]
        vol_metric_names = ["V100", "V150", "V200"]

        for idx, (name, data) in enumerate(dvh_data.items()):
            color = DVH_COLORS[idx % len(DVH_COLORS)]
            m = data["metrics"]
            
            is_first = idx == 0
            line_w = 3 if is_first else 2

            # --- cDVH series ---
            dose_centers_c, cumulative_pct = data["cumulative_dvh"]
            arr_dose_c = vtk.vtkFloatArray()
            arr_dose_c.SetName("Dose_Gy")
            arr_vol_c = vtk.vtkFloatArray()
            arr_vol_c.SetName("Volume_pct")
            for k in range(len(dose_centers_c)):
                arr_dose_c.InsertNextValue(float(dose_centers_c[k]))
                arr_vol_c.InsertNextValue(float(cumulative_pct[k]))
            c_series, c_table = _make_series(
                f"cDVH_{name}", arr_dose_c, arr_vol_c, color,
                line_width=line_w
            )
            c_series.SetName(name)
            c_series.SetMarkerSize(0)
            c_series.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
            cDVH_chart.AddAndObservePlotSeriesNodeID(c_series.GetID())
            shNode.CreateItem(cDVH_chartItemId, c_series)
            shNode.CreateItem(dvhFolderId, c_table)

            # --- dDVH series ---
            dose_centers_d, differential_pct = data["differential_dvh"]
            arr_dose_d = vtk.vtkFloatArray()
            arr_dose_d.SetName("Dose_Gy")
            arr_vol_d = vtk.vtkFloatArray()
            arr_vol_d.SetName("Volume_pct")
            for k in range(len(dose_centers_d)):
                arr_dose_d.InsertNextValue(float(dose_centers_d[k]))
                arr_vol_d.InsertNextValue(float(differential_pct[k]))
            d_series, d_table = _make_series(
                f"dDVH_{name}", arr_dose_d, arr_vol_d, color,
                line_width=line_w
            )
            d_series.SetName(name)
            d_series.SetMarkerSize(0)
            d_series.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
            dDVH_chart.AddAndObservePlotSeriesNodeID(d_series.GetID())
            shNode.CreateItem(dDVH_chartItemId, d_series)
            shNode.CreateItem(dvhFolderId, d_table)

            metrics_lines.append(
                f"<b style='color:rgb({int(color[0]*255)},{int(color[1]*255)},{int(color[2]*255)})'>{name}</b>: "
                f"Dmax={m['Dmax']:.1f} Dmean={m['Dmean']:.1f} D90={m['D90']:.1f} D50={m['D50']:.1f} | "
                f"V100={m['V100']:.1f}% V150={m['V150']:.1f}% V200={m['V200']:.1f}% | "
                f"CI={m['CI']:.3f} HI={m['HI']:.3f} HI_n={m['HI_n']:.3f} COV={m['COV']:.3f} GI={m['GI']:.3f}"
            )
            
            # Process events periodically to prevent UI freeze
            if idx % 3 == 0:
                slicer.app.processEvents()

        self.ui.dvhMetricsBrowser.setText("<br>".join(metrics_lines))

        try:
            # X-axis range is already set to 0-600 Gy in _apply_chart_style
            # This allows users to see the full dose range while defaulting to 0-600 Gy view
            # Users can manually zoom/pan to see doses beyond 600 Gy if needed
            
            if hasattr(slicer.modules, 'plots') and slicer.modules.plots is not None:
                plotsLogic = slicer.modules.plots.logic()
                if plotsLogic:
                    plotsLogic.ShowChartInLayout(cDVH_chart)
        except Exception:
            self.addLog("DVH plots saved to data tree. Click the eye icon to display.", level="warning")

        # Create a master DVH table with all segments
        try:
            master_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "DVH_MasterTable")
            shNode.CreateItem(dvhFolderId, master_table)
            
            # Add columns
            name_arr = vtk.vtkStringArray()
            name_arr.SetName("Structure")
            master_table.AddColumn(name_arr)
            
            all_metric_names = dose_metric_names + vol_metric_names + ["CI", "HI", "HI_n", "COV", "GI"]
            for metric_name in all_metric_names:
                arr = vtk.vtkFloatArray()
                arr.SetName(metric_name)
                master_table.AddColumn(arr)
            
            # Get the underlying vtkTable for direct column access
            table = master_table.GetTable()
            
            # Add rows for each structure
            for idx, (name, data) in enumerate(dvh_data.items()):
                m = data["metrics"]

                # Insert values into each column's array
                name_arr.InsertNextValue(name)

                col_idx = 0
                for metric_name in all_metric_names:
                    # Get column directly from vtkTable
                    col_array = table.GetColumn(col_idx + 1)
                    if col_array:
                        col_array.InsertNextValue(m.get(metric_name, 0.0))
                    col_idx += 1

            master_table.Modified()
        except Exception as e:
            self.addLog(f"Error creating DVH Master Table: {str(e)}", level="error")

    def onSegmentButton(self):
        """Run segmentation when the user clicks the Run Segmentation button."""
        # Show confirmation dialog before starting segmentation
        msgBox = qt.QMessageBox()
        msgBox.setWindowTitle("Confirm Segmentation")
        msgBox.setText("Are you sure you want to start the segmentation process?")
        msgBox.setInformativeText("This operation may take several minutes to complete.")
        msgBox.setStandardButtons(qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
        msgBox.setDefaultButton(qt.QMessageBox.Ok)
        msgBox.setIcon(qt.QMessageBox.Question)
        
        reply = msgBox.exec_()
        if reply != qt.QMessageBox.Ok:
            self.addLog("Segmentation cancelled by user.", level="info")
            return
        
        try:
            sequenceBrowserNode = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(
                self.ui.imageSelector.currentNode()
            )
            if sequenceBrowserNode:
                if not slicer.util.confirmYesNoDisplay(
                    "The input volume you provided are part of a sequence. Do you want to segment all frames of that sequence?"
                ):
                    sequenceBrowserNode = None

            input_image = self.ui.imageSelector.currentNode()
            output_segmentation = self.ui.outputSegmentationSelector.currentNode()

            if not input_image:
                self.addLog("Error: No input image selected.", level="error")
                return

            with slicer.util.tryWithErrorDisplay("Segmentation failed.", waitCursor=True):
                segTask = self.ui.SegTaskSelector.currentText
                fast_mode = self.ui.fastModeCheckBox.checked
                self.addLog(f"<b>Starting {segTask} segmentation...</b>")
                self.addLog(f"Fast mode: {fast_mode}")

                success = self.logic.run_segTask(input_image, output_segmentation, segTask, fast_mode)

                if success:
                    self.addLog("Segmentation completed successfully!", level="success")
                else:
                    self.addLog("Segmentation failed.", level="error")
        except Exception as e:
            self.addLog(f"Error in segmentation: {str(e)}", level="error")

    def onPlanButton(self):
        """Run brachytherapy planning when the user clicks the Plan button."""
        # Show confirmation dialog before starting planning
        msgBox = qt.QMessageBox()
        msgBox.setWindowTitle("Confirm Planning")
        msgBox.setText("Are you sure you want to start the planning process?")
        msgBox.setInformativeText("This operation may take several minutes to complete.")
        msgBox.setStandardButtons(qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
        msgBox.setDefaultButton(qt.QMessageBox.Ok)
        msgBox.setIcon(qt.QMessageBox.Question)
        
        reply = msgBox.exec_()
        if reply != qt.QMessageBox.Ok:
            self.addLog("Planning cancelled by user.", level="info")
            return
        
        try:
            with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
                params = self.getPlanningParameters()
                oar_nodes = self.ui.OARImageSelector.checkedNodes()
                result = self.logic.run_brachyPlan(
                    self.ui.imageSelector.currentNode(),
                    self.ui.CTVImageSelector.currentNode(),
                    oar_nodes if oar_nodes else None,
                    params
                )
                if result is not None:
                    dose_node = None
                    progressDialog = None
                    try:
                        if isinstance(result, tuple) and len(result) == 2:
                            dose_node, progressDialog = result
                        elif result:
                            dose_node = result

                        if dose_node is not None:
                            self.overlay_dose_on_ct(self.ui.imageSelector.currentNode(), dose_node, opacity=0.5)
                            self._show_dose_legend(dose_node)
                            self.compute_and_save_dvh(self.ui.imageSelector.currentNode(), dose_node)

                        # Hide reference direction arrow after planning
                        if self._ref_direc_arrow_node:
                            self._ref_direc_arrow_node.GetDisplayNode().SetVisibility(False)
                        if self._ref_direc_interaction_node:
                            self._ref_direc_interaction_node.GetDisplayNode().SetVisibility(False)
                    finally:
                        if progressDialog is not None:
                            try:
                                progressDialog.close()
                            except Exception:
                                pass
                else:
                    self.addLog("Planning returned no results or failed.", level="error")
        except Exception as e:
            self.addLog(f"Error in planning: {str(e)}", level="error")

    def setSlicerUIVisible(self):
        """Control the visibility of Slicer UI elements and ensure Module Selection is enabled."""
        try:
            slicer.app.settings().setValue("Modules/ModuleSelection", True)
            slicer.app.settings().sync()

            exemptToolbarNames = [
                "MainToolBar",
                "ViewToolBar",
                "ModuleSelectorToolBar",
                *self.toolbarNames,
            ]
            mainWindow = slicer.util.mainWindow()
            slicer.util.setDataProbeVisible(False)
            slicer.util.setMenuBarsVisible(False)
            slicer.util.setModuleHelpSectionVisible(True)
            slicer.util.setModulePanelTitleVisible(False)
            slicer.util.setPythonConsoleVisible(False)
            slicer.util.setApplicationLogoVisible(False)

            allToolbars = mainWindow.findChildren(qt.QToolBar)
            keepToolbars = []
            for toolbar in allToolbars:
                if toolbar.objectName in exemptToolbarNames:
                    keepToolbars.append(toolbar)

            try:
                moduleSelector = mainWindow.moduleSelector()
                if moduleSelector is not None:
                    moduleSelectorToolBar = moduleSelector.parent()
                    if moduleSelectorToolBar is not None and moduleSelectorToolBar not in keepToolbars:
                        keepToolbars.append(moduleSelectorToolBar)
            except Exception as e:
                logging.warning(f"Could not access module selector toolbar: {e}")
            slicer.util.setToolbarsVisible(False, keepToolbars)
        except Exception as e:
            self.addLog(f"Error setting Slicer UI visibility: {str(e)}", level="error")

    def modifyWindowUI(self):
        """Customize the application UI by initializing the settings toolbar."""
        self.initializeSettingsToolBar()

    def insertToolBar(self, beforeToolBarName, name, title=None):
        """Insert a new toolbar before the specified existing toolbar.

        Args:
            beforeToolBarName: Object name of the toolbar to insert before.
            name: Object name for the new toolbar.
            title: Display title for the new toolbar (defaults to name).

        Returns:
            qt.QToolBar: The newly created toolbar, or None on failure.
        """
        try:
            beforeToolBar = slicer.util.findChild(slicer.util.mainWindow(), beforeToolBarName)
            if title is None:
                title = name
            toolBar = qt.QToolBar(title)
            toolBar.name = name
            slicer.util.mainWindow().insertToolBar(beforeToolBar, toolBar)
            self._toolbars[name] = toolBar
            return toolBar
        except Exception as e:
            self.addLog(f"Error inserting toolbar: {str(e)}", level="error")
            return None

    def initializeSettingsToolBar(self):
        """Create the settings toolbar with a gear icon and settings dialog."""
        try:
            settingsToolBar = self.insertToolBar("MainToolBar", "SettingsToolBar", title="Settings")
            if settingsToolBar is None:
                return
            gearIcon = qt.QIcon(self.resourcePath("Icons/Gears.png"))
            self.settingsAction = settingsToolBar.addAction(gearIcon, "")

            self.settingsDialog = slicer.util.loadUI(self.resourcePath("UI/Settings.ui"))
            self.settingsUI = slicer.util.childWidgetVariables(self.settingsDialog)
            self.settingsUI.CustomUICheckBox.toggled.connect(self.setCustomUIVisible)
            self.settingsUI.CustomStyleCheckBox.toggled.connect(self.toggleStyle)
            self.settingsAction.triggered.connect(self.raiseSettings)
        except Exception as e:
            self.addLog(f"Error initializing settings toolbar: {str(e)}", level="error")

    def initializePlanningParameters(self):
        """Initialize all planning parameter UI controls from the config settings."""
        try:
            args = setting()

            self.ui.targetValueSpinBox.setValue(args.radiation_array_params["target_value"])
            self.ui.obstacleValueSpinBox.setValue(args.radiation_array_params["obstacle_value"])
            self.ui.backgroundValueSpinBox.setValue(args.radiation_array_params["background_value"])
            self.ui.backlitAngleSpinBox.setValue(args.radiation_array_params["backlit_angle"])
            self.ui.maxCandiTrajSpinBox.setValue(args.radiation_array_params["maximum_candidate_trajectories"])

            self.ui.seedRadiusSpinBox.setValue(args.seed_info["radius"])
            self.ui.seedLengthSpinBox.setValue(args.seed_info["length"])
            if "num_of_seeds" in args.seed_info:
                self.ui.seedCountMinSpinBox.setValue(args.seed_info["num_of_seeds"][0])
                self.ui.seedCountMaxSpinBox.setValue(args.seed_info["num_of_seeds"][1])
            if "seed_avr_dose" in args.seed_info:
                self.ui.seedDoseSpinBox.setValue(args.seed_info["seed_avr_dose"])

            self.ui.inLowestEnergySpinBox.setValue(args.in_lowest_energy * DOSE_SCALE_FACTOR)
            self.ui.outHighestEnergySpinBox.setValue(args.out_highest_energy * DOSE_SCALE_FACTOR)
            self.ui.dvhRateSpinBox.setValue(args.DVH_rate)
            self.ui.maxIterSpinBox.setValue(args.max_iter)

            self.ui.refDirecXSpinBox.setValue(args.reference_direc[0])
            self.ui.refDirecYSpinBox.setValue(args.reference_direc[1])
            self.ui.refDirecZSpinBox.setValue(args.reference_direc[2])

            self.ui.maxEpisodesSpinBox.setValue(args.rf_params["max_episodes"])
            self.ui.bandwidthSpinBox.setValue(args.rf_params["bandwidth"])
            self.ui.useReinforceLearningCheckBox.setChecked(args.use_rf)

            self._planning_params = self.getPlanningParametersFromUI()

            # Setup mutually exclusive collapsible buttons in planningParamsCollapsibleButton
            self._setup_exclusive_collapsible_buttons()

            # Set Dose Visualization collapsible button to collapsed by default
            dose_viz_btn = getattr(self.ui, 'doseVisualizationCollapsibleButton', None)
            if dose_viz_btn:
                dose_viz_btn.checked = False
        except Exception as e:
            self.addLog(f"Error initializing planning parameters: {str(e)}", level="error")

    def _setup_exclusive_collapsible_buttons(self):
        """Setup mutually exclusive collapsible buttons in planningParamsCollapsibleButton.

        When one sub-collapsible button is expanded, others at the same level
        will be collapsed automatically to save space.
        """
        try:
            # List of sub-collapsible buttons inside planningParamsCollapsibleButton
            sub_collapsible_buttons = [
                self.ui.seedInfoCollapsibleButton,
                self.ui.refDirecCollapsibleButton,
                self.ui.radiationParamsCollapsibleButton,
                self.ui.doseConstraintsCollapsibleButton,
                self.ui.rlParamsCollapsibleButton,
            ]

            def make_exclusive_handler(current_button, all_buttons):
                """Create a handler that collapses other buttons when current is expanded."""
                def handler():
                    # Check if current button is now expanded
                    if current_button.checked:
                        # Collapse all other buttons
                        for btn in all_buttons:
                            if btn is not current_button and btn.checked:
                                btn.checked = False
                return handler

            # Connect each button's toggled signal
            for btn in sub_collapsible_buttons:
                if btn:
                    btn.connect("contentsCollapsed(bool)", make_exclusive_handler(btn, sub_collapsible_buttons))

            # Connect all collapsible buttons to adjust splitter when expanded/collapsed
            all_collapsible_buttons = sub_collapsible_buttons + [
                getattr(self.ui, 'segmentationCollapsibleButton', None),
                getattr(self.ui, 'planningParamsCollapsibleButton', None),
                getattr(self.ui, 'doseVisualizationCollapsibleButton', None),
                getattr(self.ui, 'CollapsibleButton', None),
            ]
            
            # Sub-button names (nested inside planningParamsCollapsibleButton)
            _sub_btn_names = {b.objectName for b in sub_collapsible_buttons if b}

            for btn in all_collapsible_buttons:
                if btn and self._mainSplitter:
                    def make_resize_handler(button):
                        def handler(collapsed):
                            if not self._mainSplitter:
                                return
                            sizes = list(self._mainSplitter.sizes())
                            is_sub = button.objectName in _sub_btn_names

                            if is_sub:
                                # Sub-button inside planningParams — measure and adjust parent
                                pp_widget = getattr(self.ui, 'planningParamsCollapsibleButton', None)
                                if not pp_widget:
                                    return
                                pp_idx = -1
                                for j in range(self._mainSplitter.count()):
                                    w = self._mainSplitter.widget(j)
                                    if w and w.objectName == 'planningParamsCollapsibleButton':
                                        pp_idx = j
                                        break
                                if pp_idx < 0:
                                    return
                                old_pp_h = sizes[pp_idx]
                                # Measure exact content height after sub-button state changed
                                new_pp_h = self._measure_content_height(pp_widget)
                                pp_widget.setMinimumHeight(new_pp_h)
                                pp_widget.setMaximumHeight(new_pp_h)
                                delta = new_pp_h - old_pp_h
                                if delta != 0:
                                    sizes[pp_idx] = new_pp_h
                                    # Take/give from stretchable containers
                                    for j in range(self._mainSplitter.count()):
                                        w = self._mainSplitter.widget(j)
                                        if w and w.objectName in ['dataTreeCollapsibleButton', 'CollapsibleButton']:
                                            if sizes[j] - delta >= 80:
                                                sizes[j] -= delta
                                                break
                                    self._mainSplitter.setSizes(sizes)
                            else:
                                # Top-level button in splitter
                                idx = -1
                                for i in range(self._mainSplitter.count()):
                                    w = self._mainSplitter.widget(i)
                                    if w and w.objectName == button.objectName:
                                        idx = i
                                        break
                                if idx < 0:
                                    return
                                is_stretchable = button.objectName in ['dataTreeCollapsibleButton', 'CollapsibleButton']

                                if not collapsed:
                                    # Expanding
                                    try:
                                        button.setMinimumHeight(0)
                                        button.setMaximumHeight(16777215)
                                    except: pass

                                    if is_stretchable:
                                        target_height = 400 if button.objectName == 'dataTreeCollapsibleButton' else 300
                                        button.setMinimumHeight(80)
                                        button.setMaximumHeight(16777215)
                                    else:
                                        # Non-stretchable: measure exact content height
                                        button.updateGeometry()
                                        if button.objectName == 'planningParamsCollapsibleButton':
                                            target_height = self._measure_content_height(button)
                                        else:
                                            target_height = max(button.sizeHint.height(), 80)
                                        button.setMinimumHeight(target_height)
                                        button.setMaximumHeight(target_height)

                                    if sizes[idx] < target_height:
                                        needed = target_height - sizes[idx]
                                        for j in range(self._mainSplitter.count()):
                                            w = self._mainSplitter.widget(j)
                                            if w and w.objectName in ['dataTreeCollapsibleButton', 'CollapsibleButton']:
                                                take = min(needed, sizes[j] - 80)
                                                if take > 0:
                                                    sizes[j] -= take
                                                    needed -= take
                                                if needed <= 0:
                                                    break
                                        sizes[idx] = target_height
                                        self._mainSplitter.setSizes(sizes)

                                else:
                                    # Collapsing
                                    current_height = sizes[idx]
                                    header_height = 30
                                    try:
                                        button.setMinimumHeight(header_height)
                                        button.setMaximumHeight(header_height)
                                    except: pass

                                    yielded_space = current_height - header_height
                                    if yielded_space > 0:
                                        sizes[idx] = header_height
                                        for j in range(self._mainSplitter.count()):
                                            w = self._mainSplitter.widget(j)
                                            if w and w.objectName in ['dataTreeCollapsibleButton', 'CollapsibleButton']:
                                                sizes[j] += yielded_space
                                                break
                                        self._mainSplitter.setSizes(sizes)
                            # Update splitter minimum height for correct scrollbar behavior
                            self._updateSplitterMinHeight()
                        return handler
                    btn.connect("contentsCollapsed(bool)", make_resize_handler(btn))

        except Exception:
            pass

    def restoreDefaultParameters(self):
        """Restore all planning parameters to default values from config."""
        self.initializePlanningParameters()

    def getPlanningParametersFromUI(self):
        """Collect current planning parameters from the embedded UI controls.

        Returns:
            argparse.Namespace: Planning parameters namespace object with UI values.
        """
        try:
            args = setting()

            args.radiation_array_params["target_value"] = self.ui.targetValueSpinBox.value
            args.radiation_array_params["obstacle_value"] = self.ui.obstacleValueSpinBox.value
            args.radiation_array_params["background_value"] = self.ui.backgroundValueSpinBox.value
            args.radiation_array_params["backlit_angle"] = self.ui.backlitAngleSpinBox.value
            args.radiation_array_params["maximum_candidate_trajectories"] = self.ui.maxCandiTrajSpinBox.value

            args.seed_info["radius"] = self.ui.seedRadiusSpinBox.value
            args.seed_info["length"] = self.ui.seedLengthSpinBox.value
            args.seed_info["num_of_seeds"] = [self.ui.seedCountMinSpinBox.value, self.ui.seedCountMaxSpinBox.value]
            args.seed_info["seed_avr_dose"] = self.ui.seedDoseSpinBox.value

            args.in_lowest_energy = self.ui.inLowestEnergySpinBox.value / DOSE_SCALE_FACTOR
            args.out_highest_energy = self.ui.outHighestEnergySpinBox.value / DOSE_SCALE_FACTOR

            # Convert relative iso_dose_values (fractions of in_lowest_energy) to absolute values
            args.iso_dose_params['iso_dose_values'] = self.ui.inLowestEnergySpinBox.value * np.array(args.iso_dose_params['iso_dose_values'])

            args.DVH_rate = self.ui.dvhRateSpinBox.value
            args.max_iter = self.ui.maxIterSpinBox.value

            # Get reference direction from UI and normalize it
            ref_direc = np.array(
                [self.ui.refDirecXSpinBox.value, self.ui.refDirecYSpinBox.value, self.ui.refDirecZSpinBox.value]
            )
            norm = np.linalg.norm(ref_direc)
            if norm > 1e-6:
                ref_direc_normalized = ref_direc / norm
                args.reference_direc = ref_direc_normalized
                # Only update UI if values changed significantly (avoid overwriting user input)
                # Check if current values are already close to normalized values
                current_norm = np.linalg.norm(ref_direc)
                if abs(current_norm - 1.0) > 0.01:  # Only update if not already normalized
                    self._ref_direc_updating = True
                    try:
                        self.ui.refDirecXSpinBox.value = round(ref_direc_normalized[0], 3)
                        self.ui.refDirecYSpinBox.value = round(ref_direc_normalized[1], 3)
                        self.ui.refDirecZSpinBox.value = round(ref_direc_normalized[2], 3)
                    finally:
                        self._ref_direc_updating = False
            else:
                args.reference_direc = ref_direc

            args.rf_params["max_episodes"] = self.ui.maxEpisodesSpinBox.value
            args.rf_params["bandwidth"] = self.ui.bandwidthSpinBox.value
            args.use_rf = self.ui.useReinforceLearningCheckBox.checked

            return args
        except Exception as e:
            self.addLog(f"Error reading planning parameters from UI: {str(e)}", level="error")
            return setting()

    def setPlanningParametersToUI(self, params):
        """Set embedded UI control values from a planning parameters namespace.

        Args:
            params: Planning parameters namespace object.
        """
        try:
            self.ui.targetValueSpinBox.setValue(params.radiation_array_params["target_value"])
            self.ui.obstacleValueSpinBox.setValue(params.radiation_array_params["obstacle_value"])
            self.ui.backgroundValueSpinBox.setValue(params.radiation_array_params["background_value"])
            self.ui.backlitAngleSpinBox.setValue(params.radiation_array_params["backlit_angle"])
            self.ui.maxCandiTrajSpinBox.setValue(params.radiation_array_params["maximum_candidate_trajectories"])
            self.ui.seedRadiusSpinBox.setValue(params.seed_info["radius"])
            self.ui.seedLengthSpinBox.setValue(params.seed_info["length"])
            self.ui.seedCountMinSpinBox.setValue(params.seed_info["num_of_seeds"][0])
            self.ui.seedCountMaxSpinBox.setValue(params.seed_info["num_of_seeds"][1])
            self.ui.seedDoseSpinBox.setValue(params.seed_info["seed_avr_dose"])
            self.ui.inLowestEnergySpinBox.setValue(params.in_lowest_energy * DOSE_SCALE_FACTOR)
            self.ui.outHighestEnergySpinBox.setValue(params.out_highest_energy * DOSE_SCALE_FACTOR)
            self.ui.dvhRateSpinBox.setValue(params.DVH_rate)
            self.ui.maxIterSpinBox.setValue(params.max_iter)
            self.ui.refDirecXSpinBox.setValue(params.reference_direc[0])
            self.ui.refDirecYSpinBox.setValue(params.reference_direc[1])
            self.ui.refDirecZSpinBox.setValue(params.reference_direc[2])
            self.ui.maxEpisodesSpinBox.setValue(params.rf_params["max_episodes"])
            self.ui.bandwidthSpinBox.setValue(params.rf_params["bandwidth"])
            self.ui.useReinforceLearningCheckBox.setChecked(params.use_rf)
        except Exception as e:
            self.addLog(f"Error setting planning parameters to UI: {str(e)}", level="error")

    def getPlanningParameters(self):
        """Return the current planning parameters for use in planning.

        Returns:
            argparse.Namespace: Current planning parameters.
        """
        return self.getPlanningParametersFromUI()

    def _on_input_selection_changed(self, node=None):
        """Triggered when image or segmentation selector changes.

        Auto-computes reference direction when both inputs are available.
        Visualizes body shell when CT is selected.

        Args:
            node: The newly selected node (unused, required by signal).
        """
        try:
            ct_node = self.ui.imageSelector.currentNode()
            seg_node = self.ui.CTVImageSelector.currentNode()
            if ct_node is not None and seg_node is not None:
                self._auto_compute_reference_direction(silent=True)
        except Exception:
            pass

    def _create_ref_direction_arrow_from_spinbox(self):
        """Create a reference direction arrow when user manually inputs direction.
        
        Creates a simple arrow at a default position that can be updated
        as the user changes the spinbox values.
        """
        try:
            # Remove old arrow if exists
            if self._ref_direc_arrow_node is not None:
                self._ref_direc_arrow_node.RemoveObserver(self._ref_direc_arrow_tag)
                slicer.mrmlScene.RemoveNode(self._ref_direc_arrow_node)
                self._ref_direc_arrow_node = None
            
            for name in ["RefDirectionArrow"]:
                old_nodes = slicer.mrmlScene.GetNodesByName(name)
                for i in range(old_nodes.GetNumberOfItems()):
                    node = old_nodes.GetItemAsObject(i)
                    if node:
                        slicer.mrmlScene.RemoveNode(node)
                old_nodes.UnRegister(None)
            
            # Get direction from spinbox
            d = np.array([
                self.ui.refDirecXSpinBox.value,
                self.ui.refDirecYSpinBox.value,
                self.ui.refDirecZSpinBox.value
            ], dtype=np.float64)
            norm = np.linalg.norm(d)
            if norm < 1e-6:
                d = np.array([0, 0, 1], dtype=np.float64)  # Default direction
            else:
                d = d / norm
            
            # Flip direction 180° to match clinical convention
            d = -d
            
            # Default position at origin with offset
            base_ras = np.array([0.0, 0.0, 50.0], dtype=np.float64)
            arrow_length = 50.0
            arrowhead_length = 10.0
            arrowhead_angle = 30.0
            
            tip_ras = base_ras + d * arrow_length
            
            # Create shaft
            shaft_points = vtk.vtkPoints()
            shaft_points.InsertNextPoint(base_ras[0], base_ras[1], base_ras[2])
            shaft_points.InsertNextPoint(tip_ras[0], tip_ras[1], tip_ras[2])
            
            shaft_lines = vtk.vtkCellArray()
            shaft_lines.InsertNextCell(2)
            shaft_lines.InsertCellPoint(0)
            shaft_lines.InsertCellPoint(1)
            
            shaft_poly = vtk.vtkPolyData()
            shaft_poly.SetPoints(shaft_points)
            shaft_poly.SetLines(shaft_lines)
            
            # Create arrowhead
            arrowhead1_dir = self._rotate_vector(d, arrowhead_angle)
            arrowhead2_dir = self._rotate_vector(d, -arrowhead_angle)
            arrowhead1_start = tip_ras - arrowhead1_dir * arrowhead_length
            arrowhead2_start = tip_ras - arrowhead2_dir * arrowhead_length
            
            arrowhead_points = vtk.vtkPoints()
            arrowhead_points.InsertNextPoint(arrowhead1_start[0], arrowhead1_start[1], arrowhead1_start[2])
            arrowhead_points.InsertNextPoint(tip_ras[0], tip_ras[1], tip_ras[2])
            arrowhead_points.InsertNextPoint(arrowhead2_start[0], arrowhead2_start[1], arrowhead2_start[2])
            
            arrowhead_lines = vtk.vtkCellArray()
            arrowhead_lines.InsertNextCell(2)
            arrowhead_lines.InsertCellPoint(0)
            arrowhead_lines.InsertCellPoint(1)
            arrowhead_lines.InsertNextCell(2)
            arrowhead_lines.InsertCellPoint(1)
            arrowhead_lines.InsertCellPoint(2)
            
            arrowhead_poly = vtk.vtkPolyData()
            arrowhead_poly.SetPoints(arrowhead_points)
            arrowhead_poly.SetLines(arrowhead_lines)
            
            # Combine
            append_filter = vtk.vtkAppendPolyData()
            append_filter.AddInputData(shaft_poly)
            append_filter.AddInputData(arrowhead_poly)
            append_filter.Update()
            
            # Create model node
            model_node = slicer.modules.models.logic().AddModel(append_filter.GetOutput())
            model_node.SetName("RefDirectionArrow")
            
            display_node = model_node.GetDisplayNode()
            if display_node:
                display_node.SetColor(1.0, 0.2, 0.2)
                display_node.SetOpacity(1.0)
                display_node.SetVisibility(True)
                display_node.SetLineWidth(5.0)
            
            model_node.SetSelectable(1)
            self._ref_direc_arrow_node = model_node

            # Create interaction line node with visible control points
            line_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode")
            line_node.SetName("RefDirectionArrow_Interaction")
            line_node.AddControlPoint(vtk.vtkVector3d(base_ras[0], base_ras[1], base_ras[2]))
            line_node.AddControlPoint(vtk.vtkVector3d(tip_ras[0], tip_ras[1], tip_ras[2]))
            line_node.SetLocked(0)  # Allow interaction

            # Force create display node to ensure visibility can be controlled
            line_node.CreateDefaultDisplayNodes()

            # Configure display node for visible control points
            line_display = line_node.GetDisplayNode()
            if line_display:
                line_display.SetVisibility(True)
                line_display.SetVisibility2D(True)
                line_display.SetVisibility3D(True)
                line_display.SetColor(1.0, 0.2, 0.2)  # Red color to match arrow
                line_display.SetLineWidth(3.0)
                line_display.SetGlyphScale(1.5)  # Larger control points
                line_display.SetTextScale(0)  # Hide text labels
                line_display.SetGlyphType(slicer.vtkMRMLMarkupsDisplayNode.Sphere3D)
                line_display.SetPointLabelsVisibility(False)  # Hide point labels

            # Ensure Subject Hierarchy has visibility control for this node
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            if shNode is not None:
                line_itemID = shNode.GetItemByDataNode(line_node)
                if line_itemID != shNode.GetInvalidItemID():
                    shNode.SetItemDisplayVisibility(line_itemID, 1)

            self._ref_direc_arrow_tag = line_node.AddObserver(
                vtk.vtkCommand.ModifiedEvent, self._on_ref_direc_arrow_modified
            )
            self._ref_direc_interaction_node = line_node

        except Exception as e:
            self.addLog(f"Failed to create reference direction arrow: {str(e)}")

    def _on_ref_direc_spinbox_changed(self):
        """Handle reference direction spinbox changes.
        
        This function is now disabled - spinbox only displays values.
        Arrow can only be adjusted by dragging control points.
        """
        # Spinbox is read-only - arrow can only be adjusted by dragging control points
        pass

    def _update_ref_direction_arrow_from_spinbox(self):
        """Update arrow direction and position to ensure it passes through CTV centroid.
        
        When direction changes, recalculate arrow position so that the arrow's
        extension line passes through the CTV centroid.
        """
        if self._ref_direc_interaction_node is None or self._ref_direc_arrow_node is None:
            return
        
        # Get current direction from spinbox
        d = np.array([
            self.ui.refDirecXSpinBox.value,
            self.ui.refDirecYSpinBox.value,
            self.ui.refDirecZSpinBox.value
        ], dtype=np.float64)
        norm = np.linalg.norm(d)
        if norm < 1e-6:
            return
        d = d / norm

        # Flip direction 180° to match clinical convention
        d = -d
        
        # Get CTV and CT nodes
        ct_node = self.ui.imageSelector.currentNode()
        seg_node = self.ui.CTVImageSelector.currentNode()
        if ct_node is None or seg_node is None:
            return
        
        try:
            # Calculate CTV centroid in RAS coordinates
            ctv_centroid_ras = self._compute_ctv_centroid_ras(ct_node, seg_node)
            if ctv_centroid_ras is None:
                return
            
            n = self._ref_direc_interaction_node
            if n.GetNumberOfControlPoints() < 2:
                return
            
            arrow_length = 50.0
            arrowhead_length = 10.0
            arrowhead_angle = 30.0
            ctv_offset = 50.0  # Arrow base 5cm from CTV along direction
            
            # Calculate new arrow base position: 50mm from CTV in opposite direction
            # This ensures arrow points toward CTV and extension line passes through CTV
            base_ras = ctv_centroid_ras - d * ctv_offset
            tip_ras = base_ras + d * arrow_length
            
            self._ref_direc_updating = True
            try:
                # Update interaction line node control points
                n.SetNthControlPointPosition(0, base_ras[0], base_ras[1], base_ras[2])
                n.SetNthControlPointPosition(1, tip_ras[0], tip_ras[1], tip_ras[2])
                
                # Calculate arrowhead points
                arrowhead1_dir = self._rotate_vector(d, arrowhead_angle)
                arrowhead2_dir = self._rotate_vector(d, -arrowhead_angle)
                arrowhead1_start = tip_ras - arrowhead1_dir * arrowhead_length
                arrowhead2_start = tip_ras - arrowhead2_dir * arrowhead_length
                
                # Update arrow model geometry
                arrow_model = self._ref_direc_arrow_node
                poly_data = arrow_model.GetPolyData()
                
                points = poly_data.GetPoints()
                points.SetPoint(0, base_ras[0], base_ras[1], base_ras[2])
                points.SetPoint(1, tip_ras[0], tip_ras[1], tip_ras[2])
                points.SetPoint(2, arrowhead1_start[0], arrowhead1_start[1], arrowhead1_start[2])
                points.SetPoint(3, tip_ras[0], tip_ras[1], tip_ras[2])
                points.SetPoint(4, arrowhead2_start[0], arrowhead2_start[1], arrowhead2_start[2])
                
                poly_data.Modified()
                arrow_model.Modified()
            finally:
                self._ref_direc_updating = False
        except Exception:
            pass
    
    def _compute_ctv_centroid_ras(self, ct_node, seg_node):
        """Compute CTV centroid in RAS coordinates.
        
        Args:
            ct_node: CT volume node
            seg_node: Segmentation node (CTV)
            
        Returns:
            numpy array: CTV centroid in RAS coordinates, or None if failed
        """
        try:
            # Get CTV array from segmentation
            if hasattr(seg_node, 'GetSegmentation'):
                # It's a segmentation node
                seg = seg_node.GetSegmentation()
                segment_ids = vtk.vtkStringArray()
                seg.GetSegmentIDs(segment_ids)
                
                # Get visible segments
                display_node = seg_node.GetDisplayNode()
                visible_segment_ids = []
                for i in range(segment_ids.GetNumberOfValues()):
                    seg_id = segment_ids.GetValue(i)
                    if display_node:
                        if display_node.GetSegmentVisibility(seg_id):
                            visible_segment_ids.append(seg_id)
                    else:
                        visible_segment_ids.append(seg_id)
                
                if not visible_segment_ids:
                    return None
                
                # Export visible segments to labelmap
                label_map = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "_temp_ctv_label")
                slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                    seg_node, visible_segment_ids, label_map, ct_node
                )
                ctv_array = slicer.util.arrayFromVolume(label_map)
                slicer.mrmlScene.RemoveNode(label_map)
            else:
                # It's already a labelmap volume
                ctv_array = slicer.util.arrayFromVolume(seg_node)
            
            if ctv_array is None or ctv_array.size == 0:
                return None
            
            # Find non-zero voxels (CTV mask)
            ctv_mask = ctv_array > 0
            if not np.any(ctv_mask):
                return None
            
            # Calculate centroid in IJK coordinates
            indices = np.where(ctv_mask)
            centroid_ijk = np.array([
                np.mean(indices[0]),  # k
                np.mean(indices[1]),  # j  
                np.mean(indices[2])   # i
            ])
            
            # Convert IJK to RAS
            ijk_to_ras = vtk.vtkMatrix4x4()
            ct_node.GetIJKToRASMatrix(ijk_to_ras)
            
            # Convert from [k, j, i] to [i, j, k] for matrix multiplication
            ijk_point = [centroid_ijk[2], centroid_ijk[1], centroid_ijk[0], 1.0]
            ras_point = [0.0, 0.0, 0.0, 1.0]
            ijk_to_ras.MultiplyPoint(ijk_point, ras_point)
            
            return np.array([ras_point[0], ras_point[1], ras_point[2]], dtype=np.float64)
            
        except Exception:
            return None

    def _on_ref_direc_arrow_modified(self, caller, event):
        """Handle arrow control point interaction.
        
        When user drags control points, update both the spinbox values
        and the arrow model geometry.
        """
        if self._ref_direc_updating:
            return
        if self._ref_direc_interaction_node is None or self._ref_direc_arrow_node is None:
            return
        try:
            n = self._ref_direc_interaction_node
            if n.GetNumberOfControlPoints() < 2:
                return
            base_pos = [0.0, 0.0, 0.0]
            tip_pos = [0.0, 0.0, 0.0]
            n.GetNthControlPointPosition(0, base_pos)
            n.GetNthControlPointPosition(1, tip_pos)
            base = np.array(base_pos, dtype=np.float64)
            tip = np.array(tip_pos, dtype=np.float64)
            d = tip - base
            norm = np.linalg.norm(d)
            if norm < 1e-6:
                return
            d_normalized = d / norm
            
            arrowhead_length = 10.0
            arrowhead_angle = 30.0
            
            self._ref_direc_updating = True
            try:
                # 1. Update backend parameters directly to ensure sync
                plan_direc = -d_normalized
                if hasattr(self, "_planning_params"):
                    self._planning_params.reference_direc = plan_direc.copy()

                # 2. Update spinbox values (using setValue for signal triggers)
                self.ui.refDirecXSpinBox.setValue(round(plan_direc[0], 3))
                self.ui.refDirecYSpinBox.setValue(round(plan_direc[1], 3))
                self.ui.refDirecZSpinBox.setValue(round(plan_direc[2], 3))

                # 3. Update arrow model geometry
                arrow_model = self._ref_direc_arrow_node
                if arrow_model is None:
                    return
                    
                poly_data = arrow_model.GetPolyData()
                if poly_data is None:
                    return
                    
                points = poly_data.GetPoints()
                if points is None:
                    return
                
                # Calculate arrowhead points
                arrowhead1_dir = self._rotate_vector(d_normalized, arrowhead_angle)
                arrowhead2_dir = self._rotate_vector(d_normalized, -arrowhead_angle)
                arrowhead1_start = tip - arrowhead1_dir * arrowhead_length
                arrowhead2_start = tip - arrowhead2_dir * arrowhead_length
                
                # Update all points: base, tip, arrowhead1_start, tip, arrowhead2_start
                points.SetPoint(0, base[0], base[1], base[2])
                points.SetPoint(1, tip[0], tip[1], tip[2])
                points.SetPoint(2, arrowhead1_start[0], arrowhead1_start[1], arrowhead1_start[2])
                points.SetPoint(3, tip[0], tip[1], tip[2])
                points.SetPoint(4, arrowhead2_start[0], arrowhead2_start[1], arrowhead2_start[2])
                
                points.Modified()
                poly_data.Modified()
                arrow_model.Modified()
                
                # Force update display
                display_node = arrow_model.GetDisplayNode()
                if display_node:
                    display_node.Modified()
            finally:
                self._ref_direc_updating = False
        except Exception as e:
            self.addLog(f"Error updating reference direction arrow: {str(e)}", level="warning")

    def _auto_compute_reference_direction(self, checked=False, silent=False):
        """Auto-compute reference direction from body surface nearest to CTV.

        Extracts a body shell from the CT volume using thresholding and
        morphological operations, finds the shell region closest to the
        CTV, and computes the inward surface normal as the reference
        direction for needle planning. The result is displayed in RAS
        coordinates in the UI spin boxes.

        The body shell is always visualized as a labelmap volume.
        The reference direction arrow is only computed when both CT
        and segmentation (CTV) are available.

        Args:
            checked: Button checked state (unused, required by signal).
            silent: If True, suppress error messages (for auto-trigger mode).
        """
        try:
            ct_node = self.ui.imageSelector.currentNode()
            seg_node = self.ui.CTVImageSelector.currentNode()

            if ct_node is None:
                if not silent:
                    self.addLog("Cannot auto-compute: CT image is required.")
                return

            self.ui.autoRefDirecButton.enabled = False
            self.ui.autoRefDirecButton.text = "..."
            self.addLog("Computing body shell and reference direction...")
            slicer.app.processEvents()

            ct_node_id = ct_node.GetID()
            # Define resample_size before the if/else block to ensure it's always available
            resample_size = [128, 128, NEW_SLICES_ROUNDED]
            
            if ct_node_id in self._geometry_cache:
                self.addLog("  Using cached CT resampling...")
                cached = self._geometry_cache[ct_node_id]
                ct_resampled = cached['ct_resampled']
                ct_array = cached['ct_array']
                spacing_zyx = cached['spacing_zyx']
                direction_matrix = cached['direction_matrix']
            else:
                ct_image = sitkUtils.PullVolumeFromSlicer(ct_node)

                self.addLog("  Resampling CT...")
                slicer.app.processEvents()
                ct_resampled = self.logic.image_resample_size(ct_image, resample_size, is_label=False)
                del ct_image
                ct_array = sitk.GetArrayFromImage(ct_resampled)

                spacing_xyz = np.array(ct_resampled.GetSpacing())
                spacing_zyx = spacing_xyz[::-1]
                direction = np.array(ct_resampled.GetDirection()).reshape(3, 3)
                direction_matrix = direction.copy()

                self._geometry_cache[ct_node_id] = {
                    'ct_resampled': ct_resampled,
                    'ct_array': ct_array,
                    'spacing_zyx': spacing_zyx,
                    'direction_matrix': direction_matrix,
                }

            seg_image = None
            target_value = 1
            if seg_node is not None:
                labelMapNode = None
                visibleSegmentIDs = None
                try:
                    self.addLog("  Loading segmentation...")
                    slicer.app.processEvents()
                    if isinstance(seg_node, slicer.vtkMRMLSegmentationNode):
                        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                        labelMapNode.SetName("_auto_ref_dir_temp_labelmap")
                        
                        # Get only visible segment IDs
                        visibleSegmentIDs = vtk.vtkStringArray()
                        segmentation = seg_node.GetSegmentation()
                        allSegmentIDs = vtk.vtkStringArray()
                        segmentation.GetSegmentIDs(allSegmentIDs)
                        
                        # Get display node to check visibility
                        display_node = seg_node.GetDisplayNode()
                        if display_node is None:
                            seg_node.CreateDefaultDisplayNodes()
                            display_node = seg_node.GetDisplayNode()
                        
                        for i in range(allSegmentIDs.GetNumberOfValues()):
                            segmentID = allSegmentIDs.GetValue(i)
                            # Check if segment is visible using display node
                            if display_node:
                                is_visible = display_node.GetSegmentVisibility(segmentID)
                            else:
                                # Fallback: export all if no display node
                                is_visible = True
                            if is_visible:
                                visibleSegmentIDs.InsertNextValue(segmentID)
                        
                        self.addLog(f"  Exporting {visibleSegmentIDs.GetNumberOfValues()} visible segments for reference direction")
                        
                        if visibleSegmentIDs.GetNumberOfValues() > 0:
                            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                                seg_node, visibleSegmentIDs, labelMapNode, ct_node
                            )
                            seg_image = sitkUtils.PullVolumeFromSlicer(labelMapNode)
                    elif isinstance(seg_node, slicer.vtkMRMLLabelMapVolumeNode):
                        seg_image = sitkUtils.PullVolumeFromSlicer(seg_node)
                finally:
                    if labelMapNode is not None:
                        displayNode = labelMapNode.GetDisplayNode()
                        if displayNode:
                            slicer.mrmlScene.RemoveNode(displayNode)
                        storageNode = labelMapNode.GetStorageNode()
                        if storageNode:
                            slicer.mrmlScene.RemoveNode(storageNode)
                        slicer.mrmlScene.RemoveNode(labelMapNode)

                if seg_image is not None:
                    seg_resampled = self.logic.image_resample_size(seg_image, resample_size, is_label=True)
                    del seg_image
                    seg_array = sitk.GetArrayFromImage(seg_resampled)
                    # Use any non-zero value as target (visible segments are exported as 1, 2, 3, ...)
                    # The compute_body_shell_and_ref_direction function will use all non-zero values
                    target_value = 1  # Default, but function should handle any non-zero
                else:
                    seg_array = np.zeros_like(ct_array, dtype=np.uint8)
            else:
                seg_array = np.zeros_like(ct_array, dtype=np.uint8)

            self.addLog("  Extracting body shell and computing direction...")
            slicer.app.processEvents()
            ref_direc_ras, body_shell, closest_pt_vox, ctv_centroid_vox = compute_body_shell_and_ref_direction(
                ct_array, seg_array, spacing_zyx, target_value, direction_matrix
            )
            del ct_array, seg_array

            if body_shell is not None:
                self._visualize_body_shell(ct_resampled, body_shell, ct_node)

            if ref_direc_ras is not None:
                self.ui.refDirecXSpinBox.setValue(float(ref_direc_ras[0]))
                self.ui.refDirecYSpinBox.setValue(float(ref_direc_ras[1]))
                self.ui.refDirecZSpinBox.setValue(float(ref_direc_ras[2]))
                self.addLog(
                    f"Auto-computed reference direction (RAS): "
                    f"[{ref_direc_ras[0]:.3f}, {ref_direc_ras[1]:.3f}, {ref_direc_ras[2]:.3f}]"
                )

                if closest_pt_vox is not None and ctv_centroid_vox is not None:
                    # Update existing arrow if it exists, otherwise create new one
                    if self._ref_direc_arrow_node is not None and self._ref_direc_interaction_node is not None:
                        self._update_ref_direction_arrow_position(ct_node, ct_resampled, closest_pt_vox, ctv_centroid_vox, ref_direc_ras)
                    else:
                        self._show_ref_direction_arrow(ct_node, ct_resampled, closest_pt_vox, ctv_centroid_vox, ref_direc_ras)
            else:
                if seg_node is not None:
                    if not silent:
                        self.addLog("Auto-compute failed: could not determine direction from body surface. Using current values.")
                else:
                    if not silent:
                        self.addLog("Body shell extracted. Select segmentation (CTV) to compute reference direction.")

            self.ui.autoRefDirecButton.enabled = True
            self.ui.autoRefDirecButton.text = "Auto"

        except Exception as e:
            self.addLog(f"Auto-compute reference direction failed: {str(e)}. Using current values.")
            try:
                self.ui.autoRefDirecButton.enabled = True
                self.ui.autoRefDirecButton.text = "Auto"
            except Exception:
                pass

    def _visualize_body_shell(self, sitk_image, shell_array, ct_node):
        """Visualize the body shell as a segmentation node in Slicer.

        Args:
            sitk_image: SimpleITK.Image with geometry metadata.
            shell_array: 3D uint8 array of the body shell mask.
            ct_node: Original CT volume node for geometry reference.
        """
        try:
            old_nodes = slicer.mrmlScene.GetNodesByName("BodyShell")
            for i in range(old_nodes.GetNumberOfItems()):
                node = old_nodes.GetItemAsObject(i)
                if node:
                    slicer.mrmlScene.RemoveNode(node)
            old_nodes.UnRegister(None)

            seg_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            seg_node.SetName("BodyShell")
            seg_node.SetReferenceImageGeometryParameterFromVolumeNode(ct_node)
            seg_node.CreateDefaultDisplayNodes()

            shell_sitk = sitk.GetImageFromArray(shell_array)
            shell_sitk.CopyInformation(sitk_image)

            # Use an oriented image data to ensure the spatial information is correctly preserved
            import vtk.util.numpy_support as vtk_np
            # VTK oriented image data is required by ImportLabelmapToSegmentationNode
            oriented_img = slicer.vtkOrientedImageData()

            dims = shell_array.shape[::-1]
            self.addLog(f"Body shell dimensions: {dims[0]} x {dims[1]} x {dims[2]}")
            oriented_img.SetDimensions(dims[0], dims[1], dims[2])
            oriented_img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)

            # Transfer data from numpy array
            flat = shell_array.astype(np.uint8).ravel(order='F')
            vtk_arr = vtk.util.numpy_support.vtk_to_numpy(oriented_img.GetPointData().GetScalars())
            vtk_arr[:] = flat

            # Set geometry information from SimpleITK image
            oriented_img.SetOrigin(sitk_image.GetOrigin())
            oriented_img.SetSpacing(sitk_image.GetSpacing())

            # Convert SITK (LPS) direction to VTK (LPS is handled by Slicer internally for display, but here we set internal matrix)
            direction = sitk_image.GetDirection()
            v_matrix = vtk.vtkMatrix4x4()
            for r in range(3):
                for c in range(3):
                    v_matrix.SetElement(r, c, direction[r*3+c])
            oriented_img.SetGeometryFromImageToWorldMatrix(v_matrix)

            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(oriented_img, seg_node)
            
            segmentation = seg_node.GetSegmentation()
            segment_ids = segmentation.GetSegmentIDs()
            if segment_ids.GetNumberOfValues() > 0:
                segment_id = segment_ids.GetValue(0)
                segment = segmentation.GetSegment(segment_id)
                segment.SetName("BodyShell")
                segment.SetColor(0.8, 0.6, 0.2)

            seg_node.CreateClosedSurfaceRepresentation()
            display_node = seg_node.GetDisplayNode()
            if display_node:
                display_node.SetVisibility(False)  # Hidden by default, user can manually show
                display_node.SetVisibility3D(False)
                display_node.SetOpacity3D(0.3)

            self.addLog("Body shell created as segmentation 'BodyShell' (hidden by default).")
        except Exception as e:
            self.addLog(f"Failed to visualize body shell: {str(e)}")

    def _show_ref_direction_arrow(self, ct_node, sitk_image, closest_pt_vox, ctv_centroid_vox, ref_direc_ras):
        """Draw a 3D arrow using three lines: shaft and two arrowheads.

        Creates an arrow with three line segments:
        - Shaft: from base to tip
        - Two arrowhead lines: from tip back at an angle
        
        The arrow is displayed as a ModelNode that can be shown/hidden.
        Interaction is supported via control points for SpinBox sync.

        Args:
            ct_node: Original vtkMRMLScalarVolumeNode for IJKToRAS transform.
            sitk_image: SimpleITK.Image (resampled) with geometry.
            closest_pt_vox: 3-element array [k, j, i] of shell point.
            ctv_centroid_vox: 3-element array [k, j, i] of CTV centroid.
            ref_direc_ras: 3-element unit vector in RAS space.
        """
        try:
            # Check if RefDirectionArrow already exists in scene
            existing_arrow_nodes = slicer.mrmlScene.GetNodesByName("RefDirectionArrow")
            existing_arrow = None
            if existing_arrow_nodes.GetNumberOfItems() > 0:
                existing_arrow = existing_arrow_nodes.GetItemAsObject(0)

            # Check if interaction node already exists
            existing_interaction_nodes = slicer.mrmlScene.GetNodesByName("RefDirectionArrow_Interaction")
            existing_interaction = None
            if existing_interaction_nodes.GetNumberOfItems() > 0:
                existing_interaction = existing_interaction_nodes.GetItemAsObject(0)

            # If both exist, just update position instead of recreating
            if existing_arrow is not None and existing_interaction is not None:
                self._ref_direc_arrow_node = existing_arrow
                self._ref_direc_interaction_node = existing_interaction
                # Re-observer the interaction node
                if hasattr(self, '_ref_direc_arrow_tag') and self._ref_direc_arrow_tag:
                    existing_interaction.RemoveObserver(self._ref_direc_arrow_tag)
                self._ref_direc_arrow_tag = existing_interaction.AddObserver(
                    vtk.vtkCommand.ModifiedEvent, self._on_ref_direc_arrow_modified
                )
                # Update position with new data
                self._update_ref_direction_arrow_position(ct_node, sitk_image, closest_pt_vox, ctv_centroid_vox, ref_direc_ras)
                return

            # Clean up existing nodes if found in scene
            if self._ref_direc_arrow_node is not None:
                # Verify node is still in scene before removing
                if self._ref_direc_arrow_node.GetScene() == slicer.mrmlScene:
                    if hasattr(self, '_ref_direc_arrow_tag') and self._ref_direc_arrow_tag:
                        self._ref_direc_arrow_node.RemoveObserver(self._ref_direc_arrow_tag)
                    slicer.mrmlScene.RemoveNode(self._ref_direc_arrow_node)
                self._ref_direc_arrow_node = None

            # Also clean up interaction node if it exists in scene
            if self._ref_direc_interaction_node is not None:
                if self._ref_direc_interaction_node.GetScene() == slicer.mrmlScene:
                    slicer.mrmlScene.RemoveNode(self._ref_direc_interaction_node)
                self._ref_direc_interaction_node = None

            for name in ["RefDirectionArrow", "RefDirectionArrow_Interaction"]:
                old_nodes = slicer.mrmlScene.GetNodesByName(name)
                for i in range(old_nodes.GetNumberOfItems()):
                    node = old_nodes.GetItemAsObject(i)
                    if node:
                        slicer.mrmlScene.RemoveNode(node)
                old_nodes.UnRegister(None)

            # Get transform from resampled image IJK to RAS
            rs_direction = np.array(sitk_image.GetDirection()).reshape(3, 3)
            rs_spacing = np.array(sitk_image.GetSpacing(), dtype=np.float64)
            rs_origin = np.array(sitk_image.GetOrigin(), dtype=np.float64)

            def resampled_vox_to_ras(v):
                """Convert resampled voxel coordinates [k, j, i] to RAS coordinates."""
                # v is in [k, j, i] order (zyx), convert to [i, j, k] (xyz)
                ijk_xyz = np.array(v[::-1], dtype=np.float64)
                # Transform to LPS: LPS = direction * (ijk * spacing) + origin
                lps = rs_direction @ (ijk_xyz * rs_spacing) + rs_origin
                # Convert LPS to RAS: RAS = [-L, -P, S]
                ras = np.array([-lps[0], -lps[1], lps[2]], dtype=np.float64)
                return ras

            surface_final_ras = resampled_vox_to_ras(closest_pt_vox)
            ctv_centroid_ras = resampled_vox_to_ras(ctv_centroid_vox)

            # Compute direction from surface point to CTV centroid
            d = ctv_centroid_ras - surface_final_ras
            norm = np.linalg.norm(d)
            if norm > 1e-6:
                d = d / norm  # Direction points from surface toward CTV

            arrow_length = 50.0
            ctv_offset = 50.0  # Arrow base 5cm outside body surface
            arrowhead_length = 10.0
            arrowhead_angle = 30.0

            # Base is 50mm outside body surface (opposite to CTV direction)
            base_ras = surface_final_ras - d * ctv_offset
            # Tip points toward CTV (50mm from base along direction)
            tip_ras = base_ras + d * arrow_length
            # Shaft ends at the tip (so arrowhead and shaft meet at the tip)
            shaft_end_ras = tip_ras

            shaft_points = vtk.vtkPoints()
            shaft_points.InsertNextPoint(base_ras[0], base_ras[1], base_ras[2])
            shaft_points.InsertNextPoint(shaft_end_ras[0], shaft_end_ras[1], shaft_end_ras[2])

            shaft_lines = vtk.vtkCellArray()
            shaft_lines.InsertNextCell(2)
            shaft_lines.InsertCellPoint(0)
            shaft_lines.InsertCellPoint(1)

            shaft_poly = vtk.vtkPolyData()
            shaft_poly.SetPoints(shaft_points)
            shaft_poly.SetLines(shaft_lines)

            arrowhead1_dir = self._rotate_vector(d, arrowhead_angle)
            arrowhead2_dir = self._rotate_vector(d, -arrowhead_angle)

            arrowhead1_start = tip_ras - arrowhead1_dir * arrowhead_length
            arrowhead2_start = tip_ras - arrowhead2_dir * arrowhead_length

            arrowhead_points = vtk.vtkPoints()
            arrowhead_points.InsertNextPoint(arrowhead1_start[0], arrowhead1_start[1], arrowhead1_start[2])
            arrowhead_points.InsertNextPoint(tip_ras[0], tip_ras[1], tip_ras[2])
            arrowhead_points.InsertNextPoint(arrowhead2_start[0], arrowhead2_start[1], arrowhead2_start[2])

            arrowhead_lines = vtk.vtkCellArray()
            arrowhead_lines.InsertNextCell(2)
            arrowhead_lines.InsertCellPoint(0)
            arrowhead_lines.InsertCellPoint(1)
            arrowhead_lines.InsertNextCell(2)
            arrowhead_lines.InsertCellPoint(1)
            arrowhead_lines.InsertCellPoint(2)

            arrowhead_poly = vtk.vtkPolyData()
            arrowhead_poly.SetPoints(arrowhead_points)
            arrowhead_poly.SetLines(arrowhead_lines)

            append_filter = vtk.vtkAppendPolyData()
            append_filter.AddInputData(shaft_poly)
            append_filter.AddInputData(arrowhead_poly)
            append_filter.Update()

            model_node = slicer.modules.models.logic().AddModel(append_filter.GetOutput())
            model_node.SetName("RefDirectionArrow")
            
            display_node = model_node.GetDisplayNode()
            if display_node:
                display_node.SetColor(1.0, 0.2, 0.2)
                display_node.SetOpacity(1.0)
                display_node.SetVisibility(True)
                display_node.SetLineWidth(5.0)
            
            model_node.SetSelectable(1)

            self._ref_direc_arrow_node = model_node

            # Create interaction line node with visible control points
            line_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode")
            line_node.SetName("RefDirectionArrow_Interaction")
            line_node.AddControlPoint(vtk.vtkVector3d(base_ras[0], base_ras[1], base_ras[2]))
            line_node.AddControlPoint(vtk.vtkVector3d(tip_ras[0], tip_ras[1], tip_ras[2]))
            line_node.SetLocked(0)  # Allow interaction

            # Force create display node to ensure visibility can be controlled
            line_node.CreateDefaultDisplayNodes()

            # Configure display node for visible control points
            line_display = line_node.GetDisplayNode()
            if line_display:
                line_display.SetVisibility(True)
                line_display.SetVisibility2D(True)
                line_display.SetVisibility3D(True)
                line_display.SetColor(1.0, 0.2, 0.2)  # Red color to match arrow
                line_display.SetLineWidth(3.0)
                line_display.SetGlyphScale(1.5)  # Larger control points
                line_display.SetTextScale(0)  # Hide text labels
                line_display.SetGlyphType(slicer.vtkMRMLMarkupsDisplayNode.Sphere3D)
                line_display.SetPointLabelsVisibility(False)  # Hide point labels

            # Ensure Subject Hierarchy has visibility control for this node
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            if shNode is not None:
                line_itemID = shNode.GetItemByDataNode(line_node)
                if line_itemID != shNode.GetInvalidItemID():
                    shNode.SetItemDisplayVisibility(line_itemID, 1)

            self._ref_direc_arrow_tag = line_node.AddObserver(
                vtk.vtkCommand.ModifiedEvent, self._on_ref_direc_arrow_modified
            )
            self._ref_direc_interaction_node = line_node

        except Exception as e:
            self.addLog(f"Failed to show reference direction arrow: {str(e)}")

    def _update_ref_direction_arrow_position(self, ct_node, sitk_image, closest_pt_vox, ctv_centroid_vox, ref_direc_ras):
        """Update existing reference direction arrow to new position.
        
        Updates both the arrow model and the interaction line node to the
        new position computed from body shell and CTV centroid.
        
        Args:
            ct_node: Original vtkMRMLScalarVolumeNode for IJKToRAS transform.
            sitk_image: SimpleITK.Image (resampled) with geometry.
            closest_pt_vox: 3-element array [k, j, i] of shell point.
            ctv_centroid_vox: 3-element array [k, j, i] of CTV centroid.
            ref_direc_ras: 3-element unit vector in RAS space.
        """
        try:
            if self._ref_direc_arrow_node is None or self._ref_direc_interaction_node is None:
                return
            
            # Get transform from resampled image IJK to RAS
            rs_direction = np.array(sitk_image.GetDirection()).reshape(3, 3)
            rs_spacing = np.array(sitk_image.GetSpacing(), dtype=np.float64)
            rs_origin = np.array(sitk_image.GetOrigin(), dtype=np.float64)

            def resampled_vox_to_ras(v):
                """Convert resampled voxel coordinates [k, j, i] to RAS coordinates."""
                ijk_xyz = np.array(v[::-1], dtype=np.float64)
                lps = rs_direction @ (ijk_xyz * rs_spacing) + rs_origin
                ras = np.array([-lps[0], -lps[1], lps[2]], dtype=np.float64)
                return ras

            surface_final_ras = resampled_vox_to_ras(closest_pt_vox)
            ctv_centroid_ras = resampled_vox_to_ras(ctv_centroid_vox)

            # Compute direction from surface point to CTV centroid
            d = ctv_centroid_ras - surface_final_ras
            norm = np.linalg.norm(d)
            if norm > 1e-6:
                d = d / norm

            arrow_length = 50.0
            ctv_offset = 50.0
            arrowhead_length = 10.0
            arrowhead_angle = 30.0

            # Base is 50mm outside body surface (opposite to CTV direction)
            base_ras = surface_final_ras - d * ctv_offset
            tip_ras = base_ras + d * arrow_length

            self._ref_direc_updating = True
            try:
                # Update interaction line node
                line_node = self._ref_direc_interaction_node
                line_node.SetNthControlPointPosition(0, base_ras[0], base_ras[1], base_ras[2])
                line_node.SetNthControlPointPosition(1, tip_ras[0], tip_ras[1], tip_ras[2])
                
                # Update arrow model geometry
                arrow_model = self._ref_direc_arrow_node
                poly_data = arrow_model.GetPolyData()
                if poly_data is None:
                    return
                    
                points = poly_data.GetPoints()
                if points is None:
                    return
                
                # Calculate arrowhead points
                arrowhead1_dir = self._rotate_vector(d, arrowhead_angle)
                arrowhead2_dir = self._rotate_vector(d, -arrowhead_angle)
                arrowhead1_start = tip_ras - arrowhead1_dir * arrowhead_length
                arrowhead2_start = tip_ras - arrowhead2_dir * arrowhead_length
                
                # Update all points
                points.SetPoint(0, base_ras[0], base_ras[1], base_ras[2])
                points.SetPoint(1, tip_ras[0], tip_ras[1], tip_ras[2])
                points.SetPoint(2, arrowhead1_start[0], arrowhead1_start[1], arrowhead1_start[2])
                points.SetPoint(3, tip_ras[0], tip_ras[1], tip_ras[2])
                points.SetPoint(4, arrowhead2_start[0], arrowhead2_start[1], arrowhead2_start[2])
                
                points.Modified()
                poly_data.Modified()
                arrow_model.Modified()
                
                # Force update display
                display_node = arrow_model.GetDisplayNode()
                if display_node:
                    display_node.Modified()
            finally:
                self._ref_direc_updating = False
                
        except Exception as e:
            self.addLog(f"Failed to update reference direction arrow: {str(e)}")

    def _rotate_vector(self, vec, angle_degrees, axis=None):
        """Rotate a vector around an axis by an angle.
        
        Args:
            vec: 3D vector to rotate.
            angle_degrees: Rotation angle in degrees.
            axis: Axis to rotate around (None = automatic perpendicular axis).
        
        Returns:
            Rotated 3D vector.
        """
        vec = np.array(vec, dtype=np.float64)
        vec = vec / np.linalg.norm(vec)
        
        if axis is None:
            if abs(vec[2]) < 0.9:
                axis = np.cross(vec, [0, 0, 1])
            else:
                axis = np.cross(vec, [1, 0, 0])
            axis = axis / np.linalg.norm(axis)
        
        angle_rad = np.radians(angle_degrees)
        cos_a = np.cos(angle_rad)
        sin_a = np.sin(angle_rad)
        
        rot_matrix = (
            cos_a * np.eye(3) +
            sin_a * np.array([[0, -axis[2], axis[1]],
                              [axis[2], 0, -axis[0]],
                              [-axis[1], axis[0], 0]]) +
            (1 - cos_a) * np.outer(axis, axis)
        )
        
        return rot_matrix @ vec

    def toggleStyle(self, visible):
        """Toggle between custom application style and default style.

        Args:
            visible: If True, apply custom style; if False, reset to default.
        """
        try:
            if visible:
                self.applyApplicationStyle()
            else:
                slicer.app.styleSheet = ""
        except Exception:
            pass

    def raiseSettings(self, _):
        """Show the settings dialog.

        Args:
            _: Unused trigger argument.
        """
        try:
            self.settingsDialog.exec()
        except Exception:
            pass

    def setCustomUIVisible(self):
        """Set custom UI elements visible and hide default Slicer UI."""
        self.setSlicerUIVisible()

    def applyApplicationStyle(self):
        """Apply custom application style from the QSS file and style view widgets."""
        try:
            SlicerCustomAppUtilities.applyStyle([slicer.app], self.resourcePath("BrachyPlan.qss"))
            self.styleThreeDWidget()
            self.styleSliceWidgets()
        except Exception as e:
            self.addLog(f"Error applying application style: {str(e)}", level="error")

    def styleThreeDWidget(self):
        """Style the 3D view widget."""
        try:
            viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        except Exception as e:
            logging.debug(f"Could not style 3D widget: {e}")

    def styleSliceWidgets(self):
        """Style all slice view widgets."""
        try:
            for name in slicer.app.layoutManager().sliceViewNames():
                sliceWidget = slicer.app.layoutManager().sliceWidget(name)
                self.styleSliceWidget(sliceWidget)
        except Exception as e:
            logging.debug(f"Could not style slice widgets: {e}")

    def styleSliceWidget(self, sliceWidget):
        """Style a single slice view widget.

        Args:
            sliceWidget: The slice widget to style.
        """
        try:
            controller = sliceWidget.sliceController()
        except Exception as e:
            logging.debug(f"Could not style slice widget: {e}")

    # ========================================================================
    # Needle Drag Monitoring & Replan
    # ========================================================================

    def _on_needle_modified(self, caller, event):
        """Callback when a Needle node is modified (e.g. dragged).

        Uses a QTimer debounce to detect drag end (200ms after last change).
        """
        line_node = caller
        if not line_node:
            return
        # Skip events during reset, from hidden nodes, or while dialog is open
        if getattr(self, '_suppress_needle_observer', False):
            return
        if getattr(self, '_replan_dialog_active', False):
            return
        displayNode = line_node.GetDisplayNode()
        if displayNode and not displayNode.GetVisibility():
            return
        node_id = line_node.GetID()
        current_start = [0, 0, 0]
        current_end = [0, 0, 0]
        line_node.GetNthControlPointPosition(0, current_start)
        line_node.GetNthControlPointPosition(1, current_end)
        if node_id not in self.logic._needle_original_positions:
            return
        # Skip if position matches the originalStart/originalEnd attributes (e.g., after reset)
        attr_start = line_node.GetAttribute("originalStart")
        attr_end = line_node.GetAttribute("originalEnd")
        if attr_start and attr_end:
            try:
                orig_s = [float(x) for x in attr_start.split(",")]
                orig_e = [float(x) for x in attr_end.split(",")]
                at_original = (all(abs(current_start[i] - orig_s[i]) < 0.5 for i in range(3)) and
                               all(abs(current_end[i] - orig_e[i]) < 0.5 for i in range(3)))
                if at_original:
                    return
            except (ValueError, IndexError):
                pass
        original = self.logic._needle_original_positions[node_id]
        start_changed = any(abs(current_start[i] - original["start"][i]) > 0.5 for i in range(3))
        end_changed = any(abs(current_end[i] - original["end"][i]) > 0.5 for i in range(3))
        if start_changed or end_changed:
            self.addLog(f"[OBSERVER] position changed for {line_node.GetName()}, starting timer")
            self._dragged_needle = line_node
            if hasattr(self, '_drag_check_timer'):
                self._drag_check_timer.stop()
            self._drag_check_timer = qt.QTimer()
            self._drag_check_timer.timeout.connect(self._check_drag_end)
            self._drag_check_timer.setSingleShot(True)
            self._drag_check_timer.start(200)

    def _check_drag_end(self):
        """Check if drag has ended and show replan dialog if position changed."""
        # Skip if observer is suppressed (e.g., during replan needle reconstruction)
        if getattr(self, '_suppress_needle_observer', False):
            self.addLog("[DRAG CHECK] suppressed, skipping")
            return
        line_node = self._dragged_needle
        if not line_node:
            self.addLog("[DRAG CHECK] no dragged needle, skipping")
            return
        node_id = line_node.GetID()
        current_start = [0, 0, 0]
        current_end = [0, 0, 0]
        line_node.GetNthControlPointPosition(0, current_start)
        line_node.GetNthControlPointPosition(1, current_end)
        original = self.logic._needle_original_positions.get(node_id, {})
        self.addLog(f"[DRAG CHECK] node={line_node.GetName()}, id={node_id}")
        self.addLog(f"[DRAG CHECK]   current_tip=[{current_end[0]:.1f},{current_end[1]:.1f},{current_end[2]:.1f}]")
        self.addLog(f"[DRAG CHECK]   current_tail=[{current_start[0]:.1f},{current_start[1]:.1f},{current_start[2]:.1f}]")
        self.addLog(f"[DRAG CHECK]   original_tip=[{original.get('end',[0,0,0])[0]:.1f},{original.get('end',[0,0,0])[1]:.1f},{original.get('end',[0,0,0])[2]:.1f}]")
        self.addLog(f"[DRAG CHECK]   original_tail=[{original.get('start',[0,0,0])[0]:.1f},{original.get('start',[0,0,0])[1]:.1f},{original.get('start',[0,0,0])[2]:.1f}]")
        self.addLog(f"[DRAG CHECK]   all_keys={list(self.logic._needle_original_positions.keys())}")
        if not original:
            return
        start_changed = any(abs(current_start[i] - original["start"][i]) > 0.5 for i in range(3))
        end_changed = any(abs(current_end[i] - original["end"][i]) > 0.5 for i in range(3))
        if start_changed or end_changed:
            self._show_replan_dialog(line_node)
            self.logic._needle_original_positions[node_id] = {"start": list(current_start), "end": list(current_end)}
        self._dragged_needle = None

    def _show_replan_dialog(self, line_node):
        """Show replan confirmation dialog after needle drag."""
        # Prevent duplicate dialogs from overlapping timer events
        if getattr(self, '_replan_dialog_active', False):
            return
        self._replan_dialog_active = True
        # Stop timer to prevent duplicate dialogs
        if hasattr(self, '_drag_check_timer'):
            self._drag_check_timer.stop()
        self.addLog(f"[DIALOG] showing replan dialog for {line_node.GetName()}")
        try:
            needle_index = int(line_node.GetName().split('_')[-1])
        except (ValueError, IndexError):
            needle_index = "?"
        message = (
            f"Needle {needle_index} has been manually adjusted.\n\n"
            f"Would you like to replan this needle?\n\n"
            f"This will:\n"
            f"1. Remove existing seeds on this needle\n"
            f"2. Recalculate seed positions along the new trajectory\n"
            f"3. Regenerate dose map and iso-surfaces\n\n"
            f"Select 'Cancel' to keep the needle at its current position.\n"
            f"You can drag again or replan later."
        )
        answer = slicer.util.confirmOkCancelDisplay(text=message, windowTitle="Replan Confirmation")
        if answer:
            self._execute_replan(needle_index, line_node)
        else:
            # Keep needle at current position — update stored original
            # so subsequent drags compare against the new position.
            current_start = [0, 0, 0]
            current_end = [0, 0, 0]
            line_node.GetNthControlPointPosition(0, current_end)
            line_node.GetNthControlPointPosition(1, current_start)
            node_id = line_node.GetID()
            self.logic._needle_original_positions[node_id] = {
                "start": list(current_start), "end": list(current_end)
            }
            line_node.SetAttribute("originalStart", f"{current_start[0]},{current_start[1]},{current_start[2]}")
            line_node.SetAttribute("originalEnd", f"{current_end[0]},{current_end[1]},{current_end[2]}")
        # Clear dragged needle reference after dialog closes
        self._dragged_needle = None
        self._replan_dialog_active = False

    def _reset_needle_to_original(self, line_node):
        """Reset the needle to its original position before drag.

        Uses originalStart/originalEnd attributes stored on the node.

        Args:
            line_node: The needle node to reset.
        """
        try:
            originalStart = line_node.GetAttribute("originalStart")
            originalEnd = line_node.GetAttribute("originalEnd")
            if originalStart and originalEnd:
                start_coords = [float(x) for x in originalStart.split(",")]
                end_coords = [float(x) for x in originalEnd.split(",")]
                # Temporarily suppress observer to prevent infinite loop
                self._suppress_needle_observer = True
                line_node.SetNthControlPointPosition(0, start_coords[0], start_coords[1], start_coords[2])
                line_node.SetNthControlPointPosition(1, end_coords[0], end_coords[1], end_coords[2])
                self._suppress_needle_observer = False
                self.addLog(f"Needle reset to original position")
            else:
                self.addLog(f"Warning: No original position stored for needle", level="warning")
        except Exception as e:
            self.addLog(f"Error resetting needle position: {str(e)}", level="error")

    def _execute_replan(self, needle_index, line_node):
        """Execute replan for a single Needle after manual drag.

        Workflow:
            1. Convert dragged needle RAS -> resampled IJK.
            2. Call Logic.execute_replan (uses put_seeds).
            3. Create new plan folder, copy old nodes, hide old plan.
            4. Rebuild dose volume, isodose, seed/needle markups.

        Args:
            needle_index: Index of the dragged needle.
            line_node: The dragged needle vtkMRMLMarkupsLineNode.
        """
        progressDialog = None
        try:
            if not self.logic._trajectory_info or needle_index >= len(self.logic._trajectory_info):
                self.addLog("No plan data available for replan.", level="error")
                return

            if self.logic._resampled_ct_image is None:
                self.addLog("Resampled image data not available for replan.", level="error")
                return

            # Show progress dialog
            progressDialog = createProgressDialog("Replanning needle...")
            progressDialog.setValue(5)
            slicer.app.processEvents()

            # Get Needle endpoints (RAS)
            end_pos = [0, 0, 0]    # Tip (inside body)
            start_pos = [0, 0, 0]  # Tail (outside body)
            line_node.GetNthControlPointPosition(0, end_pos)
            line_node.GetNthControlPointPosition(1, start_pos)

            # Direction in RAS: from tail to tip (inward)
            direction_ras = np.array(end_pos) - np.array(start_pos)
            norm = np.linalg.norm(direction_ras)
            if norm < 1e-6:
                self.addLog("Invalid needle direction.", level="error")
                return
            direction_ras = direction_ras / norm

            # Convert RAS -> resampled IJK
            # The dragged needle is in RAS space of the ORIGINAL CT.
            # Trajectories and seeds are in resampled IJK space (128x128xN).
            # Must use the RESAMPLED image's geometry for conversion.
            #
            # Resampled fMat = [D_res*S_res | O_res; 0 0 0 1]
            # Forward: RAS = fMat_res @ [ijk_res, 1] = D_res*S_res*ijk_res + O_res
            # Reverse: ijk_res = inv(fMat_res) @ [RAS, 1]
            #        = inv(D_res) * (RAS - O_res) / S_res
            inputVolume = self._parameterNode.GetNodeReference("InputVolume")
            if not inputVolume:
                self.addLog("No input volume for coordinate transform.", level="error")
                return

            resampled_image = self.logic._resampled_ct_image
            if resampled_image is None:
                self.addLog("No resampled CT image for coordinate transform.", level="error")
                return

            # Use resampled image's LPS geometry for coordinate conversion.
            # PullVolumeFromSlicer converts RAS to LPS, so the resampled image is in LPS.
            resampled_origin = np.array(resampled_image.GetOrigin())  # LPS
            resampled_spacing = np.array(resampled_image.GetSpacing())
            resampled_direction = np.array(resampled_image.GetDirection()).reshape(3, 3)  # LPS

            # Position: Slicer RAS -> LPS -> resampled IJK
            lps_pos = np.array([-end_pos[0], -end_pos[1], end_pos[2]])
            lps_minus_origin = lps_pos - resampled_origin
            v = (lps_minus_origin @ resampled_direction) / resampled_spacing
            new_start_ijk = v[::-1]  # [x,y,z] -> [z,y,x]

            # Direction: Slicer RAS -> LPS -> resampled IJK
            lps_dir = np.array([-direction_ras[0], -direction_ras[1], direction_ras[2]])
            v_dir = (lps_dir @ resampled_direction) / resampled_spacing
            ijk_direction = v_dir[::-1]  # [x,y,z] -> [z,y,x]
            ijk_norm = np.linalg.norm(ijk_direction)
            if ijk_norm < 1e-8:
                self.addLog("Invalid IJK direction after transform.", level="error")
                return
            ijk_direction = ijk_direction / ijk_norm

            # DEBUG: Log coordinate conversion
            self.addLog(f"[REPLAN DEBUG] RAS tip: [{end_pos[0]:.1f}, {end_pos[1]:.1f}, {end_pos[2]:.1f}]")
            self.addLog(f"[REPLAN DEBUG] new_start_ijk: [{new_start_ijk[0]:.1f}, {new_start_ijk[1]:.1f}, {new_start_ijk[2]:.1f}]")
            self.addLog(f"[REPLAN DEBUG] ijk_direction: [{ijk_direction[0]:.4f}, {ijk_direction[1]:.4f}, {ijk_direction[2]:.4f}]")

            # Check if new position is within CTV
            ctv_image = self.logic._resampled_ctv_image
            if ctv_image is not None:
                ctv_arr = sitk.GetArrayFromImage(ctv_image)
                ctv_shape = ctv_arr.shape
                self.addLog(f"[REPLAN DEBUG] CTV shape: {ctv_shape}")
                ijk_int = np.round(new_start_ijk).astype(int)
                # new_start_ijk is [z,y,x], ctv_shape is (z,y,x)
                in_bounds = all(0 <= ijk_int[d] < ctv_shape[d] for d in range(3))
                self.addLog(f"[REPLAN DEBUG] ijk_int: {ijk_int}, in_bounds: {in_bounds}")
                if in_bounds:
                    ctv_val = ctv_arr[ijk_int[0], ijk_int[1], ijk_int[2]]
                    self.addLog(f"[REPLAN DEBUG] CTV value at position: {ctv_val}")
                else:
                    self.addLog(f"[REPLAN DEBUG] Position OUT OF BOUNDS!")

            # Build new trajectory (reuse original depths from stored trajectory info)
            stored_traj = self.logic._trajectory_info[needle_index]["trajectory"]
            new_trajectory = [
                new_start_ijk.tolist(),
                ijk_direction.tolist(),
                stored_traj[2],  # target_depths
                stored_traj[3],  # background_depths
            ]

            # Load dose model (unloaded after original planning)
            progressDialog.setLabelText("Loading dose model...")
            progressDialog.setValue(20)
            slicer.app.processEvents()
            dose_model = self.logic._get_or_load_dose_model()

            # Call replan via Logic
            progressDialog.setLabelText("Replanning needle with put_seeds...")
            progressDialog.setValue(40)
            slicer.app.processEvents()
            self.addLog("Replanning needle with put_seeds...")
            plan_res, sum_array, success = self.logic.execute_replan(
                new_trajectory, needle_index
            )

            if not success or plan_res is None:
                self.addLog("Replan found no valid seed positions for this needle position.", level="warning")
                if progressDialog:
                    progressDialog.close()
                slicer.util.infoDisplay(
                    "No better seed position found for the adjusted needle.\n"
                    "You can continue dragging or right-click the needle in Data Tree to reset.",
                    windowTitle="Replan Result"
                )
                return

            progressDialog.setLabelText("Creating new plan folder...")
            progressDialog.setValue(60)
            slicer.app.processEvents()

            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            inputVolume = self._parameterNode.GetNodeReference("InputVolume")
            if not inputVolume:
                self.addLog("No input volume for replan.", level="error")
                return

            old_plan_folder = self.logic._current_plan_folder
            old_plan_name = self.logic._current_plan_folder_name

            # DEBUG: Log needle state BEFORE replan
            pre_start = [0, 0, 0]
            pre_end = [0, 0, 0]
            line_node.GetNthControlPointPosition(0, pre_end)
            line_node.GetNthControlPointPosition(1, pre_start)
            self.addLog(f"[REPLAN-DEBUG] BEFORE replan: node={line_node.GetName()}, id={line_node.GetID()}")
            self.addLog(f"[REPLAN-DEBUG]   tip(CP0)=[{pre_end[0]:.1f},{pre_end[1]:.1f},{pre_end[2]:.1f}]")
            self.addLog(f"[REPLAN-DEBUG]   tail(CP1)=[{pre_start[0]:.1f},{pre_start[1]:.1f},{pre_start[2]:.1f}]")
            self.addLog(f"[REPLAN-DEBUG]   _dragged_needle={getattr(self, '_dragged_needle', None)}")
            self.addLog(f"[REPLAN-DEBUG]   _suppress={getattr(self, '_suppress_needle_observer', False)}")

            # --- Step 0: Remove observer from dragged needle BEFORE any modifications ---
            # Prevents stale callbacks during folder copy/hide operations
            node_id = line_node.GetID()
            if node_id in self.logic._needle_observer_tags:
                tag = self.logic._needle_observer_tags.pop(node_id)
                line_node.RemoveObserver(tag)
            if hasattr(self.logic, '_observer_callbacks'):
                self.logic._observer_callbacks.pop(node_id, None)
            # Stop any pending drag timer and clear dragged needle reference
            if hasattr(self, '_drag_check_timer'):
                self._drag_check_timer.stop()
            self._dragged_needle = None

            # --- Step 1: Copy old plan folder to new plan folder, then hide old ---
            # _copy_folder_children moves the SAME MRML objects (not deep copy).
            # The needle stays at the dragged position in the new plan.
            # The old plan is hidden, so no visual change.
            self.logic._plan_counter += 1
            new_plan_folder = self.logic._create_plan_folder(self.logic._plan_counter)
            new_plan_name = f"Plan_{self.logic._plan_counter}"
            self._copy_folder_children(shNode, old_plan_folder, new_plan_folder)
            self._set_folder_visibility(shNode, old_plan_folder, False)

            # --- Step 3: In new plan folder, hide dragged needle's seeds and all iso_surfaces ---
            dragged_needle_name = line_node.GetName()  # e.g., "1_0"
            children = vtk.vtkIdList()
            shNode.GetItemChildren(new_plan_folder, children, True)
            for ci in range(children.GetNumberOfIds()):
                child_id = children.GetId(ci)
                data_node = shNode.GetItemDataNode(child_id)
                if not data_node:
                    continue
                name = data_node.GetName()
                # Hide dragged needle's seed fiducial (e.g., "Plan_1_CTV_seed_0")
                if "_seed_" in name and dragged_needle_name.split("_")[-1] in name:
                    shNode.SetItemDisplayVisibility(child_id, False)
                    if data_node.GetDisplayNode():
                        data_node.GetDisplayNode().SetVisibility(False)
                # Hide all iso_surfaces
                if name.startswith("IsoDose"):
                    shNode.SetItemDisplayVisibility(child_id, False)
                    if data_node.GetDisplayNode():
                        data_node.GetDisplayNode().SetVisibility(False)

            # --- Step 4: Replan only the dragged needle ---
            new_plan_name_prefix = f"Plan_{self.logic._plan_counter}"
            self.logic._current_plan_folder = new_plan_folder
            self.logic._current_plan_folder_name = new_plan_name_prefix
            self.logic._all_plan_folders.append(new_plan_folder)

            # Update _trajectory_info for dragged needle
            for i, res in enumerate(plan_res):
                seeds_voxel = []
                for seed in res[1]:
                    pos = np.array(seed[0]).reshape(-1)
                    direc = np.array(seed[1]).reshape(-1)
                    seeds_voxel.append((pos, direc))
                self.logic._trajectory_info[needle_index] = {
                    "trajectory": res[0],
                    "seeds_voxel": seeds_voxel,
                    "seed_radiations": list(res[2])
                }

            self.logic._current_plan_res = plan_res
            self.logic._current_radiation = sum_array

            # --- Step 5: Delete old seed node for dragged needle, create new one ---
            DIRECTION_REVERSAL_SIGN = -1
            fMat = vtk.vtkMatrix4x4()
            inputVolume.GetIJKToRASDirectionMatrix(fMat)

            # Find and remove old seed fiducial for dragged needle
            # Seed nodes are children of needle items in the SH hierarchy.
            # Walk up ancestors to check if the seed belongs to the new plan folder.
            needle_suffix = dragged_needle_name.split("_")[-1]  # e.g., "0"
            old_seed_node = None
            nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLMarkupsFiducialNode")
            for i in range(nodes.GetNumberOfItems()):
                node = nodes.GetItemAsObject(i)
                name = node.GetName()
                if "_seed_" in name and needle_suffix in name.split("_seed_")[-1]:
                    item_id = shNode.GetItemByDataNode(node)
                    if item_id:
                        # Check if this node is under the new plan folder (any ancestor level)
                        parent_id = shNode.GetItemParent(item_id)
                        while parent_id and parent_id != 0:
                            if parent_id == new_plan_folder:
                                old_seed_node = node
                                break
                            parent_id = shNode.GetItemParent(parent_id)
                    if old_seed_node:
                        break

            if old_seed_node:
                # Add new seeds to the existing needle line's fiducial
                needle_item = shNode.GetItemByDataNode(line_node)
                new_fiducial = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
                ctv_node = self._parameterNode.GetNodeReference("SegmentedVolume")
                ctv_name = ctv_node.GetName() if ctv_node else "CTV"
                new_fiducial.SetName(f"{new_plan_name_prefix}_{ctv_name}_seed_{needle_index}")
                new_fiducial.CreateDefaultDisplayNodes()
                new_fiducial.GetDisplayNode().SetPointLabelsVisibility(False)
                new_fiducial.GetDisplayNode().SetPropertiesLabelVisibility(False)
                new_fiducial.GetDisplayNode().SetTextScale(0.8)
                new_fiducial.SetLocked(True)
                new_fid_id = shNode.GetItemByDataNode(new_fiducial)
                shNode.SetItemParent(new_fid_id, needle_item if needle_item else new_plan_folder)

                replanned_seeds = plan_res[-1][1]  # Replanned needle is the LAST entry in plan_res
                # Seeds from replan_single_needle — use SAME transform as run_brachyPlan
                seed_positions_ras = []
                for j, seed in enumerate(replanned_seeds):
                    pos = np.array(seed[0]).reshape(-1)
                    transformedPos = [0, 0, 0, 1]
                    fMat.MultiplyPoint([pos[0], pos[1], pos[2], 1], transformedPos)
                    direction = np.array(seed[1]).reshape(-1)
                    ras_dir = [DIRECTION_REVERSAL_SIGN * direction[0],
                               DIRECTION_REVERSAL_SIGN * direction[1],
                               direction[2]]
                    seed_positions_ras.append((transformedPos[:3], ras_dir))
                    new_fiducial.AddControlPoint(transformedPos[:3])

                # Use the dragged needle direction directly as ground truth.
                # Deriving dir_vec from seed directions introduces small angular
                # errors that get amplified by DIRECTION_EXTENSION (100mm),
                # causing large needle displacement after replan.
                needle_dir = np.array(end_pos) - np.array(start_pos)
                needle_dir_norm = np.linalg.norm(needle_dir)
                if needle_dir_norm > 1e-6:
                    dir_vec = needle_dir / needle_dir_norm
                else:
                    # Fallback: use first seed's direction if needle has zero length
                    dir_vec = np.array(seed_positions_ras[0][1], dtype=np.float64)
                    norm = np.linalg.norm(dir_vec)
                    if norm > 1e-6:
                        dir_vec = dir_vec / norm
                    else:
                        dir_vec = np.array([0.0, 0.0, 1.0])

                # Create capsules with the computed direction
                if len(seed_positions_ras) >= 1:
                    for j, (pos_ras, _) in enumerate(seed_positions_ras):
                        self.logic.create_capsule_stl(j, new_fiducial, pos_ras, dir_vec)

                # Remove old seed fiducial
                slicer.mrmlScene.RemoveNode(old_seed_node)

                # Update needle line endpoints using the same dir_vec
                if len(seed_positions_ras) >= 1:
                    positions = np.array([p for p, _ in seed_positions_ras])
                    p0 = positions[0]

                    t_values = np.dot(positions - p0, dir_vec)
                    shallow_center = p0 + np.min(t_values) * dir_vec
                    deep_center = p0 + np.max(t_values) * dir_vec

                    new_start = shallow_center - (DIRECTION_EXTENSION * dir_vec)
                    new_end = deep_center + ((SEED_LENGTH / 2.0) * dir_vec)

                    self.addLog(f"[REBUILD] dir_vec=[{dir_vec[0]:.3f},{dir_vec[1]:.3f},{dir_vec[2]:.3f}]")
                    self.addLog(f"[REBUILD] shallow=[{shallow_center[0]:.1f},{shallow_center[1]:.1f},{shallow_center[2]:.1f}]")
                    self.addLog(f"[REBUILD] deep=[{deep_center[0]:.1f},{deep_center[1]:.1f},{deep_center[2]:.1f}]")
                    self.addLog(f"[REBUILD] new_end(tip)=[{new_end[0]:.1f},{new_end[1]:.1f},{new_end[2]:.1f}]")
                    self.addLog(f"[REBUILD] new_start(tail)=[{new_start[0]:.1f},{new_start[1]:.1f},{new_start[2]:.1f}]")

                    # Stop any pending drag timer before suppressing observer
                    if hasattr(self, '_drag_check_timer'):
                        self._drag_check_timer.stop()
                    self._suppress_needle_observer = True
                    line_node.SetNthControlPointPosition(0, *new_end)
                    line_node.SetNthControlPointPosition(1, *new_start)
                    line_node.SetAttribute("originalStart",
                                           f"{new_start[0]},{new_start[1]},{new_start[2]}")
                    line_node.SetAttribute("originalEnd",
                                           f"{new_end[0]},{new_end[1]},{new_end[2]}")
                    # Keep suppress active through processEvents to prevent observer interference
                    slicer.app.processEvents()
                    self._suppress_needle_observer = False

            # Also update the aggregated "Seed" fiducial node (name may still have old plan prefix)
            all_seed_node = None
            nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLMarkupsFiducialNode")
            for i in range(nodes.GetNumberOfItems()):
                node = nodes.GetItemAsObject(i)
                if node.GetName().endswith("_Seed") or node.GetName() == "Seed":
                    item_id = shNode.GetItemByDataNode(node)
                    if item_id:
                        parent_id = shNode.GetItemParent(item_id)
                        while parent_id and parent_id != 0:
                            if parent_id == new_plan_folder:
                                all_seed_node = node
                                break
                            parent_id = shNode.GetItemParent(parent_id)
                    if all_seed_node:
                        break

            if all_seed_node:
                # Rebuild aggregated Seed node from ALL needles' trajectory info
                all_seed_node.RemoveAllControlPoints()
                for info in self.logic._trajectory_info:
                    for seed_pos, seed_dir in info.get("seeds_voxel", []):
                        pos = np.array(seed_pos).reshape(-1)
                        transformedPos = [0, 0, 0, 1]
                        fMat.MultiplyPoint([pos[0], pos[1], pos[2], 1], transformedPos)
                        all_seed_node.AddControlPoint(transformedPos[:3])

            # --- Step 6: Delete old iso_surfaces, rebuild new ones ---
            progressDialog.setLabelText("Rebuilding dose volume and iso-surfaces...")
            progressDialog.setValue(80)
            slicer.app.processEvents()
            # Remove old isodose models in new plan folder
            model_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLModelNode")
            for i in range(model_nodes.GetNumberOfItems()):
                model_node = model_nodes.GetItemAsObject(i)
                if model_node.GetName().startswith("IsoDose"):
                    item_id = shNode.GetItemByDataNode(model_node)
                    if item_id and shNode.GetItemParent(item_id) == new_plan_folder:
                        slicer.mrmlScene.RemoveNode(model_node)

            # Remove old dose volume in new plan folder
            vol_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeNode")
            for i in range(vol_nodes.GetNumberOfItems()):
                vol_node = vol_nodes.GetItemAsObject(i)
                if vol_node.GetName().endswith("_RTDoseMap") or vol_node.GetName() == "RTDoseMap":
                    item_id = shNode.GetItemByDataNode(vol_node)
                    if item_id and shNode.GetItemParent(item_id) == new_plan_folder:
                        slicer.mrmlScene.RemoveNode(vol_node)

            # Rebuild dose volume and iso_surfaces
            self._rebuild_dose_volume(sum_array, inputVolume, shNode, new_plan_folder)

            # Recompute DVH analysis for the new dose distribution
            try:
                new_dose_name = self.logic._get_plan_node_name("RTDoseMap")
                new_dose_node = slicer.util.getNode(new_dose_name)
                if new_dose_node:
                    self.compute_and_save_dvh(inputVolume, new_dose_node)
            except Exception as e:
                self.addLog(f"DVH update after replan: {str(e)}", level="warning")

            # Update needle original position from current (possibly reconstructed) endpoints
            node_id = line_node.GetID()
            final_start = [0, 0, 0]
            final_end = [0, 0, 0]
            line_node.GetNthControlPointPosition(0, final_end)
            line_node.GetNthControlPointPosition(1, final_start)
            self.logic._needle_original_positions[node_id] = {
                "start": list(final_start), "end": list(final_end)
            }
            line_node.SetAttribute("originalStart", f"{final_start[0]},{final_start[1]},{final_start[2]}")
            line_node.SetAttribute("originalEnd", f"{final_end[0]},{final_end[1]},{final_end[2]}")

            # DEBUG: Final state after replan
            self.addLog(f"[REPLAN-DEBUG] FINAL state after replan:")
            self.addLog(f"[REPLAN-DEBUG]   node_id={node_id}, node_name={line_node.GetName()}")
            self.addLog(f"[REPLAN-DEBUG]   _needle_original_positions[{node_id}]={self.logic._needle_original_positions.get(node_id)}")
            self.addLog(f"[REPLAN-DEBUG]   _dragged_needle={getattr(self, '_dragged_needle', None)}")

            # Stop any pending drag timer and clear state before re-registering observer
            if hasattr(self, '_drag_check_timer'):
                self._drag_check_timer.stop()
            self._dragged_needle = None

            # Suppress observer briefly during re-registration to prevent spurious events
            self._suppress_needle_observer = True
            self.logic._setup_needle_observer(line_node)
            slicer.app.processEvents()  # Process any pending events while suppressed
            self._suppress_needle_observer = False
            self.addLog(f"[REPLAN-DEBUG] Observer re-registered for {line_node.GetName()}")

            # Unload dose model
            self.logic._unload_dose_model()

            progressDialog.setValue(100)
            self.addLog(f"Replan completed for Needle {needle_index}")
            # DEBUG: Final verification
            verify = [0, 0, 0]
            line_node.GetNthControlPointPosition(0, verify)
            self.addLog(f"[REPLAN-DEBUG] VERIFICATION: tip(CP0) after replan = [{verify[0]:.1f},{verify[1]:.1f},{verify[2]:.1f}]")
            self.addLog(f"[REPLAN-DEBUG] VERIFICATION: _needle_original_positions = {self.logic._needle_original_positions}")

        except Exception as e:
            self.addLog(f"Replan failed: {str(e)}", level="error")
            import traceback
            self.addLog(traceback.format_exc(), level="error")
        finally:
            if progressDialog:
                progressDialog.close()

    def _copy_folder_children(self, shNode, src_folder, dst_folder):
        """Copy all child items from src folder to dst folder in Subject Hierarchy.

        Args:
            shNode: SubjectHierarchyNode.
            src_folder: Source folder item ID.
            dst_folder: Destination folder item ID.
        """
        children = vtk.vtkIdList()
        shNode.GetItemChildren(src_folder, children)
        for i in range(children.GetNumberOfIds()):
            child_id = children.GetId(i)
            shNode.SetItemParent(child_id, dst_folder)

    def _set_folder_visibility(self, shNode, folder_item_id, visible):
        """Set visibility of a Subject Hierarchy folder and all its contents.

        Args:
            shNode: SubjectHierarchyNode.
            folder_item_id: Folder item ID.
            visible: True to show, False to hide.
        """
        # Set folder visibility via SubjectHierarchy
        shNode.SetItemDisplayVisibility(folder_item_id, visible)
        # Also set visibility on all descendant data nodes' display nodes
        # (needed because folder visibility doesn't always propagate)
        children = vtk.vtkIdList()
        shNode.GetItemChildren(folder_item_id, children, True)  # True = recursive
        for i in range(children.GetNumberOfIds()):
            child_id = children.GetId(i)
            shNode.SetItemDisplayVisibility(child_id, visible)
            data_node = shNode.GetItemDataNode(child_id)
            if data_node and hasattr(data_node, 'GetDisplayNode'):
                dn = data_node.GetDisplayNode()
                if dn:
                    dn.SetVisibility(visible)

    def _hide_plan_folder_contents(self, shNode, folder_item_id):
        """Hide all contents of a plan folder (used after copying old plan).

        Args:
            shNode: SubjectHierarchyNode.
            folder_item_id: Plan folder item ID.
        """
        self._set_folder_visibility(shNode, folder_item_id, False)

    def _rebuild_dose_volume(self, sum_array, inputVolume, shNode, plan_folder):
        """Rebuild dose volume from cumulative radiation array.

        Args:
            sum_array: Cumulative dose array (float32, resampled space).
            inputVolume: Original CT volume for geometry reference.
            shNode: SubjectHierarchyNode.
            plan_folder: Plan folder item ID.
        """
        try:
            import SimpleITK as sitk
            args = self.logic._current_plan_args
            myspacing = self.logic._resampled_ct_image.GetSpacing()
            myorigin = self.logic._resampled_ct_image.GetOrigin()
            dimension = inputVolume.GetImageData().GetDimensions()

            dose_ = sitk.GetImageFromArray(sum_array)
            dose_.SetSpacing(myspacing)
            dose_ = self.logic.image_resample_size(dose_, dimension)
            dose_array_gy = sitk.GetArrayFromImage(dose_).astype(np.float64) * DOSE_SCALE_FACTOR

            dose_name = self.logic._get_plan_node_name("RTDoseMap")
            dose_node = slicer.util.addVolumeFromArray(
                dose_array_gy, nodeClassName="vtkMRMLScalarVolumeNode"
            )
            del dose_array_gy

            spacing = inputVolume.GetSpacing()
            origin = inputVolume.GetOrigin()
            fMat = vtk.vtkMatrix4x4()
            inputVolume.GetIJKToRASDirectionMatrix(fMat)

            dose_node.SetSpacing(spacing)
            dose_node.SetOrigin(origin)
            dose_node.SetIJKToRASDirectionMatrix(fMat)

            dose_node.SetAttribute("DicomRtImport.DoseVolume", "1")

            doseID = shNode.GetItemByDataNode(dose_node)
            shNode.SetItemParent(doseID, plan_folder)
            shNode.SetItemName(doseID, dose_name)

            # Move dose volume to study level (same as normal plan) so it appears in 2D views
            volume1ItemID = shNode.GetItemByDataNode(inputVolume)
            studyItemID = shNode.GetItemAncestorAtLevel(volume1ItemID, "Study")
            if studyItemID and studyItemID != 0:
                shNode.SetItemParent(doseID, studyItemID)

            # Configure display
            displayNode = dose_node.GetScalarVolumeDisplayNode()
            if displayNode:
                try:
                    colorNodeID = slicer.modules.colors.logic().GetPETColorNodeID(
                        slicer.vtkMRMLPETProceduralColorNode.PETrainbow2
                    )
                    if colorNodeID:
                        displayNode.SetAndObserveColorNodeID(colorNodeID)
                    displayNode.AutoWindowLevelOff()
                    displayNode.SetWindow(600)
                    displayNode.SetLevel(300)
                    scalarRange = dose_node.GetImageData().GetScalarRange()
                    displayNode.SetLowerThreshold(0)
                    displayNode.SetUpperThreshold(scalarRange[1])
                    displayNode.Modified()
                except Exception:
                    pass

            # Overlay dose on CT (same as normal plan: overlay_dose_on_ct)
            # Sets CT as background, dose as foreground, and initializes opacity slider
            self.overlay_dose_on_ct(inputVolume, dose_node, opacity=0.5)

            # Show color legend (MUST be after overlay_dose_on_ct — see _show_dose_legend docstring)
            self._show_dose_legend(dose_node)

            # Create isodose surfaces
            args_iso = args.iso_dose_params
            self.logic.create_isodose_surface(
                dose_node, inputVolume,
                args_iso["iso_dose_values"], args_iso["iso_colors"],
                args_iso["iso_opacities"], model_name="IsoDose"
            )
            # Move isodose models to plan folder
            model_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLModelNode")
            for i in range(model_nodes.GetNumberOfItems()):
                model_node = model_nodes.GetItemAsObject(i)
                name = model_node.GetName()
                if name.startswith("IsoDose"):
                    modelItemID = shNode.GetItemByDataNode(model_node)
                    if modelItemID:
                        shNode.SetItemParent(modelItemID, plan_folder)

            self.addLog("Dose volume and isodose surfaces rebuilt.")
        except Exception as e:
            self.addLog(f"Error rebuilding dose volume: {str(e)}", level="error")

    def _rebuild_seed_needle_markups(self, plan_res, inputVolume, shNode, plan_folder):
        """Rebuild seed fiducial and needle line markups from plan result.

        Args:
            plan_res: Plan result list of [trajectory, seeds_world, seed_radiations].
                Seeds are in world/physical coordinates (from position_transform).
            inputVolume: Original CT volume for coordinate transform.
            shNode: SubjectHierarchyNode.
            plan_folder: Plan folder item ID.
        """
        try:
            DIRECTION_REVERSAL_SIGN = -1

            # Use the SAME fMat as run_brachyPlan: inputVolume.GetIJKToRASDirectionMatrix
            fMat = vtk.vtkMatrix4x4()
            inputVolume.GetIJKToRASDirectionMatrix(fMat)

            ctv_node = self._parameterNode.GetNodeReference("SegmentedVolume")
            ctv_name = ctv_node.GetName() if ctv_node else "CTV"

            # Create single fiducial node for all seeds
            fiducialNode_all = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
            fiducialNode_all.SetName(self.logic._get_plan_node_name("Seed"))
            fiducialNode_all.CreateDefaultDisplayNodes()
            fiducialNode_all.GetDisplayNode().SetPointLabelsVisibility(False)
            fiducialNode_all.GetDisplayNode().SetPropertiesLabelVisibility(False)
            fiducialNode_all.GetDisplayNode().SetTextScale(0.8)
            fiducialNode_all.SetLocked(True)
            seedAllID = shNode.GetItemByDataNode(fiducialNode_all)
            shNode.SetItemParent(seedAllID, plan_folder)

            for i, res in enumerate(plan_res):
                seeds = res[1]
                if not seeds:
                    continue

                # Create needle line node
                lineNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode")
                lineNode.SetName(f"{self.logic._plan_counter}_{i}")
                lineNode.CreateDefaultDisplayNodes()
                displayNode = lineNode.GetDisplayNode()
                if displayNode:
                    displayNode.SetPointLabelsVisibility(True)
                    displayNode.SetPropertiesLabelVisibility(False)
                    displayNode.SetTextScale(2.4)
                    displayNode.SetVisibility(True)
                try:
                    lineNode.RemoveAllMeasurements()
                except Exception:
                    pass
                lineID = shNode.GetItemByDataNode(lineNode)
                shNode.SetItemParent(lineID, plan_folder)
                shNode.SetItemDisplayVisibility(lineID, True)

                # Create seed fiducial node for this needle
                fiducialNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
                fiducialNode.SetName(self.logic._get_plan_node_name(f"{ctv_name}_seed_{i}"))
                fiducialNode.GetDisplayNode().SetPointLabelsVisibility(False)
                fiducialNode.GetDisplayNode().SetPropertiesLabelVisibility(False)
                fiducialNode.GetDisplayNode().SetTextScale(0.8)
                fiducialNode.SetLocked(True)
                pointsID = shNode.GetItemByDataNode(fiducialNode)
                shNode.SetItemParent(pointsID, lineID)

                # Add seed positions
                seed_positions = []
                for j, seed in enumerate(seeds):
                    pos = np.array(seed[0]).reshape(-1)
                    transformedPos = [0, 0, 0, 1]
                    fMat.MultiplyPoint([pos[0], pos[1], pos[2], 1], transformedPos)

                    direction = np.array(seed[1]).reshape(-1)
                    direction = [DIRECTION_REVERSAL_SIGN * direction[0],
                                 DIRECTION_REVERSAL_SIGN * direction[1],
                                 direction[2]]

                    fiducialNode_all.AddControlPoint(transformedPos[:3])
                    seed_positions.append((transformedPos[:3], direction))

                    self.logic.create_capsule_stl(j, fiducialNode, transformedPos[:3], direction)

                # Create needle line from seed positions
                if len(seed_positions) >= 1:
                    positions = np.array([pos for pos, _ in seed_positions])
                    p0 = positions[0]
                    dir_vec = np.array(seed_positions[0][1], dtype=np.float64)
                    norm = np.linalg.norm(dir_vec)
                    if norm > 1e-6:
                        dir_vec = dir_vec / norm
                    else:
                        dir_vec = np.array([0.0, 0.0, 1.0])

                    t_values = np.dot(positions - p0, dir_vec)
                    shallow_center = p0 + np.min(t_values) * dir_vec
                    deep_center = p0 + np.max(t_values) * dir_vec

                    start_point = shallow_center - (DIRECTION_EXTENSION * dir_vec)
                    end_point = deep_center + ((SEED_LENGTH / 2.0) * dir_vec)

                    lineNode.AddControlPoint(*end_point)
                    lineNode.AddControlPoint(*start_point)
                    lineNode.SetAttribute("lineIndex", str(i))
                    lineNode.SetAttribute("originalStart",
                                          f"{start_point[0]},{start_point[1]},{start_point[2]}")
                    lineNode.SetAttribute("originalEnd",
                                          f"{end_point[0]},{end_point[1]},{end_point[2]}")

                    if displayNode:
                        displayNode.SetColor(0, 1, 0)

                # Register needle drag observer
                self.logic._setup_needle_observer(lineNode)

            self.addLog(f"Rebuilt {len(plan_res)} needle markups with seeds.")
        except Exception as e:
            self.addLog(f"Error rebuilding seed/needle markups: {str(e)}", level="error")

    def _update_replan_visualization(self, modified_needle_index, new_radiation):
        """Update visualization after a successful replan.

        Removes old needle/seeds/dose/isosurfaces and recreates them
        with the updated plan data.

        Args:
            modified_needle_index: Index of the replanned needle.
            new_radiation: Updated cumulative radiation array.
        """
        try:
            inputVolume = self._parameterNode.GetNodeReference("InputVolume")
            if not inputVolume:
                return
            fMat = vtk.vtkMatrix4x4()
            inputVolume.GetIJKToRASDirectionMatrix(fMat)

            # Remove old needle and seeds for this index
            self._remove_needle_visualization(modified_needle_index)

            # Recreate needle and seeds
            self._recreate_needle_and_seeds(modified_needle_index, fMat)

            # Update dose map
            self._recreate_dose_map(new_radiation, inputVolume)

            self.addLog(f"Visualization updated for Needle {modified_needle_index}")
        except Exception as e:
            self.addLog(f"Error updating replan visualization: {str(e)}", level="error")

    def _remove_needle_visualization(self, needle_index):
        """Remove visualization nodes for a specific needle.

        Args:
            needle_index: Index of the needle to remove.
        """
        try:
            # Remove Needle line node
            needle_name = self.logic._get_plan_node_name(f"Needle_{needle_index}")
            try:
                needle_node = slicer.util.getNode(needle_name)
                slicer.mrmlScene.RemoveNode(needle_node)
            except slicer.MRMLNodeNotFoundException:
                pass

            # Remove seed fiducial nodes for this needle
            ctv_node = self._parameterNode.GetNodeReference("SegmentedVolume")
            ctv_name = ctv_node.GetName() if ctv_node else "CTV"
            seed_name = self.logic._get_plan_node_name(f"{ctv_name}_seed_{needle_index}")
            try:
                seed_node = slicer.util.getNode(seed_name)
                slicer.mrmlScene.RemoveNode(seed_node)
            except slicer.MRMLNodeNotFoundException:
                pass
        except Exception as e:
            self.addLog(f"Error removing needle visualization: {str(e)}", level="warning")

    def _recreate_needle_and_seeds(self, needle_index, fMat):
        """Recreate a needle and its seeds from trajectory info.

        Args:
            needle_index: Index of the needle to recreate.
            fMat: IJK to RAS direction matrix.
        """
        try:
            info = self.logic._trajectory_info[needle_index]
            seeds = info["seeds"]
            if not seeds:
                return

            DIRECTION_REVERSAL_SIGN = -1

            # Create Needle line
            lineNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode")
            lineNode.SetName(self.logic._get_plan_node_name(f"Needle_{needle_index}"))
            lineNode.CreateDefaultDisplayNodes()

            # Calculate needle endpoints from seeds
            seed_positions = []
            for seed in seeds:
                pos = np.array(seed[0]).reshape(-1)
                transformedPos = [0, 0, 0, 1]
                fMat.MultiplyPoint([pos[0], pos[1], pos[2], 1], transformedPos)
                direction = np.array(seed[1]).reshape(-1)
                direction = [DIRECTION_REVERSAL_SIGN * direction[0],
                             DIRECTION_REVERSAL_SIGN * direction[1],
                             direction[2]]
                seed_positions.append((transformedPos[:3], direction))

            positions = np.array([pos for pos, _ in seed_positions])
            p0 = positions[0]
            dir_vec = np.array(seed_positions[0][1], dtype=np.float64)
            dir_vec = dir_vec / np.linalg.norm(dir_vec)

            t_values = np.dot(positions - p0, dir_vec)
            t_min, t_max = np.min(t_values), np.max(t_values)

            start_point = p0 + t_min * dir_vec - (DIRECTION_EXTENSION * dir_vec)
            end_point = p0 + t_max * dir_vec + ((SEED_LENGTH / 2.0) * dir_vec)

            lineNode.AddControlPoint(*end_point)
            lineNode.AddControlPoint(*start_point)
            lineNode.SetAttribute("originalStart", f"{start_point[0]},{start_point[1]},{start_point[2]}")
            lineNode.SetAttribute("originalEnd", f"{end_point[0]},{end_point[1]},{end_point[2]}")

            # Set parent to current plan folder
            if self.logic._current_plan_folder:
                shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                lineID = shNode.GetItemByDataNode(lineNode)
                shNode.SetItemParent(lineID, self.logic._current_plan_folder)

            # Setup drag observer
            self.logic._setup_needle_observer(lineNode)
        except Exception as e:
            self.addLog(f"Error recreating needle {needle_index}: {str(e)}", level="error")

    def _recreate_dose_map(self, new_radiation, inputVolume):
        """Recreate the dose map from updated radiation data.

        Args:
            new_radiation: Updated cumulative radiation array.
            inputVolume: The input CT volume node for geometry reference.
        """
        try:
            # new_radiation is the cumulative dose array from seed dose summation
            dose_array = new_radiation.astype(np.float32)

            # Update dose volume
            dose_name = self.logic._get_plan_node_name("RTDoseMap")
            try:
                dose_node = slicer.util.getNode(dose_name)
            except slicer.MRMLNodeNotFoundException:
                dose_node = None

            if dose_node:
                # Update existing
                slicer.util.updateVolumeFromArray(dose_node, dose_array)
                dose_node.CopyDirections(inputVolume)
                dose_node.SetOrigin(inputVolume.GetOrigin())
                dose_node.SetSpacing(inputVolume.GetSpacing())
            else:
                # Create new
                dose_node = slicer.util.addVolumeFromArray(
                    dose_array,
                    nodeName=dose_name,
                    origin=inputVolume.GetOrigin(),
                    spacing=inputVolume.GetSpacing(),
                )
                dose_node.CopyDirections(inputVolume)
                if self.logic._current_plan_folder:
                    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
                    doseID = shNode.GetItemByDataNode(dose_node)
                    shNode.SetItemParent(doseID, self.logic._current_plan_folder)

            # Update dose overlay
            self.overlay_dose_on_ct(inputVolume, dose_node)
        except Exception as e:
            self.addLog(f"Error recreating dose map: {str(e)}", level="error")

class BrachyPlanLogic(ScriptedLoadableModuleLogic):
    """Implements the underlying logic for the BrachyPlan module.

    Handles segmentation task dispatching, brachytherapy plan execution,
    dose visualization, seed model creation, and image resampling.

    Attributes:
        logCallback: Optional callback function for UI log messages.
        segTaskFunctionMap: Dictionary mapping task names to their config.
        segTasks: List of available segmentation task names.
        _current_base_nifti_path: Path to the last generated base NIfTI.
        _dose_model: Cached dose prediction model instance.
        _dose_model_path: Path to the loaded dose model weights.
    """

    def __init__(self):
        """Initialize the BrachyPlan logic class."""
        ScriptedLoadableModuleLogic.__init__(self)
        self.logCallback = None
        self._segmentation_in_progress = False
        self.segTaskFunctionMap = {
            "Total": {
                "function": self._run_total_segmentation,
                "label_value": None,
                "color": [0.0, 0.0, 0.0],
            },
            "Head and Neck Tumor": {
                "function": self._run_head_neck_tumor_segmentation,
                "label_value": 200,
                "color": [0.8, 0.2, 0.2],
            },
            "Pancreatic Tumor": {
                "function": self._run_pancreatic_tumor_segmentation,
                "label_value": 201,
                "color": [0.9, 0.7, 0.0],
            },
            "Prostate Tumor": {
                "function": self._run_prostate_tumor_segmentation,
                "label_value": 202,
                "color": [0.0, 0.8, 0.0],
            },
            "Liver Tumor": {
                "function": self._run_liver_tumor_segmentation,
                "label_value": 203,
                "color": [0.8, 0.0, 0.8],
            },
            "Skin": {
                "function": self._run_skin_segmentation,
                "label_value": 204,
                "color": [1.0, 0.9, 0.8],
            },
        }
        self.segTasks = list(self.segTaskFunctionMap.keys())
        self._current_base_nifti_path = None
        self._dose_model = None
        self._dose_model_path = None
        # Plan hierarchy management
        self._plan_counter = 0
        self._current_plan_folder = None
        self._current_plan_folder_name = None
        self._all_plan_folders = []
        # Replan data
        self._trajectory_info = []
        self._current_plan_res = None
        self._current_plan_args = None
        self._current_radiation = None
        self._current_radiation_volume = None
        self._current_dose_image = None
        self._resampled_ct_image = None
        self._resampled_ctv_image = None
        # Needle drag monitoring
        self._needle_observer_tags = {}
        self._needle_original_positions = {}
        self._dragged_needle = None

    def log(self, text, level='info'):
        """Log a message to both the system logger and the UI callback.

        Args:
            text: Message text to log.
            level: Logging level ('info', 'error', etc.). Defaults to 'info'.
        """
        if level == 'error':
            logging.error(text)
        else:
            logging.info(text)

        if self.logCallback:
            try:
                self.logCallback(text, level=level)
            except TypeError:
                self.logCallback(text)

    def getDefaultPlanningParams(self):
        """Get default planning parameters from the config settings.

        Returns:
            argparse.Namespace: Default planning parameters.
        """
        return setting()

    def _get_or_load_dose_model(self):
        """Get the cached dose model, loading it if necessary.

        Returns:
            DoseUNet: The loaded spacing-normalized dose prediction model in eval mode.

        Raises:
            RuntimeError: If the model file does not exist or fails to load.
        """
        from plans.dose_pre.model_loader import resolve_dose_model_path

        resolved_path = resolve_dose_model_path()
        if resolved_path and self._dose_model is not None and self._dose_model_path == str(resolved_path):
            return self._dose_model

        self.log("Loading dose prediction model...")
        dose_model, model_error, model_path = load_dose_model(device="cpu")
        if dose_model is None:
            raise RuntimeError(model_error or "dose_unet_spacing1mm model could not be loaded")

        self._dose_model = dose_model
        self._dose_model_path = model_path
        return dose_model
    
    def _unload_dose_model(self):
        """Unload the dose model to free memory."""
        if self._dose_model is not None:
            del self._dose_model
            self._dose_model = None
            self._dose_model_path = None
            gc.collect()
            self.log("Dose prediction model unloaded from memory.")

    def _find_totalsegmentator_exe(self):
        """Locate the TotalSegmentator executable.

        Returns:
            str: Path to the TotalSegmentator executable.

        Raises:
            RuntimeError: If TotalSegmentator is not found.
        """
        ts_exe = shutil.which("TotalSegmentator")

        if not ts_exe:
            python_dir = os.path.dirname(self._get_python_executable())
            candidate = os.path.join(python_dir, "TotalSegmentator")
            if os.path.exists(candidate):
                ts_exe = candidate

        if not ts_exe:
            raise RuntimeError(
                "TotalSegmentator CLI not found. Please install it via: pip install totalsegmentator"
            )
        return ts_exe

    def _get_python_executable(self):
        """Get the packaged Python executable path for subprocess calls.

        In 3D Slicer, sys.executable points to PythonSlicer.exe which may not
        be on PATH. sys.prefix and shutil.which may find a DIFFERENT system
        Python (e.g. C:/Python314) causing SRE module mismatch.

        The only reliable anchor is __file__ of this module:
          <app>/r/Zhiyuan-build/lib/Zhiyuan-5.9/qt-scripted-modules/BrachyPlan.py
        python.exe is at:
          <app>/r/Zhiyuan-build/lib/Python/bin/python.exe

        IMPORTANT: Use python.exe, NOT PythonSlicer.exe. PythonSlicer.exe is a
        CTK launcher that reads .ini files and OVERRIDES PYTHONHOME with a wrong
        path (bin/lib/Python instead of lib/Python). python.exe respects the
        PYTHONHOME env var we set in _get_clean_subprocess_env.

        Returns:
            str: Path to the packaged python.exe.

        Raises:
            RuntimeError: If no packaged Python executable is found.
        """
        # Primary: derive from __file__ (always correct in packaged env)
        # __file__ = <app>/r/Zhiyuan-build/lib/Zhiyuan-5.9/qt-scripted-modules/BrachyPlan.py
        # python.exe = <app>/r/Zhiyuan-build/lib/Python/bin/python.exe
        # Need "..", ".." to go from qt-scripted-modules -> Zhiyuan-5.9 -> lib
        module_dir = os.path.dirname(os.path.abspath(__file__))
        exe_name = "python.exe" if os.name == "nt" else "python3"

        # Packaged environment: lib/Python/bin/python.exe
        packaged_dir = os.path.normpath(os.path.join(module_dir, "..", "..", "Python", "bin"))
        python_exe = os.path.join(packaged_dir, exe_name)
        if os.path.isfile(python_exe):
            return python_exe

        # Development environment: r/python-install/bin/python.exe
        # module_dir = r/Slicer-build/lib/Zhiyuan-5.9/qt-scripted-modules
        # python.exe = r/python-install/bin/python.exe
        dev_dir = os.path.normpath(os.path.join(module_dir, "..", "..", "..", "..", "python-install", "bin"))
        python_exe = os.path.join(dev_dir, exe_name)
        if os.path.isfile(python_exe):
            return python_exe

        raise RuntimeError(
            "Packaged Python not found. Searched: {!r} and {!r}".format(
                os.path.join(packaged_dir, exe_name),
                os.path.join(dev_dir, exe_name)
            )
        )

    def _get_clean_subprocess_env(self):
        """Get a clean environment for subprocess calls.

        PythonSlicer.exe computes PYTHONHOME relative to its own directory,
        which resolves incorrectly (bin/lib/Python instead of lib/Python).
        We must explicitly set PYTHONHOME to the correct packaged Python root.

        Also adds bin/Release to PATH so that SimpleITK DLLs can be found
        by the Python extension modules (.pyd files).

        Returns:
            dict: Clean environment variables with correct PYTHONHOME and PATH.
        """
        env = os.environ.copy()
        for var in ("PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE"):
            env.pop(var, None)

        # Set correct PYTHONHOME
        # Packaged: <app>/r/Zhiyuan-build/lib/Python
        # Dev:      <app>/r/python-install
        module_dir = os.path.dirname(os.path.abspath(__file__))
        packaged_home = os.path.normpath(os.path.join(
            module_dir, "..", "..", "Python"
        ))
        dev_home = os.path.normpath(os.path.join(
            module_dir, "..", "..", "..", "..", "python-install"
        ))
        python_home = packaged_home if os.path.isdir(packaged_home) else dev_home
        env["PYTHONHOME"] = python_home

        # Add bin/Release to PATH so SimpleITK DLLs can be found by
        # subprocess and its background workers (multiprocessing.spawn).
        # Packaged: <app>/r/Zhiyuan-build/bin/Release/
        # Dev:      <app>/r/Slicer-build/bin/Release/
        packaged_bin = os.path.normpath(os.path.join(
            module_dir, "..", "..", "..", "bin", "Release"
        ))
        dev_bin = os.path.normpath(os.path.join(
            module_dir, "..", "..", "..", "..", "bin", "Release"
        ))
        bin_release = packaged_bin if os.path.isdir(packaged_bin) else dev_bin
        if os.path.isdir(bin_release):
            existing_path = env.get("PATH", "")
            env["PATH"] = bin_release + (os.pathsep + existing_path if existing_path else "")
            existing_lp = env.get("LibraryPaths", "")
            env["LibraryPaths"] = bin_release + (os.pathsep + existing_lp if existing_lp else "")

        return env

    def _get_totalseg_weights_path(self):
        """Get the TotalSegmentator weights path.

        Returns:
            str: Path to the weights directory.
        """
        if "TOTALSEG_WEIGHTS_PATH" in os.environ:
            return os.environ["TOTALSEG_WEIGHTS_PATH"]
        module_dir = os.path.dirname(__file__)
        return os.path.join(module_dir, "plans", "seg", "total")

    def _get_device_str(self):
        """Get the device string for TotalSegmentator.

        Returns:
            str: 'gpu' if CUDA is available, 'cpu' otherwise.
        """
        device = self.getDefaultPlanningParams().dl_params["device"]
        if "cuda" not in str(device):
            return "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                return "gpu"
            self.log("  CUDA requested but not available, falling back to CPU", level="warning")
            return "cpu"
        except Exception:
            self.log("  Cannot check CUDA availability, falling back to CPU", level="warning")
            return "cpu"

    def _check_gpu_memory(self, required_mb=4000):
        """Check if GPU has enough free memory for inference.

        Args:
            required_mb (int): Minimum required free memory in MB.

        Returns:
            bool: True if sufficient memory or cannot check, False if insufficient.
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return True
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            free_mb = free_bytes / (1024 ** 2)
            return free_mb >= required_mb
        except Exception:
            return True

    def _process_oar_volumes(self, oar_volumes, input_volume, target_size, oar_value):
        """Process multiple OAR volumes into a single combined labelmap.

        Each OAR volume is processed to extract visible segments, then all segments
        are remapped to the specified oar_value and combined into a single labelmap.

        Args:
            oar_volumes: List of vtkMRMLLabelMapVolumeNode or vtkMRMLSegmentationNode.
            input_volume: Reference volume for spatial alignment.
            target_size: Target size for resampling (e.g., [128, 128, 64]).
            oar_value: The label value to use for all OAR voxels.

        Returns:
            numpy.ndarray: Combined and resampled OAR labelmap, or None if no valid OARs.
        """
        if not oar_volumes:
            return None

        combined_oar = None
        temp_nodes = []

        for idx, oar_vol in enumerate(oar_volumes):
            if oar_vol is None:
                continue

            try:
                current_oar = None

                if isinstance(oar_vol, slicer.vtkMRMLSegmentationNode):
                    visibleSegmentIDs = vtk.vtkStringArray()
                    segmentation = oar_vol.GetSegmentation()
                    allSegmentIDs = vtk.vtkStringArray()
                    segmentation.GetSegmentIDs(allSegmentIDs)

                    display_node = oar_vol.GetDisplayNode()
                    if display_node is None:
                        oar_vol.CreateDefaultDisplayNodes()
                        display_node = oar_vol.GetDisplayNode()

                    visible_count = 0
                    for i in range(allSegmentIDs.GetNumberOfValues()):
                        segmentID = allSegmentIDs.GetValue(i)
                        if display_node:
                            is_visible = display_node.GetSegmentVisibility(segmentID)
                        else:
                            is_visible = True
                        if is_visible:
                            visibleSegmentIDs.InsertNextValue(segmentID)
                            visible_count += 1

                    if visible_count == 0:
                        self.log(f"  OAR volume {idx}: no visible segments, skipping")
                        continue

                    self.log(f"  Processing OAR volume {idx}: {visible_count} visible segments")

                    oarLabelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                    oarLabelMapNode.SetName(f"OAR_Temp_{idx}_{uuid.uuid4().hex[:8]}")
                    temp_nodes.append(oarLabelMapNode)

                    slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                        oar_vol,
                        visibleSegmentIDs,
                        oarLabelMapNode,
                        input_volume,
                    )
                    current_oar = oarLabelMapNode

                elif isinstance(oar_vol, slicer.vtkMRMLLabelMapVolumeNode):
                    current_oar = oar_vol

                else:
                    self.log(f"  OAR volume {idx}: unsupported type, skipping")
                    continue

                if current_oar is not None:
                    oar_sitk = sitkUtils.PullVolumeFromSlicer(current_oar)
                    oar_array = sitk.GetArrayFromImage(oar_sitk)
                    oar_sitk = None

                    oar_resampled = self.image_resample_size(
                        sitk.GetImageFromArray(oar_array.astype(np.uint8)),
                        target_size,
                        is_label=True
                    )
                    oar_array = sitk.GetArrayFromImage(oar_resampled)
                    oar_resampled = None

                    oar_array = (oar_array > 0).astype(np.uint8) * oar_value

                    if combined_oar is None:
                        combined_oar = oar_array
                    else:
                        combined_oar = np.maximum(combined_oar, oar_array)

            except Exception as e:
                self.log(f"  Error processing OAR volume {idx}: {str(e)}")
                continue

        for temp_node in temp_nodes:
            try:
                displayNode = temp_node.GetDisplayNode()
                if displayNode:
                    slicer.mrmlScene.RemoveNode(displayNode)
                storageNode = temp_node.GetStorageNode()
                if storageNode:
                    slicer.mrmlScene.RemoveNode(storageNode)
                slicer.mrmlScene.RemoveNode(temp_node)
            except Exception:
                pass

        if combined_oar is not None:
            self.log(f"  Combined OAR labelmap created with value {oar_value}")
            reference_sitk = self._get_reference_sitk_image(input_volume, target_size)
            combined_oar_image = sitk.GetImageFromArray(combined_oar)
            combined_oar_image.CopyInformation(reference_sitk)
            return combined_oar_image

        return None

    def _get_reference_sitk_image(self, input_volume, target_size):
        """Get a reference SimpleITK image for resampling.

        Args:
            input_volume: Reference volume node.
            target_size: Target size for resampling.

        Returns:
            SimpleITK.Image: Reference image with correct spacing, origin, direction.
        """
        input_sitk = sitkUtils.PullVolumeFromSlicer(input_volume)
        input_array = sitk.GetArrayFromImage(input_sitk)
        input_spacing = input_sitk.GetSpacing()
        input_origin = input_sitk.GetOrigin()
        input_direction = input_sitk.GetDirection()

        current_size = input_sitk.GetSize()
        input_sitk = None

        scale = [float(current_size[i]) / float(target_size[i]) for i in range(3)]
        new_spacing = [input_spacing[i] * scale[i] for i in range(3)]

        reference_sitk = sitk.Image(target_size[0], target_size[1], target_size[2], sitk.sitkUInt8)
        reference_sitk.SetSpacing(new_spacing)
        reference_sitk.SetOrigin(input_origin)
        reference_sitk.SetDirection(input_direction)

        return reference_sitk

    def create_isodose_surface(self, dose_node, ctv_node, iso_dose_values, colors, opacities, model_name="IsoSurfaceModel", progressDialog=None):
        """Create isodose surface models for dose visualization.

        Generates 3D surface models at specified isodose values using
        marching cubes, with optional smoothing.

        Args:
            dose_node: Volume node containing dose data.
            ctv_node: Volume node containing CTV (clinical target volume) data.
            iso_dose_values: List of isodose values to generate surfaces for.
            colors: List of RGB color tuples for each isodose surface.
            opacities: List of opacity values (0-1) for each isodose surface.
            model_name: Name prefix for the generated model nodes.
            progressDialog: Optional progress dialog for UI updates.

        Returns:
            vtkMRMLModelNode or None: The last created isodose model node, or None on failure.
        """
        try:
            # Use GenerateUniqueName for transform to avoid reuse issues
            transform_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLinearTransformNode",
                slicer.mrmlScene.GenerateUniqueName("BrachyPlan_Transform")
            )
            ijk_to_ras_matrix = vtk.vtkMatrix4x4()
            dose_node.GetIJKToRASMatrix(ijk_to_ras_matrix)
            transform_node.SetMatrixTransformToParent(ijk_to_ras_matrix)

            ctv_image = slicer.util.arrayFromVolume(ctv_node)
            dose_array = slicer.util.arrayFromVolume(dose_node).copy()
            dose_array[ctv_image == 0] = 0

            # Use GenerateUniqueName to avoid node reuse issues
            temp_dose_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLScalarVolumeNode", slicer.mrmlScene.GenerateUniqueName("_temp_isodose")
            )
            slicer.util.updateVolumeFromArray(temp_dose_node, dose_array)
            # Explicitly copy spatial info from dose_node to prevent stale metadata
            temp_dose_node.CopyOrientation(dose_node)
            temp_dose_node.SetSpacing(dose_node.GetSpacing())
            temp_dose_node.SetOrigin(dose_node.GetOrigin())

            # Use try-finally to ensure temp node is always cleaned up
            try:
                dose_image = temp_dose_node.GetImageData()

                self.log("Creating multiple ISO surface models for dose visualization...")

                last_model_node = None
                total_surfaces = len(iso_dose_values)

                for idx, (iso_dose_value, color, opacity) in enumerate(zip(iso_dose_values, colors, opacities)):
                    # Update progress if dialog provided
                    if progressDialog is not None:
                        progress_value = 90 + int((idx / total_surfaces) * 8)
                        progressDialog.setValue(progress_value)
                        progressDialog.setLabelText(f"Generating isodose surface {idx+1}/{total_surfaces} ({int(iso_dose_value)}Gy)...")
                        slicer.app.processEvents()

                    marching_cubes = vtk.vtkMarchingCubes()
                    marching_cubes.SetInputData(dose_image)
                    marching_cubes.ComputeNormalsOn()
                    marching_cubes.SetValue(0, iso_dose_value)
                    marching_cubes.Update()

                    iso_surface = marching_cubes.GetOutput()

                    if iso_surface.GetNumberOfPoints() == 0:
                        self.log(f"Skipping isodose surface {int(iso_dose_value)}Gy: no surface generated")
                        continue

                    # Optimized smoothing: reduced iterations from 50 to 15 for better performance
                    smoother = vtk.vtkSmoothPolyDataFilter()
                    smoother.SetInputData(iso_surface)
                    smoother.SetNumberOfIterations(15)  # Reduced from 50 to 15
                    smoother.SetRelaxationFactor(0.1)
                    smoother.FeatureEdgeSmoothingOff()
                    smoother.BoundarySmoothingOn()
                    smoother.Update()

                    smoothed_iso_surface = vtk.vtkPolyData()
                    smoothed_iso_surface.ShallowCopy(smoother.GetOutput())

                    model_node = slicer.mrmlScene.AddNewNodeByClass(
                        "vtkMRMLModelNode",
                        slicer.mrmlScene.GenerateUniqueName(f"{model_name}_{int(iso_dose_value)}Gy")
                    )
                    model_node.SetAndObservePolyData(smoothed_iso_surface)

                    display_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelDisplayNode")
                    display_node.SetColor(color)
                    display_node.SetOpacity(opacity)
                    display_node.SetVisibility(True)
                    display_node.SetVisibility3D(True)
                    display_node.SetVisibility2D(True)
                    display_node.BackfaceCullingOff()

                    # Associate display node with model first, then set 2D slice properties
                    model_node.SetAndObserveTransformNodeID(transform_node.GetID())
                    model_node.SetAndObserveDisplayNodeID(display_node.GetID())

                    # Set 2D slice intersection properties after association
                    try:
                        # Enable slice intersection visibility using SetVisibility2D (SetSliceIntersectionVisibility is deprecated)
                        display_node.SetVisibility2D(True)
                        # Set line width for 2D slice intersection
                        display_node.SetSliceIntersectionThickness(5.0)
                        # Also set general line width for 3D view
                        display_node.SetLineWidth(3.0)
                    except Exception:
                        pass

                    last_model_node = model_node

                return last_model_node
            finally:
                # Always remove temp node regardless of success or failure
                slicer.mrmlScene.RemoveNode(temp_dose_node)

        except Exception as e:
            self.log(f"Error creating isodose surface: {str(e)}")
            if 'temp_dose_node' in locals() and temp_dose_node is not None:
                try:
                    slicer.mrmlScene.RemoveNode(temp_dose_node)
                except Exception:
                    pass
            return None

    def execute_replan(self, new_trajectory, needle_index):
        """Execute replan for a single dragged needle.

        Calls brachy_plan_v2.replan_single_needle with the new trajectory.
        Other needles' data is taken from stored _trajectory_info.

        Args:
            new_trajectory: New trajectory in resampled IJK coordinates.
            needle_index: Index of the dragged needle.

        Returns:
            Tuple of (plan_res, sum_array, success).
        """
        try:
            import importlib
            import plans.brachy_plan_v2 as _bpv2
            importlib.reload(_bpv2)
            replan_single_needle = _bpv2.replan_single_needle

            args = self._current_plan_args

            # Build other_needles_data from stored trajectory info
            other_needles_data = []
            for i, info in enumerate(self._trajectory_info):
                if i != needle_index:
                    other_needles_data.append((
                        info["trajectory"],
                        info.get("seeds_voxel", None),
                        info["seed_radiations"]
                    ))

            self.log(f"[EXECUTE REPLAN] calling replan_single_needle, trajectory start={new_trajectory[0]}, dir={new_trajectory[1]}")
            self.log(f"[EXECUTE REPLAN] radiation_volume shape={self._current_radiation_volume.shape}, dose_image size={self._current_dose_image.GetSize()}")
            self.log(f"[EXECUTE REPLAN] other_needles_data count={len(other_needles_data)}")

            plan_res, sum_array, success = replan_single_needle(
                new_trajectory,
                other_needles_data,
                self._current_radiation_volume,
                self._current_dose_image,
                self._dose_model,
                args,
                dose_context=getattr(self, '_dose_context', None)
            )

            self.log(f"[EXECUTE REPLAN] result: success={success}, plan_res={'None' if plan_res is None else f'len={len(plan_res)}'}")
            if not success:
                # Log trajectory depths for debugging
                traj = new_trajectory
                self.log(f"[EXECUTE REPLAN] trajectory start={traj[0]}, dir={traj[1]}")
                self.log(f"[EXECUTE REPLAN] target_depths={traj[2]}, background_depths={traj[3]}")
            return plan_res, sum_array, success
        except Exception as e:
            self.log(f"Replan error: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
            return None, None, False

    def _hide_old_plan_models(self):
        """Hide all existing seed, needle, and isodose models from previous plans.

        Sets visibility to False for all nodes whose names match the patterns
        used by the planning algorithm: "Seed", "Needle_*", and "IsoDose*".
        This ensures only the latest plan results are visible.
        """
        try:
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            if not shNode:
                return
            self.log(f"Hiding old plans. Total folders: {len(self._all_plan_folders)}")
            # 1. Clean up needle observers from ALL old plans
            lineNodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLMarkupsLineNode")
            for i in range(lineNodes.GetNumberOfItems()):
                lineNode = lineNodes.GetItemAsObject(i)
                node_id = lineNode.GetID()
                if node_id in self._needle_observer_tags:
                    tag = self._needle_observer_tags.pop(node_id)
                    lineNode.RemoveObserver(tag)
                if hasattr(self, '_observer_callbacks'):
                    self._observer_callbacks.pop(node_id, None)
                self._needle_original_positions.pop(node_id, None)

            # 2. Hide ALL existing plan folders and their contents
            for folder_id in self._all_plan_folders:
                folder_name = shNode.GetItemName(folder_id)
                self.log(f"  Hiding folder: {folder_name} (id={folder_id})")
                # Set folder visibility
                shNode.SetItemDisplayVisibility(folder_id, False)
                # Also hide all descendant nodes
                children = vtk.vtkIdList()
                shNode.GetItemChildren(folder_id, children, True)  # recursive
                for ci in range(children.GetNumberOfIds()):
                    child_id = children.GetId(ci)
                    shNode.SetItemDisplayVisibility(child_id, False)
                    data_node = shNode.GetItemDataNode(child_id)
                    if data_node and hasattr(data_node, 'GetDisplayNode'):
                        dn = data_node.GetDisplayNode()
                        if dn:
                            dn.SetVisibility(False)
        except Exception as e:
            self.log(f"Warning: Could not hide old plan models: {str(e)}")

    def _create_plan_folder(self, plan_number):
        """Create a plan Folder node in the subject hierarchy.

        Args:
            plan_number: The plan number (1, 2, 3, ...).

        Returns:
            The subject hierarchy item ID of the created folder.
        """
        try:
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            plan_root = shNode.GetItemByName("Plan")
            if not plan_root:
                plan_root = shNode.CreateFolderItem(shNode.GetSceneItemID(), "Plan")
            plan_folder_name = f"Plan_{plan_number}"
            plan_folder = shNode.CreateFolderItem(plan_root, plan_folder_name)
            return plan_folder
        except Exception as e:
            self.log(f"Error creating plan folder: {str(e)}")
            return None

    def _get_plan_node_name(self, base_name):
        """Get node name with plan prefix to avoid multi-plan conflicts.

        Args:
            base_name: The base node name (e.g., "Needle_0", "RTDoseMap").

        Returns:
            Prefixed name (e.g., "Plan_1_Needle_0") or base_name if no plan.
        """
        if self._current_plan_folder_name:
            return f"{self._current_plan_folder_name}_{base_name}"
        return base_name

    def _setup_needle_observer(self, line_node):
        """Add drag monitoring to a Needle node.

        Observes PointModifiedEvent on the line node and saves the original
        control point positions for later comparison.

        Args:
            line_node: vtkMRMLMarkupsLineNode to observe.
        """
        if not line_node:
            self.log("Warning: _setup_needle_observer called with None")
            return
        node_id = line_node.GetID()
        if node_id in self._needle_observer_tags:
            self.log(f"Observer already registered for {line_node.GetName()}")
            return
        widget = getattr(self, '_widget', None)
        if not widget:
            self.log("Warning: _widget not set, cannot register needle observer")
            return

        # Store callbacks on the Logic instance to prevent garbage collection
        if not hasattr(self, '_observer_callbacks'):
            self._observer_callbacks = {}

        def _on_modified(caller_obj, event_name):
            widget._on_needle_modified(caller_obj, event_name)

        self._observer_callbacks[node_id] = _on_modified

        # Try PointModifiedEvent first, fall back to ModifiedEvent
        try:
            event_id = slicer.vtkMRMLMarkupsNode.PointModifiedEvent
            tag = line_node.AddObserver(event_id, _on_modified)
            self.log(f"Registered PointModifiedEvent observer for {line_node.GetName()} (tag={tag})")
        except Exception as e:
            self.log(f"PointModifiedEvent failed: {e}, falling back to ModifiedEvent")
            tag = line_node.AddObserver(vtk.vtkCommand.ModifiedEvent, _on_modified)
            self.log(f"Registered ModifiedEvent observer for {line_node.GetName()} (tag={tag})")

        self._needle_observer_tags[node_id] = tag

        start_pos = [0, 0, 0]
        end_pos = [0, 0, 0]
        line_node.GetNthControlPointPosition(0, start_pos)
        line_node.GetNthControlPointPosition(1, end_pos)
        self._needle_original_positions[node_id] = {"start": list(start_pos), "end": list(end_pos)}

    def _cleanup_needle_observers(self):
        """Remove all needle observers to prevent memory leaks."""
        for node_id, tag in list(self._needle_observer_tags.items()):
            node = slicer.mrmlScene.GetNodeByID(node_id)
            if node:
                node.RemoveObserver(tag)
        self._needle_observer_tags.clear()
        self._needle_original_positions.clear()
        if hasattr(self, '_observer_callbacks'):
            self._observer_callbacks.clear()

    def run_brachyPlan(self, inputVolume, ctvVolume, oarVolumes=None, params=None):
        """Run the full brachytherapy planning pipeline.

        Resamples input images, loads the dose prediction model, executes
        trajectory planning, creates seed/needle markups, generates the dose
        volume, and creates isodose surface visualizations.

        Args:
            inputVolume: Input CT volume node.
            ctvVolume: CTV segmentation node or label map volume (required).
            oarVolumes: List of OAR segmentation nodes or label map volumes (optional).
            params: Planning parameters namespace (uses defaults if None).

        Returns:
            None
        """
        try:
            progressDialog = None
            startTime = time.time()
            self.log("Start planning")

            if params is None:
                params = self.getDefaultPlanningParams()

            # Hide old plan folders BEFORE creating new one
            self._hide_old_plan_models()

            # Create plan folder in Data Tree hierarchy
            self._plan_counter += 1
            self._current_plan_folder = self._create_plan_folder(self._plan_counter)
            self._current_plan_folder_name = f"Plan_{self._plan_counter}"
            self._all_plan_folders.append(self._current_plan_folder)

            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            volume1ItemID = shNode.GetItemByDataNode(inputVolume)
            studyItemID = shNode.GetItemAncestorAtLevel(volume1ItemID, "Study")

            ctimage = inputVolume.GetImageData()
            dimension = ctimage.GetDimensions()
            spacing = inputVolume.GetSpacing()
            origin = inputVolume.GetOrigin()
            image_ = sitkUtils.PullVolumeFromSlicer(inputVolume)

            fMat = vtk.vtkMatrix4x4()
            inputVolume.GetIJKToRASDirectionMatrix(fMat)

            # DEBUG: Check if fMat includes origin
            self.log(f"[COORD DEBUG] fMat(0,3)={fMat.GetElement(0,3):.1f}, fMat(1,3)={fMat.GetElement(1,3):.1f}, fMat(2,3)={fMat.GetElement(2,3):.1f}")
            self.log(f"[COORD DEBUG] inputVolume origin: {origin}")
            self.log(f"[COORD DEBUG] fMat diagonal: ({fMat.GetElement(0,0):.4f}, {fMat.GetElement(1,1):.4f}, {fMat.GetElement(2,2):.4f})")
            self.log(f"[COORD DEBUG] inputVolume spacing: {spacing}")

            new_slices_rounded = NEW_SLICES_ROUNDED

            my_image = self.image_resample_size(image_, [128, 128, new_slices_rounded])
            del image_
            # Store for replan coordinate conversion
            self._resampled_ct_image = my_image
            myspacing = my_image.GetSpacing()
            myorigin = my_image.GetOrigin()

            # Track if we created temporary labelmap nodes (to clean up later)
            ctv_labelmap_created = False
            ctv_saved_name = ctvVolume.GetName() if ctvVolume else "CTV"

            # Process CTV volume
            if isinstance(ctvVolume, slicer.vtkMRMLSegmentationNode):
                try:
                    # Get visible segment IDs only
                    visibleSegmentIDs = vtk.vtkStringArray()
                    segmentation = ctvVolume.GetSegmentation()
                    allSegmentIDs = vtk.vtkStringArray()
                    segmentation.GetSegmentIDs(allSegmentIDs)

                    # Get display node to check visibility
                    display_node = ctvVolume.GetDisplayNode()
                    if display_node is None:
                        ctvVolume.CreateDefaultDisplayNodes()
                        display_node = ctvVolume.GetDisplayNode()

                    visible_count = 0
                    for i in range(allSegmentIDs.GetNumberOfValues()):
                        segmentID = allSegmentIDs.GetValue(i)
                        # Check if segment is visible using display node
                        if display_node:
                            is_visible = display_node.GetSegmentVisibility(segmentID)
                        else:
                            # Fallback: export all if no display node
                            is_visible = True
                        if is_visible:
                            visibleSegmentIDs.InsertNextValue(segmentID)
                            visible_count += 1

                    self.log(f"Exporting {visible_count} visible CTV segments for planning")

                    if visibleSegmentIDs.GetNumberOfValues() > 0:
                        ctvLabelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                        ctvLabelMapNode.SetName(f"{ctvVolume.GetName()}_LabelMap")

                        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                            ctvVolume,
                            visibleSegmentIDs,
                            ctvLabelMapNode,
                            inputVolume,
                        )

                        ctvVolume = ctvLabelMapNode
                        ctv_labelmap_created = True
                        ctv_saved_name = ctvLabelMapNode.GetName()
                    else:
                        raise RuntimeError("No visible CTV segments found")
                except Exception as e:
                    self.log(f"Error exporting CTV segmentation to labelmap: {str(e)}")
                    if 'ctvLabelMapNode' in locals() and ctvLabelMapNode is not None:
                        slicer.mrmlScene.RemoveNode(ctvLabelMapNode)
                    raise

            ctv_ = sitkUtils.PullVolumeFromSlicer(ctvVolume)
            ctv_image = self.image_resample_size(ctv_, [128, 128, new_slices_rounded], is_label=True)
            del ctv_
            self._resampled_ctv_image = ctv_image

            # Clean up temporary CTV labelmap node (we created it, so we own it)
            if ctv_labelmap_created and ctvVolume is not None:
                displayNode = ctvVolume.GetDisplayNode()
                if displayNode:
                    slicer.mrmlScene.RemoveNode(displayNode)
                storageNode = ctvVolume.GetStorageNode()
                if storageNode:
                    slicer.mrmlScene.RemoveNode(storageNode)
                slicer.mrmlScene.RemoveNode(ctvVolume)

            # Process OAR volumes if provided
            oar_image = None
            if oarVolumes:
                oar_value = params.radiation_array_params.get("obstacle_value", 2)
                self.log(f"Processing {len(oarVolumes)} OAR volume(s) with value {oar_value}")
                oar_image = self._process_oar_volumes(
                    oarVolumes, inputVolume, [128, 128, new_slices_rounded], oar_value
                )

            # Create radiation_volume label array (needed for replan distance_map)
            from plans.utilizations_v2 import get_planning_volume_array
            radiation_volume = get_planning_volume_array(
                ctv_image,
                oar_image,
                params.radiation_array_params.get('target_value', 1),
                params.radiation_array_params.get('obstacle_value', 2),
                params.radiation_array_params.get('background_value', 0),
            )

            progressDialog = createProgressDialog("Running brachytherapy planning... ")
            progressDialog.setValue(0)


            dose_model = self._get_or_load_dose_model()

            args = copy.deepcopy(params)
            try:
                ras_direc = np.array(args.reference_direc).reshape(-1)
                voxel_direc = ras_direction_to_voxel(ras_direc, my_image)
                args.reference_direc = voxel_direc
            except Exception as e:
                self.log(f"Direction conversion error: {e}")

            if args.use_rf:
                self.log("Trajectory planning with reinforcement learning.")
                plan_res, sum_image, dose_image = brachy_plan_rf(
                    my_image, ctv_image, oar_image, dose_model, args, progressDialog
                )
            else:
                self.log("Trajectory planning without reinforcement learning.")
                plan_res, sum_image, dose_image = brachy_plan(
                    my_image, ctv_image, oar_image, dose_model, args, progressDialog
                )

            stopTime = time.time()
            self.log(f"Processing completed in {stopTime - startTime:.2f} seconds")

            progressDialog.setValue(85)
            progressDialog.setLabelText("Creating seeds and needles...")
            slicer.app.processEvents()

            planned_seeds = []
            planned_seed_doses = []
            try:
                for res in plan_res:
                    planned_seeds.append(res[1])
                    planned_seed_doses.append(res[2])
            except Exception as e:
                self.log(f"Error extracting planned seeds: {str(e)}")

            fiducialNode_all = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
            fiducialNode_all.SetName(self._get_plan_node_name("Seed"))
            fiducialNode_all.CreateDefaultDisplayNodes()
            fiducialNode_all.GetDisplayNode().SetPointLabelsVisibility(False)
            fiducialNode_all.GetDisplayNode().SetPropertiesLabelVisibility(False)
            fiducialNode_all.GetDisplayNode().SetTextScale(0.8)
            fiducialNode_all.SetLocked(True)
            # Set parent to plan folder
            if self._current_plan_folder:
                seedAllID = shNode.GetItemByDataNode(fiducialNode_all)
                shNode.SetItemParent(seedAllID, self._current_plan_folder)
            total_num = 0

            self.log("Creating seeds and needle markups...")
            for i, seeds in enumerate(planned_seeds):
                try:
                    lineNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsLineNode")
                    lineNode.SetName(f"{self._plan_counter}_{i}")
                    # Ensure display node exists for visibility control
                    lineNode.CreateDefaultDisplayNodes()
                    displayNode = lineNode.GetDisplayNode()
                    if displayNode:
                        displayNode.SetPointLabelsVisibility(False)
                        displayNode.SetPropertiesLabelVisibility(False)
                        displayNode.SetVisibility(True)  # Ensure visible by default
                    # Disable length measurement label (remove ":xx mm" suffix)
                    try:
                        lineNode.RemoveAllMeasurements()
                    except Exception:
                        pass
                    lineID = shNode.GetItemByDataNode(lineNode)
                    # Set parent to plan folder (not volume)
                    shNode.SetItemParent(lineID, self._current_plan_folder)
                    shNode.SetItemDisplayVisibility(lineID, True)

                    fiducialNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
                    fiducialNode.SetName(self._get_plan_node_name(f"{ctv_saved_name}_seed_{i}"))
                    fiducialNode.GetDisplayNode().SetPointLabelsVisibility(False)
                    fiducialNode.GetDisplayNode().SetPropertiesLabelVisibility(False)
                    fiducialNode.GetDisplayNode().SetTextScale(0.8)
                    fiducialNode.SetLocked(True)
                    pointsID = shNode.GetItemByDataNode(fiducialNode)
                    shNode.SetItemParent(pointsID, lineID)

                    # Collect all seed positions for this needle
                    seed_positions = []
                    for j, seed in enumerate(seeds):
                        try:
                            slicer.app.processEvents()

                            pos = seed[0].reshape(-1)
                            transformedPos = [0, 0, 0, 1]
                            fMat.MultiplyPoint([pos[0], pos[1], pos[2], 1], transformedPos)

                            # DEBUG: Log first seed transformation
                            if i == 0 and j == 0:
                                self.log(f"[COORD DEBUG] first seed IJK: [{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}]")
                                self.log(f"[COORD DEBUG] first seed RAS (fMat): [{transformedPos[0]:.1f}, {transformedPos[1]:.1f}, {transformedPos[2]:.1f}]")
                                # Also compute with origin added
                                self.log(f"[COORD DEBUG] fMat+origin: [{transformedPos[0]+origin[0]:.1f}, {transformedPos[1]+origin[1]:.1f}, {transformedPos[2]+origin[2]:.1f}]")
                                self.log(f"[COORD DEBUG] resampled origin: {myorigin}, resampled spacing: {myspacing}")

                            direction = seed[1].reshape(-1)
                            direction = [DIRECTION_REVERSAL_SIGN * direction[0], DIRECTION_REVERSAL_SIGN * direction[1], direction[2]]

                            fiducialNode_all.AddControlPoint(transformedPos[:3])
                            seed_positions.append((transformedPos[:3], direction))

                            self.create_capsule_stl(j, fiducialNode, transformedPos[:3], direction)
                            total_num = total_num + 1
                        except Exception as e:
                            self.log(f"Error creating seed {j} on needle {i}: {str(e)}")
                            continue

                    # Create needle line using the pre-calculated trajectory direction
                    if len(seed_positions) >= 1:
                        try:
                            # Use the direction from the first seed
                            positions = np.array([pos for pos, _ in seed_positions])
                            p0 = positions[0]

                            dir_vec = np.array(seed_positions[0][1], dtype=np.float64)
                            norm = np.linalg.norm(dir_vec)
                            if norm > 1e-6:
                                dir_vec = dir_vec / norm
                            else:
                                dir_vec = np.array([0.0, 0.0, 1.0])

                            # Project all seed positions onto the direction vector
                            t_values = np.dot(positions - p0, dir_vec)
                            t_min = np.min(t_values)
                            t_max = np.max(t_values)

                            # Find extreme points of the seed chain along the direction
                            shallow_center = p0 + t_min * dir_vec
                            deep_center = p0 + t_max * dir_vec

                            # Extend to wrap all seeds completely
                            # Needle tail: extend BACKWARDS from the shallowest seed by DIRECTION_EXTENSION
                            start_point = shallow_center - (DIRECTION_EXTENSION * dir_vec)

                            # Needle tip: extend FORWARDS from the deepest seed by half of SEED_LENGTH
                            end_point = deep_center + ((SEED_LENGTH / 2.0) * dir_vec)

                            # Add control points to line node
                            lineNode.AddControlPoint(*end_point)
                            lineNode.AddControlPoint(*start_point)

                            lineNode.SetAttribute("lineIndex", str(i))
                            lineNode.SetAttribute("originalStart", f"{start_point[0]},{start_point[1]},{start_point[2]}")
                            lineNode.SetAttribute("originalEnd", f"{end_point[0]},{end_point[1]},{end_point[2]}")

                            displayNode = lineNode.GetDisplayNode()
                            if displayNode:
                                displayNode.SetColor(0, 1, 0)
                                shNode.ItemModified(lineID)

                        except Exception as e:
                            self.log(f"Error tracking needle line {i}: {str(e)}")
                    # Register needle drag observer
                    self._setup_needle_observer(lineNode)
                except Exception as e:
                    self.log(f"Error creating needle {i}: {str(e)}")
                    continue

            progressDialog.setValue(90)
            progressDialog.setLabelText("Generating dose map...")
            slicer.app.processEvents()

            dose_node = None
            try:
                # Save cumulative radiation for replan before it's consumed
                saved_cumulative_radiation = sum_image.copy()
                dose_ = sitk.GetImageFromArray(sum_image)
                dose_.SetSpacing(myspacing)
                dose_ = self.image_resample_size(dose_, dimension)
                dose_array_gy = sitk.GetArrayFromImage(dose_).astype(np.float64) * DOSE_SCALE_FACTOR
                del sum_image
                dose_node = slicer.util.addVolumeFromArray(
                    dose_array_gy, nodeClassName="vtkMRMLScalarVolumeNode"
                )
                del dose_array_gy
                
                dose_node.SetSpacing(spacing)
                dose_node.SetOrigin(origin)
                dose_node.SetIJKToRASDirectionMatrix(fMat)

                doseID = shNode.GetItemByDataNode(dose_node)
                shNode.SetItemParent(doseID, self._current_plan_folder)
                shNode.SetItemName(doseID, self._get_plan_node_name("RTDoseMap"))
            except Exception as e:
                self.log(f"Error generating dose volume: {str(e)}")
                try:
                    progressDialog.close()
                except Exception:
                    pass
                return None

            if studyItemID and studyItemID != 0:
                shNode.SetItemParent(doseID, studyItemID)

            if studyItemID and studyItemID != 0:
                doseUnitNameInStudy = shNode.GetItemAttribute(studyItemID, "DicomRtImport.DoseUnitName")
                doseUnitValueInStudy = shNode.GetItemAttribute(studyItemID, "DicomRtImport.DoseUnitValue")

                defaultDoseUnitName = doseUnitNameInStudy if doseUnitNameInStudy else "Gy"
                defaultDoseUnitValue = doseUnitValueInStudy if doseUnitValueInStudy else "1.0"

                shNode.SetItemAttribute(studyItemID, "DicomRtImport.DoseUnitName", defaultDoseUnitName)
                shNode.SetItemAttribute(studyItemID, "DicomRtImport.DoseUnitValue", defaultDoseUnitValue)

            dose_node.SetAttribute("DicomRtImport.DoseVolume", "1")

            displayNode = dose_node.GetScalarVolumeDisplayNode()
            if displayNode:
                try:
                    colorNodeID = slicer.modules.colors.logic().GetPETColorNodeID(
                        slicer.vtkMRMLPETProceduralColorNode.PETrainbow2
                    )
                    if colorNodeID:
                        displayNode.SetAndObserveColorNodeID(colorNodeID)
                    displayNode.AutoWindowLevelOff()
                    displayNode.SetWindow(600)
                    displayNode.SetLevel(300)
                    scalarRange = dose_node.GetImageData().GetScalarRange()
                    displayNode.SetLowerThreshold(0)
                    displayNode.SetUpperThreshold(scalarRange[1])
                    try:
                        colorLegendDisplayNode = slicer.modules.colors.logic().AddDefaultColorLegendDisplayNode(dose_node)
                        if colorLegendDisplayNode:
                            colorLegendDisplayNode.SetTitleText("Dose (Gy)")
                            colorLegendDisplayNode.SetVisibility(True)
                            colorLegendDisplayNode.SetVisibility2D(True)
                            colorLegendDisplayNode.SetVisibility3D(True)
                            colorLegendDisplayNode.Modified()
                            slicer.app.processEvents()
                    except Exception as e:
                        self.log(f"Error creating color legend: {str(e)}")
                    displayNode.Modified()
                except Exception as e:
                    self.log(f"Error configuring dose display: {str(e)}")

            # Collect existing isodose model names BEFORE creating new ones
            existing_isodose_names = set()
            model_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLModelNode")
            for i in range(model_nodes.GetNumberOfItems()):
                name = model_nodes.GetItemAsObject(i).GetName()
                if name.startswith("IsoDose"):
                    existing_isodose_names.add(name)

            isodose_node = self.create_isodose_surface(
                dose_node,
                inputVolume,
                args.iso_dose_params["iso_dose_values"],
                args.iso_dose_params["iso_colors"],
                args.iso_dose_params["iso_opacities"],
                model_name="IsoDose",
                progressDialog=progressDialog,
            )

            # Move only NEWLY created isodose model nodes to plan folder
            if self._current_plan_folder:
                moved_count = 0
                model_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLModelNode")
                for i in range(model_nodes.GetNumberOfItems()):
                    model_node = model_nodes.GetItemAsObject(i)
                    name = model_node.GetName()
                    if name.startswith("IsoDose") and name not in existing_isodose_names:
                        modelItemID = shNode.GetItemByDataNode(model_node)
                        if modelItemID:
                            shNode.SetItemParent(modelItemID, self._current_plan_folder)
                            moved_count += 1
                self.log(f"Moved {moved_count} new isodose models to plan folder")
            else:
                self.log("Warning: _current_plan_folder is None, cannot move isodose models")

            shNode.RequestOwnerPluginSearch(doseID)
            shNode.ItemModified(doseID)

            self.log(
                f"Generate {total_num} seeds, {len(planned_seeds)} needles, {len(args.iso_dose_params['iso_opacities'])} ISO dose models"
            )

            # Save plan data for replan support
            self._current_plan_res = plan_res
            self._current_plan_args = args
            self._current_radiation = saved_cumulative_radiation
            self._current_radiation_volume = radiation_volume
            self._current_dose_image = dose_image

            # Save trajectory info for each needle
            # seeds from optimal_plan are in world/physical coords (position_transform output)
            # stored as-is for replan use
            self._trajectory_info = []
            for res in plan_res:
                seeds_voxel = []
                for seed in res[1]:
                    ijk_pos = np.array(seed[0]).reshape(-1)
                    ijk_dir = np.array(seed[1]).reshape(-1)
                    seeds_voxel.append((ijk_pos, ijk_dir))
                self._trajectory_info.append({
                    "trajectory": res[0],
                    "seeds_voxel": seeds_voxel,
                    "seed_radiations": list(res[2])
                })

            # Unload dose model to free memory
            self._unload_dose_model()

            return dose_node, progressDialog

        except Exception as e:
            self.log(f"Error in brachytherapy planning: {str(e)}")
            self.log(traceback.format_exc())
            if progressDialog is not None:
                try:
                    progressDialog.close()
                except Exception:
                    pass
            return None

    def is_totalsegmentator_available(self):
        """Check if TotalSegmentator module is available in the current Slicer environment.

        Returns:
            bool: True if TotalSegmentator is available, False otherwise.
        """
        try:
            return hasattr(slicer.modules, "totalsegmentator")
        except Exception:
            return False

    def run_segTask(self, input_volume, output_segmentation, task, fast_mode):
        """Run a segmentation task by name.

        Dispatches to the appropriate task function based on the task name.

        Args:
            input_volume: Input volume node.
            output_segmentation: Output segmentation node.
            task: Task name string (e.g., "Total", "Liver Tumor", "Skin").
            fast_mode: Whether to use fast mode.

        Returns:
            bool: True if task completed successfully, False otherwise.
        """
        if self._segmentation_in_progress:
            self.log("Segmentation task already in progress. Please wait.")
            return False

        self._segmentation_in_progress = True
        try:
            task_config = self.segTaskFunctionMap.get(task)

            if not task_config:
                self.log(f"Error: Unknown task name '{task}'")
                return False

            task_function = task_config.get("function")
            label_value = task_config.get("label_value")

            if task_function:
                return task_function(input_volume, output_segmentation, fast_mode, label_value)
            return False
        finally:
            self._segmentation_in_progress = False

    def _run_total_segmentation(self, input_volume, output_segmentation, fast_mode, label_value):
        """Run TotalSegmentator 'total' task to generate the base 1-104 NIfTI.

        Args:
            input_volume: Input volume node.
            output_segmentation: Output segmentation node.
            fast_mode: Whether to use fast mode.
            label_value: Label value (not used for total task).

        Returns:
            bool: True if segmentation completed successfully, False otherwise.
        """
        progressDialog = None
        temp_dir = None
        try:
            if output_segmentation is None:
                seg_name = f"Segmentation_total_{input_volume.GetName()}"
                output_segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", seg_name)

            temp_dir = slicer.util.tempDirectory()
            input_file = os.path.join(temp_dir, "input.nii.gz")
            result_file = os.path.join(temp_dir, "segmentations.nii.gz")

            storage = slicer.mrmlScene.CreateNodeByClass("vtkMRMLVolumeArchetypeStorageNode")
            storage.SetFileName(input_file)
            storage.UseCompressionOff()
            storage.WriteData(input_volume)
            storage.UnRegister(None)

            device_str = self._get_device_str()

            python_exe = self._get_python_executable()
            cmd = [python_exe, "-m", "totalsegmentator"]
            cmd.extend(["-i", input_file, "-o", result_file])
            cmd.extend(["--ml", "--task", "total", "--device", device_str])
            if fast_mode:
                cmd.append("--fast")

            progressDialog = createProgressDialog("Running TotalSegmentator...")
            progressDialog.setValue(0)

            success = self._run_totalsegmentator_subprocess(cmd, progressDialog)
            if not success:
                return False

            if not os.path.exists(result_file):
                raise RuntimeError("Segmentation result file not found")

            self._current_base_nifti_path = result_file
            self.log(f"Base Total NIfTI generated at: {self._current_base_nifti_path}")

            self._load_final_nifti_to_slicer(result_file, input_volume, output_segmentation)

            progressDialog.setValue(100)
            progressDialog.close()

            self.log("TotalSegmentator completed successfully.")
            return True

        except Exception as e:
            self.log(f"Error: {str(e)}")
            if progressDialog is not None:
                try:
                    progressDialog.setValue(100)
                    progressDialog.close()
                except Exception:
                    pass
            return False
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_totalsegmentator_subprocess(self, cmd, progressDialog):
        """Execute TotalSegmentator subprocess with non-blocking progress tracking.

        Runs the command in a separate thread for output reading and updates
        the progress dialog in the main UI loop.

        Args:
            cmd: Command list to execute.
            progressDialog: Progress dialog instance.

        Returns:
            bool: True if execution succeeded.

        Raises:
            RuntimeError: If the subprocess fails or returns a non-zero exit code.
        """
        self.log(f"Executing command: {' '.join(cmd)}")
        start_time = time.time()

        env = self._get_clean_subprocess_env()
        if "TOTALSEG_WEIGHTS_PATH" not in env:
            env["TOTALSEG_WEIGHTS_PATH"] = self._get_totalseg_weights_path()
        self.log(f"  Python exe: {cmd[0]}")
        self.log(f"  TOTALSEG_WEIGHTS_PATH: {env.get('TOTALSEG_WEIGHTS_PATH', 'N/A')}")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace',
            env=env
        )

        output_lines = deque()
        progress_counter = {"value": 0, "done": False, "error": None}
        progress_lock = threading.Lock()

        def read_output():
            try:
                for line in proc.stdout:
                    stripped = line.strip()
                    if stripped:
                        output_lines.append(stripped)
                        with progress_lock:
                            progress_counter["value"] = min(progress_counter["value"] + 1, 95)
                proc.wait()
                if proc.returncode != 0:
                    with progress_lock:
                        progress_counter["error"] = f"TotalSegmentator failed with return code {proc.returncode}"
            except Exception as e:
                with progress_lock:
                    progress_counter["error"] = str(e)
            finally:
                with progress_lock:
                    progress_counter["done"] = True

        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        while True:
            slicer.app.processEvents()
            while output_lines:
                self.log(output_lines.popleft())
            with progress_lock:
                if progress_counter["done"]:
                    break
                current_value = progress_counter["value"]
            progressDialog.setValue(current_value)
            time.sleep(0.1)

        while output_lines:
            self.log(output_lines.popleft())

        with progress_lock:
            error_msg = progress_counter["error"]

        if error_msg:
            raise RuntimeError(error_msg)

        elapsed_time = time.time() - start_time
        self.log(f"TotalSegmentator completed in {elapsed_time:.2f} seconds")

        if proc.returncode != 0:
            raise RuntimeError(
                f"TotalSegmentator failed with return code {proc.returncode}. Check log output above for details."
            )

        return True

    def _write_volume_to_nifti(self, volume_node, output_path):
        """Write a volume node to a NIfTI file.

        Args:
            volume_node: Input volume node.
            output_path: Path to save the NIfTI file.
        """
        try:
            storage = slicer.mrmlScene.CreateNodeByClass("vtkMRMLVolumeArchetypeStorageNode")
            storage.SetFileName(output_path)
            storage.UseCompressionOff()
            storage.WriteData(volume_node)
            storage.UnRegister(None)
        except Exception as e:
            self.log(f"Error writing volume to NIfTI: {str(e)}")
            raise

    def _run_single_task_segmentation(
        self,
        input_volume,
        output_segmentation,
        fast_mode,
        label_value,
        task_name,
        ts_task,
        result_filename,
        use_ml=False,
        supports_fast=True,
        source_label=None,
        target_label=None,
        progress_label=None,
    ):
        """Run a single TotalSegmentator task independently.

        This method is fully decoupled and does NOT require running the
        'Total' task first.

        Args:
            input_volume: Input volume node.
            output_segmentation: Output segmentation node.
            fast_mode: Whether to use fast mode.
            label_value: Custom label value for the result.
            task_name: Display name for logging.
            ts_task: TotalSegmentator task name string.
            result_filename: Expected output NIfTI filename.
            use_ml: Whether to use multi-label output (--ml flag).
            supports_fast: Whether this task supports --fast mode.
            source_label: Label value in the result NIfTI to extract (None = load entire file).
            target_label: Label value to assign in the final segmentation.
            progress_label: Label for the progress dialog.

        Returns:
            bool: True if segmentation completed successfully, False otherwise.
        """
        progressDialog = None
        temp_dir = None
        try:
            if output_segmentation is None:
                seg_name = f"Segmentation_{task_name}_{input_volume.GetName()}"
                output_segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", seg_name)

            temp_dir = slicer.util.tempDirectory()
            input_file = os.path.join(temp_dir, "input.nii.gz")
            output_dir = os.path.join(temp_dir, "segmentation")

            self._write_volume_to_nifti(input_volume, input_file)

            ts_exe = self._find_totalsegmentator_exe()
            device_str = self._get_device_str()

            cmd = [ts_exe]
            cmd.extend(["-i", input_file, "-o", output_dir])
            if use_ml:
                cmd.append("--ml")
            cmd.extend(["--task", ts_task, "--device", device_str])
            if supports_fast and fast_mode:
                cmd.append("--fast")

            if progress_label is None:
                progress_label = f"Running {task_name} Segmentation..."
            progressDialog = createProgressDialog(progress_label)
            progressDialog.setValue(0)

            success = self._run_totalsegmentator_subprocess(cmd, progressDialog)
            if not success:
                return False

            result_file = os.path.join(output_dir, result_filename)
            if not os.path.exists(result_file):
                raise RuntimeError(f"Result file ({result_filename}) not found")

            if source_label is not None and target_label is not None:
                self.log(f"Extracting {task_name} (label {source_label}) and assigning as label {target_label}...")
                mask_img = nib.load(result_file)
                mask_data = mask_img.get_fdata()
                mask_pixels = mask_data == source_label
                new_data = np.zeros_like(mask_data, dtype=np.uint8)
                new_data[mask_pixels] = target_label
                new_img = nib.Nifti1Image(new_data, mask_img.affine, mask_img.header)
                new_result_file = os.path.join(temp_dir, "relabelled.nii.gz")
                nib.save(new_img, new_result_file)
                result_file = new_result_file

            self._load_final_nifti_to_slicer(result_file, input_volume, output_segmentation)
            self.log(f"{task_name} segmentation completed successfully.")

            progressDialog.setValue(100)
            progressDialog.close()
            return True

        except Exception as e:
            self.log(f"Error in {task_name} segmentation: {str(e)}")
            if progressDialog:
                try:
                    progressDialog.close()
                except Exception:
                    pass
            return False
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_head_neck_tumor_segmentation(self, input_volume, output_segmentation, fast_mode, label_value):
        """Run Head and Neck Tumor segmentation (not yet implemented).

        Args:
            input_volume: Input volume node.
            output_segmentation: Output segmentation node.
            fast_mode: Whether to use fast mode.
            label_value: Label value for the segmentation.

        Returns:
            bool: Always False (not yet implemented).
        """
        self.log("Running Head and Neck Tumor segmentation...")
        self.log("To be developed...")
        return False

    def _run_pancreatic_tumor_segmentation(self, input_volume, output_segmentation, fast_mode, label_value):
        """Executes pancreatic tumor segmentation using a local nnU-Net v2 model.

        This function handles environment injection, temporary file management,
        real-time logging, and progress tracking for the nnU-Net inference process.

        Args:
            input_volume (vtkMRMLScalarVolumeNode): The input CT volume node.
            output_segmentation (vtkMRMLSegmentationNode): The target segmentation node.
            fast_mode (bool): If True, reduces preprocessing threads, disables TTA
                (test-time augmentation), and uses fastest prediction settings.
            label_value (str): The display name for the segmented structure.

        Returns:
            bool: True if segmentation succeeded, False otherwise.
        """
        self.log("<b>Starting Local nnU-Net Pancreatic Tumor segmentation...</b>")

        module_dir = os.path.dirname(__file__)
        base_results_dir = os.path.join(module_dir, "plans", "seg", "pancreatic_tumor")

        if not os.path.exists(base_results_dir):
            self.log(f"  <b>ERROR:</b> Model directory not found: {base_results_dir}", level="error")
            return False

        dataset_id = "005"
        config_name = "3d_fullres"
        trainer_name = "nnUNetTrainer"
        plan_name = "nnUNetPlans"
        config_dir_name = f"{trainer_name}__{plan_name}__{config_name}"
        dataset_dir = os.path.join(base_results_dir, f"Dataset{dataset_id}_Pancreas")
        config_dir = os.path.join(dataset_dir, config_dir_name)

        plans_json_path = os.path.join(config_dir, "plans.json")
        if not os.path.exists(plans_json_path):
            self.log(f"  <b>ERROR:</b> plans.json not found: {plans_json_path}", level="error")
            return False

        dataset_json_path = os.path.join(config_dir, "dataset.json")
        if not os.path.exists(dataset_json_path):
            dataset_json_src = os.path.join(dataset_dir, "dataset.json")
            if os.path.exists(dataset_json_src):
                self.log(f"  Copying dataset.json to config directory for nnU-Net v2 compatibility...")
                shutil.copy2(dataset_json_src, dataset_json_path)

        if not self._check_gpu_memory(required_mb=4000):
            self.log("  <b>WARNING:</b> Low GPU memory detected. Inference may fail or be unstable.", level="warning")

        env = self._get_clean_subprocess_env()
        env["nnUNet_results"] = base_results_dir
        env["nnUNet_raw"] = base_results_dir
        env["nnUNet_preprocessed"] = os.path.join(base_results_dir, "nnUNet_preprocessed")

        temp_dir = None
        progressDialog = None
        try:
            temp_dir = tempfile.mkdtemp()
            input_folder = os.path.join(temp_dir, "input")
            output_folder = os.path.join(temp_dir, "output")
            os.makedirs(input_folder, exist_ok=True)
            os.makedirs(output_folder, exist_ok=True)

            input_nifti_path = os.path.join(input_folder, "case_0001_0000.nii.gz")
            self.log("  Exporting Slicer volume to temporary NIfTI...")

            try:
                sitk_image = sitkUtils.PullVolumeFromSlicer(input_volume)
                sitk.WriteImage(sitk_image, input_nifti_path)

                if not os.path.exists(input_nifti_path):
                    self.log("  Failed to export volume: file not created", level="error")
                    return False

                file_size = os.path.getsize(input_nifti_path)
                self.log(f"  Exported volume size: {file_size / (1024*1024):.2f} MB")

            except Exception as e:
                self.log(f"  Failed to export volume: {str(e)}", level="error")
                return False

            python_exe = self._get_python_executable()
            # Use wrapper script because nnunetv2's predict_from_raw_data.py
            # __main__ block hardcodes Dataset004_Hippocampus test code.
            # -m mode points directly to model folder, bypassing dataset ID resolution.
            wrapper_script = os.path.join(module_dir, "plans", "seg", "nnunet_infer.py")
            cmd = [
                python_exe, wrapper_script,
                "-m", config_dir,
                "-i", input_folder,
                "-o", output_folder,
                "-f", "0",
                "--disable_tta" if fast_mode else "",
            ]
            cmd = [c for c in cmd if c]

            if fast_mode:
                self.log("  Fast mode enabled: reduced threads, disabled TTA")
                env["nnUNet_n_proc_DA"] = "2"
                env["OMP_NUM_THREADS"] = "4"

            device_str = self._get_device_str()
            nnunet_device = "cpu" if device_str == "cpu" else "cuda"
            cmd += ["-device", nnunet_device]
            self.log(f"  Using device: {nnunet_device}")

            self.log(f"  Executing: {' '.join(cmd)}")
            self.log(f"  Python exe: {cmd[0]}")
            self.log(f"  nnUNet_results: {env.get('nnUNet_results', 'N/A')}")

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            progressDialog = createProgressDialog("Running nnU-Net Pancreatic Tumor segmentation...")
            progressDialog.setValue(0)
            progressDialog.setLabelText("Preparing inference...")
            slicer.app.processEvents()

            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                startupinfo=startupinfo,
                encoding='utf-8',
                errors='replace'
            )

            output_lines = deque()
            progress_data = {"value": 0, "done": False, "error": None, "total_steps": 75, "current_step": 0}
            progress_lock = threading.Lock()

            def read_output():
                try:
                    while True:
                        line = process.stdout.readline()
                        if not line and process.poll() is not None:
                            break
                        stripped = line.strip()
                        if stripped:
                            output_lines.append(stripped)
                            if "%" in stripped and "/" in stripped:
                                try:
                                    parts = stripped.split()
                                    step = 0
                                    pct = 0
                                    for p in parts:
                                        if "/" in p:
                                            try:
                                                step = int(p.split("/")[0])
                                            except ValueError:
                                                pass
                                        if p.endswith("%"):
                                            try:
                                                pct = int(p[:-1])
                                            except ValueError:
                                                pass
                                    if step > 0:
                                        with progress_lock:
                                            progress_data["current_step"] = step
                                            progress_data["value"] = min(10 + int(pct * 0.8), 90)
                                except Exception:
                                    pass
                        if not line:
                            break
                    process.wait()
                    with progress_lock:
                        if process.returncode != 0:
                            progress_data["error"] = f"nnU-Net failed with return code {process.returncode}"
                        progress_data["done"] = True
                        progress_data["value"] = 95
                except Exception as e:
                    with progress_lock:
                        progress_data["error"] = str(e)
                        progress_data["done"] = True

            reader_thread = threading.Thread(target=read_output, daemon=True)
            reader_thread.start()

            while True:
                slicer.app.processEvents()
                # Don't discard output_lines — keep them for error diagnostics
                with progress_lock:
                    if progress_data["done"]:
                        break
                    current_value = progress_data["value"]
                    current_step = progress_data["current_step"]
                progressDialog.setValue(current_value)
                if current_step > 0:
                    progressDialog.setLabelText(f"Inference progress: {current_step}/{progress_data['total_steps']} steps")
                slicer.app.processEvents()
                time.sleep(0.1)

            # Collect remaining output lines
            all_output = list(output_lines)
            output_lines.clear()

            progressDialog.setValue(95)
            progressDialog.setLabelText("Processing results...")
            slicer.app.processEvents()

            with progress_lock:
                error_msg = progress_data["error"]

            if error_msg:
                self.log(f"<b>ERROR:</b> {progress_data['error']}", level="error")
                self.log(f"  Command: {' '.join(cmd)}", level="error")
                self.log(f"  nnUNet_results: {env.get('nnUNet_results', 'N/A')}", level="error")
                self.log(f"  nnUNet_raw: {env.get('nnUNet_raw', 'N/A')}", level="error")
                if all_output:
                    self.log(f"  nnU-Net output ({len(all_output)} lines):", level="error")
                    for line in all_output[-30:]:
                        self.log(f"    {line}", level="error")
                else:
                    self.log("  nnU-Net produced no output", level="error")
                return False

            self.log("  Searching for prediction output...")
            output_files = [f for f in os.listdir(output_folder) if f.endswith('.nii.gz')]

            if not output_files:
                self.log("  Error: No prediction output files found", level="error")
                return False

            output_nifti_filename = output_files[0]
            output_nifti_path = os.path.join(output_folder, output_nifti_filename)
            self.log(f"  Found output file: {output_nifti_filename}")

            if not os.path.exists(output_nifti_path):
                self.log("  Error: Output file path invalid", level="error")
                return False

            output_size = os.path.getsize(output_nifti_path)
            self.log(f"  Output file size: {output_size / (1024*1024):.2f} MB")

            self.log("  Importing segmentation result to Zhiyuan...")

            try:
                output_sitk = sitk.ReadImage(output_nifti_path)
            except Exception as e:
                self.log(f"  Failed to read output NIfTI: {str(e)}", level="error")
                return False

            temp_labelmap = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLabelMapVolumeNode",
                f"nnUNet_Temp_{int(time.time())}"
            )

            label_names = {
                1: ("Pancreatic Tumor", [0.9, 0.3, 0.3]),
                2: ("Artery", [0.8, 0.1, 0.1]),
                3: ("Vein", [0.2, 0.2, 0.8]),
                4: ("Pancreas", [0.9, 0.7, 0.5]),
                5: ("Unknown_5", [0.5, 0.5, 0.5]),
                6: ("Unknown_6", [0.3, 0.3, 0.3]),
            }

            try:
                sitkUtils.PushVolumeToSlicer(output_sitk, temp_labelmap)

                if output_segmentation:
                    success = slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                        temp_labelmap,
                        output_segmentation
                    )

                    if not success:
                        self.log("  Failed to import labelmap to segmentation", level="error")
                        return False

                    seg = output_segmentation.GetSegmentation()
                    num_segments = seg.GetNumberOfSegments()
                    if num_segments > 0:
                        labelmap_array = slicer.util.arrayFromVolume(temp_labelmap)
                        unique_labels = sorted(set(labelmap_array.flatten()))
                        unique_labels = [int(l) for l in unique_labels if int(l) > 0]

                        display_node = output_segmentation.GetDisplayNode()
                        if display_node is None:
                            output_segmentation.CreateDefaultDisplayNodes()
                            display_node = output_segmentation.GetDisplayNode()

                        segment_id_to_label = {}
                        for i, label_val in enumerate(unique_labels):
                            if i < seg.GetNumberOfSegments():
                                segment = seg.GetNthSegment(i)
                                if segment is None:
                                    continue
                                segment_id = seg.GetNthSegmentID(i)
                                segment_id_to_label[segment_id] = label_val

                                if label_val in label_names:
                                    name, color = label_names[label_val]
                                    segment.SetName(name)
                                    segment.SetColor(color)
                                else:
                                    segment.SetName(f"Unknown_{label_val}")
                                    segment.SetColor([0.5, 0.5, 0.5])

                                if display_node and label_val != 1:
                                    display_node.SetSegmentVisibility(segment_id, False)
                                self.log(f"  Segment {label_val}: '{segment.GetName()}'")

                        if 1 not in unique_labels:
                            self.log("  WARNING: Pancreatic Tumor (label 1) not found in output", level="warning")

                        self.log(f"  Segmentation imported: {num_segments} segments, only Tumor visible")
                    else:
                        self.log("  Warning: No segments found in output", level="warning")

                progressDialog.setValue(100)
                progressDialog.setLabelText("Completed!")
                slicer.app.processEvents()

                self.log("<b>Pancreatic tumor segmentation completed successfully.</b>")
                return True

            finally:
                if temp_labelmap:
                    slicer.mrmlScene.RemoveNode(temp_labelmap)

        except Exception as e:
            self.log(f"<b>ERROR:</b> Unexpected error during segmentation: {str(e)}", level="error")
            self.log(f"  Traceback: {traceback.format_exc()}", level="error")
            return False

        finally:
            if progressDialog is not None:
                try:
                    progressDialog.close()
                except Exception:
                    pass
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_prostate_tumor_segmentation(self, input_volume, output_segmentation, fast_mode, label_value):
        """Run Prostate Tumor segmentation (not yet implemented).

        Args:
            input_volume: Input volume node.
            output_segmentation: Output segmentation node.
            fast_mode: Whether to use fast mode.
            label_value: Label value for the segmentation.

        Returns:
            bool: Always False (not yet implemented).
        """
        self.log("Running Prostate Tumor segmentation...")
        self.log("To be developed...")
        return False

    def _run_liver_tumor_segmentation(self, input_volume, output_segmentation, fast_mode, label_value):
        """Run TotalSegmentator 'liver_vessels' task and extract tumor (label 2).

        This task is fully decoupled and does NOT require running 'Total' task first.

        Args:
            input_volume: Input volume node.
            output_segmentation: Output segmentation node.
            fast_mode: Whether to use fast mode.
            label_value: Label value for the tumor segmentation.

        Returns:
            bool: True if segmentation completed successfully, False otherwise.
        """
        return self._run_single_task_segmentation(
            input_volume=input_volume,
            output_segmentation=output_segmentation,
            fast_mode=fast_mode,
            label_value=label_value,
            task_name="Liver Tumor",
            ts_task="liver_vessels",
            result_filename="liver_vessels.nii.gz",
            use_ml=False,
            supports_fast=True,
            source_label=2,
            target_label=label_value,
            progress_label="Running Liver Tumor Segmentation...",
        )

    def _run_skin_segmentation(self, input_volume, output_segmentation, fast_mode, label_value):
        """Run TotalSegmentator 'body' task and extract the skin label.

        In TotalSegmentator v2, 'skin' is no longer a standalone task but
        is included as a label in the 'body' task output. The body task
        produces: body, body_trunc, body_extremities, skin. This method
        runs --task body and extracts the skin label directly.

        Args:
            input_volume: Input volume node.
            output_segmentation: Output segmentation node.
            fast_mode: Whether to use fast mode.
            label_value: Label value for the skin segmentation.

        Returns:
            bool: True if segmentation completed successfully, False otherwise.
        """
        progressDialog = None
        temp_dir = None
        try:
            if output_segmentation is None:
                seg_name = f"Segmentation_Skin_{input_volume.GetName()}"
                output_segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", seg_name)

            temp_dir = slicer.util.tempDirectory()
            input_file = os.path.join(temp_dir, "input.nii.gz")
            output_dir = os.path.join(temp_dir, "segmentation")

            self._write_volume_to_nifti(input_volume, input_file)

            ts_exe = self._find_totalsegmentator_exe()
            device_str = self._get_device_str()

            cmd = [ts_exe]
            cmd.extend(["-i", input_file, "-o", output_dir])
            cmd.extend(["--task", "body", "--device", device_str])
            if fast_mode:
                cmd.append("--fast")

            progressDialog = createProgressDialog("Running Skin Segmentation (via body task)...")
            progressDialog.setValue(0)

            success = self._run_totalsegmentator_subprocess(cmd, progressDialog)
            if not success:
                return False

            skin_file = os.path.join(output_dir, "skin.nii.gz")
            if os.path.exists(skin_file):
                self.log("Found skin.nii.gz from body task, extracting directly...")
                skin_img = nib.load(skin_file)
                skin_data = skin_img.get_fdata().astype(np.uint8)

                result_data = np.zeros_like(skin_data, dtype=np.uint8)
                result_data[skin_data > 0] = label_value

                result_img = nib.Nifti1Image(result_data, skin_img.affine, skin_img.header)
                result_file = os.path.join(temp_dir, "skin_extracted.nii.gz")
                nib.save(result_img, result_file)

                self._load_final_nifti_to_slicer(result_file, input_volume, output_segmentation)
            else:
                self.log("skin.nii.gz not found, falling back to body mask shell extraction...")
                from scipy.ndimage import binary_erosion

                body_file = os.path.join(output_dir, "body.nii.gz")
                if not os.path.exists(body_file):
                    raise RuntimeError("Neither skin.nii.gz nor body.nii.gz found in output")

                body_img = nib.load(body_file)
                body_data = body_img.get_fdata().astype(np.uint8)

                spacing = np.array(body_img.header.get_zooms())
                min_spacing = max(float(np.min(spacing)), 0.1)
                shell_thickness_mm = 5.0
                iterations = max(1, int(round(shell_thickness_mm / min_spacing)))

                eroded_data = binary_erosion(body_data, iterations=iterations).astype(np.uint8)
                shell_data = body_data - eroded_data

                result_data = np.zeros_like(body_data, dtype=np.uint8)
                result_data[shell_data > 0] = label_value

                result_img = nib.Nifti1Image(result_data, body_img.affine, body_img.header)
                result_file = os.path.join(temp_dir, "skin_shell.nii.gz")
                nib.save(result_img, result_file)

                self._load_final_nifti_to_slicer(result_file, input_volume, output_segmentation)

            self.log("Skin segmentation completed successfully.")

            progressDialog.setValue(100)
            progressDialog.close()
            return True

        except Exception as e:
            self.log(f"Error in Skin segmentation: {str(e)}")
            if progressDialog:
                try:
                    progressDialog.close()
                except Exception:
                    pass
            return False
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _merge_label_into_base(self, base_path, new_mask_path, source_label, target_label):
        """Merge a new mask label into a base NIfTI file.

        Reads the new mask, replaces source_label pixels with target_label,
        and writes the merged result back to the base file.

        Args:
            base_path: Path to the base NIfTI file.
            new_mask_path: Path to the new mask NIfTI file.
            source_label: Label value in the new mask to extract.
            target_label: Label value to assign in the merged result.

        Returns:
            bool: True if merge completed successfully, False otherwise.
        """
        try:
            base_img = nib.load(base_path)
            base_data = base_img.get_fdata()

            mask_img = nib.load(new_mask_path)
            mask_data = mask_img.get_fdata()

            mask_pixels = mask_data == source_label
            base_data[mask_pixels] = target_label

            merged_img = nib.Nifti1Image(base_data.astype(np.uint8), base_img.affine, base_img.header)
            nib.save(merged_img, base_path)
            return True
        except Exception as e:
            self.log(f"Error merging NIfTI labels: {str(e)}")
            return False

    def _load_total_segmentator_label_mapping(self):
        """Load TotalSegmentator label mapping from external JSON file.

        Returns:
            dict: Label mapping dictionary with label_id as key and organ name as value.
                  Returns empty dict if loading fails.
        """
        try:
            # Get the directory of the current module
            module_dir = os.path.dirname(os.path.abspath(__file__))
            mapping_file = os.path.join(module_dir, "plans", "seg", "total", "label_mapping.json")

            if not os.path.exists(mapping_file):
                self.log(f"Label mapping file not found: {mapping_file}")
                return {}

            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)

            # Convert string keys to integers for easier lookup
            label_map = {int(k): v for k, v in mapping_data.get("label_map", {}).items()}
            self.log(f"Loaded TotalSegmentator label mapping: {len(label_map)} classes")
            return label_map

        except Exception as e:
            self.log(f"Error loading label mapping: {str(e)}")
            return {}

    # TotalSegmentator v2 OAR categories - bones and vessels are default visible for OAR
    DEFAULT_VISIBLE_OAR_KEYWORDS = [
        # Bones (sacrum, vertebrae, humerus, scapula, clavicula, femur, hip, rib, sternum)
        "sacrum", "vertebrae", "humerus", "scapula", "clavicula", "femur", "hip", "rib", "sternum",
        # Vessels (heart, aorta, pulmonary_vein, brachiocephalic, subclavian_artery, carotid_artery, 
        #          brachiocephalic_vein, atrial_appendage, vena_cava, portal_vein, splenic_vein, iliac_artery, iliac_vena)
        "heart", "aorta", "pulmonary_vein", "brachiocephalic", "subclavian_artery", "carotid_artery",
        "brachiocephalic_vein", "atrial_appendage", "vena_cava", "portal_vein", "splenic_vein",
        "iliac_artery", "iliac_vena"
    ]

    def _is_default_visible_oar(self, segment_name):
        """Check if a segment should be visible by default for OAR purposes.
        
        Args:
            segment_name: Name of the segment.
            
        Returns:
            bool: True if segment is bone or vessel (should be visible by default).
        """
        segment_name_lower = segment_name.lower()
        for keyword in self.DEFAULT_VISIBLE_OAR_KEYWORDS:
            if keyword in segment_name_lower:
                return True
        return False

    def _rename_segments_from_label_mapping(self, output_segmentation, label_mapping):
        """Rename segments in segmentation node using label mapping and set default visibility.

        Args:
            output_segmentation: The segmentation node containing segments to rename.
            label_mapping: Dictionary mapping label IDs to organ names.
        """
        if not label_mapping:
            return

        try:
            segmentation = output_segmentation.GetSegmentation()
            num_renamed = 0
            num_visible = 0
            
            # Get display node for setting visibility
            display_node = output_segmentation.GetDisplayNode()
            if display_node is None:
                output_segmentation.CreateDefaultDisplayNodes()
                display_node = output_segmentation.GetDisplayNode()

            for i in range(segmentation.GetNumberOfSegments()):
                segment = segmentation.GetNthSegment(i)
                segment_name = segment.GetName()
                segment_id = segmentation.GetNthSegmentID(i)

                # Try to extract label value from segment name
                # Slicer typically names imported segments as "Segment_X" or just the number
                label_val = None
                try:
                    if segment_name.startswith("Segment_"):
                        label_val = int(segment_name.split("_")[1])
                    else:
                        # Try to parse the segment name as a number
                        label_val = int(segment_name)
                except (ValueError, IndexError):
                    continue

                # Rename if we have a mapping for this label
                if label_val is not None and label_val in label_mapping:
                    new_name = label_mapping[label_val]
                    segment.SetName(new_name)
                    num_renamed += 1
                    
                    # Set default visibility - bones and vessels visible, others hidden
                    is_visible = self._is_default_visible_oar(new_name)
                    # Use display node's SetSegmentVisibility to control visibility in Slicer
                    if display_node:
                        display_node.SetSegmentVisibility(segment_id, is_visible)
                    # Also set tag for our own tracking
                    segment.SetTag("Visible", "1" if is_visible else "0")
                    if is_visible:
                        num_visible += 1

            if num_renamed > 0:
                self.log(f"Renamed {num_renamed} segments to anatomical names, {num_visible} visible by default")

        except Exception as e:
            self.log(f"Error renaming segments: {str(e)}")

    def _load_final_nifti_to_slicer(self, nifti_path, input_volume, output_segmentation):
        """Load a NIfTI label map into a Slicer segmentation node.

        Clears existing segments, imports the label map, and forces the
        segmentation geometry to match the input CT volume. Also renames
        segments using TotalSegmentator anatomical names if available.

        Args:
            nifti_path: Path to the NIfTI file.
            input_volume: Input volume node for geometry reference.
            output_segmentation: Output segmentation node to populate.

        Raises:
            RuntimeError: If loading the NIfTI file fails.
        """
        try:
            self.log(f"Loading merged NIfTI to Slicer: {nifti_path}")
            label_node = slicer.util.loadLabelVolume(nifti_path)
            if label_node:
                segLogic = slicer.vtkSlicerSegmentationsModuleLogic()

                output_segmentation.GetSegmentation().RemoveAllSegments()

                segLogic.ImportLabelmapToSegmentationNode(label_node, output_segmentation)

                output_segmentation.SetReferenceImageGeometryParameterFromVolumeNode(input_volume)

                # Load label mapping and rename segments
                label_mapping = self._load_total_segmentator_label_mapping()
                self._rename_segments_from_label_mapping(output_segmentation, label_mapping)

                slicer.mrmlScene.RemoveNode(label_node)
                self.log("Successfully updated Segmentation Node in Slicer.")
            else:
                raise RuntimeError("Failed to load merged NIfTI into Slicer")
        except RuntimeError:
            raise
        except Exception as e:
            self.log(f"Error loading NIfTI to Slicer: {str(e)}")
            raise

    def addLine(self, inputVolume, inputLine, inputCT):
        """Adjust a line segment to be perpendicular to a reference plane.

        Args:
            inputVolume: Input volume node (plane).
            inputLine: Input line markup node.
            inputCT: Input CT volume node.

        Raises:
            ValueError: If input plane or line is invalid.
        """
        try:
            if not inputVolume or not inputLine:
                raise ValueError("Input plane or line is invalid")

            normal = np.empty(3)
            inputVolume.GetNormal(normal)
            point1 = np.empty(3)
            inputLine.GetPosition1(point1)
            point2 = np.empty(3)
            inputLine.GetPosition2(point2)
            distance = math.sqrt(sum((point1[i] - point2[i]) ** 2 for i in range(3)))

            normal_unit = np.array(normal) / np.linalg.norm(normal)
            move_vector = normal_unit * distance

            new_point2 = [point1[i] + move_vector[i] for i in range(3)]

            inputLine.SetPosition2(new_point2)

            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            planeID = shNode.GetItemByDataNode(inputVolume)
            lineID = shNode.GetItemByDataNode(inputLine)
            ctID = shNode.GetItemByDataNode(inputCT)
            shNode.SetItemParent(planeID, ctID)
            shNode.SetItemParent(lineID, ctID)
        except Exception as e:
            self.log(f"Error in addLine: {str(e)}")
            raise

    def create_capsule_stl(
        self,
        seed_num,
        input_points_node,
        center,
        direction,
        length=SEED_LENGTH,
        radius=SEED_RADIUS,
        resolution=SEED_RESOLUTION,
        name=None,
    ):
        """Create a capsule-shaped 3D model for a radioactive seed.

        The capsule consists of a cylinder body with two hemispherical end caps.
        The model is added to the Slicer scene as a child of the input points node.

        Args:
            seed_num: Seed number for naming.
            input_points_node: Input points markup node (parent in subject hierarchy).
            center: Center position of the capsule (x, y, z).
            direction: Direction vector of the capsule (x, y, z).
            length: Length of the capsule cylinder portion.
            radius: Radius of the capsule.
            resolution: Resolution of the sphere sources for end caps.
            name: Optional name for the model node.
        """
        try:
            magnitude = math.sqrt(sum([x**2 for x in direction]))
            if magnitude == 0:
                self.log("Error: Zero direction vector in create_capsule_stl")
                return
            direction = [x / magnitude for x in direction]
            length = length - radius * 2.0

            start_point = (
                center[0] - 0.5 * length * direction[0],
                center[1] - 0.5 * length * direction[1],
                center[2] - 0.5 * length * direction[2],
            )

            end_point = (
                center[0] + 0.5 * length * direction[0],
                center[1] + 0.5 * length * direction[1],
                center[2] + 0.5 * length * direction[2],
            )

            cylinder_source = vtk.vtkCylinderSource()
            cylinder_source.SetRadius(radius)
            cylinder_source.SetHeight(length)
            cylinder_source.SetResolution(CAPSULE_CYLINDER_RESOLUTION)
            cylinder_source.Update()

            desired_direction = np.array(direction)
            desired_direction = desired_direction / np.linalg.norm(desired_direction)
            current_direction = np.array([0.0, 1.0, 0.0])
            rotation_axis = np.cross(current_direction, desired_direction)
            cos_angle = np.clip(
                np.dot(current_direction, desired_direction)
                / (np.linalg.norm(current_direction) * np.linalg.norm(desired_direction)),
                -1.0, 1.0
            )
            rotation_angle = np.arccos(cos_angle)

            transform = vtk.vtkTransform()
            transform.RotateWXYZ(np.degrees(rotation_angle), rotation_axis)
            transform_filter = vtk.vtkTransformPolyDataFilter()
            transform_filter.SetInputConnection(cylinder_source.GetOutputPort())
            transform_filter.SetTransform(transform)
            transform_filter.Update()

            transform2 = vtk.vtkTransform()
            transform2.Translate(center)
            transform_filter2 = vtk.vtkTransformPolyDataFilter()
            transform_filter2.SetInputConnection(transform_filter.GetOutputPort())
            transform_filter2.SetTransform(transform2)
            transform_filter2.Update()

            tri1 = vtk.vtkTriangleFilter()
            tri1.SetInputConnection(transform_filter2.GetOutputPort())
            tri1.Update()

            sphere1 = vtk.vtkSphereSource()
            sphere1.SetRadius(radius + CAPSULE_SPHERE_RADIUS_OFFSET)
            sphere1.SetPhiResolution(resolution)
            sphere1.SetThetaResolution(resolution)
            sphere1.SetCenter(start_point)
            sphere1.Update()

            tri2 = vtk.vtkTriangleFilter()
            tri2.SetInputConnection(sphere1.GetOutputPort())
            tri2.Update()

            sphere2 = vtk.vtkSphereSource()
            sphere2.SetRadius(radius + CAPSULE_SPHERE_RADIUS_OFFSET)
            sphere2.SetPhiResolution(resolution)
            sphere2.SetThetaResolution(resolution)
            sphere2.SetCenter(end_point)
            sphere2.Update()

            tri3 = vtk.vtkTriangleFilter()
            tri3.SetInputConnection(sphere2.GetOutputPort())
            tri3.Update()

            appendFilter = vtk.vtkAppendPolyData()
            appendFilter.AddInputData(tri1.GetOutput())
            appendFilter.AddInputData(tri2.GetOutput())
            appendFilter.AddInputData(tri3.GetOutput())
            appendFilter.Update()
            triangleFilter = vtk.vtkTriangleFilter()
            triangleFilter.SetInputConnection(appendFilter.GetOutputPort())
            triangleFilter.Update()

            final_polydata = vtk.vtkPolyData()
            final_polydata.ShallowCopy(triangleFilter.GetOutput())

            # Clean up VTK pipeline - only disconnect filters that have input ports
            # Source objects (vtkCylinderSource, vtkSphereSource) have no input ports
            transform_filter.SetInputConnection(None)
            transform_filter2.SetInputConnection(None)
            tri1.SetInputConnection(None)
            tri2.SetInputConnection(None)
            tri3.SetInputConnection(None)
            appendFilter.RemoveAllInputs()
            triangleFilter.SetInputConnection(None)

            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            pointsID = shNode.GetItemByDataNode(input_points_node)

            seed_node = slicer.modules.models.logic().AddModel(final_polydata)
            seed_node.SetName(f"{input_points_node.GetName()}_seed_{seed_num}")
            seedID = shNode.GetItemByDataNode(seed_node)

            descriptionText = np.array2string(np.array(direction))
            shNode.SetItemAttribute(seedID, "Direction", descriptionText)
            descriptionText = np.array2string(np.array(center))
            shNode.SetItemAttribute(seedID, "Center", descriptionText)
            shNode.SetItemParent(seedID, pointsID)
            shNode.RequestOwnerPluginSearch(seedID)
            shNode.ItemModified(seedID)

        except Exception as e:
            self.log(f"Error creating capsule STL: {str(e)}")

    def image_resample_size(self, sitk_image, new_size=None, is_label=False):
        """Resample a SimpleITK image to a target voxel size.

        Args:
            sitk_image: Input SimpleITK image.
            new_size: Target size as [x, y, z]. Defaults to [128, 128, 128].
            is_label: Whether the image is a label map (uses nearest neighbor interpolation).

        Returns:
            SimpleITK.Image: Resampled image.

        Raises:
            Exception: If resampling fails.
        """
        if new_size is None:
            new_size = RESAMPLE_DEFAULT_SIZE

        try:
            size = np.array(sitk_image.GetSize())
            spacing = np.array(sitk_image.GetSpacing())
            new_size_arr = np.array(new_size)
            new_spacing_refine = size * spacing / new_size_arr
            new_spacing_refine = [float(s) for s in new_spacing_refine]
            new_size_int = [round(s) for s in new_size_arr]

            resample = sitk.ResampleImageFilter()
            resample.SetOutputDirection(sitk_image.GetDirection())
            resample.SetOutputOrigin(sitk_image.GetOrigin())
            resample.SetSize(new_size_int)
            resample.SetOutputSpacing(new_spacing_refine)

            if is_label:
                resample.SetInterpolator(sitk.sitkNearestNeighbor)
            else:
                resample.SetInterpolator(sitk.sitkLinear)

            newimage = resample.Execute(sitk_image)
            return newimage
        except Exception as e:
            self.log(f"Error in image_resample_size: {str(e)}")
            raise

    def image_resample_spacing(self, sitk_image, new_spacing=None, is_label=False):
        """Resample a SimpleITK image to a target voxel spacing.

        Args:
            sitk_image: Input SimpleITK image.
            new_spacing: Target spacing as [x, y, z]. Defaults to [1, 1, 1].
            is_label: Whether the image is a label map (uses nearest neighbor interpolation).

        Returns:
            SimpleITK.Image: Resampled image.

        Raises:
            Exception: If resampling fails.
        """
        if new_spacing is None:
            new_spacing = RESAMPLE_DEFAULT_SPACING

        try:
            size = np.array(sitk_image.GetSize())
            spacing = np.array(sitk_image.GetSpacing())
            new_spacing_arr = [float(s) for s in new_spacing]
            new_size_refine = size * spacing / np.array(new_spacing_arr)
            new_size_refine = [round(s) for s in new_size_refine]

            resample = sitk.ResampleImageFilter()
            resample.SetOutputDirection(sitk_image.GetDirection())
            resample.SetOutputOrigin(sitk_image.GetOrigin())
            resample.SetSize(new_size_refine)
            resample.SetOutputSpacing(new_spacing_arr)

            if is_label:
                resample.SetInterpolator(sitk.sitkNearestNeighbor)
            else:
                resample.SetInterpolator(sitk.sitkLinear)

            newimage = resample.Execute(sitk_image)
            return newimage
        except Exception as e:
            self.log(f"Error in image_resample_spacing: {str(e)}")
            raise
