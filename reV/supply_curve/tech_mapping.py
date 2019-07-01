# -*- coding: utf-8 -*-
"""
Created on Fri Jun 21 16:05:47 2019

@author: gbuster
"""
import h5py
import concurrent.futures as cf
import pandas as pd
import numpy as np
import os
from scipy.spatial import cKDTree
import logging
from warnings import warn

from reV.handlers.resource import Resource
from reV.handlers.outputs import Outputs
from reV.supply_curve.points import SupplyCurveExtent
from reV.utilities.exceptions import FileInputWarning, FileInputError


logger = logging.getLogger(__name__)


class TechMapping:
    """Framework to create map between tech layer (exclusions), res, and gen"""

    def __init__(self, fpath_excl, fpath_map, fpath_out, dset,
                 distance_upper_bound=0.03, resolution=2560, n_cores=None):
        """
        Parameters
        ----------
        fpath_excl : str
            Filepath to exclusions geotiff (tech layer).
        fpath_map : str
            Filepath to .h5 resource or generation file that we're mapping to.
        fpath_out : str
            .h5 filepath to save tech mapping results to, or to read from
            (if exists).
        dset : str
            Dataset name in fpath_out to save mapping results to.
        distance_upper_bound : float | None
            Upper boundary distance for KNN lookup between exclusion points and
            resource points. None will calculate a good distance based on the
            resource meta data coordinates. 0.03 is a good value for a 4km
            resource grid and finer.
        resolution : int | None
            Supply curve resolution used for the tech mapping calc. This is not
            the final supply curve point resolution.
        n_cores : int | None
            Number of cores to run mapping on. None uses all available cpus.
        """

        self._distance_upper_bound = distance_upper_bound
        self._fpath_excl = fpath_excl
        self._fpath_map = fpath_map
        self._fpath_out = fpath_out
        self._dset = dset
        self._check_fout()

        self._sc = SupplyCurveExtent(fpath_excl, resolution=resolution)
        self._resolution = self._sc._res

        if n_cores is None:
            n_cores = os.cpu_count()
        self._n_cores = n_cores

        logger.info('Initialized TechMapping object with {} calc chunks for '
                    '{} tech exclusion points'
                    .format(len(self._sc), len(self._sc.exclusions)))

    def _check_fout(self):
        """Check the TechMapping output file for cached data."""

        emsg = None
        wmsg = None
        if os.path.exists(self._fpath_out):
            with h5py.File(self._fpath_out, 'a') as f:

                if 'fpath_excl' not in f.attrs:
                    wmsg = ('Pre-existing TechMapping file does not have a '
                            '"fpath_excl" attribute to verify the exclusions '
                            'layer it was based on. TechMapping proceeding '
                            'at-risk.')

                if (os.path.basename(f.attrs['fpath_excl'])
                        != os.path.basename(self._fpath_excl)):
                    wmsg = ('Exclusions file "{}" used to create the '
                            'pre-existing TechMapping file did not match the '
                            'new input exclusions file "{}". '
                            'TechMapping proceeding at-risk.'
                            .format(os.path.basename(f.attrs['fpath_excl']),
                                    os.path.basename(self._fpath_excl)))

                if 'latitude' not in f or 'longitude' not in f:
                    emsg = ('Datasets "latitude" and/or "longitude" not in '
                            'pre-existing TechMapping file "{}". '
                            'Cannot proceed.'
                            .format(os.path.basename(self._fpath_excl)))

                if self._dset in f:
                    wmsg = ('TechMap results dataset "{}" is being replaced '
                            'in pre-existing TechMapping file "{}"'
                            .format(self._dset, self._fpath_out))

        if wmsg is not None:
            logger.warning(wmsg)
            warn(wmsg, FileInputWarning)
        if emsg is not None:
            logger.exception(emsg)
            raise FileInputError(emsg)

    def _init_out_arrays(self):
        """Initialize full sized output arrays.

        Returns
        -------
        ind : np.ndarray
            1D integer array filled with -1's with length equal to the number
            of tech exclusion points in the supply curve extent.
        coords : np.ndarray
            2D integer array (N, 2) filled with 0's with length equal to the
            number of tech exclusion points in the supply curve extent.
        """

        N = len(self._sc.exclusions)
        ind = -1 * np.ones((N, ), dtype=np.int32)
        coords = np.zeros((N, 2), dtype=np.float32)
        return ind, coords

    @property
    def distance_upper_bound(self):
        """Get the upper bound on NN distance between excl and res points.

        Returns
        -------
        distance_upper_bound : float
            Estimate of the upper bound distance based on the distance between
            resource points. Calculated as half of the diagonal between
            closest resource points, with an extra 5% margin.
        """

        if self._distance_upper_bound is None:

            with Resource(self._fpath_map, str_decode=False) as res:
                lats = res.get_meta_arr('latitude')

            dists = np.abs(lats - np.roll(lats, 1))
            dists = dists[(dists != 0)]
            self._distance_upper_bound = 1.05 * (2 ** 0.5) * (dists.min() / 2)

            logger.info('Distance upper bound was infered to be: {}'
                        .format(self._distance_upper_bound))

        return self._distance_upper_bound

    @staticmethod
    def _unpack_coords(gids, sc, fpath_out,
                       coord_labels=('latitude', 'longitude')):
        """Unpack the exclusion layer coordinates for TechMapping.

        Parameters
        ----------
        gids : np.ndarray
            Supply curve gids with tech exclusion points to map to the
            resource meta points.
        sc : SupplyCurveExtent
            reV supply curve extent object
        fpath_out : str
            .h5 filepath to save tech mapping results to, or to read from
            (if exists).
        coord_labels : tuple
            Labels for the coordinate datasets.

        Returns
        -------
        coords_out : list
            List of arrays of the un-projected latitude, longitude array of
            tech exclusion points. List entries correspond to input gids.
        lat_range : tuple
            Latitude (min, max) values associated with the un-projected
            coordinates of the input gids.
        lon_range : tuple
            Longitude (min, max) values associated with the un-projected
            coordinates of the input gids.
        """

        coords_out = []
        lat_range = None
        lon_range = None

        for gid in gids:
            row_slice, col_slice = sc.get_excl_slices(gid)

            if os.path.exists(fpath_out):
                with h5py.File(fpath_out, 'r') as f:
                    emeta = np.vstack(
                        (f['latitude'][row_slice, col_slice].flatten(),
                         f['longitude'][row_slice, col_slice].flatten())).T
            else:
                emeta = sc.exclusions['meta', row_slice, col_slice]
                emeta = emeta[coord_labels].values

            coords_out.append(emeta)

            if lat_range is None:
                lat_range = [np.min(emeta[:, 0]), np.max(emeta[:, 0])]
                lon_range = [np.min(emeta[:, 1]), np.max(emeta[:, 1])]
            else:
                lat_range[0] = np.min((lat_range[0], np.min(emeta[:, 0])))
                lat_range[1] = np.max((lat_range[1], np.max(emeta[:, 0])))
                lon_range[0] = np.min((lon_range[0], np.min(emeta[:, 1])))
                lon_range[1] = np.max((lon_range[1], np.max(emeta[:, 1])))
        return coords_out, lat_range, lon_range

    def _parallel_resource_map(self):
        """Map all resource gids to exclusion gids in parallel.

        Returns
        -------
        ind_all : np.ndarray
            Index values of the NN resource point. -1 if no res point found.
            1D integer array with length equal to the number of tech exclusion
            points in the supply curve extent.
        coords_all : np.ndarray
            Un-projected latitude, longitude array of tech exclusion points.
            0's if no res point found. 2D integer array (N, 2) filled with 0's
            with length equal to the number of tech exclusion points in the
            supply curve extent.
        """

        gids = np.array(list(range(len(self._sc))), dtype=np.uint32)
        gid_chunks = np.array_split(gids, int(np.ceil(len(gids) / 2)))

        # init full output arrays
        ind_all, coords_all = self._init_out_arrays()

        n_finished = 0
        futures = {}
        with cf.ProcessPoolExecutor(max_workers=self._n_cores) as executor:

            # iterate through split executions, submitting each to worker
            for i, gid_set in enumerate(gid_chunks):
                # submit executions and append to futures list
                futures[executor.submit(self.map_resource_gids,
                                        gid_set,
                                        self._fpath_excl,
                                        self._fpath_map,
                                        self._fpath_out,
                                        self.distance_upper_bound,
                                        self._resolution)] = i

            for future in cf.as_completed(futures):
                n_finished += 1
                logger.info('Parallel TechMapping futures collected: '
                            '{} out of {}'
                            .format(n_finished, len(futures)))

                i = futures[future]
                result = future.result()
                for j, gid in enumerate(gid_chunks[i]):
                    i_out_arr = self._sc.get_flat_excl_ind(gid)
                    ind_all[i_out_arr] = result[0][j]
                    coords_all[i_out_arr, :] = result[1][j]

        return ind_all, coords_all

    @staticmethod
    def map_resource_gids(gids, fpath_excl, fpath_res, fpath_out,
                          distance_upper_bound, resolution, margin=0.1):
        """Map exclusion gids to the resource meta.

        Parameters
        ----------
        gids : np.ndarray
            Supply curve gids with tech exclusion points to map to the
            resource meta points.
        fpath_excl : str
            Filepath to exclusions geotiff (tech layer).
        fpath_res : str
            Filepath to .h5 resource file that we're mapping to.
        fpath_out : str
            .h5 filepath to save tech mapping results to, or to read from
            (if exists).
        distance_upper_bound : float | None
            Upper boundary distance for KNN lookup between exclusion points and
            resource points.
        resolution : int
            Supply curve resolution used for the tech mapping. Must correspond
            to the resolution used to make the gids input. This is not
            the final supply curve point resolution.
        margin : float
            Margin when reducing the resource lat/lon.

        Returns
        -------
        ind : list
            List of arrays of index values from the NN. List entries correspond
            to input gids.
        coords : np.ndarray
            List of arrays of the un-projected latitude, longitude array of
            tech exclusion points. List entries correspond to input gids.
        """

        logger.debug('Getting tech layer coordinates for chunks {} through {}'
                     .format(gids[0], gids[-1]))

        ind_out = []
        coord_labels = ['latitude', 'longitude']

        sc = SupplyCurveExtent(fpath_excl, resolution=resolution)

        coords_out, lat_range, lon_range = TechMapping._unpack_coords(
            gids, sc, fpath_out, coord_labels=coord_labels)

        with Resource(fpath_res, str_decode=False) as res:
            res_meta = np.vstack((res.get_meta_arr(coord_labels[0]),
                                  res.get_meta_arr(coord_labels[1]))).T

        mask = ((res_meta[:, 0] > lat_range[0] - margin)
                & (res_meta[:, 0] < lat_range[1] + margin)
                & (res_meta[:, 1] > lon_range[0] - margin)
                & (res_meta[:, 1] < lon_range[1] + margin))

        # pylint: disable-msg=C0121
        mask_ind = np.where(mask == True)[0]  # noqa: E712

        if np.sum(mask) > 0:
            res_tree = cKDTree(res_meta[mask, :])

            logger.debug('Running tech mapping for chunks {} through {}'
                         .format(gids[0], gids[-1]))
            for i, _ in enumerate(gids):
                dist, ind = res_tree.query(coords_out[i])
                ind = mask_ind[ind]
                ind[(dist > distance_upper_bound)] = -1
                ind_out.append(ind)
        else:
            logger.debug('No close res points for chunks {} through {}'
                         .format(gids[0], gids[-1]))
            for _ in gids:
                ind_out.append(-1)

        return ind_out, coords_out

    def _parallel_gen_map(self, res_map_dset):
        """Map all generation gids to pre-mapped resource gids in parallel.

        Parameters
        ----------
        res_map_dset : str
            Pre-existing dataset name in fpath_out to retrieve
            resource-mapping results.

        Returns
        -------
        ind_all : np.ndarray
            Index values of the NN gen point. -1 if no gen point found.
            1D integer array with length equal to the number of tech exclusion
            points in the supply curve extent.
        """

        if not os.path.exists(self._fpath_out):
            raise FileInputError('TechMap file must exist before the '
                                 'generation mapping can run. Could not '
                                 'find file: {}'.format(self._fpath_out))
        with h5py.File(self._fpath_out, 'r') as f:
            if res_map_dset not in list(f):
                raise FileInputError('Could not find pre-existing resource '
                                     'map dataset "{}" in res map file: {}'
                                     .format(res_map_dset, self._fpath_out))

        gids = np.array(list(range(len(self._sc))), dtype=np.uint32)
        gid_chunks = np.array_split(gids, int(np.ceil(len(gids) / 2)))

        # init full output arrays
        gen_gids_all, _ = self._init_out_arrays()

        n_finished = 0
        futures = {}
        with cf.ProcessPoolExecutor(max_workers=self._n_cores) as executor:

            # iterate through split executions, submitting each to worker
            for i, gid_set in enumerate(gid_chunks):
                # submit executions and append to futures list
                futures[executor.submit(self.map_gen_gids,
                                        gid_set,
                                        self._fpath_excl,
                                        self._fpath_map,
                                        self._fpath_out,
                                        res_map_dset,
                                        self._resolution)] = i

            for future in cf.as_completed(futures):
                n_finished += 1
                logger.info('Parallel TechMapping futures collected: '
                            '{} out of {}'
                            .format(n_finished, len(futures)))

                i = futures[future]
                result = future.result()
                for j, gid in enumerate(gid_chunks[i]):
                    i_out_arr = self._sc.get_flat_excl_ind(gid)
                    gen_gids_all[i_out_arr] = result[j]

        return gen_gids_all

    @staticmethod
    def map_gen_gids(gids, fpath_excl, fpath_gen, fpath_out, res_map_dset,
                     resolution):
        """Map exclusion gids to the resource meta.

        Parameters
        ----------
        gids : np.ndarray
            Supply curve gids with tech exclusion points to map to the
            resource meta points.
        fpath_excl : str
            Filepath to exclusions geotiff (tech layer).
        fpath_gen : str
            Filepath to .h5 generation file that we're mapping to.
        fpath_out : str
            .h5 filepath to save tech mapping results to, or to read from
            (if exists).
        res_map_dset : str
            Pre-existing dataset name in fpath_out to retrieve
            resource-mapping results.
        resolution : int
            Supply curve resolution used for the tech mapping. Must correspond
            to the resolution used to make the gids input. This is not
            the final supply curve point resolution.

        Returns
        -------
        gen_gids_out : list
            List of arrays of generation index values from the NN. List
            entries correspond to input gids.
        """

        logger.debug('Getting tech layer coordinates for chunks {} through {}'
                     .format(gids[0], gids[-1]))
        gen_gids_out = []
        sc = SupplyCurveExtent(fpath_excl, resolution=resolution)

        with Outputs(fpath_gen, str_decode=False) as gen:
            gen_meta = gen.meta[['gid']]
            gen_meta['gen_gid'] = gen_meta.index.values

        for gid in gids:
            row_slice, col_slice = sc.get_excl_slices(gid)

            with h5py.File(fpath_out, 'r') as f:
                res_gid = f[res_map_dset][row_slice, col_slice].flatten()

            res_gid = pd.DataFrame({'res_gid': res_gid})
            gen_gids = pd.merge(res_gid, gen_meta, left_on='res_gid',
                                right_on='gid', how='left')['gen_gid'].values
            gen_gids[np.isnan(gen_gids)] = -1
            gen_gids.astype(np.int32)
            gen_gids_out.append(gen_gids)
        else:
            logger.debug('No close gen points for chunks {} through {}'
                         .format(gids[0], gids[-1]))
            for _ in gids:
                gen_gids_out.append(-1)

        return gen_gids_out

    def save_tech_map(self, ind, coords, fpath_out, dset, chunks=(128, 128)):
        """Save tech mapping indices and coordinates to an h5 output file.

        Parameters
        ----------
        ind : np.ndarray
            Index values of the NN resource point.
        coords : np.ndarray
            Un-projected latitude, longitude array of tech exclusion points.
        fpath_out : str
            .h5 filepath to save tech mapping results.
        dset : str
            Dataset name in fpath_out to save mapping results to.
        chunks : tuple
            Chunk shape of the 2D output datasets.
        """

        if not fpath_out.endswith('.h5'):
            fpath_out += '.h5'

        logger.info('Writing tech map "{}" to {}'.format(dset, fpath_out))

        shape = self._sc.exclusions.shape
        chunks = (np.min((shape[0], chunks[0])), np.min((shape[1], chunks[1])))

        if not os.path.exists(fpath_out):
            if coords is not None:
                with h5py.File(fpath_out, 'w') as f:
                    f.create_dataset('latitude', shape=shape,
                                     dtype=coords.dtype,
                                     data=coords[:, 0].reshape(shape),
                                     chunks=chunks)
                    f.create_dataset('longitude', shape=shape,
                                     dtype=coords.dtype,
                                     data=coords[:, 1].reshape(shape),
                                     chunks=chunks)
                    f.attrs['fpath_excl'] = self._fpath_excl

        with h5py.File(fpath_out, 'a') as f:
            if dset in list(f):
                f[dset][...] = ind.reshape(shape)
            else:
                f.create_dataset(dset, shape=shape, dtype=ind.dtype,
                                 data=ind.reshape(shape), chunks=chunks)

            f[dset].attrs['fpath'] = self._fpath_map
            f[dset].attrs['distance_upper_bound'] = self.distance_upper_bound

        logger.info('Successfully saved tech map "{}" to {}'
                    .format(dset, fpath_out))

    @classmethod
    def run_resource_map(cls, fpath_excl, fpath_res, fpath_out, res_map_dset,
                         **kwargs):
        """Run parallel mapping and save to h5 file.

        Parameters
        ----------
        fpath_excl : str
            Filepath to exclusions geotiff (tech layer).
        fpath_res : str
            Filepath to .h5 resource file that we're mapping to.
        fpath_out : str
            .h5 filepath to save tech mapping results.
        res_map_dset : str
            Dataset name in fpath_out to save mapping results to.
        kwargs : dict
            Keyword args to initialize the TechMapping object.
        """

        mapper = cls(fpath_excl, fpath_res, fpath_out, res_map_dset, **kwargs)
        ind, coords = mapper._parallel_resource_map()
        mapper.save_tech_map(ind, coords, fpath_out, res_map_dset)

    @classmethod
    def run_gen_map(cls, fpath_excl, fpath_gen, fpath_out, gen_map_dset,
                    res_map_dset, **kwargs):
        """Run parallel mapping and save to h5 file.

        Parameters
        ----------
        fpath_excl : str
            Filepath to exclusions geotiff (tech layer).
        fpath_gen : str
            Filepath to .h5 gen file that we're mapping to.
        fpath_out : str
            .h5 filepath to save tech mapping results.
        gen_map_dset : str
            Dataset name in fpath_out to save gen mapping results to.
        res_map_dset : str
            Pre-existing dataset name in fpath_out to retrieve
            resource-mapping results.
        kwargs : dict
            Keyword args to initialize the TechMapping object.
        """

        mapper = cls(fpath_excl, fpath_gen, fpath_out, gen_map_dset, **kwargs)
        ind = mapper._parallel_gen_map(res_map_dset)
        mapper.save_tech_map(ind, None, fpath_out, gen_map_dset)
