from arcgis.features import GeoAccessor, GeoSeriesAccessor

import arcpy
import networkx as nx
import pandas as pd
import numpy as np

class BaseArcGISGraph(object):
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
        # df = pd.concat([df, df.SHAPE.apply(pd.Series)], axis=1)
        self.df = df.copy()

        df = df[[l, r]]
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
