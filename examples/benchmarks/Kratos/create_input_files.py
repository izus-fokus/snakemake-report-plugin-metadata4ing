import json
import sys

import gmsh
import meshio
import re
from pint import UnitRegistry
import numpy as np

ureg = UnitRegistry()


class PlateWithHoleSolution:
    def __init__(self, E, nu, radius, L, load):
        self.radius = radius
        self.L = L
        self.load = load
        self.E = E
        self.nu = nu

    def polar(self, x):
        r = np.hypot(x[0], x[1])
        theta = np.atan2(x[1], x[0])
        return r, theta
    
    def hypot_str(self, x, y):
        return f"sqrt({x}*{x} + {y}*{y})"
    def polar_str(self, x, y):
        r = self.hypot_str(x, y)
        theta = f"atan2({y}, {x})"
        return r, theta
    
    def displacement_str(self, x, y):
        r, theta = self.polar_str(x,y)
        a = str(self.radius)

        T = str(self.load)
        Ta_8mu = f"({T} * {a} / (4 * {self.E} / (1.0 + 1.0 * {self.nu})))"
        k = f"((3.0 - {self.nu}) / (1.0 + {self.nu}))"

        ct = f"cos({theta})"
        c3t = f"cos(3 * {theta})"
        st = f"sin({theta})"
        s3t = f"sin(3 * {theta})"

        fac = f"2 * pow({a} / {r}, 3)"

        ux = f"{Ta_8mu} * ({r} / {a} * ({k} + 1.0) * {ct} + 2.0 * {a} / {r} * ((1.0 + {k}) * {ct} + {c3t}) - {fac} * {c3t})"

        uy = f"{Ta_8mu} * (({r} / {a}) * ({k} - 3.0) * {st} + 2.0 * {a} / {r} * ((1.0 - {k}) * {st} + {s3t}) - {fac} * {s3t})"

        return ux, uy

    def stress(self, x):
        r, theta = self.polar(x)
        T = self.load
        a = self.radius
        cos2t = np.cos(2 * theta)
        cos4t = np.cos(4 * theta)
        sin2t = np.sin(2 * theta)
        sin4t = np.sin(4 * theta)

        fac1 = (a * a) / (r * r)
        fac2 = 1.5 * fac1 * fac1

        sxx = T - T * fac1 * (1.5 * cos2t + cos4t) + T * fac2 * cos4t
        syy = -T * fac1 * (0.5 * cos2t - cos4t) - T * fac2 * cos4t
        sxy = -T * fac1 * (0.5 * sin2t + sin4t) + T * fac2 * sin4t

        return sxx, sxy, sxy, syy

# Parameters
name = sys.argv[1]
experiment_file = sys.argv[2]
parameter_file = sys.argv[3]

# Load parameters
with open(parameter_file) as f:
    parameters = json.load(f)
print(parameters)

length = (
    ureg.Quantity(parameters["length"]["value"], parameters["length"]["unit"])
    .to_base_units()
    .magnitude
)
radius = (
    ureg.Quantity(parameters["radius"]["value"], parameters["radius"]["unit"])
    .to_base_units()
    .magnitude
)
youngs_modulus = (
    ureg.Quantity(parameters["young-modulus"]["value"], parameters["young-modulus"]["unit"])
    .to_base_units()
    .magnitude
)
poisson_ratio = (
    ureg.Quantity(parameters["poisson-ratio"]["value"], parameters["poisson-ratio"]["unit"])
    .to_base_units()
    .magnitude
)
# create mesh
"""
4---------3
|         |
5_        |
  \       |
   1______2

"""


gmsh.initialize()
gmsh.model.add(name)

element_size = (
    ureg.Quantity(
        parameters["element-size"]["value"], parameters["element-size"]["unit"]
    )
    .to_base_units()
    .magnitude
)
gmsh.option.setNumber("Mesh.CharacteristicLengthMin", element_size)
gmsh.option.setNumber("Mesh.CharacteristicLengthMax", element_size)
gmsh.option.setNumber("Mesh.CharacteristicLengthFactor", 1.0)
gmsh.option.setNumber("Mesh.ElementOrder", parameters["element-order"])

z = 0.0
lc = 1.0

x0 = 0.0
x1 = x0 + radius
x2 = x0 + length
y0 = 0.0
y1 = y0 + radius
y2 = y0 + length

