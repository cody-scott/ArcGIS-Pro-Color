import arcpy
import pandas as pd
import numpy as np
import networkx as nx

from matplotlib import cm
from pathlib import Path
import json
from typing import Optional, Union
from arcgis.features import GeoAccessor, GeoSeriesAccessor


class BaseArcGISGraph:
    def __init__(self):
        self.df = None
        self.graph = None
        arcpy.env.overwriteOutput = True

    def save_graph(self, _path):
        """Save the networkx graph to a csv file

        Args:
            _path (str): Target path for the csv file
        """
        nx.to_pandas_edgelist(self.graph).to_csv(_path, index=False)

    def load_graph(self, _path):
        """Load networkx graph from a csv file

        Args:
            _path (str): Target path for the csv file
        """
        _df = pd.read_csv(_path)        
        self.graph = nx.from_pandas_edgelist(
            _df,
            'source',
            'target',
            edge_attr=[_ for _ in _df.columns if _ not in ['source', 'target']]
        )
    
    def build_relationships(self, feature, comp_field):
        """For a given input point feature, generate a dataframe with the relationships between each point.

        Since this comes from the line feature, it should have a point for each end of adjacent lines. 
        The dataset is spatial joined to itself to find the adjacent lines.

        Then, the dataframe is filter to remove the duplicate relationships and self relationships.

        return structure is simply the two join columns (column name, column name_1) and the X and Y coordinates.

        Args:
            feature (str): Input feature class
            comp_field (str): field to use for the comparison of each relationship

        Returns:
            pd.DataFrame: dataframe of the relationships
        """
        res = arcpy.SpatialJoin_analysis(
            target_features=feature,
            join_features=feature,
            out_feature_class="memory/feature_join",
            join_operation="JOIN_ONE_TO_MANY",
            join_type="KEEP_ALL"
        )

        l = f"{comp_field}"
        r = f"{comp_field}_1" 
        
        df = pd.DataFrame.spatial.from_featureclass(res)        
        df = pd.concat([df, df.SHAPE.apply(pd.Series)], axis=1)
        self.df = df.copy()

        df = df[[l, r]]
        df = df.loc[df[l]!=df[r]]
        df = df.loc[
            pd.DataFrame(
                np.sort(df[[l, r]], 1),
                index=df.index
            ).drop_duplicates(keep='first').index
        ]        
        self.df = df
        return df

    def build_graph(self, feature, field):
        """For a given feature, build a networkx graph.

        Graph is build from an input feature and a field to denote its relationship to other features.

        Args:
            feature (arcpy._mp.Layer): input layer
            field (str): Name of the field to use

        Returns:
            networkx graph: Graph object
        """
        ostate = arcpy.env.addOutputsToMap
        arcpy.env.addOutputsToMap = False
        f = self.convert_feature_to_ends(feature, field)
        df = self.build_relationships(f, field)

        G = nx.from_pandas_edgelist(
            df,
            field,
            f'{field}_1'
        )

        arcpy.env.addOutputsToMap = ostate 
        self.graph=G
        return G

class ArcGISPolygonGraph(BaseArcGISGraph):
    def __init__(self):
        super().__init__()

    def build_graph(self, feature, field):
        """For a given feature, build a networkx graph.

        Graph is build from an input feature and a field to denote its relationship to other features.

        Args:
            feature (arcpy._mp.Layer): input layer
            field (str): Name of the field to use

        Returns:
            networkx graph: Graph object
        """
        ostate = arcpy.env.addOutputsToMap
        arcpy.env.addOutputsToMap = False
        df = self.build_relationships(feature, field)

        G = nx.from_pandas_edgelist(
            df,
            field,
            f'{field}_1'
        )

        arcpy.env.addOutputsToMap = ostate 
        self.graph=G
        return G

