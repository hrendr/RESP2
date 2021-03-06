"""
resp2.py includes the basic functions to parameterize a molecule with RESP2 charges.
It allows to create a molecule from a Smiles string and obtain 3D structures.
It uses openeye's omega to generate conformations.
Respyte is used to select ESP grid points
Psi4 is used for the QM calculations.

It can generate RESP2 charges with any given Delta value.

It can also be used to scale RESP1 charges (only neutral molecules).
"""

### Global imports
import sys, os
try:
    from openeye import oechem
    from openeye import oeomega
except ModuleNotFoundError:
    print('Could not load openeye!')
import logging as log

try:
    import resp2.create_mol2_pdb as create_mol2_pdb
except ModuleNotFoundError:
    import create_mol2_pdb
try:
    import pybel
    import openbabel
except ModuleNotFoundError:
    print('Could not import pybel')
import shutil
import glob


### Local functions

### Functions to create ForceBalance targets. Not required for RESP2 charges per se.

def create_fb_input(name='', targets=[], forcefield='smirnoff99Frosst.offxml', port='3333', type='single',
                    mol2_files=[], convergence='tight'):
    """
    Module to create a ForceBalance input file for training or testing purposes.

    :param name: Name of the ForceBalance input file you want to create.
    :param targets: The targets you want to inlcude in the run.
    :param forcefield: Name of the forcefield file.
    :param port: Port to use for work_queue.
    :param type: Single point or an optimization.
    :param mol2_files: List of mol2 files necessary for the calculation. Usually this should include all RESP2 charge files.
    :param convergence: <tight> or <loose> convergence criteria.
    :return: 0 if succesful.
    """
    cwdir = os.getcwd()
    if os.path.isdir('targets') == True:
        os.chdir('targets')
    output = open(name, 'w')
    create_fb_input_header(output=output, port=port, type=type, forcefield=forcefield, mol2_files=mol2_files,
                           convergence=convergence)
    for ele in targets:
        abb = os.path.basename(glob.glob('{}-liquid/*box.pdb'.format(ele))[0])
        abb = abb.split('-')[0]
        output.write('''

$target
name {}-liquid
type Liquid_SMIRNOFF
weight 1.0
liquid_coords    {}-box.pdb
liquid_eq_steps       50000
liquid_prod_steps    5000000
liquid_timestep 1.0
liquid_interval         1.0
save_traj               2
gas_coords          {}.pdb
gas_eq_steps     5000000
gas_prod_steps     20000000
gas_timestep 0.5
$end
'''.format(ele, abb, abb))
    os.chdir(cwdir)


def create_fb_input_header(output=None, port='3333', type='single', forcefield='smirnoff99Frosst.offxml', mol2_files=[],
                           convergence='tight'):
    """
    This function is used to generate the header of the ForceBalance input file ($options section).
    The targets are not included in this function. Is used by create_fb_input.

    :param output: File to write to.
    :param forcefield: Name of the forcefield file.
    :param port: Port to use for work_queue.
    :param type: Single point or an optimization.
    :param mol2_files: List of mol2 files necessary for the calculation. Usually this should include all RESP2 charge files.
    :param convergence: <tight> or <loose> convergence criteria.
    :return:
    """
    output.write('''$options\n
wp_port {}
asynchronous    
penalty_type L2
jobtype {}
forcefield {} '''.format(port, type, forcefield))
    for ele in mol2_files:
        output.write(ele + ' ')
    output.write('\nmaxstep 100\nPENALTY_ADDITIVE 10\n')

    if convergence == 'tight':
        output.write("""
convergence_step 0.001
convergence_objective 30
convergence_gradient 30
criteria 2
""")
    elif convergence == 'loose':
        output.write("""
convergence_step 0.005
convergence_objective 0.05
convergence_gradient 0.001
criteria 1
        """)

    else:
        log.error('Convergence criteria not recognized')
        sys.exit(1)

    output.write('''
eig_lowerbound 0.01
finite_difference_h 0.001
penalty_additive 1.0
trust0 0.15
mintrust 0.05
error_tolerance 1.0
adaptive_factor 0.2
adaptive_damping 1.0
normalize_weights no
print_hessian
constrain_charge false
backup false

priors
   NonbondedForce/Atom/epsilon          : 0.1
   NonbondedForce/Atom/rmin_half        : 1.0
/priors

''')

    return 0


