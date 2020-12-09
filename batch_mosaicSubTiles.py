import os, string, sys, argparse, glob, subprocess
from collections import namedtuple
matlab_scripts = '/mnt/pgc/data/scratch/claire/repos/setsm_postprocessing4'
quads = ['1_1','1_2','2_1','2_2']

Task = namedtuple('Task', 't st')

project_choices = [
    'arcticdem',
    'rema',
    'earthdem',
]

tileDefFile_utm_north = 'PGC_UTM_Mosaic_Tiles_North.mat'
tileDefFile_utm_south = 'PGC_UTM_Mosaic_Tiles_South.mat'
tileDefFile_utm_options = "{} or {}".format(tileDefFile_utm_north, tileDefFile_utm_south)
project_tileDefFile_dict = {
    'arcticdem': 'PGC_Imagery_Mosaic_Tiles_Arctic.mat',
    'rema': 'PGC_Imagery_Mosaic_Tiles_Antarctic.mat',
    'earthdem': tileDefFile_utm_options,
}
project_version_dict = {
    'arcticdem': 'ArcticDEM|4.1',
    'rema': 'REMA|2.0',
    'earthdem': 'EarthDEM|1.0',
}

def main():

    ## args
    parser = argparse.ArgumentParser()
    parser.add_argument("srcdir", help="source root dir (level above tile name dir)")
    parser.add_argument("tiles", help="list of tiles, comma delimited")
    parser.add_argument("res", choices=['2','10'], help="resolution (2 or 10)")

    parser.add_argument("--lib-path", default=matlab_scripts,
                        help="path to referenced Matlab functions (default={}".format(matlab_scripts))
    parser.add_argument("--project", default=None, choices=project_choices,
                        help="sets the default value of project-specific arguments")
    parser.add_argument("--tile-def", default=None,
                        help="mosaic tile definition mat file (default is {})".format(
                            ', '.join(["{} if --project={}".format(val, dom) for dom, val in project_tileDefFile_dict.items()])
                        ))
    parser.add_argument("--version", default=None,
                        help="mosaic version (default is {})".format(
                            ', '.join(["{} if --project={}".format(val, dom) for dom, val in
                                       project_version_dict.items()])
                        ))
    parser.add_argument('--quads', action='store_true', default=False,
            help="build into quad subtiles")

    parser.add_argument('--bypass-bst-finfile-req', action='store_true', default=False,
            help="do not require BST finfiles exist before mosaicking tiles")
    parser.add_argument('--relax-bst-finfile-req', action='store_true', default=False,
            help="allow mosaicking tiles with no BST finfile if 10,000-th subtile exists")
    parser.add_argument('--require-mst-finfiles', action='store_true', default=False,
            help="let existence of MST finfiles dictate reruns")

    parser.add_argument("--pbs", action='store_true', default=False,
            help="submit tasks to PBS")
    parser.add_argument("--qsubscript",
            help="qsub script to use in PBS submission (default is qsub_mosaicSubTiles.sh in script root folder)")
    parser.add_argument("--dryrun", action='store_true', default=False,
            help='print actions without executing')

    args = parser.parse_args()

    tiles = args.tiles.split(',')
    srcdir = os.path.abspath(args.srcdir)
    scriptdir = os.path.abspath(os.path.dirname(sys.argv[0]))

    matlab_script = 'mosaicSubTiles'

    ## Set default arguments by project setting
    if args.project is None and True in [arg is None for arg in [args.tile_def]]:
        parser.error("--project arg must be provided if one of the following arguments is not provided: {}".format(
            ' '.join(["--tile-def"])
        ))
    if args.tile_def is None:
        args.tile_def = project_tileDefFile_dict[args.project]

    ## Verify path arguments
    if not os.path.isdir(srcdir):
        parser.error("srcdir does not exist: {}".format(srcdir))
    if not os.path.isdir(args.lib_path):
        parser.error("--lib-path does not exist: {}".format(args.lib_path))
    if args.project == 'earthdem':
        pass
    else:
        tile_def_abs = os.path.join(scriptdir, args.tile_def)
        if not os.path.isfile(tile_def_abs):
            parser.error("--tile-def file does not exit: {}".format(tile_def_abs))

    ## Verify qsubscript
    if args.qsubscript is None:
        qsubpath = os.path.join(scriptdir,'qsub_mosaicSubTiles.sh')
    else:
        qsubpath = os.path.abspath(args.qsubscript)
    if not os.path.isfile(qsubpath):
        parser.error("qsub script path is not valid: %s" %qsubpath)

    if args.bypass_bst_finfile_req and args.relax_bst_finfile_req:
        parser.error("--bypass-bst-finfile-req and --relax-bst-finfile-req arguments are mutually exclusive")

    tasks = []
    error_messages = []
    check_subtile_dir = []

    i=0
    if len(tiles) > 0:

        for tile in tiles:
            if args.quads:
                for quad in quads:
                    tasks.append(Task(tile, quad))
            else:
                tasks.append(Task(tile, 'null'))

    print("{} tasks found".format(len(tasks)))

    if len(tasks) > 0:
        for task in tasks:

            tile = task.t

            tile_def = args.tile_def

            if tile_def == tileDefFile_utm_options:
                assert args.project == 'earthdem'

                utm_tilename_parts = tile.split('_')
                utm_tilename_prefix = utm_tilename_parts[0]
                if not utm_tilename_prefix.startswith('utm'):
                    parser.error("Expected only UTM tile names (e.g. 'utm10n_01_01'), but got '{}'".format(tile))

                if tile_def == tileDefFile_utm_options:
                    if utm_tilename_prefix.endswith('n'):
                        tile_def = tileDefFile_utm_north
                    elif utm_tilename_prefix.endswith('s'):
                        tile_def = tileDefFile_utm_south
                    else:
                        parser.error("UTM tile name prefix does not end with 'n' or 's' (e.g. 'utm10n'): {}".format(tile))

                tile_def_abs = os.path.join(scriptdir, tile_def)
                if not os.path.isfile(tile_def_abs):
                    parser.error("tile def file does not exit: {}".format(tile_def_abs))

            if task.st == 'null':
                dstfn = "{}_{}m.mat".format(task.t,args.res)
            else:
                dstfn = "{}_{}_{}m.mat".format(task.t,task.st,args.res)
            dstfp = os.path.join(srcdir, task.t, dstfn)
            finfile = os.path.join(srcdir, task.t, dstfn.replace('.mat','.fin'))
            subtile_dir = os.path.join(srcdir,task.t,'subtiles')

            if not os.path.isdir(subtile_dir):
                message = 'ERROR! Subtile directory ({}) does not exist, skipping {}'.format(subtile_dir, dstfn)
                print(message)
                error_messages.append(message)
                continue

            run_tile = True
            removing_existing_output = False

            mst_finfile = finfile
            bst_final_subtile_fp = os.path.join(subtile_dir, '{}_10000_{}m.mat'.format(task.t, args.res))
            bst_finfile = bst_final_subtile_fp.replace('.mat', '.fin')
            bst_finfile_2m = os.path.join(subtile_dir, '{}_10000_2m.fin'.format(task.t))

            if (not args.bypass_bst_finfile_req) and (not any([os.path.isfile(f) for f in [bst_finfile, bst_finfile_2m]])):
                if args.relax_bst_finfile_req and os.path.isfile(bst_final_subtile_fp):
                    print('WARNING: BST finfile ({}) does not exist for tile {}, but 10,000-th subtile exists so will run'.format(bst_finfile, dstfn))
                else:
                    print('BST finfile ({}) does not exist, skipping {}'.format(bst_finfile, dstfn))
                    if os.path.isfile(bst_final_subtile_fp):
                        print('  (but 10,000-th subtile exists; can provide --relax-bst-finfile-req argument to mosaic this tile anyways)')
                    run_tile = False
            else:
                for bst_finfile_temp in list({bst_finfile, bst_finfile_2m, bst_final_subtile_fp}):
                    if os.path.isfile(bst_finfile_temp):
                        if os.path.isfile(mst_finfile) and (os.path.getmtime(bst_finfile_temp) > os.path.getmtime(mst_finfile)):
                            print('BST finfile ({}) is newer than MST finfile ({})'.format(bst_finfile_temp, mst_finfile))
                            removing_existing_output = True
                        elif os.path.isfile(dstfp) and (os.path.getmtime(bst_finfile_temp) > os.path.getmtime(dstfp)):
                            print('BST finfile ({}) is newer than MST output ({})'.format(bst_finfile_temp, dstfp))
                            removing_existing_output = True

            if removing_existing_output:
                dstfps_old_pattern = dstfp.replace('.mat', '*')
                dstfps_old = glob.glob(dstfps_old_pattern)
                if dstfps_old:
                    print('{}Removing old MST results matching {}'.format('(dryrun) ' if args.dryrun else '', dstfps_old_pattern))
                    if not args.dryrun:
                        for dstfp_old in dstfps_old:
                            os.remove(dstfp_old)

            if os.path.isfile(dstfp) and not args.require_mst_finfiles:
                print('Output exists, skipping {}'.format(dstfn))
                run_tile = False
            elif os.path.isfile(finfile):
                if not os.path.isfile(dstfp):
                    message = "WARNING! MST finfile exists ({}) but expected output does not exist ({}) for tile {}".format(
                        finfile, dstfp, dstfn
                    )
                    print(message)
                    error_messages.append(message)
                    check_subtile_dir.append(subtile_dir)
                print('finfile exists, skipping {}'.format(dstfn))
                run_tile = False

            if run_tile:
                ## if pbs, submit to scheduler
                i+=1
                if args.pbs:
                    job_name = 'mst_{}'.format(task.t)
                    cmd = r'qsub -N {1} -v p1={2},p2={3},p3={4},p4={5},p5={6},p6={7},p7={8},p8={9},p9={10},p10={11},p11={12} {0}'.format(
                        qsubpath,
                        job_name,
                        scriptdir,
                        args.lib_path,
                        matlab_script,
                        subtile_dir,
                        args.res,
                        dstfp,
                        task.t,
                        tile_def,
                        task.st,
                        finfile,
                        project_version_dict[args.project],
                    )
                    print(cmd)
                    if not args.dryrun:
                        subprocess.call(cmd, shell=True)

                ## else run matlab
                else:
                    if task.st == 'null':
                        cmd = """matlab -nojvm -nodisplay -nosplash -r "try; addpath('{0}'); addpath('{1}'); [x0,x1,y0,y1]=getTileExtents('{6}','{7}'); projstr=getTileProjection('{7}'); {2}('{3}',{4},'{5}','projection',projstr,'version','{8}','extent',[x0,x1,y0,y1]); catch e; disp(getReport(e)); exit(1); end; exit(0);" """.format(
                            scriptdir,
                            args.lib_path,
                            matlab_script,
                            subtile_dir,
                            args.res,
                            dstfp,
                            task.t,
                            tile_def,
                            project_version_dict[args.project],
                        )
                    else:
                        cmd = """matlab -nojvm -nodisplay -nosplash -r "try; addpath('{0}'); addpath('{1}'); [x0,x1,y0,y1]=getTileExtents('{7}','{8}','quadrant','{6}'); projstr=getTileProjection('{8}'); {2}('{3}',{4},'{5}','projection',projstr,'quadrant','{6}','version','{9}','extent',[x0,x1,y0,y1]); catch e; disp(getReport(e)); exit(1); end; exit(0);" """.format(
                            scriptdir,
                            args.lib_path,
                            matlab_script,
                            subtile_dir,
                            args.res,
                            dstfp,
                            task.st,
                            task.t,
                            tile_def,
                            project_version_dict[args.project],
                        )
                    print("{}, {}".format(i, cmd))
                    if not args.dryrun:
                        subprocess.call(cmd, shell=True)

    print('-----')
    print('The following tiles should be investigated and potentially rerun with BST and/or MST')
    print('-----')
    for message in error_messages:
        print(message)
    print('-----')
    print('The preceding tiles should be investigated and potentially rerun with BST and/or MST')
    check_subtile_dir = list(set(check_subtile_dir))
    print('Checking those {} super-tiles for existence of subtile results...'.format(len(check_subtile_dir)))
    print('-----')
    for subtile_dir in check_subtile_dir:
        tilename = os.path.basename(os.path.dirname(subtile_dir))
        if not glob.glob(os.path.join(subtile_dir, '{}_*{}m.mat'.format(tilename, args.res))):
            print("ERROR! No {}m results exist in subtile directory for tile {}: {}".format(args.res, tilename, subtile_dir))
    print('-----')
    print("Done")



if __name__ == '__main__':
    main()
