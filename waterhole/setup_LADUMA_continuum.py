#!/usr/bin/env python
# ian.heywood@physics.ox.ac.uk


import glob
import json
import os.path as o
import sys
sys.path.append(o.abspath(o.join(o.dirname(sys.modules[__name__].__file__), "..")))


from oxkat import generate_jobs as gen
from oxkat import config as cfg


def main():


    laduma_model = 'LADUMA_L_skymodel/LADUMA_2GC_x10-16ch'

    model_list = glob.glob(laduma_model+'*.fits')
    if len(model_list) == 0:
        print('Sky model not found.')
        print('Please put '+laduma_model+' in this location')
        sys.exit()


    USE_SINGULARITY = cfg.USE_SINGULARITY
    
    gen.preamble()
    print(gen.col()+'Selfcal and peeling setup using existing sky model cube')
    gen.print_spacer()

    # ------------------------------------------------------------------------------
    #
    # Setup paths, required containers, infrastructure
    #
    # ------------------------------------------------------------------------------


    OXKAT = cfg.OXKAT
    DATA = cfg.DATA
    GAINTABLES = cfg.GAINTABLES
    IMAGES = cfg.IMAGES
    SCRIPTS = cfg.SCRIPTS

    gen.setup_dir(GAINTABLES)
    gen.setup_dir(IMAGES)
    gen.setup_dir(cfg.LOGS)
    gen.setup_dir(cfg.SCRIPTS)


    INFRASTRUCTURE, CONTAINER_PATH = gen.set_infrastructure(sys.argv)
    if CONTAINER_PATH is not None:
        CONTAINER_RUNNER='singularity exec '
    else:
        CONTAINER_RUNNER=''


    CUBICAL_CONTAINER = gen.get_container(CONTAINER_PATH,cfg.CUBICAL_PATTERN,USE_SINGULARITY)
    OWLCAT_CONTAINER = gen.get_container(CONTAINER_PATH,cfg.OWLCAT_PATTERN,USE_SINGULARITY)
    TRICOLOUR_CONTAINER = gen.get_container(CONTAINER_PATH,cfg.TRICOLOUR_PATTERN,USE_SINGULARITY)
    WSCLEAN_CONTAINER = gen.get_container(CONTAINER_PATH,cfg.WSCLEAN_PATTERN,USE_SINGULARITY)


    # Get target information from project json file

    with open('project_info.json') as f:
        project_info = json.load(f)

    target_ids = project_info['target_ids'] 
    target_names = project_info['target_names']
    target_ms = project_info['target_ms']


    # ------------------------------------------------------------------------------
    #
    # 2GC recipe definition
    #
    # ------------------------------------------------------------------------------


    target_steps = []
    codes = []
    ii = 1
    stamp = gen.timenow()


    # Loop over targets

    for tt in range(0,len(target_ids)):

        targetname = target_names[tt]
        myms = target_ms[tt]
        CAL_3GC_PEEL_REGION = cfg.CAL_3GC_PEEL_REGION

        if CAL_3GC_PEEL_REGION == '':
            region = glob.glob('*'+targetname+'*peel*.reg')
            if len(region) == 0:
                CAL_3GC_PEEL_REGION = ''
            else:
                CAL_3GC_PEEL_REGION = region[0]

        if not o.isfile(CAL_3GC_PEEL_REGION):
            gen.print_spacer()
            print(gen.col('Target')+targetname)
            print(gen.col('Measurement Set')+myms)
            print(gen.col()+'Please provide a DS9 region file definining the source you wish to peel.')
            print(gen.col()+'This can be specified in the config or by placing a file of the form:')
            print(gen.col()+'       *'+targetname+'*peel*.reg')
            print(gen.col()+'in this folder. Skipping.')
            skip = True

        if not o.isdir(myms):

            gen.print_spacer()
            print(gen.col('Target')+targetname)
            print(gen.col('MS')+'not found, skipping')

        else:

            steps = []        
            filename_targetname = gen.scrub_target_name(targetname)


            code = gen.get_target_code(targetname)
            if code in codes:
                code += '_'+str(ii)
                ii += 1
            codes.append(code)

            # Generate output dir for CubiCal
            k_outdir = GAINTABLES+'/delaycal_'+filename_targetname+'_'+stamp+'.cc/'
            k_outname = 'delaycal_'+filename_targetname+'_'+stamp
            k_saveto = 'delaycal_'+filename_targetname+'.parmdb'
            outdir = GAINTABLES+'/peeling_'+filename_targetname+'_'+stamp+'.cc/'
            outname = 'peeling_'+filename_targetname+'_'+stamp

            prepeel_img_prefix = laduma_model
            dir1_img_prefix = prepeel_img_prefix+'-'+CAL_3GC_PEEL_REGION.split('/')[-1].split('.')[0]
          
            gen.print_spacer()
            print(gen.col('Target')+targetname)
            print(gen.col('Measurement Set')+myms)
            print(gen.col('Code')+code)


            # Target-specific kill file
            kill_file = SCRIPTS+'/kill_laduma_jobs_'+filename_targetname+'.sh'


            step = {}
            step['step'] = 0
            step['comment'] = 'Predict model visibilities from model cube'
            step['dependency'] = None
            step['id'] = 'WSDPR'+code
            step['slurm_config'] = cfg.SLURM_WSCLEAN
            step['pbs_config'] = cfg.PBS_WSCLEAN
            absmem = gen.absmem_helper(step,INFRASTRUCTURE,cfg.WSC_ABSMEM)
            syscall = CONTAINER_RUNNER+WSCLEAN_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += gen.generate_syscall_predict(msname = myms,imgbase = laduma_model,chanout = 16,absmem = absmem)
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 1
            step['comment'] = 'Run Tricolour on '+myms+' (MODEL_DATA - DATA)'
            step['dependency'] = 0
            step['id'] = 'TRIC0'+code
            step['slurm_config'] = cfg.SLURM_TRICOLOUR
            step['pbs_config'] = cfg.PBS_TRICOLOUR
            syscall = CONTAINER_RUNNER+TRICOLOUR_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += gen.generate_syscall_tricolour(myms = myms,
                        config = DATA+'/tricolour/target_flagging_1_narrow.yaml',
                        datacol = 'DATA',
                        subtractcol = 'MODEL_DATA'
                        fields = '0',
                        strategy = 'polarisation')
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 2
            step['comment'] = 'Run CubiCal with f-slope solver'
            step['dependency'] = 1
            step['id'] = 'CL2GC'+code
            step['slurm_config'] = cfg.SLURM_WSCLEAN
            step['pbs_config'] = cfg.PBS_WSCLEAN
            syscall = CONTAINER_RUNNER+CUBICAL_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += gen.generate_syscall_cubical(parset = cfg.CAL_2GC_DELAYCAL_PARSET,
                    myms = myms,
                    extra_args = '--out-dir '+k_outdir+' --out-name '+k_outname+' --k-save-to '+k_saveto)
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 3
            step['comment'] = 'Extract problem source defined by region into a separate set of model images'
            step['dependency'] = 2
            step['id'] = 'IMSPL'+code
            syscall = CONTAINER_RUNNER+CUBICAL_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += 'python '+OXKAT+'/3GC_split_model_images.py '
            syscall += '--region '+CAL_3GC_PEEL_REGION+' '
            syscall += '--prefix '+laduma_model+' '
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 4
            step['comment'] = 'Predict problem source visibilities into MODEL_DATA column of '+myms
            step['dependency'] = 3
            step['id'] = 'WS1PR'+code
            step['slurm_config'] = cfg.SLURM_WSCLEAN
            step['pbs_config'] = cfg.PBS_WSCLEAN
            absmem = gen.absmem_helper(step,INFRASTRUCTURE,cfg.WSC_ABSMEM)
            syscall = CONTAINER_RUNNER+WSCLEAN_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += gen.generate_syscall_predict(msname = myms,imgbase = dir1_img_prefix,chanout = 16, absmem = absmem)
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 5
            step['comment'] = 'Add '+cfg.CAL_3GC_PEEL_DIR1COLNAME+' column to '+myms
            step['dependency'] = 4
            step['id'] = 'ADDIR'+code
            syscall = CONTAINER_RUNNER+CUBICAL_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += 'python '+TOOLS+'/add_MS_column.py '
            syscall += '--colname '+cfg.CAL_3GC_PEEL_DIR1COLNAME+' '
            syscall += myms
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 6
            step['comment'] = 'Copy MODEL_DATA to '+cfg.CAL_3GC_PEEL_DIR1COLNAME
            step['dependency'] = 5
            step['id'] = 'CPMOD'+code
            syscall = CONTAINER_RUNNER+CUBICAL_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += 'python '+TOOLS+'/copy_MS_column.py '
            syscall += '--fromcol MODEL_DATA '
            syscall += '--tocol '+cfg.CAL_3GC_PEEL_DIR1COLNAME+' '
            syscall += myms
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 7
            step['comment'] = 'Predict full sky model visibilities into MODEL_DATA column of '+myms
            step['dependency'] = 6
            step['id'] = 'WS2PR'+code
            step['slurm_config'] = cfg.SLURM_WSCLEAN
            step['pbs_config'] = cfg.PBS_WSCLEAN
            absmem = gen.absmem_helper(step,INFRASTRUCTURE,cfg.WSC_ABSMEM)
            syscall = CONTAINER_RUNNER+WSCLEAN_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += gen.generate_syscall_predict(msname = myms,imgbase = prepeel_img_prefix,chanout = 16, absmem = absmem)
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 8
            step['comment'] = 'Copy CORRECTED_DATA to DATA'
            step['dependency'] = 7
            step['id'] = 'CPCOR'+code
            syscall = CONTAINER_RUNNER+CUBICAL_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += 'python '+TOOLS+'/copy_MS_column.py '
            syscall += '--fromcol CORRECTED_DATA '
            syscall += '--tocol DATA '
            syscall += myms
            step['syscall'] = syscall
            steps.append(step)


            step = {}
            step['step'] = 9
            step['comment'] = 'Run CubiCal to solve for G (full model) and dE (problem source), peel out problem source'
            step['dependency'] = 8
            step['id'] = 'CL3GC'+code
            step['slurm_config'] = cfg.SLURM_WSCLEAN
            step['pbs_config'] = cfg.PBS_WSCLEAN
            syscall = CONTAINER_RUNNER+CUBICAL_CONTAINER+' ' if USE_SINGULARITY else ''
            syscall += gen.generate_syscall_cubical(parset=cfg.CAL_3GC_PEEL_PARSET,myms=myms,extra_args='--out-name '+outname+' --out-dir '+outdir)
            step['syscall'] = syscall
            steps.append(step)


            target_steps.append((steps,kill_file,targetname))




    # ------------------------------------------------------------------------------
    #
    # Write the run file and kill file based on the recipe
    #
    # ------------------------------------------------------------------------------


    submit_file = 'submit_2GC_jobs.sh'

    f = open(submit_file,'w')
    f.write('#!/usr/bin/env bash\n')
    f.write('export SINGULARITY_BINDPATH='+cfg.BINDPATH+'\n')

    for content in target_steps:  
        steps = content[0]
        kill_file = content[1]
        targetname = content[2]
        id_list = []

        f.write('\n#---------------------------------------\n')
        f.write('# '+targetname)
        f.write('\n#---------------------------------------\n')

        for step in steps:

            step_id = step['id']
            id_list.append(step_id)
            if step['dependency'] is not None:
                dependency = steps[step['dependency']]['id']
            else:
                dependency = None
            syscall = step['syscall']
            if 'slurm_config' in step.keys():
                slurm_config = step['slurm_config']
            else:
                slurm_config = cfg.SLURM_DEFAULTS
            if 'pbs_config' in step.keys():
                pbs_config = step['pbs_config']
            else:
                pbs_config = cfg.PBS_DEFAULTS
            comment = step['comment']

            run_command = gen.job_handler(syscall = syscall,
                            jobname = step_id,
                            infrastructure = INFRASTRUCTURE,
                            dependency = dependency,
                            slurm_config = slurm_config,
                            pbs_config = pbs_config)


            f.write('\n# '+comment+'\n')
            f.write(run_command)

        if INFRASTRUCTURE != 'node':
            f.write('\n# Generate kill script for '+targetname+'\n')
        if INFRASTRUCTURE == 'idia' or INFRASTRUCTURE == 'hippo':
            kill = 'echo "scancel "$'+'" "$'.join(id_list)+' > '+kill_file+'\n'
            f.write(kill)
        elif INFRASTRUCTURE == 'chpc':
            kill = 'echo "qdel "$'+'" "$'.join(id_list)+' > '+kill_file+'\n'
            f.write(kill)

        
    f.close()

    gen.make_executable(submit_file)

    gen.print_spacer()
    print(gen.col('Run file')+submit_file)
    gen.print_spacer()

    # ------------------------------------------------------------------------------



if __name__ == "__main__":


    main()