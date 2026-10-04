import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_startup
from tools import design_assemblies as assemblies


class Collection(list):
    @property
    def count(self):
        return len(self)

    def item(self, index):
        return self[index]


class Matrix:
    def __init__(self, values=None):
        self.values = list(values or [1, 0, 0, 0, 0, 1, 0, 0,
                                      0, 0, 1, 0, 0, 0, 0, 1])

    @property
    def translation(self):
        return SimpleNamespace(x=self.values[3], y=self.values[7], z=self.values[11])

    def asArray(self):
        return list(self.values)

    def setWithArray(self, values):
        self.values = list(values)
        return True


class Origin:
    def createForAssemblyContext(self, occurrence):
        return ("origin", occurrence.fullPathName)


def component(name, component_id):
    return SimpleNamespace(name=name, id=component_id, entityToken="component-" + component_id,
                           isValid=True, joints=Collection(), asBuiltJoints=Collection(),
                           originConstructionPoint=Origin(), bRepBodies=Collection())


def occurrence(path, owner, token):
    value = SimpleNamespace(fullPathName=path, name=path.rsplit("+", 1)[-1],
                            component=owner, entityToken=token, isValid=True,
                            isGrounded=False, isGroundToParent=False,
                            isReferencedComponent=False, isDerived=False,
                            isVisible=True, transform2=Matrix(), assemblyContext=None,
                            nativeObject=None)

    def delete():
        value.isValid = False
        return True
    value.deleteMe = delete
    return value


class Limits:
    def __init__(self):
        self.minimumValue = 0
        self.maximumValue = 0
        self.restValue = 0
        self.isMinimumValueEnabled = False
        self.isMaximumValueEnabled = False
        self.isRestValueEnabled = False


def joint(name="Hinge"):
    motion = SimpleNamespace(objectType="adsk::fusion::RevoluteJointMotion",
                             rotationValue=0.0, rotationLimits=Limits())
    value = SimpleNamespace(name=name, entityToken="joint-" + name, isValid=True,
                            nativeObject=None, assemblyContext=None, jointMotion=motion,
                            isLocked=False, isSuppressed=False, isFlipped=False,
                            occurrenceOne=None, occurrenceTwo=None, healthState="healthy",
                            errorOrWarningMessage="")
    value.createForAssemblyContext = lambda context: value
    value.timelineObject = SimpleNamespace(rollTo=lambda before: True)
    value.setAsRigidJointMotion = lambda: setattr(value, "jointMotion", SimpleNamespace(
        objectType="adsk::fusion::RigidJointMotion")) or True
    value.setAsRevoluteJointMotion = lambda axis: True
    value.setAsSliderJointMotion = lambda axis: True
    value.deleteMe = lambda: setattr(value, "isValid", False) or True
    return value


class Occurrences(Collection):
    def __init__(self, root, all_occurrences):
        super().__init__()
        self.root = root
        self.all_occurrences = all_occurrences

    def addNewComponent(self, matrix):
        comp = component("Component", "created")
        item = occurrence("Component:1", comp, "occ-created")
        self.append(item)
        self.all_occurrences.append(item)
        return item

    def addExistingComponent(self, comp, matrix):
        item = occurrence(comp.name + ":2", comp, "occ-copy")
        self.append(item)
        self.all_occurrences.append(item)
        return item


