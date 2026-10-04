import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup
from tools import core_design


class Collection(list):
    @property
    def count(self):
        return len(self)

    def item(self, index):
        return self[index]


class Point(SimpleNamespace):
    def move(self, vector):
        self.geometry.x += vector.x
        self.geometry.y += vector.y
        self.geometry.z += vector.z
        return True


def point(x, y):
    return Point(geometry=SimpleNamespace(x=x, y=y, z=0))


def line(token, x1=0, y1=0, x2=1, y2=0):
    return SimpleNamespace(
        entityToken=token,
        objectType="adsk::fusion::SketchLine",
        isConstruction=False,
        isFixed=False,
        isFullyConstrained=False,
        isDeletable=True,
        isLinked=False,
        isValid=True,
        startSketchPoint=point(x1, y1),
        endSketchPoint=point(x2, y2),
        length=((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5,
        isCenterLine=False,
        deleteMe=Mock(return_value=True),
    )


def circle(token, x=0, y=0, radius=1):
    return SimpleNamespace(
        entityToken=token,
        objectType="adsk::fusion::SketchCircle",
        isConstruction=False,
        isFixed=False,
        isFullyConstrained=False,
        isDeletable=True,
        isLinked=False,
        isValid=True,
        centerSketchPoint=point(x, y),
        radius=radius,
        deleteMe=Mock(return_value=True),
    )


class CoreDesignTests(unittest.TestCase):
    def setUp(self):
        self.line = line("line-1")
        self.circle = circle("circle-1")
        self.constraints = Collection()
        self.constraints.addHorizontal = Mock(
            return_value=self.constraint("constraint-1", "HorizontalConstraint")
        )
        self.constraints.addParallel = Mock(
            return_value=self.constraint("constraint-2", "ParallelConstraint")
        )
        self.constraints.addPerpendicular2 = Mock(
            return_value=self.constraint("constraint-3", "PerpendicularConstraint")
        )
        self.constraints.addCoincident = Mock(
            return_value=self.constraint("constraint-4", "CoincidentConstraint")
        )
        self.dimensions = Collection()
        self.design = SimpleNamespace(computeAll=Mock(return_value=True))
        self.design.findEntityByToken = self.find
        self.sketch = SimpleNamespace(
            name="Layout",
            entityToken="sketch-1",
            parentComponent=SimpleNamespace(parentDesign=self.design),
            sketchCurves=Collection([self.line, self.circle]),
            geometricConstraints=self.constraints,
            sketchDimensions=self.dimensions,
        )
        self.sketch.sketchCurves.sketchLines = SimpleNamespace(
            addByTwoPoints=Mock(), addTwoPointRectangle=Mock()
        )
        self.sketch.sketchCurves.sketchCircles = SimpleNamespace(
            addByCenterRadius=Mock()
        )
        finder = patch.object(core_design, "_find_sketch", return_value=self.sketch)
        finder.start()
        self.addCleanup(finder.stop)
        p3 = patch.object(
            core_design.adsk.core,
            "Point3D",
            SimpleNamespace(create=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)),
            create=True,
        )
        v3 = patch.object(
            core_design.adsk.core,
            "Vector3D",
            SimpleNamespace(create=lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)),
            create=True,
        )
        p3.start(); v3.start()
        self.addCleanup(p3.stop); self.addCleanup(v3.stop)

    def constraint(self, token, kind):
        return SimpleNamespace(
            entityToken=token,
            objectType="adsk::fusion::" + kind,
            isDeletable=True,
            isValid=True,
            deleteMe=Mock(return_value=True),
        )

    def dimension(self, token="dimension-1"):
        return SimpleNamespace(
            entityToken=token,
            objectType="adsk::fusion::SketchLinearDimension",
            isDriving=True,
            isDeletable=True,
            isValid=True,
            value=2.5,
            parameter=SimpleNamespace(name="d1", expression="25 mm", unit="mm"),
            deleteMe=Mock(return_value=True),
        )

    def find(self, token):
        entities = list(self.sketch.sketchCurves) + list(self.constraints) + list(self.dimensions)
        return [entity for entity in entities if entity.entityToken == token]

    def test_geometry_list_has_coordinates_and_tokens(self):
        result = core_design.geometry_list({"sketch": "sketch-1"})
        self.assertEqual(result["geometry"][0]["start"], {"x_mm": 0.0, "y_mm": 0.0})
        self.assertEqual(result["geometry"][1]["radius_mm"], 10.0)
        self.assertIn("four SketchLine", result["rectangle_note"])

    def test_line_and_circle_creation_return_stable_tokens(self):
        created_line = line("new-line")
        created_circle = circle("new-circle")
        self.sketch.sketchCurves.sketchLines.addByTwoPoints.return_value = created_line
        self.sketch.sketchCurves.sketchCircles.addByCenterRadius.return_value = created_circle
        result = core_design.lines_add({
            "sketch": "sketch-1", "x1_mm": 0, "y1_mm": 0,
            "x2_mm": 10, "y2_mm": 0,
        })
        self.assertEqual(result["line"]["token"], "new-line")
        result = core_design.circles_add({
            "sketch": "sketch-1", "center_x_mm": 0, "center_y_mm": 0,
            "radius_mm": 10,
        })
        self.assertEqual(result["circle"]["token"], "new-circle")

    def test_line_edit_moves_both_endpoints_in_mm(self):
        result = core_design.lines_edit({
            "sketch": "sketch-1", "entity": "line-1",
            "x1_mm": 10, "y1_mm": 20, "x2_mm": 30, "y2_mm": 40,
        })
        self.assertEqual(result["line"]["start"], {"x_mm": 10.0, "y_mm": 20.0})
        self.assertEqual(result["line"]["end"], {"x_mm": 30.0, "y_mm": 40.0})

    def test_circle_edit_moves_center_and_sets_radius(self):
        result = core_design.circles_edit({
            "sketch": "sketch-1", "entity": "circle-1",
            "center_x_mm": 5, "center_y_mm": 6, "radius_mm": 12,
        })
        self.assertEqual(result["circle"]["center"], {"x_mm": 5.0, "y_mm": 6.0})
        self.assertEqual(result["circle"]["radius_mm"], 12.0)
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            core_design.circles_edit({
                "sketch": "sketch-1", "entity": "circle-1",
                "center_x_mm": 0, "center_y_mm": 0, "radius_mm": 0,
            })

    def test_rectangle_creation_requires_four_lines_and_returns_each_token(self):
        lines = Collection([line("r" + str(index)) for index in range(4)])
        self.sketch.sketchCurves.sketchLines.addTwoPointRectangle.return_value = lines
        result = core_design.rectangles_add({
            "sketch": "sketch-1", "x1_mm": 0, "y1_mm": 0,
            "x2_mm": 20, "y2_mm": 10,
        })
        self.assertEqual([item["token"] for item in result["lines"]], ["r0", "r1", "r2", "r3"])

    def test_construction_toggle_and_entity_delete_are_verified(self):
        changed = core_design.geometry_set_construction({
            "sketch": "sketch-1", "entity": "line-1", "construction": True,
        })
        self.assertTrue(changed["geometry"]["construction"])
        deleted = core_design.geometry_delete({"sketch": "sketch-1", "entity": "line-1"})
        self.assertEqual(deleted["deleted"]["token"], "line-1")
        self.line.deleteMe.assert_called_once()

    def test_fixed_toggle_uses_public_sketch_entity_property(self):
        result = core_design.geometry_set_fixed({
            "sketch": "sketch-1", "entity": "line-1", "fixed": True,
        })
        self.assertTrue(result["geometry"]["fixed"])

    def test_stale_or_wrong_entity_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            core_design.geometry_delete({"sketch": "sketch-1", "entity": "missing"})
        with self.assertRaisesRegex(ValueError, "Line edit requires"):
            core_design.lines_edit({
                "sketch": "sketch-1", "entity": "circle-1",
                "x1_mm": 0, "y1_mm": 0, "x2_mm": 1, "y2_mm": 1,
            })

    def test_constraints_list_add_and_delete(self):
        existing = self.constraint("existing", "HorizontalConstraint")
        self.constraints.append(existing)
        listed = core_design.constraints_list({"sketch": "sketch-1"})
        self.assertEqual(listed["constraints"][0]["token"], "existing")
        added = core_design.constraints_add({
            "sketch": "sketch-1", "type": "horizontal", "entity": "line-1",
        })
        self.assertEqual(added["constraint"]["type"], "HorizontalConstraint")
        core_design.constraints_delete({"sketch": "sketch-1", "constraint": "existing"})
        existing.deleteMe.assert_called_once()

    def test_constraint_shapes_are_validated(self):
        second = line("line-2")
        self.sketch.sketchCurves.append(second)
        core_design.constraints_add({
            "sketch": "sketch-1", "type": "perpendicular",
            "entity": "line-1", "second_entity": "line-2",
        })
        self.constraints.addPerpendicular2.assert_called_once_with(self.line, second)
        core_design.constraints_add({
            "sketch": "sketch-1", "type": "coincident",
            "entity": "line-1", "point": "end", "second_entity": "circle-1",
        })
        self.constraints.addCoincident.assert_called_once_with(
            self.line.endSketchPoint, self.circle
        )
        core_design.constraints_add({
            "sketch": "sketch-1", "type": "coincident",
            "entity": "line-1", "point": "start", "second_entity": "line-2",
            "second_point": "end",
        })
        self.constraints.addCoincident.assert_called_with(
            self.line.startSketchPoint, second.endSketchPoint
        )

    def test_dimensions_list_set_with_expected_value_and_delete(self):
        dimension = self.dimension()
        self.dimensions.append(dimension)
        listed = core_design.dimensions_list({"sketch": "sketch-1"})
        self.assertEqual(listed["dimensions"][0]["expression"], "25 mm")
        changed = core_design.dimensions_set({
            "sketch": "sketch-1", "dimension": "dimension-1",
            "expected_expression": "25 mm", "expression": "30 mm",
        })
        self.assertEqual(changed["dimension"]["expression"], "30 mm")
        self.design.computeAll.assert_called_once()
        core_design.dimensions_delete({"sketch": "sketch-1", "dimension": "dimension-1"})
        dimension.deleteMe.assert_called_once()

    def test_dimension_concurrent_change_and_direct_mode_are_rejected(self):
        dimension = self.dimension()
        self.dimensions.append(dimension)
        with self.assertRaisesRegex(ValueError, "changed since inspection"):
            core_design.dimensions_set({
                "sketch": "sketch-1", "dimension": "dimension-1",
                "expected_expression": "20 mm", "expression": "30 mm",
            })
        dimension.parameter = None
        with self.assertRaisesRegex(ValueError, "direct-modeling"):
            core_design.dimensions_set({
                "sketch": "sketch-1", "dimension": "dimension-1",
                "expression": "30 mm",
            })


if __name__ == "__main__":
    unittest.main()
