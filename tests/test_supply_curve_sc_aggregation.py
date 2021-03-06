# -*- coding: utf-8 -*-
"""
Created on Wed Jun 19 15:37:05 2019

@author: gbuster
"""
import json
import os
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from reV.supply_curve.sc_aggregation import SupplyCurveAggregation
from reV import TESTDATADIR

EXCL = os.path.join(TESTDATADIR, 'ri_exclusions/ri_exclusions.h5')
GEN = os.path.join(TESTDATADIR, 'gen_out/ri_my_pv_gen.h5')
AGG_BASELINE = os.path.join(TESTDATADIR, 'sc_out/baseline_agg_summary.csv')
TM_DSET = 'techmap_nsrdb'
RES_CLASS_DSET = 'ghi_mean-means'
RES_CLASS_BINS = [0, 4, 100]
DATA_LAYERS = {'pct_slope': {'dset': 'ri_srtm_slope',
                             'method': 'mean'},
               'reeds_region': {'dset': 'ri_reeds_regions',
                                'method': 'mode'},
               'padus': {'dset': 'ri_padus',
                         'method': 'mode'}}

EXCL_DICT = {'ri_srtm_slope': {'inclusion_range': (None, 5),
                               'exclude_nodata': True},
             'ri_padus': {'exclude_values': [1],
                          'exclude_nodata': True}}

RTOL = 0.001


def test_aggregation_extent(resolution=64):
    """Get the SC points aggregation summary and test that there are expected
    columns and that all resource gids were found"""

    summary = SupplyCurveAggregation.summary(EXCL, GEN, TM_DSET,
                                             excl_dict=EXCL_DICT,
                                             res_class_dset=None,
                                             res_class_bins=None,
                                             data_layers=DATA_LAYERS,
                                             resolution=resolution)

    all_res_gids = []
    for gids in summary['res_gids']:
        all_res_gids += gids

    assert 'sc_col_ind' in summary
    assert 'sc_row_ind' in summary
    assert 'gen_gids' in summary
    assert len(set(all_res_gids)) == 177


def test_parallel_agg(resolution=64):
    """Test that parallel aggregation yields the same results as serial
    aggregation."""

    gids = list(range(50, 70))
    summary_serial = SupplyCurveAggregation.summary(EXCL, GEN, TM_DSET,
                                                    excl_dict=EXCL_DICT,
                                                    res_class_dset=None,
                                                    res_class_bins=None,
                                                    resolution=resolution,
                                                    gids=gids, max_workers=1)
    summary_parallel = SupplyCurveAggregation.summary(EXCL, GEN, TM_DSET,
                                                      excl_dict=EXCL_DICT,
                                                      res_class_dset=None,
                                                      res_class_bins=None,
                                                      resolution=resolution,
                                                      gids=gids, max_workers=3)

    assert all(summary_serial == summary_parallel)


def test_aggregation_summary():
    """Test the aggregation summary method against a baseline file."""

    s = SupplyCurveAggregation.summary(EXCL, GEN, TM_DSET,
                                       excl_dict=EXCL_DICT,
                                       res_class_dset=RES_CLASS_DSET,
                                       res_class_bins=RES_CLASS_BINS,
                                       data_layers=DATA_LAYERS,
                                       max_workers=1)

    if not os.path.exists(AGG_BASELINE):
        s.to_csv(AGG_BASELINE)
        raise Exception('Aggregation summary baseline file did not exist. '
                        'Created: {}'.format(AGG_BASELINE))

    else:
        for c in ['res_gids', 'gen_gids', 'gid_counts']:
            s[c] = s[c].astype(str)

        s_baseline = pd.read_csv(AGG_BASELINE, index_col=0)

        assert_frame_equal(s, s_baseline, check_dtype=False)


def test_aggregation_scalar_excl():
    """Test the aggregation summary with exclusions of 0.5"""

    gids_subset = list(range(0, 20))
    excl_dict_1 = {'ri_padus': {'exclude_values': [1]}}
    s1 = SupplyCurveAggregation.summary(EXCL, GEN, TM_DSET,
                                        excl_dict=excl_dict_1,
                                        res_class_dset=RES_CLASS_DSET,
                                        res_class_bins=RES_CLASS_BINS,
                                        data_layers=DATA_LAYERS,
                                        max_workers=1, gids=gids_subset)
    excl_dict_2 = {'ri_padus': {'exclude_values': [1],
                                'weight': 0.5}}
    s2 = SupplyCurveAggregation.summary(EXCL, GEN, TM_DSET,
                                        excl_dict=excl_dict_2,
                                        res_class_dset=RES_CLASS_DSET,
                                        res_class_bins=RES_CLASS_BINS,
                                        data_layers=DATA_LAYERS,
                                        max_workers=1, gids=gids_subset)

    dsets = ['area_sq_km', 'capacity']
    for dset in dsets:
        diff = (s1[dset].values / s2[dset].values)
        msg = ('Fractional exclusions failed for {} which has values {} and {}'
               .format(dset, s1[dset].values, s2[dset].values))
        assert all(diff == 2), msg

    for i in s1.index:
        counts_full = s1.loc[i, 'gid_counts']
        counts_half = s2.loc[i, 'gid_counts']

        for j, counts in enumerate(counts_full):
            msg = ('GID counts for fractional exclusions failed for index {}!'
                   .format(i))
            assert counts == 2 * counts_half[j], msg


def test_aggregation_category_layer():
    """Test aggregation of data layers with category method"""
    data_layers = {'pct_slope': {'dset': 'ri_srtm_slope',
                                 'method': 'mean'},
                   'reeds_region': {'dset': 'ri_reeds_regions',
                                    'method': 'category'},
                   'padus': {'dset': 'ri_padus',
                             'method': 'category'}}

    s = SupplyCurveAggregation.summary(EXCL, GEN, TM_DSET, EXCL_DICT,
                                       res_class_dset=RES_CLASS_DSET,
                                       res_class_bins=RES_CLASS_BINS,
                                       data_layers=data_layers,
                                       max_workers=1)

    for i in s.index.values:
        counts = s.loc[i, 'gid_counts']
        rr = s.loc[i, 'reeds_region']
        assert isinstance(rr, str)
        rr = json.loads(rr)
        assert isinstance(rr, dict)
        rr_sum = sum(list(rr.values()))
        padus = s.loc[i, 'padus']
        assert isinstance(padus, str)
        padus = json.loads(padus)
        assert isinstance(padus, dict)
        padus_sum = sum(list(padus.values()))
        try:
            assert padus_sum == sum(counts)
            assert padus_sum >= rr_sum
        except AssertionError:
            e = ('Categorical data layer aggregation failed:\n{}'
                 .format(s.loc[i]))
            raise RuntimeError(e)


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
