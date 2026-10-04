"""Host-side checks for the bounded extended Design API layer."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup  # Installs the host-side adsk stubs before importing tools.
from tools import design_extended as extended


class Collection:
    def __init__(self, values=()):
        self.values = list(values)
        self.count = len(self.values)

    def item(self, index):
        return self.values[index]


class ExtendedDesignTests(unittest.TestCase):
    def test_sheet_metal_rules_list_reports_unavailable_data_root(self):
        with patch.object(extended, "_rules", side_effect=RuntimeError("smDataRoot")):
            result = extended.sheet_metal_rules_list({})
        self.assertFalse(result["available"])
        self.assertEqual(result["rules"], [])
        self.assertIn("sheet-metal component", result["warning"])

    def test_unique_rejects_ambiguous_names(self):
        values = [SimpleNamespace(name="Body", entityToken="a"),
                  SimpleNamespace(name="Body", entityToken="b")]
        with self.assertRaisesRegex(ValueError, "resolve uniquely; matches: 2"):
            extended._unique(values, "Body", "Body")

    def test_capabilities_report_operation_level_blockers(self):
        features = SimpleNamespace(patchFeatures=object(), formFeatures=object())
        root = SimpleNamespace(features=features, meshBodies=object())
        design = SimpleNamespace(
            rootComponent=root,
            designSheetMetalRules=None,
            materials=object(), appearances=object(),
            isConfiguredDesign=False,
            createConfiguredDesign=lambda: None,
            designType=1,
        )
        with patch.object(extended, "_get_design", return_value=design), \
             patch.object(extended.adsk.fusion, "DesignTypes",
                          SimpleNamespace(DirectDesignType=0), create=True):
            result = extended.capabilities({})
        self.assertTrue(result["areas"]["surfaces"]["operations"]["patch"]["available"])
        self.assertFalse(result["areas"]["surfaces"]["operations"]["stitch"]["available"])
        self.assertIn("blocker", result["areas"]["surfaces"]["operations"]["stitch"])
        self.assertFalse(result["areas"]["meshes"]["operations"]["create-triangles"]["available"])
        self.assertFalse(result["areas"]["configurations"]["operations"]["edit"]["available"])
        self.assertIn("Feature creation remains unavailable",
                      result["areas"]["sheet_metal"]["blocker"])

    def test_mesh_validation_stops_before_fusion_api(self):
        get_design = Mock()
        with patch.object(extended, "_get_design", get_design):
            with self.assertRaisesRegex(ValueError, "outside the coordinate array"):
                extended.meshes_create_triangles({
                    "coordinates_mm": [0, 0, 0, 10, 0, 0, 0, 10, 0],
                    "indices": [0, 1, 3],
                })
        get_design.assert_not_called()

    def test_parametric_mesh_uses_base_feature_edit_lifecycle(self):
        body = SimpleNamespace(
            name="Mesh", entityToken="mesh-token", parentComponent=SimpleNamespace(name="Root"),
            boundingBox=SimpleNamespace(
                minPoint=SimpleNamespace(x=0, y=0, z=0),
                maxPoint=SimpleNamespace(x=1, y=1, z=0)),
            mesh=SimpleNamespace(nodeCount=3, polygonCount=1), isClosed=False, isOriented=True,
            area=0.5, volume=0, isVisible=True, opacity=1.0,
        )
        meshes = Mock()
        meshes.addByTriangleMeshData.return_value = body
        base = Mock()
        base.startEdit.return_value = True
        base.finishEdit.return_value = True
        base_features = Mock()
        base_features.add.return_value = base
        root = SimpleNamespace(meshBodies=meshes,
                               features=SimpleNamespace(baseFeatures=base_features))
        design = SimpleNamespace(rootComponent=root, designType=1)
        with patch.object(extended, "_get_design", return_value=design), \
             patch.object(extended.adsk.fusion, "DesignTypes",
                          SimpleNamespace(DirectDesignType=0), create=True):
            result = extended.meshes_create_triangles({
                "coordinates_mm": [0, 0, 0, 10, 0, 0, 0, 10, 0],
                "indices": [0, 1, 2], "name": "Triangle",
            })
        base.startEdit.assert_called_once_with()
        base.finishEdit.assert_called_once_with()
        meshes.addByTriangleMeshData.assert_called_once_with(
            [0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2], [], [])
        self.assertEqual(result["name"], "Triangle")

    def test_mesh_edit_validates_opacity(self):
        body = SimpleNamespace(name="Mesh", entityToken="m")
        with patch.object(extended, "_mesh_bodies", return_value=[body]):
            with self.assertRaisesRegex(ValueError, "between 0 and 1"):
                extended.meshes_edit({"mesh": "m", "opacity": 1.1})

    def test_sheet_metal_delete_blocks_used_rule(self):
        rule = SimpleNamespace(name="Rule", isUsed=True)
        with patch.object(extended, "_rules", return_value=Collection([rule])):
            with self.assertRaisesRegex(ValueError, "used by a component"):
                extended.sheet_metal_rules_delete({"rule": "Rule"})

    def test_configuration_list_reports_unconfigured_document(self):
        with patch.object(extended, "_get_design",
                          return_value=SimpleNamespace(configurationTopTable=None)):
            result = extended.configurations_list({})
        self.assertFalse(result["configured"])
        self.assertIn("Initialize", result["blocker"])

    def test_configuration_delete_blocks_active_row(self):
        row = SimpleNamespace(id="row-1", name="Default", index=0)
        table = SimpleNamespace(rows=Collection([row]), activeRow=row)
        with patch.object(extended, "_configuration_table", return_value=table):
            with self.assertRaisesRegex(ValueError, "active row"):
                extended.configurations_delete({"configuration": "row-1"})

    def test_configuration_edit_updates_supported_cell(self):
        cell = SimpleNamespace(objectType="ConfigurationParameterCell", expression="10 mm")
        row = Mock(id="row-1", name="Small", index=1, isTestRow=False)
        row.getCellByColumnIndex.return_value = cell
        table = SimpleNamespace(rows=Collection([row]), activeRow=None,
                                columns=SimpleNamespace(count=1))
        with patch.object(extended, "_configuration_table", return_value=table):
            result = extended.configurations_edit({
                "configuration": "row-1", "column_index": 0, "expression": "12 mm"})
        self.assertEqual(cell.expression, "12 mm")
        self.assertEqual(result["cell"]["expression"], "12 mm")

    def test_configuration_edit_rejects_unsupported_cell_field(self):
        cell = SimpleNamespace(objectType="ConfigurationMaterialCell")
        row = Mock(id="row-1", name="Small", index=1, isTestRow=False)
        row.getCellByColumnIndex.return_value = cell
        table = SimpleNamespace(rows=Collection([row]), activeRow=None,
                                columns=SimpleNamespace(count=1))
        with patch.object(extended, "_configuration_table", return_value=table):
            with self.assertRaisesRegex(ValueError, "does not support expression"):
                extended.configurations_edit({
                    "configuration": "row-1", "column_index": 0, "expression": "12 mm"})

    def test_material_apply_copies_library_asset_into_design(self):
        source = SimpleNamespace(id="steel-id", name="Steel")
        copied = SimpleNamespace(id="design-steel", name="Steel")
        library = SimpleNamespace(id="lib", name="Fusion Material Library",
                                  materials=Collection([source]), appearances=Collection())
        libraries = Collection([library])
        target = SimpleNamespace(entityToken="body-token", name="Body",
                                 material=None, appearance=None)
        design_materials = Mock()
        design_materials.itemById.return_value = None
        design_materials.addByCopy.return_value = copied
        design = SimpleNamespace(materials=design_materials, appearances=Mock())
        app = SimpleNamespace(materialLibraries=libraries)
        with patch.object(extended, "_material_target", return_value=target), \
             patch.object(extended, "_get_design", return_value=design), \
             patch.object(extended.adsk.core.Application, "get", return_value=app):
            result = extended.materials_apply({
                "target": "body-token", "library": "lib", "material": "steel-id"})
        design_materials.addByCopy.assert_called_once_with(source, "Steel")
        self.assertIs(target.material, copied)
        self.assertEqual(result["material"], "Steel")

    def test_material_copy_uses_design_collection(self):
        source = SimpleNamespace(id="steel-id", name="Steel")
        copied = SimpleNamespace(id="custom-steel", name="Custom Steel", isUsed=False,
                                 description="", appearance=None)
        library = SimpleNamespace(id="lib", name="Library",
                                  materials=Collection([source]), appearances=Collection())
        materials = Mock()
        materials.addByCopy.return_value = copied
        design = SimpleNamespace(materials=materials, appearances=Collection())
        app = SimpleNamespace(materialLibraries=Collection([library]))
        with patch.object(extended, "_get_design", return_value=design), \
             patch.object(extended.adsk.core.Application, "get", return_value=app):
            result = extended.materials_copy({
                "type": "material", "library": "lib", "source": "steel-id",
                "name": "Custom Steel"})
        materials.addByCopy.assert_called_once_with(source, "Custom Steel")
        self.assertEqual(result["id"], "custom-steel")

    def test_material_delete_blocks_used_design_asset(self):
        asset = SimpleNamespace(id="steel", name="Steel", isUsed=True)
        with patch.object(extended, "_design_asset", return_value=asset):
            with self.assertRaisesRegex(ValueError, "used by the design"):
                extended.materials_delete({"type": "material", "asset": "steel"})


if __name__ == "__main__":
    unittest.main()