def create_std_target_file(name='', density=None, folder = None, hov=None, dielectric=None):
    """
    This function creates the target data.csv files required by ForceBalance.
    Up to now only 3 properties are supported. Is used by create_target.

    :param name: Name of the molecule. Folders are named accordingly.
    :param density: Density of the molecule in kg / m3
    :param hov: Heats of Vaporization in kJ /kcal / mol
    :param dielectric: Dielectric constant
    :return: 0 if successful
    """
    header_csv = '''# This is documentation for the ForceBalance condensed phase reference data file
,,,,,,
,,,,,,
Global,rho_denom,5,,,,
Global,hvap_denom,0.5,,,,
Global,alpha_denom,1,,,,
Global,kappa_denom,5,,,,
Global,cp_denom,2,,,,
Global,eps0_denom,2,,,,
Global,use_cvib_intra,FALSE,,,,
Global,use_cvib_inter,FALSE,,,,
Global,use_cni,FALSE,,,,
,,,,,,
,,,,,,
'''
    if name == '':
        log.error(
            'You did not specify a name for the target folder. Please use create_std_target_file(name=targetname,density=targetdensity,hov=target_heat,dielectric=target_eps0)')
    f = open(os.path.join(folder,'data.csv'), 'w')
    f.write(header_csv)
    if dielectric is None:
        f.write('T,P,MBAR,Rho,Rho_wt,Hvap,Hvap_wt\n')
        f.write('298.0,1.0 atm, FALSE,{},1,{},1\n'.format(density, hov))
    else:
        f.write('T,P,MBAR,Rho,Rho_wt,Hvap,Hvap_wt,eps0,eps0_wt\n')
        f.write('298.0,1.0 atm, FALSE,{},1,{},1,{},1\n'.format(density, hov, dielectric))

    f.close()
    log.info('''Created target file {}/data.csv
    Density: {} g/l
    Heat of Vaporization: {} kcal/mol
    Dielectric Constant: {}'''.format(folder, density, hov, dielectric))
    return 0


def create_target(smiles='', name='', folder=None, density=None, hov=None, dielectric=None, resname='MOL', nmol=700, tries=2000):
    """
    This functions creates a target including folder structure mol2 files and the data.csv file.
    Charges are done separate.

    :param smiles: SMILES Code of the molecule.
    :param name: Name of the molecule. Folders are named accordingly.
    :param density: Density of the molecule in kg / m3
    :param hov: Heats of Vaporization in kJ /kcal / mol
    :param dielectric: Dielectric constant
    :param folder: Name of the folder for the target. If not specified. {name}-liquid is used.
    :param resname: Abbreviation of the Residue. Specified in the mol2
    :param nmol: Number of molecules in the liquid simulation box.
    :param tries: Number of tries to create the liquid simulation box. For bulky molecules higher values are necessary.
    :return:
    """
    # Check if folder is specified. If not than use standard folder
    if folder is None:
        folder = name + '-liquid'
    try:
        os.mkdir(folder)
    except Exception:
        log.warning('folder {} already exists'.format(folder))
    create_std_target_file(name=name, folder = folder, density=density, hov=hov, dielectric=dielectric)
    create_smifile_from_string(smiles=smiles, filename=os.path.join(folder, resname + '.smi'))
    cwd = os.getcwd()
    os.chdir(folder)
    # try except is necessary for really bulky molecules.
    try:
        create_mol2_pdb.run_create_mol2_pdb(nmol=nmol, density=density - 250, tries=tries,
                                            input= resname + '.smi', resname=resname)
    except Exception:
        try:
            create_mol2_pdb.run_create_mol2_pdb(nmol=nmol, density=density - 350, tries=tries,
                                                input=resname + '.smi', resname=resname)
        except Exception:
            create_mol2_pdb.run_create_mol2_pdb(nmol=nmol, density=density - 400, tries=tries,
                                                input= resname + '.smi', resname=resname)
    os.chdir(cwd)
    return 0