class ArcGISPolylineGraph(BaseArcGISGraph):
    def __init__(self):
        super().__init__()

    def convert_feature_to_ends(self, feature, id_field):
        """Converts a polyline feature to a point feature of the start and end location.

        First, generates a point feature class with a template of the input feature.
        Then, looping over the input feature it inserts two rows, one for each end of the feature.

        Args:
            feature (arcpy._mp.Layer): Input layer file
            id_field (str): Field to target for the ID of the feature rows

        Returns:
            str: Feature class object
        """
        desc_obj = arcpy.Describe(feature)
        sr = desc_obj.spatialReference
        f = arcpy.CreateFeatureclass_management(
            out_path="memory",
            out_name="PointFeature",
            geometry_type="POINT",
            template=feature,
            spatial_reference=sr
        )[0]

        _fields = ["SHAPE@", id_field]

        with arcpy.da.InsertCursor(f, _fields) as ic:
            with arcpy.da.SearchCursor(feature, _fields) as sc:
                for row in sc:
                    geom, *data = row

                    for _ in [geom.firstPoint, geom.lastPoint]:
                        ic.insertRow(
                            [arcpy.PointGeometry(_, sr)] + data
                        )
        return f

    def build_graph(self, feature, field):
        """For a given feature, build a networkx graph.

        Graph is build from an input feature and a field to denote its relationship to other features.

        Args:
            feature (arcpy._mp.Layer): input layer
            field (str): Name of the field to use

        Returns:
            networkx graph: Graph object
        """
        ostate = arcpy.env.addOutputsToMap
        arcpy.env.addOutputsToMap = False
        feature = self.convert_feature_to_ends(feature, field)
        df = self.build_relationships(feature, field)

        G = nx.from_pandas_edgelist(
            df,
            field,
            f'{field}_1'
        )

        arcpy.env.addOutputsToMap = ostate 
        self.graph=G
        return G


