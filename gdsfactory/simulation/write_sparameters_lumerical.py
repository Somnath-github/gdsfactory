"""Write Sparameters with Lumerical FDTD."""
import dataclasses
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

import gdsfactory as gf
from gdsfactory.component import Component
from gdsfactory.config import __version__, logger
from gdsfactory.simulation.get_sparameters_path import get_sparameters_path
from gdsfactory.tech import (
    LAYER_STACK,
    SIMULATION_SETTINGS,
    LayerStack,
    SimulationSettings,
)

run_false_warning = """
you need to pass `run=True` flag to run the simulation
To debug, you can create a lumerical FDTD session and pass it to the simulator

```
import lumapi
s = lumapi.FDTD()

import gdsfactory as gf
import gdsfactory.simulation as sim

c = gf.components.straight() # or whatever you want to simulate
sim.write_sparameters_lumerical(component=c, run=False, session=s)
```
"""

MATERIAL_NAME_TO_LUMERICAL = {
    "si": "Si (Silicon) - Palik",
    "sio2": "SiO2 (Glass) - Palik",
    "sin": "Si3N4 (Silicon Nitride) - Phillip",
}


def write_sparameters_lumerical(
    component: Component,
    session: Optional[object] = None,
    run: bool = True,
    overwrite: bool = False,
    dirpath: Path = gf.CONFIG["sparameters"],
    layer_stack: LayerStack = LAYER_STACK,
    simulation_settings: SimulationSettings = SIMULATION_SETTINGS,
    **settings,
) -> pd.DataFrame:
    """Returns and writes component Sparameters using Lumerical FDTD.

    if simulation exists it returns the Sparameters directly unless overwrite=True
    which forces a re-run of the simulation

    Lumerical units are in meters while gdsfactory units are in um

    Args:
        component: Component to simulate
        session: you can pass a session=lumapi.FDTD() for debugging
        run: True runs Lumerical, False only draws simulation
        overwrite: run even if simulation results already exists
        dirpath: where to store the simulations
        layer_stack: layer_stack
        simulation_settings: dataclass with all simulation_settings
        settings: overwrite any simulation setting
          background_material: for the background
          port_width: port width (um)
          port_height: port height (um)
          port_extension: port extension (um)
          mesh_accuracy: 2 (1: coarse, 2: fine, 3: superfine)
          zmargin: for the FDTD region 1 (um)
          ymargin: for the FDTD region 2 (um)
          xmargin: for the FDTD region
          pml_margin: for all the FDTD region
          wavelength_start: 1.2 (um)
          wavelength_stop: 1.6 (um)
          wavelength_points: 500

    Return:
        Sparameters pandas DataFrame (wavelength_nm, S11m, S11a, S12a ...)
        suffix `a` for angle and `m` for module

    """
    sim_settings = dataclasses.asdict(simulation_settings)

    layer_to_thickness = layer_stack.get_layer_to_thickness()
    layer_to_zmin = layer_stack.get_layer_to_zmin()
    layer_to_material = layer_stack.get_layer_to_material()

    if not component.ports:
        raise ValueError(f"`{component.name}` does not have any ports")

    if hasattr(component, "simulation_settings"):
        sim_settings.update(component.simulation_settings)
    for setting in settings.keys():
        if setting not in sim_settings:
            raise ValueError(
                f"`{setting}` is not a valid setting ({list(sim_settings.keys())})"
            )

    sim_settings.update(**settings)
    ss = SimulationSettings(**sim_settings)

    ports = component.ports
    component = component.copy()
    component.remove_layers(component.layers - set(layer_to_thickness.keys()))
    component._bb_valid = False

    c = gf.components.extension.extend_ports(
        component=component, length=ss.port_extension
    )
    c.flatten()
    c.name = "top"
    c.show()
    gdspath = c.write_gds()

    filepath = get_sparameters_path(
        component=component,
        dirpath=dirpath,
        layer_to_material=layer_to_material,
        layer_to_thickness=layer_to_thickness,
        **settings,
    )
    filepath_csv = filepath.with_suffix(".csv")
    filepath_sim_settings = filepath.with_suffix(".yml")
    filepath_fsp = filepath.with_suffix(".fsp")

    if run and filepath_csv.exists() and not overwrite:
        logger.info(f"Reading Sparameters from {filepath_csv}")
        return pd.read_csv(filepath_csv)

    if not run and session is None:
        print(run_false_warning)

    logger.info(f"Writing Sparameters to {filepath_csv}")
    x_min = (component.xmin - ss.xmargin - ss.pml_margin) * 1e-6
    x_max = (component.xmax + ss.xmargin + ss.pml_margin) * 1e-6
    y_min = (component.ymin - ss.ymargin - ss.pml_margin) * 1e-6
    y_max = (component.ymax + ss.ymargin + ss.pml_margin) * 1e-6

    port_orientations = [p.orientation for p in ports.values()]

    # bend
    if 90 in port_orientations:
        y_max -= ss.ymargin * 1e-6

    if 270 in port_orientations:
        y_min += ss.ymargin * 1e-6

    z = 0
    z_span = (2 * ss.zmargin + max(layer_to_thickness.values())) * 1e-6

    layers = component.get_layers()
    sim_settings.update(dict(layer_stack=layer_stack.to_dict()))

    sim_settings = dict(
        simulation_settings=sim_settings,
        component=component.get_settings(),
        version=__version__,
    )

    # from pprint import pprint
    # filepath_sim_settings.write_text(yaml.dump(sim_settings))
    # print(filepath_sim_settings)
    # pprint(sim_settings)
    # return

    try:
        import lumapi
    except ModuleNotFoundError as e:
        print(
            "Cannot import lumapi (Python Lumerical API). "
            "You can add set the PYTHONPATH variable or add it with `sys.path.append()`"
        )
        raise e
    except OSError as e:
        raise e

    start = time.time()
    s = session or lumapi.FDTD(hide=False)
    s.newproject()
    s.selectall()
    s.deleteall()
    s.addrect(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        z=z,
        z_span=z_span,
        index=1.5,
        name="clad",
    )

    material = ss.background_material
    if material not in MATERIAL_NAME_TO_LUMERICAL:
        raise ValueError(f"{material} not in {list(MATERIAL_NAME_TO_LUMERICAL.keys())}")
    material = MATERIAL_NAME_TO_LUMERICAL[material]
    s.setnamed("clad", "material", material)

    s.addfdtd(
        dimension="3D",
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        z=z,
        z_span=z_span,
        mesh_accuracy=ss.mesh_accuracy,
        use_early_shutoff=True,
    )

    for layer, thickness in layer_to_thickness.items():
        if layer not in layers:
            logger.info(f"{layer} not in {layers}")
            continue

        if layer not in layer_to_material:
            raise ValueError(f"{layer} not in {layer_to_material.keys()}")

        material_name = layer_to_material[layer]
        if material_name not in MATERIAL_NAME_TO_LUMERICAL:
            raise ValueError(
                f"{material_name} not in {list(MATERIAL_NAME_TO_LUMERICAL.keys())}"
            )
        material_name_lumerical = MATERIAL_NAME_TO_LUMERICAL[material_name]

        if layer not in layer_to_zmin:
            raise ValueError(f"{layer} not in {list(layer_to_zmin.keys())}")

        zmin = layer_to_zmin[layer] * 1e-6
        zmax = zmin + thickness * 1e-6
        z = (zmax + zmin) / 2

        s.gdsimport(str(gdspath), "top", f"{layer[0]}:{layer[1]}")
        layername = f"GDS_LAYER_{layer[0]}:{layer[1]}"
        s.setnamed(layername, "z", z)
        s.setnamed(layername, "z span", thickness * 1e-6)
        s.setnamed(layername, "material", material_name_lumerical)
        logger.info(f"adding {layer}, thickness = {thickness} um, zmin = {zmin} um ")

    for i, port in enumerate(ports.values()):
        s.addport()
        p = f"FDTD::ports::port {i+1}"
        s.setnamed(p, "x", port.x * 1e-6)
        s.setnamed(p, "y", port.y * 1e-6)
        s.setnamed(p, "z span", ss.port_height * 1e-6)

        deg = int(port.orientation)
        # if port.orientation not in [0, 90, 180, 270]:
        #     raise ValueError(f"{port.orientation} needs to be [0, 90, 180, 270]")

        if -45 <= deg <= 45:
            direction = "Backward"
            injection_axis = "x-axis"
            dxp = 0
            dyp = ss.port_width
        elif 45 < deg < 90 + 45:
            direction = "Backward"
            injection_axis = "y-axis"
            dxp = ss.port_width
            dyp = 0
        elif 90 + 45 < deg < 180 + 45:
            direction = "Forward"
            injection_axis = "x-axis"
            dxp = 0
            dyp = ss.port_width
        elif 180 + 45 < deg < 180 + 45 + 90:
            direction = "Forward"
            injection_axis = "y-axis"
            dxp = ss.port_width
            dyp = 0

        else:
            raise ValueError(
                f"port {port.name} with orientation {port.orientation} is not a valid"
                " number "
            )

        s.setnamed(p, "direction", direction)
        s.setnamed(p, "injection axis", injection_axis)
        s.setnamed(p, "y span", dyp * 1e-6)
        s.setnamed(p, "x span", dxp * 1e-6)
        # s.setnamed(p, "theta", deg)
        s.setnamed(p, "name", port.name)

    s.setglobalsource("wavelength start", ss.wavelength_start * 1e-6)
    s.setglobalsource("wavelength stop", ss.wavelength_stop * 1e-6)
    s.setnamed("FDTD::ports", "monitor frequency points", ss.wavelength_points)

    if run:
        s.save(str(filepath_fsp))
        s.deletesweep("s-parameter sweep")

        s.addsweep(3)
        s.setsweep("s-parameter sweep", "Excite all ports", 0)
        s.setsweep("S sweep", "auto symmetry", True)
        s.runsweep("s-parameter sweep")

        # collect results
        # S_matrix = s.getsweepresult("s-parameter sweep", "S matrix")
        sp = s.getsweepresult("s-parameter sweep", "S parameters")

        # export S-parameter data to file named s_params.dat to be loaded in
        # INTERCONNECT
        s.exportsweep("s-parameter sweep", str(filepath))
        print(f"wrote sparameters to {filepath}")

        keys = [key for key in sp.keys() if key.startswith("S")]
        ra = {f"{key}a": list(np.unwrap(np.angle(sp[key].flatten()))) for key in keys}
        rm = {f"{key}m": list(np.abs(sp[key].flatten())) for key in keys}

        wavelength_nm = sp["lambda"].flatten() * 1e9

        results = {"wavelength_nm": wavelength_nm}
        results.update(ra)
        results.update(rm)
        df = pd.DataFrame(results, index=wavelength_nm)

        end = time.time()
        df.to_csv(filepath_csv, index=False)
        sim_settings.update(compute_time_seconds=end - start)
        return df
    filepath_sim_settings.write_text(yaml.dump(sim_settings))


