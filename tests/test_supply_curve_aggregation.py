# -*- coding: utf-8 -*-
"""
Created on Wed Jun 19 15:37:05 2019

@author: gbuster
"""
import pandas as pd
import numpy as np
import pytest
import os
from reV.supply_curve.aggregation import Aggregation
from reV import TESTDATADIR


F_EXCL = os.path.join(TESTDATADIR, 'ri_exclusions/exclusions.tif')
F_GEN = os.path.join(TESTDATADIR, 'gen_out/ri_my_gen.h5')
F_TECHMAP = os.path.join(TESTDATADIR, 'sc_out/baseline_ri_tech_map.h5')
F_AGG_BASELINE = os.path.join(TESTDATADIR, 'sc_out/baseline_agg_summary.csv')
DSET_TM = 'res_nsrdb_full'
RES_CLASS_DSET = 'ghi_mean-means'
RES_CLASS_BINS = [[0, 4], [4, 10]]
FPATH_SLOPE = os.path.join(TESTDATADIR, "ri_exclusions/ri_srtm_slope.tif")
DATA_LAYERS = {'pct_slope': {'band': 0,
                             'method': 'mean',
                             'fpath': FPATH_SLOPE}}


def test_aggregation_extent(resolution=64):
    """Get the SC points aggregation summary and test that there are expected
    columns and that all resource gids were found"""

    summary = Aggregation.summary(F_EXCL, F_GEN, F_TECHMAP, DSET_TM,
                                  res_class_dset=None,
                                  res_class_bins=None,
                                  resolution=resolution)

    all_res_gids = []
    for gids in summary['res_gids']:
        all_res_gids += gids

    assert 'sc_col_ind' in summary
    assert 'sc_row_ind' in summary
    assert 'gen_gids' in summary
    assert len(set(all_res_gids)) == 188


def test_parallel_agg(resolution=64):
    """Test that parallel aggregation yields the same results as serial
    aggregation."""

    gids = list(range(50, 70))
    summary_serial = Aggregation.summary(F_EXCL, F_GEN, F_TECHMAP, DSET_TM,
                                         res_class_dset=None,
                                         res_class_bins=None,
                                         resolution=resolution,
                                         gids=gids, n_cores=1)
    summary_parallel = Aggregation.summary(F_EXCL, F_GEN, F_TECHMAP, DSET_TM,
                                           res_class_dset=None,
                                           res_class_bins=None,
                                           resolution=resolution,
                                           gids=gids, n_cores=3)

    assert all(summary_serial == summary_parallel)


def test_aggregation_summary():
    """Test the aggregation summary method against a baseline file."""

    s = Aggregation.summary(F_EXCL, F_GEN, F_TECHMAP, DSET_TM,
                            res_class_dset=RES_CLASS_DSET,
                            res_class_bins=RES_CLASS_BINS,
                            data_layers=DATA_LAYERS,
                            n_cores=1)

    if not os.path.exists(F_AGG_BASELINE):
        s.to_csv(F_AGG_BASELINE, index=False)
        raise Exception('Aggregation summary baseline file did not exist. '
                        'Created: {}'.format(F_AGG_BASELINE))

    else:
        s_baseline = pd.read_csv(F_AGG_BASELINE, index_col=0)

        for i, c in enumerate(s.columns):
            if c in s_baseline:
                if not np.issubdtype(s.dtypes[i], np.object_):
                    m = ('Aggregation summary column did not match baseline '
                         'file: "{}"'.format(c))
                    assert np.allclose(s[c].values, s_baseline[c].values), m


def execute_pytest(capture='all', flags='-rapP'):
    """Execute module as pytest with detailed summary report.

    Parameters
    ----------
    capture : str
        Log or stdout/stderr capture option. ex: log (only logger),
        all (includes stdout/stderr)
    flags : str
        Which tests to show logs and results for.
    """

    fname = os.path.basename(__file__)
    pytest.main(['-q', '--show-capture={}'.format(capture), fname, flags])


if __name__ == '__main__':
    execute_pytest()