class BaseColor:
    def __init__(self, cmap: Optional[str]=None, graph: Optional[ArcGISPolylineGraph]=None):
        self.graph = graph
        self.color_mappings = self.load_mappings(cmap)
        self.arcgis_graph_class = None
        
    def load_mappings(self, path: str):        
        if path is None:
            return None
                
        with Path(path).open('r') as f:
            c = json.load(f)
        
        return c
        
    def save_mappings(self, path: str):
        if self.color_mappings is None:
            raise "Must run apply_colors() first"
        with Path(path).open('w') as f:
            json.dump(self.color_mappings, f, indent=4)

    def build_color_map(self, graph):
        c = nx.greedy_color(graph)
        out = {}
        for _ in c:
            v = out.get(c[_], [])
            v.append(_)
            out[c[_]] = v
        return out

    def get_id_mapping(self, _id: str):
        if self.color_mappings is None:
            raise "Must run apply_colors() first"

        for _ in self.color_mappings:
            if _id in self.color_mappings[_]:
                return _
             
    def reapply_colors(self, layer: arcpy._mp.Layer, field: str):
        """Re apply mapping to an existing layer

        This is called either after calling `apply_colors` first, or by suppling a color mapping in the init.

        color map can be saved via `save_mappings` method.

        Args:
            layer (arcpy._mp.Layer): The target layer to apply the colors to
            field (str): target field to apply the colors to
        """
        if self.color_mappings is None:
            raise "Must run apply_colors() first"
        self.update_cim(layer, field, self.color_mappings)

    def apply_colors(self, layer: arcpy._mp.Layer, field: str):
        """Apply the greedy color algorithm to the graph and update the layer's CIM

        If the class is instanciated with a graph, then the graph is used, otherwise
        a new graph is generated from the layer input.

        You may want to re-use a graph if you are applying the same colors to multiple subsets of a dataset.
        Might be costly to create intially, so the graph is cached and can be re-applied in small chunks.

        graph is saved using the `save_graph` method in the ArcGISPolylineGraph class.

        Args:
            layer (arcpy._mp.Layer): The target layer to apply the colors to
            field (str): target field to apply the colors to
        """
        if self.graph is None:
            g = self.arcgis_graph_class()
            g.build_graph(layer, field)
            self.graph = g
        else:
            print('using supplied graph')
            
        c = self.build_color_map(self.graph.graph)
        self.color_mappings = c

        self.update_cim(layer, field, c)
    
    def create_cim_obj(self, name: str):
        return arcpy.cim.CreateCIMObjectFromClassName(name, 'V2')

    def update_cim(self, layer: arcpy._mp.Layer, field: str, cmap: dict):
        cim_def = layer.getDefinition('V2')
        gg = self.create_renderer_cim(field, cmap)
        cim_def.renderer = gg
        cim_def.symbolLayerDrawing = self.create_cim_obj('CIMSymbolLayerDrawing')
        layer.setDefinition(cim_def)

    def create_renderer_cim(self, field: str, cmap: dict, *args, **kwargs):
        rend = self.create_cim_obj('CIMUniqueValueRenderer')
        rend.defaultLabel = "<all other values>"
        rend.defaultSymbol = self._create_symbol()
        rend.colorRamp = self._color_ramp()
        rend.defaultSymbolPatch = "Default"
        rend.polygonSymbolColorTarget = "Fill"
        rend.useDefaultSymbol = True
        rend.valueExpressionInfo = None
        
        rend.fields = [field]
        rend.groups = [self._build_cim_groups(field, cmap)]
        return rend

    def _color_ramp(self, *args, **kwargs):   
        c_space = self.create_cim_obj('CIMICCColorSpace')
        c_space.url = kwargs.get('colorSpace__url', 'Default RGB')
        
        c_ramp = self.create_cim_obj('CIMRandomHSVColorRamp')
        c_ramp.colorSpace = c_space
        
        _defaults = {
            "maxH" : 360,
            "minS" : 15,
            "maxS" : 30,
            "minV" : 99,
            "maxV" : 100,
            "minAlpha" : 100,
            "maxAlpha" : 100
        }
        
        for _ in _defaults:
            # _val = kwargs.get(f"colorSpace__{_}")
            _val = None
            _val = _val if _val is not None else _defaults[_]
            setattr(c_ramp, _, _val)
        
        return c_ramp

    def _create_color_cim(self, cim_type: str, cim_values: list, *args, **kwargs):
        _color = self.create_cim_obj(cim_type)
        _color.values = cim_values
        return _color

    def _create_symbol(self, *args, **kwargs):   
        raise NotImplementedError
        symbol_layer = self.create_cim_obj('CIMSolidStroke')
        cval = kwargs.get(
            'CIMColor', 
            {
                'cim_type': 'CIMRGBColor',
                'cim_values': [130, 130, 130, 100]
            }
        )
        _rgb_color = self._create_color_cim(**cval)
        _stroke_defaults = {
            "enable" : True,
            "capStyle" : "Round",
            "joinStyle" : "Round",
            "lineStyle3D" : "Strip",
            "miterLimit" : 10,
            "width" : 1,
            "color" : _rgb_color
        }
        for _ in _stroke_defaults:
            _val = _stroke_defaults[_]
            setattr(symbol_layer, _, _val)

        
        symbol = self.create_cim_obj('CIMLineSymbol')
        symbol.symbolLayers = [symbol_layer]
        
        symbol_ref = self.create_cim_obj('CIMSymbolReference')
        symbol_ref.symbol = symbol
        return symbol_ref

    def _build_cim_groups(self, field: str, cmap: dict):
        _group = self.create_cim_obj('CIMUniqueValueGroup')
        _group.heading = field
        _group.classes = []
        _colors = [
            [int(_*255) for _ in cm.Paired(_)[:3]]
            for _ in np.linspace(0, 1, len(cmap))
        ]
        
        for _, color in zip(cmap, _colors):
            _group.classes.append(
                self._build_cmap_class(_, cmap[_], color)
            )
            
        return _group
        
    def _build_cmap_class(self, index: Union[str, int], values: list, _rgb: list):
        raise NotImplementedError
        uv_class = self.create_cim_obj('CIMUniqueValueClass')
        uv_class.editable = True    
        uv_class.visible = True
        uv_class.patch = "LineHorizontal"
        
        uv_class.label = str(index)
        uv_class.symbol = self._create_symbol(
            CIMColor={
                    'cim_type': 'CIMRGBColor',
                    'cim_values': _rgb + [100]
                }
        )
        uv_class.values = self._build_cmap_class_values(values)
    
    def _build_cmap_class_values(self, values):
        return_values = []
        for _ in values:
            _val_cim = self.create_cim_obj('CIMUniqueValue')
            _val_cim.fieldValues = [str(_)]
            return_values.append(_val_cim)
        
        return values