class Joints(Collection):
    def __init__(self):
        super().__init__()
        self.last_input = None

    def createInput(self, one, two):
        self.last_input = SimpleNamespace(geometryOrOriginOne=one, geometryOrOriginTwo=two,
                                          isFlipped=False,
                                          setAsRigidJointMotion=lambda: True,
                                          setAsRevoluteJointMotion=lambda axis: True,
                                          setAsSliderJointMotion=lambda axis: True)
        return self.last_input

    def add(self, value):
        item = joint("Joint")
        self.append(item)
        return item


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        assemblies._selectors.clear()
        self.root = component("Root", "root")
        self.root.timeline = None
        self.root.joints = Joints()
        self.all_occurrences = Collection()
        self.root.allOccurrences = self.all_occurrences
        self.root.occurrences = Occurrences(self.root, self.all_occurrences)
        self.front_component = component("Leg", "leg")
        self.front = occurrence("Robot:1+Front:1", self.front_component, "front")
        self.rear = occurrence("Robot:1+Rear:1", self.front_component, "rear")
        self.all_occurrences.extend([self.front, self.rear])
        self.design = SimpleNamespace(rootComponent=self.root,
                                      timeline=SimpleNamespace(moveToEnd=lambda: None))
        entities = [self.root, self.front_component, self.front, self.rear]
        self.design.findEntityByToken = lambda token: [
            item for item in entities if getattr(item, "entityToken", None) == token]
        self.document = SimpleNamespace(creationId="doc-a", name="Robot")
        self.context = patch.object(assemblies, "_context",
                                    return_value=(self.document, self.design))
        self.context.start()
        self.addCleanup(self.context.stop)
        matrix_api = SimpleNamespace(create=lambda: Matrix())
        value_api = SimpleNamespace(createByString=lambda expression: expression)
        directions = SimpleNamespace(XAxisJointDirection="x", YAxisJointDirection="y",
                                     ZAxisJointDirection="z")
        geometry = SimpleNamespace(
            createByPoint=lambda point: ("point", point),
            createByCurve=lambda curve, keypoint: ("curve", curve, keypoint),
            createByPlanarFace=lambda face, edge, keypoint: ("planar", face, edge, keypoint),
            createByNonPlanarFace=lambda face, keypoint: ("nonplanar", face, keypoint))
        keypoints = SimpleNamespace(StartKeyPoint="start", MiddleKeyPoint="middle",
                                    EndKeyPoint="end", CenterKeyPoint="center")
        self.matrix_patch = patch.object(assemblies.adsk.core, "Matrix3D", matrix_api,
                                         create=True)
        self.value_patch = patch.object(assemblies.adsk.core, "ValueInput", value_api,
                                        create=True)
        self.direction_patch = patch.object(assemblies.adsk.fusion, "JointDirections",
                                            directions, create=True)
        self.geometry_patch = patch.object(assemblies.adsk.fusion, "JointGeometry",
                                           geometry, create=True)
        self.keypoint_patch = patch.object(assemblies.adsk.fusion, "JointKeyPointTypes",
                                           keypoints, create=True)
        self.matrix_patch.start(); self.value_patch.start(); self.direction_patch.start()
        self.geometry_patch.start()
        self.keypoint_patch.start()
        self.addCleanup(self.matrix_patch.stop); self.addCleanup(self.value_patch.stop)
        self.addCleanup(self.direction_patch.stop)
        self.addCleanup(self.geometry_patch.stop)
        self.addCleanup(self.keypoint_patch.stop)

    def test_joint_geometry_lists_and_resolves_face_edge_vertex_tokens(self):
        def topology(kind, token, geometry=None):
            native = SimpleNamespace(entityToken=token, objectType="adsk::fusion::" + kind,
                                     geometry=geometry)
            native.createForAssemblyContext = lambda occurrence: native
            return native
        face = topology("BRepFace", "face-1",
                        SimpleNamespace(objectType="adsk::core::Plane"))
        edge = topology("BRepEdge", "edge-1")
        vertex = topology("BRepVertex", "vertex-1")
        self.front_component.bRepBodies.append(SimpleNamespace(
            faces=Collection([face]), edges=Collection([edge]), vertices=Collection([vertex])))
        selector = assemblies.selector_for("occurrence", self.front)
        listed = assemblies.joint_geometry_list({"occurrence": selector})["geometry"]
        self.assertEqual([row["kind"] for row in listed],
                         ["origin", "face", "edge", "vertex"])
        self.assertEqual(assemblies._joint_geometry(self.front, "face-1")[1], "face")
        self.assertEqual(assemblies._joint_geometry(self.front, "edge-1", "middle")[1], "edge")
        self.assertEqual(assemblies._joint_geometry(self.front, "vertex-1")[1], "vertex")

    def test_joint_geometry_rejects_token_from_other_occurrence(self):
        foreign = SimpleNamespace(entityToken="foreign", objectType="adsk::fusion::BRepEdge")
        foreign.createForAssemblyContext = lambda occurrence: foreign
        other = component("Other", "other")
        other.bRepBodies.append(SimpleNamespace(faces=Collection(), edges=Collection([foreign]),
                                                vertices=Collection()))
        with self.assertRaisesRegex(ValueError, "selected occurrence"):
            assemblies._joint_geometry(self.front, "foreign")

    def test_occurrence_selectors_are_stable_ambiguous_and_stale(self):
        listed = assemblies.occurrences_list({})
        selector = next(item["selector"] for item in listed["occurrences"]
                        if item["path"].endswith("Front:1"))
        self.assertEqual(selector, assemblies.selector_for("occurrence", self.front))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            assemblies._resolve("occurrence", "Leg")
        self.front.isValid = False
        self.all_occurrences.remove(self.front)
        with self.assertRaisesRegex(ValueError, "stale"):
            assemblies._resolve("occurrence", selector)

    def test_component_create_instance_rename_and_delete_guards(self):
        created = assemblies.components_create({"name": "Arm"})["created"]
        self.assertEqual(created["component"], "Arm")
        component_selector = assemblies.selector_for("component", self.front_component)
        copied = assemblies.occurrences_create({"component": component_selector})["created"]
        self.assertEqual(copied["component"], "Leg")
        result = assemblies.components_rename({"component": component_selector,
                                               "name": "Walking Leg"})
        self.assertEqual(result["affected_occurrences"], 3)
        with self.assertRaisesRegex(ValueError, "multiple occurrences"):
            assemblies.components_delete({"component": component_selector})

    def test_occurrence_ground_transform_and_delete(self):
        selector = assemblies.selector_for("occurrence", self.front)
        result = assemblies.occurrences_ground({"occurrence": selector,
                                                "to_parent": True})
        self.assertEqual(result["relative_to"], "parent")
        self.assertFalse(assemblies.occurrences_unground(
            {"occurrence": selector, "to_parent": True})["grounded"])
        values = [1, 0, 0, 4, 0, 1, 0, 5, 0, 0, 1, 6, 0, 0, 0, 1]
        transformed = assemblies.occurrences_transform({"occurrence": selector,
                                                        "matrix": values})
        self.assertEqual(transformed["matrix"], values)
        self.assertEqual(transformed["native_matrix"][3:12:4], [0.4, 0.5, 0.6])
        self.assertEqual(assemblies.occurrences_delete({"occurrence": selector})["deleted"],
                         "Robot:1+Front:1")

    def test_joint_create_list_inspect_edit_limits_and_delete(self):
        front = assemblies.selector_for("occurrence", self.front)
        rear = assemblies.selector_for("occurrence", self.rear)
        created = assemblies.joints_create({"occurrence_one": front,
                                            "occurrence_two": rear,
                                            "type": "revolute", "axis": "z",
                                            "name": "Hip", "angle_deg": 5})["created"]
        selector = created["selector"]
        self.assertEqual(created["name"], "Hip")
        self.assertEqual(assemblies.joints_inspect({"joint": selector})["joint"]["name"],
                         "Hip")
        limits = assemblies.joints_limits_set({"joint": selector, "axis": "rotation",
                                               "minimum": -30, "maximum": 40, "rest": 5})
        self.assertAlmostEqual(limits["limits"]["minimum"], -30)
        cleared = assemblies.joints_limits_clear({"joint": selector,
                                                  "axis": "rotation",
                                                  "rest": True})
        self.assertIsNone(cleared["limits"]["rest"])
        edited = assemblies.joints_edit({"joint": selector, "locked": True,
                                         "suppressed": True, "name": "Locked Hip"})
        self.assertTrue(edited["current"]["locked"])
        self.assertFalse(assemblies.joints_unlock({"joint": selector})
                         ["current"]["locked"])
        self.assertFalse(assemblies.joints_unsuppress({"joint": selector})
                         ["current"]["suppressed"])
        self.assertEqual(assemblies.joints_delete({"joint": selector})["deleted"],
                         "Locked Hip")

    def test_invalid_matrix_limits_document_and_same_occurrence_are_rejected(self):
        selector = assemblies.selector_for("occurrence", self.front)
        with self.assertRaisesRegex(ValueError, "16 finite"):
            assemblies.occurrences_transform({"occurrence": selector, "matrix": [1]})
        with self.assertRaisesRegex(ValueError, "two different"):
            assemblies.joints_create({"occurrence_one": selector,
                                      "occurrence_two": selector, "type": "rigid"})
        self.root.joints.append(joint())
        joint_selector = assemblies.selector_for("joint", self.root.joints[0])
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            assemblies.joints_limits_set({"joint": joint_selector, "axis": "rotation",
                                          "minimum": 10, "maximum": -10, "rest": None})
        self.context.stop()
        with patch.object(assemblies, "_context", side_effect=ValueError("Active document changed")):
            with self.assertRaisesRegex(ValueError, "Active document changed"):
                assemblies.occurrences_list({"document_id": "wrong"})


if __name__ == "__main__":
    unittest.main()