def create_smifile_from_string(smiles='', filename=''):
    """
    Writes a SMILES string to a file.

    :param smiles: SMILES Code of the molecule.
    :param filename: Filename (.smi)
    :return:
    """
    f = open(filename, 'w')
    f.write(smiles)
    f.close()

    return 0


### RESP2 functions. Ordered in sequence of expected use.

def create_conformers(infile=None, outfile=None, resname=None, folder= None, name = None):

    """
    This function takes a mol1 file and runs Openeye's omega to create conformers for the molecules
    The conformers are stored in separated files, adding the number of the conformer at the end of the filename

    :param infile: Path to input file
    :param outfile: Path to output file return
    :param folder: Name of the folder for the target. If not specified. {name}-liquid is used.
    :param resname: Abbreviation of the Residue. Specified in the mol2
    :return: Number of conformers for this molecule
    """
    if folder is None and name is None:
        log.error('Please specify keyword argument folder or name')
        sys.exit(1)
    elif folder is None:
        folder = name +'-liquid'
    infilepath = os.path.join(folder, infile)
    outfilepath = os.path.join(folder, outfile)
    ifs = oechem.oemolistream()
    if not ifs.open(infilepath):
        oechem.OEThrow.Fatal("Unable to open %s for reading" % infilepath)

    ofs = oechem.oemolostream()
    if not ofs.open(outfilepath):
        oechem.OEThrow.Fatal("Unable to open %s for writing" % outfilepath)

    if not oechem.OEIs2DFormat(ofs.GetFormat()):
        oechem.OEThrow.Fatal("Invalid output file format for 2D coordinates!")

    omegaOpts = oeomega.OEOmegaOptions()
    omega = oeomega.OEOmega(omegaOpts)
    omega.SetCommentEnergy(True)
    omega.SetEnumNitrogen(True)
    omega.SetSampleHydrogens(True)
    omega.SetEnergyWindow(9.0)
    omega.SetMaxConfs(5)
    omega.SetRangeIncrement(2)
    omega.SetRMSRange([0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
    filename = '{}-conformers'.format(resname)
    for mol in ifs.GetOEMols():
        ret_code = omega.Build(mol)
        if ret_code == oeomega.OEOmegaReturnCode_Success:
            oechem.OEWriteMolecule(ofs, mol)
            for k, conf in enumerate(mol.GetConfs()):
                ofs1 = oechem.oemolostream()
                if not ofs1.open(os.path.join(folder, filename + '_' + str(k + 1) + '.mol2')):
                    oechem.OEThrow.Fatal("Unable to open %s for writing" % os.path.join(folder, filename + '_' + str(k + 1) + '.mol2'))
                oechem.OEWriteMolecule(ofs1, conf)
                nconf = k + 1
            log.info('Created conformations for {} and saved them to {}'.format(infilepath, outfilepath))

        else:
            oechem.OEThrow.Warning("%s: %s" % (mol.GetTitle(), oeomega.OEGetOmegaError(ret_code)))

    return nconf

def optimize_conformers(opt=True, name='', resname='MOL', number_of_conformers=1, folder = None):
    """
    Optimize all conformers using psi4. This is done in a 3 step approach were the level of theory is
    increased stepwise. The resulting structures ares saved as xyz files. If opt = False the
    optimization is omitted and only the files are copied

    :param opt: True if optimization should be performed.
    :param name: Name of the molecule. Folders are named accordingly.
    :param resname: Abbreviation of the Residue. Specified in the mol2
    :param number_of_conformers: Number of conformers for this molecule
    :param folder: Name of the folder for the target. If not specified. {name}-liquid is used.

    :return:
    """
    header = """memory 12 gb
molecule mol {
noreorient
nocom
    """
    tail_m1 = """
}
set basis 6-31G*
optimize('HF')
set basis cc-pV(D+d)Z
optimize('HF')
set basis cc-pV(D+d)Z
optimize('PW6B95')

"""

    # 2 Convert mol2 files to xyz files and put them in the corresponding folder
    obConversion = openbabel.OBConversion()
    obConversion.SetInAndOutFormats("mol2", "xyz")

    if folder is None:
        folder = name +'-liquid'
    filename = name
    for i in range(1, number_of_conformers + 1):
        inputfile = os.path.join(folder, resname + '-conformers_' + str(i) + '.mol2')
        outputfile = os.path.join(folder, resname + '-conformers_' + str(i) + '.xyz')
        print('DEBUG {}'.format(inputfile))
        mol = openbabel.OBMol()
        obConversion.ReadFile(mol, inputfile)
        obConversion.WriteFile(mol, outputfile)

    if opt == True:

        for i in range(1, number_of_conformers + 1):
            xyz_file = os.path.join(folder, resname + '-conformers_' + str(i) + '.xyz')
            psi4_input_file = os.path.join(folder, resname + '-conformers_' + str(i) + '.in')
            psi4_output_file = os.path.join(folder, resname + '-conformers_' + str(i) + '.out')
            f = open(xyz_file, 'r')
            coordinates = f.readlines()[2:]
            f.close()
            f = open(psi4_input_file, 'w')
            f.write(header)
            f.write('0 1\n')
            for line in coordinates:
                f.write(line)
            f.write(tail_m1)
            f.write("mol.save_xyz_file('{}',True)".format(
                os.path.join(folder, resname + '-confermers_opt_' + str(i) + '.xyz')))

            f.close()

            os.system('psi4 {} -n 4'.format(psi4_input_file))
            if 'beer' in open(psi4_output_file).read():
                log.info('Optimization of {} and conformer {} succesful'.format(filename, i))
            else:
                log.error('Optimization of {} and conformer {} FAILED!!!!!!'.format(filename, i))

    else:
        for i in range(1, number_of_conformers + 1):
            if not os.path.exists(os.path.join(folder, resname + '-confermers_opt_' + str(i) + '.xyz')):
                shutil.copy(os.path.join(folder, resname + '-confermers_' + str(i) + '.xyz'),
                            os.path.join(folder, resname + '-confermers_opt_' + str(i) + '.xyz'))



def create_respyte(type='RESP1', name='', resname='MOL', number_of_conformers=1, opt_folder=None ):
    """
    This function creates the respyte input files to generate the selection of ESP grid points by calling the function
    create_respyte_input_files.
    Additionally, it generates the input for the psi4 QM calculation at the requested level of theory.

    Theory level is determined by the type of the calculation.
    RESP1 uses HF/6-31G*;
    RESP2GAS uses PW6BP94/aug-cc-pV(D+d)Z;
    RESP2LIQUID uses PW6BP94/aug-cc-pV(D+d)Z with PCM (water).

    :param type: Defines what type of QM calculation to perform
    :param name: Name of the compound
    :param resname: 3 letter abbreviation of the compound
    :param number_of_conformers: Number of conformers used for this compound
    :param opt_folder: Name of the folder used for optimize_conformers. If not specified. {name}-liquid is used.

    :return: 0 if successful
    """
    # 1 Create folder structure for respyte
    # Details of the folder structure are explained in the respyte github repository
    if opt_folder is None:
        opt_folder = name +'-liquid'

    foldername = name + '-' + type
    try:
        os.mkdir(foldername)
    except Exception:
        log.warning('folder {} already exists'.format(foldername))
    input_folder = os.path.join(foldername, 'input')
    molecule_folder = os.path.join(input_folder, 'molecules')
    mol_folder = os.path.join(molecule_folder, 'mol1')
    try:
        os.mkdir(input_folder)
    except Exception:
        log.warning('folder {} already exists'.format(input_folder))

    try:
        os.mkdir(molecule_folder)
    except Exception:
        log.warning('folder {} already exists'.format(molecule_folder))

    try:
        os.mkdir(mol_folder)
    except Exception:
        log.warning('folder {} already exists'.format(mol_folder))

    for i in range(1, number_of_conformers + 1):
        conf_folder = os.path.join(mol_folder, 'conf' + str(i))
        try:
            os.mkdir(conf_folder)
        except Exception:
            log.warning('folder {} already exists'.format(conf_folder))

    log.info('Create folder structure for {} with {} conformers'.format(name, number_of_conformers))

    # 2 Create Respyte and RESP Optimizer input files
    create_respyte_input_files(type=type, name=name, resname=resname, number_of_conformers=number_of_conformers)

    # 3 Copy optimized files
    # Looks for the optimized files
    for i in range(1, number_of_conformers + 1):
        shutil.copyfile(os.path.join(opt_folder, resname + '-confermers_opt_' + str(i) + '.xyz'),
                        os.path.join('{}-{}/input/molecules/mol1/conf{}/mol1_conf{}.xyz'.format(name, type, i, i)))

    # 4 Run RESPyte and PSI4
    calculate_respyte(type=type, name=name, resname=resname, number_of_conformers=number_of_conformers)

    return 0


def calculate_respyte(type='RESP1', name='', resname='MOL', number_of_conformers=1):
    """
    This function performs the psi4 calculation and the respyte calculation and checks if the
    calculation was successful.

    :param type: defines what type of QM calculation to perform
    :param name: name of the compound
    :param resname: 3 letter abbreviation of the compound
    :param number_of_conformers: Number of conformers used for this compound
    :return: 0 if successful
    """
    foldername = name + '-' + type
    cwdr = os.getcwd()
    os.chdir(foldername)
    mol_folder = 'input/molecules/mol1/'
    for i in range(1, number_of_conformers + 1):
        conf_folder = os.path.join(mol_folder, 'conf' + str(i))
        tmp_folder = os.path.join(conf_folder, 'tmp/')
        try:
            shutil.rmtree(tmp_folder)
        except Exception:
            pass
    os.system('python ~/programs/respyte/respyte/esp_generator.py')
    for i in range(1, number_of_conformers + 1):
        conf_folder = os.path.join(mol_folder, 'conf' + str(i))
        psi4_output_file = os.path.join(conf_folder, 'tmp/output.dat')
        if 'beer' in open(psi4_output_file).read():
            log.info('ESP calculation for {} and conformer {} successful'.format(name, i))
        else:
            log.error('ESP calculation for {} and conformer {} FAILED!!!!!!'.format(name, i))

    os.system('python ~/programs/respyte/respyte/resp_optimizer.py')
    os.chdir(cwdr)
    return 0


def create_respyte_input_files(type='RESP1', name='', resname='MOL', number_of_conformers=1):
    """
    This function performs the psi4 calculation and the respyte calculations and checks if the
    calculation was successful.

    :param type: Defines what type of QM calculation to perform
    :param name: Name of the compound
    :param number_of_conformers: Number of conformers used for this compound
    :return: 0 if successful
    """
    if type == 'RESP1':
        method = 'HF'
        basis = '6-31G*'
        pcm = 'N'
    elif type == 'RESP2GAS':

        method = 'PW6B95'
        basis = 'aug-cc-pV(D+d)Z'
        pcm = 'N'
    elif type == 'RESP2LIQUID':
        method = 'PW6B95'
        basis = 'aug-cc-pV(D+d)Z'
        pcm = 'Y\n    solvent   : water'
    else:
        log.error('Charge type not recognized')
        sys.exit()

    # input.yml
    input_file = open('{}-{}/input/input.yml'.format(name, type), 'w')
    input_file.write("""molecules:
    mol1 : {}
charges :
    mol1 : 0
cheminformatics : openeye

grid_setting :
    forcegen  : Y
    type      : msk # msk(default)/ extendedmsk/ fcc/ newfcc/ vdwfactors/ vdwconstants
    radii     : bondi # bondi(default)/ modbondi
    method    : {}
    basis     : {}
    pcm       : {}
    space     : 0.4
    innner    : 1.6
    outer     : 2.1

    
    
    """.format(number_of_conformers, method, basis, pcm))

    input_file.close()
    # respyte.yml
    respyte_file = open('{}-{}/input/respyte.yml'.format(name, type), 'w')

    respyte_file.write("""
    molecules :
        mol1 : {}
    charges :
        mol1 : 0

    cheminformatics : openeye

    boundary_select:
        radii    : bondi
        inner    : 1.3
        outer    : 2.1

    restraint :
        penalty : 2-stg-fit
        matrices :
            - esp
        a1      : 0.0005
        a2      : 0.001
        b       : 0.1

        """.format(number_of_conformers))
    respyte_file.close()

    return 0




def create_charge_file(name='', resname='MOL', delta=0.0, type='RESP1'):
    """
    This function creates a MOL2 file with either RESP1 scaled charges or RESP2 charges
    with a certain mixing parameter.

    :param name: Name of the compound.
    :param resname: 3 letter abbreviation of the compound.
    :param delta: Mixing parameter given as absolute value ( not percent)
    :param type: RESP1 or RESP2 type charges
    :return:
    """
    if type == 'RESP1':
        mol2_resp1 = name + '-RESP1/resp_output/mol1_conf1.mol2'
        f = open(mol2_resp1)
        output_file = os.path.join(name + '-liquid', resname + '_R1_' + str(int(delta * 100)) + '.mol2')
        output = open(output_file, 'w')

        # Read in RESP1 charges
        v = 0
        resp1charges = []
        lines = f.readlines()
        for line in lines:
            if '@<TRIPOS>ATOM' in line:
                v = 1
            elif '@<TRIPOS>BOND' in line:
                v = 2
            elif v == 1:
                entry = line.split()
                resp1charges.append(float(entry[8]))
        f.close()
        charges = []
        for i in range(len(resp1charges)):
            charges.append(resp1charges[i] * delta)


    elif type == 'RESP2':
        mol2_gas = name + '-RESP2GAS/resp_output/mol1_conf1.mol2'
        mol2_liquid = name + '-RESP2LIQUID/resp_output/mol1_conf1.mol2'
        output_file = os.path.join(name + '-liquid', resname + '_R2_' + str(int(delta * 100)) + '.mol2')
        f = open(mol2_gas, 'r')
        f2 = open(mol2_liquid, 'r')
        output = open(output_file, 'w')

        # Read in gas phase charges (gpc)
        v = 0
        gpc = []
        lines = f.readlines()
        for line in lines:
            if '@<TRIPOS>ATOM' in line:
                v = 1
            elif '@<TRIPOS>BOND' in line:
                v = 2
            elif v == 1:
                entry = line.split()
                gpc.append(float(entry[8]))
        f.close()

        # Read in implicit solvent charges (isc)
        v = 0
        isc = []
        lines2 = f2.readlines()
        for line in lines2:
            if '@<TRIPOS>ATOM' in line:
                v = 1
            elif '@<TRIPOS>BOND' in line:
                v = 2
            elif v == 1:
                entry = line.split()
                isc.append(float(entry[8]))
        f2.close()

        charges = []
        for i in range(len(isc)):
            charges.append(gpc[i] * (1.0 - delta) + isc[i] * delta)

    else:
        log.error('The type you defined is not recognized. Up to now only RESP1 and RESP2 are valid options')
        sys.exit(1)

    log.info('Created charges {} type charges with a delta value of {}'.format(type, delta))
    v = 0
    num = 0
    if lines[1].startswith('***') or lines[1].startswith('resp_gas') or lines[1].startswith('mol1_conf1'):
        lines[1] = '{}\n'.format(resname)
    for i, line in enumerate(lines):
        if '@<TRIPOS>ATOM' in line:
            v = 1
            output.write(line)
        elif '@<TRIPOS>BOND' in line:
            v = 2
            output.write(line)
        elif v == 1:
            entry = line.split()
            output.write(
                "{:>7} {:<3}{:>15}{:>10}{:>10} {:<3}{:>8}{:>5}{:>14.4f} \n".format(
                    entry[0], entry[1], entry[2], entry[3],
                    entry[4], entry[5], entry[6], resname,
                    charges[num]))
            num += 1
        else:
            output.write(line)
    f.close()
    output.close()

    return 0




def create_RESP2(smi = None,folder='', opt=True, name='', resname='MOL', delta=1.0, density=None, hov=None, dielectric=None):
    """
    Creates a mol2 file with RESP2 charges from a mol2 file (resname.mol2) or from a smiles string.

    :param folder: folder to write the output files.
    :param opt: True when generated conformers should be locally optimized.
    :param name: Name of the compound
    :param density: Density of the molecule in kg / m3
    :param hov: Heats of Vaporization in kJ /kcal / mol
    :param dielectric: Dielectric constant
    :param folder: Name of the folder for the target. If not specified. {name}-liquid is used.
    :param resname: Abbreviation of the Residue. Specified in the mol2
    :param delta: Fraction (in percent) of liquid charges. default=1.0
    :return:
    """

    if folder is None:
        folder = name + '-liquid'
    if not os.path.isdir(folder):
        os.mkdir(folder)
    infile = '{}.mol2'.format(resname)
    infile_path = os.path.join(folder, '{}.mol2'.format(resname))
    if not os.path.isfile(infile_path):
        log.warning('Could not find file: {}'.format(infile_path))
        if smi is not None:
            log.warning('Create molecule from SMILES string')
            outputfile = os.path.join(folder, resname + '.mol2')
            mymol = pybel.readstring("smi", smi)
            mymol.addh()
            mymol.make3D()
            mymol.write(format='mol2',filename=outputfile, overwrite=True)
    outfile = '{}-conformers.mol2'.format(resname)
    number_of_conformers = create_conformers(infile=infile, outfile=outfile,resname = resname,folder = folder)
    optimize_conformers(name=name, resname=resname, opt=opt, number_of_conformers=number_of_conformers,folder = folder)
    create_respyte(name=name, resname=resname, type='RESP2LIQUID', number_of_conformers=number_of_conformers)
    create_respyte(name=name, resname=resname, type='RESP2GAS', number_of_conformers=number_of_conformers)
    create_respyte(name=name, resname=resname, type='RESP1', number_of_conformers=number_of_conformers)
    create_charge_file(name=name, resname=resname, type='RESP1', delta=delta)
    return 0


if __name__ == "__main__":
    log.getLogger().setLevel(log.INFO)
    #create_RESP2(smi = 'CO', opt=True, name='methanol2', resname='MET', folder='methanol-liquid')\
    #print(os.getcwd())
    number_of_conformers = create_conformers(infile='MTH.mol2', resname = 'MTH', outfile='MTH-conformers.mol2', folder = '/home/mschauperl/programs/RESP2/example/methanol2-liquid')

    #optimize_conformers(name='methanol2', resname='MTH', opt=True, number_of_conformers=1)