center = gmsh.model.geo.addPoint(x0, y0, z, lc)
p1 = gmsh.model.geo.addPoint(x1, y0, z, lc)
p2 = gmsh.model.geo.addPoint(x2, y0, z, lc)
p3 = gmsh.model.geo.addPoint(x2, y2, z, lc)
p4 = gmsh.model.geo.addPoint(x0, y2, z, lc)
p5 = gmsh.model.geo.addPoint(x0, y1, z, lc)

l1 = gmsh.model.geo.addLine(p1, p2)
l2 = gmsh.model.geo.addLine(p2, p3)
l3 = gmsh.model.geo.addLine(p3, p4)
l4 = gmsh.model.geo.addLine(p4, p5)
l5 = gmsh.model.geo.addCircleArc(p5, center, p1)

curve = gmsh.model.geo.addCurveLoop([l1, l2, l3, l4, l5])
plane = gmsh.model.geo.addPlaneSurface([curve])
gmsh.model.geo.synchronize()
gmsh.model.geo.removeAllDuplicates()
gmsh.model.addPhysicalGroup(2, [plane], 1, name="surface")
gmsh.model.addPhysicalGroup(1, [l4], 1, name="boundary_left")
gmsh.model.addPhysicalGroup(1, [l1], 2, name="boundary_bottom")
gmsh.model.addPhysicalGroup(1, [l2], 3, name="boundary_right")
gmsh.model.addPhysicalGroup(1, [l3], 4, name="boundary_top")

groups = {"surface": (2,1), "boundary_left": (1,1), "boundary_bottom": (1,2), "boundary_right": (1,3), "boundary_top": (1,4)}

gmsh.model.mesh.generate(2)
gmsh.write("data/mesh_" + name + ".msh")
gmsh.finalize()

mesh = meshio.read("data/mesh_" + name + ".msh")




meshio.write("data/mesh_" + name + ".mdpa", mesh)


with open("data/mesh_" + name + ".mdpa", "r") as f:
    # replace all occurences of Triangle with SmallStrainElement
    text = f.read()

    text = text.replace("Triangle2D3", "SmallDisplacementElement2D3N")
    text = text.replace("Triangle2D6", "SmallDisplacementElement2D6N")

    text = re.sub(r"Begin\s+Elements\s+Line2D[\n\s\d]*End\s+Elements", "", text)
    
    mesh_tags = np.array(re.findall(r"Begin\s+NodalData\s+gmsh:dim_tags[\s\n]*(.*)End\s+NodalData\s+gmsh:dim_tags",text, flags=re.DOTALL)[0].replace("np.int64", "").replace("(","").replace(")","").split(), dtype=np.int32).reshape(-1, 3)
    
    text = re.sub(r"Begin\s+NodalData\s+gmsh:dim_tags[\s\n]*(.*)End\s+NodalData\s+gmsh:dim_tags","",text, flags=re.DOTALL)


append = "\nBegin SubModelPart boundary_left\n"
append += "    Begin SubModelPartNodes\n        "
nodes = np.argwhere(np.isclose(mesh.points[:,0], x0)).flatten()+1
append += "\n        ".join(map(str, nodes)) + "\n"
append += "    End SubModelPartNodes\n"
append += "End SubModelPart\n"

text += append

append = "\nBegin SubModelPart boundary_bottom\n"
append += "    Begin SubModelPartNodes\n        "
nodes = np.argwhere(np.isclose(mesh.points[:,1], y0)).flatten() +1
append += "\n        ".join(map(str, nodes)) + "\n"
append += "    End SubModelPartNodes\n"
append += "End SubModelPart\n"

text += append

append = "\nBegin SubModelPart boundary_right\n"
append += "    Begin SubModelPartNodes\n        "
nodes = np.argwhere(np.isclose(mesh.points[:,0], x2)).flatten() + 1 
append += "\n        ".join(map(str, nodes)) + "\n"
append += "    End SubModelPartNodes\n"
append += "End SubModelPart\n"

text += append

append = "\nBegin SubModelPart boundary_top\n"
append += "    Begin SubModelPartNodes\n        "
nodes = np.argwhere(np.isclose(mesh.points[:,1], y2)).flatten() + 1 
append += "\n        ".join(map(str, nodes)) + "\n"
append += "    End SubModelPartNodes\n"
append += "End SubModelPart\n"

