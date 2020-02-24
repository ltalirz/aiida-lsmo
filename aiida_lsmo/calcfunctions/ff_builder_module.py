"""ff_builder calcfunction."""
import tempfile
import shutil
import os
import ruamel.yaml as yaml

from aiida.orm import SinglefileData
from aiida.engine import calcfunction


def load_yaml():
    """ Load the ff_data.yaml as a dict."""
    thisdir = os.path.dirname(os.path.abspath(__file__))
    yamlfullpath = os.path.join(thisdir, 'ff_data.yaml')
    with open(yamlfullpath, 'r') as stream:
        ff_data = yaml.safe_load(stream)
    return ff_data


def string_to_singlefiledata(string, filename):
    """Convert a string to a SinglefileData."""
    tempdir = tempfile.mkdtemp(prefix="aiida_ff-builder_")
    filepath = os.path.join(tempdir, filename)
    with open(filepath, "w") as fobj:
        fobj.write(string)
    singlefiledata = SinglefileData(file=filepath)
    shutil.rmtree(tempdir)
    return singlefiledata


def render_ff_mixing_def(ff_data, params):
    """Render the force_field_mixing_rules.def file."""
    output = []
    output.append("# general rule for shifted vs truncated (file generated by aiida-raspa)")
    output.append(['truncated', 'shifted'][params['shifted']])
    output.append("# general rule tail corrections")
    output.append(['no', 'yes'][params['tail_corrections']])
    output.append("# number of defined interactions")

    force_field_lines = []
    ff_mix_found = False  #If becomes True, needs to handle the mixing differently
    # TODO: this needs to be sorted for python versions where dictionaries are not sorted! #pylint: disable=fixme
    # If separate_interactions==True, prints only "zero-potential" interactions for the molecules
    for atom_type, ff_pot in ff_data['framework'][params['ff_framework']]['atom_types'].items():
        force_field_lines.append(" ".join([str(x) for x in [atom_type] + ff_pot]))
    for molecule, ff_name in params['ff_molecules'].items():
        for atom_type, val in ff_data[molecule][ff_name]['atom_types'].items():
            if 'force_field_mix' in val:
                ff_mix_found = True
                ff_pot = val['force_field_mix']
            else:
                ff_pot = val['force_field']
            # In case of "separate_interactions" write the ff only if zero-potential particle
            if not params['separate_interactions'] or ff_pot[0].lower() == "zero-potential":
                force_field_lines.append(" ".join([str(x) for x in [atom_type] + ff_pot]))

    output.append(len(force_field_lines))
    output.append("# atom_type, interaction, parameters")
    output.extend(force_field_lines)
    output.append("# general mixing rule for Lennard-Jones")
    output.append(params['mixing_rule'])
    string = "\n".join([str(x) for x in output]) + "\n"
    return string_to_singlefiledata(string, "force_field_mixing_rules.def"), ff_mix_found


def mix_molecule_ff(ff_list, mixing_rule):
    """Mix molecule-molecule interactions in case of separate_interactions: return mixed ff_list"""
    from math import sqrt
    ff_mix = []
    for i, ffi in enumerate(ff_list):
        for ffj in ff_list[i:]:
            if ffi[1].lower() == ffj[1].lower() == 'lennard-jones':
                eps_mix = sqrt(ffi[2] * ffj[2])
                if mixing_rule == 'lorentz-berthelot':
                    sig_mix = 0.5 * (ffi[3] + ffj[3])
                elif mixing_rule == 'jorgensen':
                    sig_mix = sqrt(ffi[3] * ffj[3])
                ff_mix.append("{} {} lennard-jones {:.5f} {:.5f}".format(ffi[0], ffj[0], eps_mix, sig_mix))
            elif "zero-potential" in [ffi[1], ffj[1]]:
                ff_mix.append("{} {} zero-potential".format(ffi[0], ffj[0]))
            elif ffi[1].lower() == ffj[1].lower() == 'feynman-hibbs-lennard-jones':
                eps_mix = sqrt(ffi[2] * ffj[2])
                if mixing_rule == 'lorentz-berthelot':
                    sig_mix = 0.5 * (ffi[3] + ffj[3])
                elif mixing_rule == 'jorgensen':
                    sig_mix = sqrt(ffi[3] * ffj[3])
                reduced_mass = ffi[4]  # assuming that ffi==ffj, for the moment
                ff_mix.append("{} {} feynman-hibbs-lennard-jones {:.5f} {:.5f} {:.5f}".format(
                    ffi[0], ffj[0], eps_mix, sig_mix, reduced_mass))
            else:
                raise NotImplementedError('FFBuilder is not able to mix different/unknown potentials.')
    return ff_mix