def _sample_write_coupler_ring():
    """Write Sparameters when changing a component setting."""
    return [
        write_sparameters_lumerical(
            gf.components.coupler_ring(
                width=width, length_x=length_x, radius=radius, gap=gap
            )
        )
        for width in [0.5]
        for length_x in [0.1, 1, 2, 3, 4]
        for gap in [0.15, 0.2]
        for radius in [5, 10]
    ]


def _sample_bend_circular():
    """Write Sparameters for a circular bend with different radius."""
    return [
        write_sparameters_lumerical(gf.components.bend_circular(radius=radius))
        for radius in [2, 5, 10]
    ]


def _sample_bend_euler():
    """Write Sparameters for a euler bend with different radius."""
    return [
        write_sparameters_lumerical(gf.components.bend_euler(radius=radius))
        for radius in [2, 5, 10]
    ]


def _sample_convergence_mesh():
    return [
        write_sparameters_lumerical(
            component=gf.components.straight(length=2),
            mesh_accuracy=mesh_accuracy,
        )
        for mesh_accuracy in [1, 2, 3]
    ]


def _sample_convergence_wavelength():
    return [
        write_sparameters_lumerical(
            component=gf.components.straight(length=2),
            wavelength_start=wavelength_start,
        )
        for wavelength_start in [1.2, 1.4]
    ]


if __name__ == "__main__":
    component = gf.components.straight(length=2)
    r = write_sparameters_lumerical(component=component, mesh_accuracy=1, run=True)
    # c = gf.components.coupler_ring(length_x=3)
    # c = gf.components.mmi1x2()
    # r = write_sparameters_lumerical(component=component, layer_to_thickness={(1, 0): 200}, run=False)
    # print(r)
    # print(r.keys())
    # print(component.ports.keys())
