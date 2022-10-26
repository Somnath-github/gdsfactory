from pathlib import Path
from typing import Optional, Union, cast

import gdstk
import numpy as np
from omegaconf import OmegaConf

from gdsfactory.cell import cell
from gdsfactory.component import Component
from gdsfactory.component_reference import CellArray
from gdsfactory.config import CONFIG, logger
from gdsfactory.name import get_name_short


@cell
def import_gds(
    gdspath: Union[str, Path],
    cellname: Optional[str] = None,
    gdsdir: Optional[Union[str, Path]] = None,
    read_metadata: bool = True,
    hashed_name: bool = True,
    **kwargs,
) -> Component:
    """Returns a Componenent from a GDS file.

    based on phidl/geometry.py

    if any cell names are found on the component CACHE we append a $ with a
    number to the name

    Args:
        gdspath: path of GDS file.
        cellname: cell of the name to import (None) imports top cell.
        gdsdir: optional GDS directory.
        read_metadata: loads metadata if it exists.
        hashed_name: appends a hash to a shortened component name.
        kwargs: extra to add to component.info (polarization, wavelength ...).

    """
    gdspath = Path(gdsdir) / Path(gdspath) if gdsdir else Path(gdspath)
    if not gdspath.exists():
        raise FileNotFoundError(f"No file {gdspath!r} found")

    metadata_filepath = gdspath.with_suffix(".yml")

    gdsii_lib = gdstk.read_gds(str(gdspath))
    top_level_cells = gdsii_lib.top_level()
    cellnames = [c.name for c in top_level_cells]

    if not cellnames:
        raise ValueError(f"no cells found in {str(gdspath)!r}")

    if cellname is not None:
        if cellname not in gdsii_lib.cells:
            raise ValueError(
                f"cell {cellname!r} is not in file {gdspath} with cells {cellnames}"
            )
        topcell = gdsii_lib.cells[cellname]
    elif len(top_level_cells) == 1:
        topcell = top_level_cells[0]
    elif len(top_level_cells) > 1:
        raise ValueError(
            f"import_gds() There are multiple top-level cells in {gdspath!r}, "
            f"you must specify `cellname` to select of one of them among {cellnames}"
        )

    D_list = []
    cell_to_device = {}
    for c in gdsii_lib.cells:
        D = Component(name=c.name)
        D._cell = c

        D.name = c.name
        for label in c.labels:
            rotation = label.rotation
            if rotation is None:
                rotation = 0
            label_ref = D.add_label(
                text=label.text,
                position=np.asfarray(label.position),
                magnification=label.magnification,
                rotation=rotation * 180 / np.pi,
                layer=(label.layer, label.texttype),
            )
            label_ref.anchor = label.anchor

        if hashed_name:
            D.name = get_name_short(D.name)

        cell_to_device[c] = D
        D_list += [D]

    for D in D_list:
        # First convert each reference so it points to the right Component
        converted_references = []
        for e in D.references:
            ref_device = cell_to_device[e.ref_cell]
            dr = CellArray(component=ref_device)
            dr.owner = D
            dr._reference = e
            converted_references.append(dr)

    component = cell_to_device[topcell]
    cast(Component, component)

    if read_metadata and metadata_filepath.exists():
        logger.info(f"Read YAML metadata from {metadata_filepath}")
        metadata = OmegaConf.load(metadata_filepath)

        if "settings" in metadata:
            component.settings = OmegaConf.to_container(metadata.settings)

        if "ports" in metadata:
            for port_name, port in metadata.ports.items():
                if port_name not in component.ports:
                    component.add_port(
                        name=port_name,
                        center=port.center,
                        width=port.width,
                        orientation=port.orientation,
                        layer=tuple(port.layer),
                        port_type=port.port_type,
                    )

    component.info.update(**kwargs)
    component.imported_gds = True
    return component


if __name__ == "__main__":

    gdspath = CONFIG["gdsdir"] / "mzi2x2.gds"
    # c = import_gds(gdspath, flatten=True, name="TOP")
    # c.settings = {}
    # print(clean_value_name(c))
    c = import_gds(gdspath, flatten=False, polarization="te")
    # c = import_gds("/home/jmatres/gdsfactory/gdsfactory/gdsdiff/gds_diff_git.py")
    c.show(show_ports=True)
