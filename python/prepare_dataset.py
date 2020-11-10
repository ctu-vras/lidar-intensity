#!/usr/bin/env python3

import argparse

import psutil
import yaml

import gta

CONFIG_FILE = 'gta.yml'


def run(parsed_args):
    gta.db.open_connection(parsed_args)
    args.log_data = gta.io.load_log_file(args)
    gta.db.get_runs(parsed_args)
    for run_id in parsed_args.runs:
        gta.db.process_run(run_id, parsed_args)
    parsed_args.conn.commit()
    parsed_args.cursor.close()
    parsed_args.conn.close()


def process_field(parsed_args, yaml_config, field, fail=True):
    arg = getattr(parsed_args, field)
    if field in yaml_config:
        if arg is not None:
            if parsed_args.verbose:
                print(f'Setting field {field} from command line overwriting value from a config file!')
                print(f'Old value: {yaml_config[field]}\nNew value: {arg}')
        else:
            setattr(parsed_args, field, yaml_config[field])
    else:
        if arg is None and fail:
            raise RuntimeError(f'Field {field} is not specified on command line nor in a config file!')
    return parsed_args


def parse_args():
    parser = argparse.ArgumentParser(
        description='Tool for preparing datasets and fetching metadata from database.',
        epilog='All arguments can be specified either in config file or on command line. Command line arguments take precedence over config file.',
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=50, width=159),
    )
    parser.add_argument('-cf', '--config_file', default='gta.yml', type=str, help='Config file location')
    parser.add_argument('-cs', '--conn_string', default=None, type=str, help='Connection string for the database. Same as in managed GTA plugin')
    parser.add_argument('-od', '--output_dir', default=None, type=str, help='Output directory')
    parser.add_argument('-id', '--in_dir', default=None, type=str, help='input directory')
    parser.add_argument('-nc', '--num_cameras', type=int, default=None, help='Number of cameras. Could be None to infer from database for each run')
    parser.add_argument(
        '-np',
        '--num_processes',
        type=int,
        default=None,
        help='Number of processes to launch. If left at None, it wiill default to half of available CPUs',
    )
    parser.add_argument('-lf', '--log_file', type=str, default=None, help='Log file from managed GTA plugin. It helps to correct malformed data.')
    needs_all = parser.add_mutually_exclusive_group()
    needs_all.add_argument('-na', '--needs_all', default=None, action='store_true', help='Whether all cameras from one scene are needed')
    needs_all.add_argument('-nna', '--not_needs_all', default=None, action='store_false', dest='needs_all')
    all_runs = parser.add_mutually_exclusive_group()
    all_runs.add_argument('-ar', '--all_runs', default=None, action='store_true', help='Whether all runs in the database should be exported')
    all_runs.add_argument('-nar', '--not_all_runs', default=None, action='store_false', dest='all_runs')
    delete = parser.add_mutually_exclusive_group()
    delete.add_argument(
        '-do',
        '--delete_originals',
        default=None,
        action='store_true',
        help='Delete original files to reduce memory on a drive\nWarning: It will not be possible to run this script again, if you delete the files!',
    )
    delete.add_argument('-ndo', '--not_delete_originals', default=None, action='store_false', dest='delete_originals')
    delete_invalid = parser.add_mutually_exclusive_group()
    delete_invalid.add_argument('-di', '--delete_invalid', default=None, action='store_true', help='Delete invalid entries from database.')
    delete_invalid.add_argument('-ndi', '--not_delete_invalid', default=None, action='store_false', dest='delete_invalid')
    verbose = parser.add_mutually_exclusive_group()
    verbose.add_argument('-v', '--verbose', default=None, action='store_true', help='Verbose output')
    verbose.add_argument('-nv', '--not_verbose', default=None, action='store_false', dest='verbose')

    parser.add_argument(
        '-r', '--runs', nargs='*', default=None, type=int, help='Which runs to export. Lookup run_ids in your database', metavar='RUN_ID'
    )

    parsed = parser.parse_args()
    try:
        with open(parsed.config_file, 'rt', encoding='utf-8') as f:
            yaml_config = yaml.safe_load(f)
    except (FileNotFoundError, yaml.error.YAMLError) as err:
        print(f'Failed to load config file {parsed.config_file}! All arguments have to be specified on command line!')
        print(f'Error was: {err}')
        yaml_config = dict()

    parsed = process_field(parsed, yaml_config, 'verbose')
    parsed = process_field(parsed, yaml_config, 'conn_string')
    parsed = process_field(parsed, yaml_config, 'output_dir')
    parsed = process_field(parsed, yaml_config, 'in_dir')
    parsed = process_field(parsed, yaml_config, 'num_cameras', fail=False)
    parsed = process_field(parsed, yaml_config, 'num_processes', fail=False)
    parsed = process_field(parsed, yaml_config, 'needs_all')
    parsed = process_field(parsed, yaml_config, 'all_runs')
    parsed = process_field(parsed, yaml_config, 'log_file')
    parsed = process_field(parsed, yaml_config, 'delete_originals')
    parsed = process_field(parsed, yaml_config, 'delete_invalid')
    parsed = process_field(parsed, yaml_config, 'runs', fail=not parsed.all_runs)

    if parsed.num_processes is None:
        parsed.num_processes = int(psutil.cpu_count() / 2)

    return parsed


if __name__ == '__main__':
    args = parse_args()
    run(args)