def render_ff_def(ff_data, params, ff_mix_found):
    """Render the force_field.def file."""
    output = []
    output.append("# rules to overwrite (file generated by aiida-raspa)")
    output.append(0)
    output.append("# number of defined interactions")
    if params['separate_interactions'] or ff_mix_found:
        ff_list = []
        for molecule, ff_name in params["ff_molecules"].items():
            for atom_type, val in ff_data[molecule][ff_name]['atom_types'].items():
                ff_pot = val['force_field']
                if ff_pot == 'dummy_separate':  # Exclude molatoms-moldummy interactions
                    ff_list.append([atom_type] + ['zero-potential'])
                else:
                    ff_list.append([atom_type] + ff_pot)
        mixing_rule = params['mixing_rule'].lower()
        ff_mix = mix_molecule_ff(ff_list, mixing_rule)
        output.append(len(ff_mix))
        output.append("# type1 type2 interaction")
        output.extend(ff_mix)
    else:
        output.append(0)
    output.append("# mixing rules to overwrite")
    output.append(0)
    string = "\n".join([str(x) for x in output]) + "\n"
    return string_to_singlefiledata(string, "force_field.def")


def render_pseudo_atoms_def(ff_data, params):
    """Render the pseudo_atoms.def file."""
    output = []
    output.append("# number of pseudo atoms")

    pseudo_atoms_lines = []
    for molecule, ff_name in params['ff_molecules'].items():
        for atom_type, val in ff_data[molecule][ff_name]['atom_types'].items():
            type_settings = val['pseudo_atom']
            pseudo_atoms_lines.append(" ".join([str(x) for x in [atom_type] + type_settings]))

    output.append(len(pseudo_atoms_lines))
    output.append("#type print as chem oxidation mass charge polarization B-factor radii connectivity " +
                  "anisotropic anisotropic-type tinker-type")
    output.extend(pseudo_atoms_lines)
    string = "\n".join([str(x) for x in output]) + "\n"
    return string_to_singlefiledata(string, "pseudo_atoms.def")


def render_molecule_def(ff_data, params, molecule_name):
    """Render the molecule.def file containing the thermophysical data, geometry and intramolecular force field."""
    ff_name = params["ff_molecules"][molecule_name]
    ff_dict = ff_data[molecule_name][ff_name]
    natoms = len(ff_dict["atomic_positions"])
    output = []
    output.append("# critical constants: Temperature [T], Pressure [Pa], and Acentric factor [-] " +
                  "(file generated by aiida-raspa)")
    output.append(ff_data[molecule_name]["critical_constants"]["tc"])
    output.append(ff_data[molecule_name]["critical_constants"]["pc"])
    output.append(ff_data[molecule_name]["critical_constants"]["af"])
    output.append("# Number Of atoms")
    output.append(natoms)
    # Now this section can only deal with rigid molecules. TODO: make it more general
    output.append("# Number of groups")
    output.append(1)
    output.append("# Group-1: rigid/flexible")
    output.append("rigid")
    output.append("# Group-1: Number of atoms")
    output.append(natoms)
    output.append("# Atomic positions")
    for i, line in enumerate(ff_dict["atomic_positions"]):
        output.append(" ".join([str(x) for x in [i] + line]))
    output.append("# Chiral centers Bond  BondDipoles Bend  UrayBradley InvBend  Torsion Imp. Torsion Bond/Bond " +
                  "Stretch/Bend Bend/Bend Stretch/Torsion Bend/Torsion IntraVDW IntraCoulomb")
    output.append(" ".join([str(x) for x in [0] + [natoms - 1] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]]))
    if natoms > 1:
        output.append("# Bond stretch: atom n1-n2, type, parameters")
        for i in range(1, natoms):
            output.append("0 {} RIGID_BOND".format(i))
    output.append("# Number of config moves")
    output.append(0)
    string = "\n".join([str(x) for x in output]) + "\n"
    return string_to_singlefiledata(string, molecule_name + ".def")


@calcfunction
def ff_builder(params):
    """AiiDA calcfunction to assemble force filed parameters into SinglefileData for Raspa."""

    # PARAMS_EXAMPLE = Dict( dict = {
    #   'ff_framework': 'UFF',              # See force fields available in ff_data.yaml as framework.keys()
    #   'ff_molecules': {                   # See molecules available in ff_data.yaml as ff_data.keys()
    #       'CO2': 'TraPPE',                    # See force fields available in ff_data.yaml as {molecule}.keys()
    #       'N2': 'TraPPE',
    #   },
    #   'shifted': True,                    # If True shift despersion interactions, if False simply truncate them.
    #   'tail_corrections': False,          # If True apply tail corrections based on homogeneous-liquid assumption
    #   'mixing_rule': 'Lorentz-Berthelot', # Options: 'Lorentz-Berthelot' or 'Jorgensen'
    #   'separate_interactions': True       # If True use framework's force field for framework-molecule interactions
    # })

    ff_data = load_yaml()
    out_dict = {}
    out_dict['ff_mixing_def'], ff_mix_found = render_ff_mixing_def(ff_data, params)
    out_dict['ff_def'] = render_ff_def(ff_data, params, ff_mix_found)
    out_dict['pseudo_atoms_def'] = render_pseudo_atoms_def(ff_data, params)
    for molecule_name in params['ff_molecules']:
        out_dict['molecule_{}_def'.format(molecule_name)] = render_molecule_def(ff_data, params, molecule_name)

    return out_dict
