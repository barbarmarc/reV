"""
Generation
"""
import click

from reV.utilities.cli_dtypes import STR
from reV.generation.cli_gen import from_config as run_gen_from_config
from reV.econ.cli_econ import from_config as run_econ_from_config
from reV.handlers.cli_collect import from_config as run_collect_from_config
from reV.pipeline.cli_pipeline import from_config as run_pipeline_from_config


@click.group()
@click.option('--name', '-n', default='reV', type=STR,
              help='Job name. Default is "reV".')
@click.option('--config_file', '-c',
              required=True, type=click.Path(exists=True),
              help='reV configuration file json for a single module.')
@click.option('-v', '--verbose', is_flag=True,
              help='Flag to turn on debug logging. Default is not verbose.')
@click.pass_context
def main(ctx, name, config_file, verbose):
    """reV 2.0 command line interface."""
    ctx.ensure_object(dict)
    ctx.obj['NAME'] = name
    ctx.obj['CONFIG_FILE'] = config_file
    ctx.obj['VERBOSE'] = verbose


@main.command()
@click.option('-v', '--verbose', is_flag=True,
              help='Flag to turn on debug logging.')
@click.pass_context
def generation(ctx, verbose):
    """Generation analysis (pv, csp, windpower, etc...)."""
    config_file = ctx.obj['CONFIG_FILE']
    verbose = any([verbose, ctx.obj['VERBOSE']])
    ctx.invoke(run_gen_from_config, config_file=config_file,
               verbose=verbose)


@main.command()
@click.option('-v', '--verbose', is_flag=True,
              help='Flag to turn on debug logging.')
@click.pass_context
def econ(ctx, verbose):
    """Econ analysis (lcoe, single-owner, etc...)."""
    config_file = ctx.obj['CONFIG_FILE']
    verbose = any([verbose, ctx.obj['VERBOSE']])
    ctx.invoke(run_econ_from_config, config_file=config_file,
               verbose=verbose)


@main.command()
@click.option('-v', '--verbose', is_flag=True,
              help='Flag to turn on debug logging.')
@click.pass_context
def collect(ctx, verbose):
    """Collect files from a job run on multiple nodes."""
    config_file = ctx.obj['CONFIG_FILE']
    verbose = any([verbose, ctx.obj['VERBOSE']])
    ctx.invoke(run_collect_from_config, config_file=config_file,
               verbose=verbose)


@main.command()
@click.option('-v', '--verbose', is_flag=True,
              help='Flag to turn on debug logging.')
@click.pass_context
def pipeline(ctx, verbose):
    """Execute multiple steps in a reV analysis pipeline."""
    config_file = ctx.obj['CONFIG_FILE']
    verbose = any([verbose, ctx.obj['VERBOSE']])
    ctx.invoke(run_pipeline_from_config, config_file=config_file,
               verbose=verbose)


if __name__ == '__main__':
    main(obj={})