text += append
with open("data/mesh_" + name + ".mdpa", "w") as f:
    f.write(text)

load = ureg.Quantity(parameters["load"]["value"], parameters["load"]["unit"]).to_base_units().magnitude
analytcial_solution = PlateWithHoleSolution(youngs_modulus, poisson_ratio, radius, length, load)

bc = analytcial_solution.displacement_str("X", "Y")


material_parameters = {
    "properties" : [{
        "model_part_name" : "Structure",
        "properties_id"   : 1,
        "Material"        : {
            "constitutive_law" : {
                 "name" : "LinearElasticPlaneStress2DLaw"
            },
            "Variables"        : {
                "YOUNG_MODULUS" : youngs_modulus,
                "POISSON_RATIO" : poisson_ratio
            },
            "Tables"           : {}
        }
    }]
}

project_parameters = {
    "problem_data"             : {
        "problem_name"    : "PlateWithHole",
        "parallel_type"   : "OpenMP",
        "start_time"      : 0.0,
        "end_time"        : 1.0,
        "echo_level"      : 0
    },
    "solver_settings"          : {
        "solver_type"                        : "Static",
        "model_part_name"                    : "Structure",
        "echo_level"                         : 1,
        "domain_size"                        : 2,
        "analysis_type"                      : "linear",
        "model_import_settings"              : {
            "input_type"     : "mdpa",
            "input_filename" : "data/mesh_" + name
        },
        "material_import_settings"           : {
            "materials_filename" : "data/StructuralMaterials_"+name+".json"
        },
        "time_stepping"                      : {
            "time_step" : 1.0
        }
    },
    "processes" : {
        "constraints_process_list" : [{
            "python_module" : "assign_vector_variable_process",
            "kratos_module" : "KratosMultiphysics",
            "Parameters"    : {
                "model_part_name" : "Structure.boundary_left",
                "variable_name"   : "DISPLACEMENT",
                "constrained"     : [True, False, True],
                "value"           : [0.0, 0.0, 0.0],
                "interval"        : [0.0,"End"]
            }
        },{
            "python_module" : "assign_vector_variable_process",
            "kratos_module" : "KratosMultiphysics",
            "Parameters"    : {
                "model_part_name" : "Structure.boundary_bottom",
                "variable_name"   : "DISPLACEMENT",
                "constrained"     : [False, True, True],
                "value"           : [0.0, 0.0, 0.0],
                "interval"        : [0.0,"End"]
            }
        },{
            "python_module" : "assign_vector_variable_process",
            "kratos_module" : "KratosMultiphysics",
            "Parameters"    : {
                "model_part_name" : "Structure.boundary_right",
                "variable_name"   : "DISPLACEMENT",
                "constrained"     : [True, True, True],
                "value"           : [bc[0], bc[1], 0.0],
                "interval"        : [0.0,"End"]
            }
        },{
            "python_module" : "assign_vector_variable_process",
            "kratos_module" : "KratosMultiphysics",
            "Parameters"    : {
                "model_part_name" : "Structure.boundary_top",
                "variable_name"   : "DISPLACEMENT",
                "constrained"     : [True, True, True],
                "value"           : [bc[0], bc[1], 0.0],
                "interval"        : [0.0,"End"]
            }
        }],
        "loads_process_list"       : [],
        "list_other_processes"     : []
    },
    
    "output_processes" : {
        "vtk_output" : [{
            "python_module" : "vtk_output_process",
            "kratos_module" : "KratosMultiphysics",
            "Parameters"    : {
                "model_part_name"                    : "Structure",
                "file_format"                        : "binary",
                "output_path"                        : "data/output_"+name,
                "output_sub_model_parts"             : False,
                "output_interval"                    : 1,
                "nodal_solution_step_data_variables" : ["DISPLACEMENT"],
                "gauss_point_variables_extrapolated_to_nodes" : ["CAUCHY_STRESS_VECTOR", "VON_MISES_STRESS"],
            }
        }]
    }
}

with open("data/StructuralMaterials_"+name+".json", "w") as f:
    json.dump(material_parameters, f, indent=4)

with open("data/input_"+name+".json", "w") as f:
    json.dump(project_parameters, f, indent=4)