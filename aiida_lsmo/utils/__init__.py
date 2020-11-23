# -*- coding: utf-8 -*-
"""aiida-lsmo utils"""
from .multiply_unitcell import check_resize_unit_cell
from .other_utilities import aiida_dict_merge, dict_merge, aiida_cif_merge, aiida_structure_merge
from .other_utilities import get_structure_from_cif, get_cif_from_structure, get_valid_dict, validate_dict

HARTREE2EV = 27.211399
HARTREE2KJMOL = 2625.500
