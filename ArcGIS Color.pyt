# -*- coding: utf-8 -*-

import arcpy
from ArcGISColor import ColorPolygon, ColorPolyline

import sys
in_pro = True if "ArcGISPro.exe" in sys.executable else False

class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "Toolbox"
        self.alias = "toolbox"

        # List of tool classes associated with this toolbox
        self.tools = [GreedyColorFeature]


class GreedyColorFeature(object):
    meta_params = {
        "input_layer": {
            'dialog_reference': """
            Input layer for the greedy color algorithm. This needs to be a layer in an existing map.

            Should be the long name of the field in the map

            Example:

            `Group Layer1/Layer1`

            or

            `Layer1`

            """
        },
        'input_field': {
            'dialog_reference': """
            String field name in the input layer.

            Example:
            `FieldA`

            `FieldB`

            """
        }
    }
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Greedy Color Feature"
        self.description = "Applies the greedy color algorithm to a feature class."
        self.canRunInBackground = False

        self.current_map = None

    def getParameterInfo(self):
        """Define parameter definitions"""
        input_layer = arcpy.Parameter(
            displayName="Input Layer",
            name="input_layer",
            # datatype="GPString",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )

        input_field = arcpy.Parameter(
            displayName="Input Field",
            name="input_field",
            datatype="Field",
            direction="Input"
        )
        input_field.parameterDependencies = [input_layer.name]

        params = [input_layer, input_field]
        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""
        p = arcpy.mp.ArcGISProject("CURRENT")
        m = p.activeMap
        layers = [_.longName for _ in m.listLayers()]

        if not hasattr(parameters[0].value, 'longName') or not parameters[0].valueAsText in layers:
            parameters[0].setErrorMessage(f"Layer not found in map. {parameters[0].valueAsText}")
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""
        _feature = parameters[0].valueAsText
        _field = parameters[1].valueAsText
        self.do_work(
            feature=_feature, 
            field=_field
        )
        return

    def do_work(self, feature, field, map_name=None, project_file=None, *args, **kwargs):
        if in_pro:
            proj = arcpy.mp.ArcGISProject("CURRENT")
            map = proj.activeMap
        else:
            proj = arcpy.mp.ArcGISProject(project_file)
            map = proj.listMaps(map_name)
            if len(map) == 0:
                msg = "No map found with name {}".format(map_name)
                arcpy.AddError(msg)
                raise Exception(msg)
            map = map[0]

        feature = self._get_map_layer(map, feature)
        _class = self._get_color_class(feature)
        _class.apply_colors(feature, field)

        if not in_pro:
            proj.save()

    def _get_map_layer(self, map, feature):
        feature = map.listLayers(feature)
        if len(feature) == 0:
            msg = f"Could not find layer in map {map.name}"
            arcpy.AddError(msg)
            raise Exception(msg)
        feature = feature[0]
        return feature

    def _get_color_class(self, feature):
        """Determine if its a polygon or a polyline, and return the appropriate color class"""
        _colors = {
            'Polygon': ColorPolygon,
            'Polyline': ColorPolyline
        }
        feature_type = arcpy.Describe(feature).shapeType
        _class_var = _colors.get(feature_type, None)
        if _class_var is None:
            msg = "Unknown feature type: {}".format(feature_type)
            arcpy.AddError(msg)
            raise Exception(msg)
        arcpy.AddMessage(f"{feature_type} shape detected")
        return _class_var()