class ColorPolygon(BaseColor):
    def __init__(self, cmap: Optional[str] = None, graph: Optional[ArcGISPolygonGraph] = None):
        super().__init__(cmap, graph)
        self.arcgis_graph_class = ArcGISPolygonGraph
    
    def _create_solid_stroke(self, *args, **kwargs):
        solid_stroke_symbol = self.create_cim_obj('CIMSolidStroke')
        cval = kwargs.get(
            'CIMColor__Stroke', 
            {
                'cim_type': 'CIMRGBColor',
                'cim_values': [110, 110, 110, 100]
            }
        )
        _stroke_defaults = {
            "enable" : True,
            "capStyle" : "Round",
            "joinStyle" : "Round",
            "lineStyle3D" : "Strip",
            "miterLimit" : 10,
            "width" : 0.7,
            "color" : self._create_color_cim(**cval)
        }
        for _ in _stroke_defaults:
            _val = _stroke_defaults[_]
            setattr(solid_stroke_symbol, _, _val)
        return solid_stroke_symbol

    def _create_fill_symbol(self, *args, **kwargs):
        sym = self.create_cim_obj("CIMSolidFill")
        cval = kwargs.get(
                    'CIMColor__Fill', 
                    {
                        'cim_type': 'CIMRGBColor',
                        'cim_values': [130, 130, 130, 100]
                    }
        )

        _stroke_defaults = {
            "enable" : True,
            "color" : self._create_color_cim(**cval)
        }
        for _ in _stroke_defaults:
            _val = _stroke_defaults[_]
            setattr(sym, _, _val)
        return sym

    def _create_symbol(self, *args, **kwargs):   
        solid_stroke_symbol = self._create_solid_stroke(*args, **kwargs)
        fill_sym = self._create_fill_symbol(*args, **kwargs)
        
        symbol = self.create_cim_obj('CIMPolygonSymbol')
        symbol.symbolLayers = [solid_stroke_symbol, fill_sym]
        
        symbol_ref = self.create_cim_obj('CIMSymbolReference')
        symbol_ref.symbol = symbol
        return symbol_ref

    def _build_cmap_class(self, index: Union[str, int], values: list, _rgb: list):
        uv_class = self.create_cim_obj('CIMUniqueValueClass')
        uv_class.editable = True    
        uv_class.visible = True
        uv_class.patch = "Default"
        
        uv_class.label = str(index)
        uv_class.symbol = self._create_symbol(
            CIMColor__Fill={
                    'cim_type': 'CIMRGBColor',
                    'cim_values': _rgb + [100]
                }
        )
        uv_class.values = self._build_cmap_class_values(values)
        return uv_class

class ColorPolyline(BaseColor):
    def __init__(self, cmap: Optional[str] = None, graph: Optional[ArcGISPolylineGraph] = None):
        super().__init__(cmap, graph)
        self.arcgis_graph_class = ArcGISPolylineGraph
        
    def _create_symbol(self, *args, **kwargs):   
        symbol_layer = self.create_cim_obj('CIMSolidStroke')
        cval = kwargs.get(
            'CIMColor', 
            {
                'cim_type': 'CIMRGBColor',
                'cim_values': [130, 130, 130, 100]
            }
        )
        _rgb_color = self._create_color_cim(**cval)
        _stroke_defaults = {
            "enable" : True,
            "capStyle" : "Round",
            "joinStyle" : "Round",
            "lineStyle3D" : "Strip",
            "miterLimit" : 10,
            "width" : 1,
            "color" : _rgb_color
        }
        for _ in _stroke_defaults:
            _val = _stroke_defaults[_]
            setattr(symbol_layer, _, _val)

        
        symbol = self.create_cim_obj('CIMLineSymbol')
        symbol.symbolLayers = [symbol_layer]
        
        symbol_ref = self.create_cim_obj('CIMSymbolReference')
        symbol_ref.symbol = symbol
        return symbol_ref

    def _build_cmap_class(self, index: Union[str, int], values: list, _rgb: list):
        uv_class = self.create_cim_obj('CIMUniqueValueClass')
        uv_class.editable = True    
        uv_class.visible = True
        uv_class.patch = "LineHorizontal"
        
        uv_class.label = str(index)
        uv_class.symbol = self._create_symbol(
            CIMColor={
                    'cim_type': 'CIMRGBColor',
                    'cim_values': _rgb + [100]
                }
        )
        uv_class.values = self._build_cmap_class_values(values)
        return uv_class


if __name__ == "__main__":
    proj = arcpy.mp.ArcGISProject(Path("NetworkTest.aprx").absolute())
    m = proj.listMaps()[0]


    l = m.listLayers('WaterP*')[0]
    cpl = ColorPolygon()
    cpl.apply_colors(l, 'Zone')
    

    # l = m.listLayers('Ayr*')[0]
    # cpl = ColorPolyline()
    # cpl.apply_colors(l, 'WaterMainID')

