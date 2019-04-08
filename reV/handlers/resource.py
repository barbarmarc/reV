"""
Classes to handle resource data
"""
import h5py
import numpy as np
import pandas as pd
import warnings

from reV.handlers.sam_resource import parse_keys, SAMResource
from reV.utilities.exceptions import (HandlerKeyError, HandlerRuntimeError,
                                      HandlerValueError, ExtrapolationWarning)


class Resource:
    """
    Base class to handle resource .h5 files
    """
    SCALE_ATTR = 'scale_factor'
    UNIT_ATTR = 'units'

    def __init__(self, h5_file, unscale=True, hsds=False):
        """
        Parameters
        ----------
        h5_file : str
            Path to .h5 resource file
        unscale : bool
            Boolean flag to automatically unscale variables on extraction
        hsds : bool
            Boolean flag to use h5pyd to handle .h5 'files' hosted on AWS
            behind HSDS
        """
        self._h5_file = h5_file
        if hsds:
            import h5pyd
            self._h5 = h5pyd.File(self._h5_file, 'r')
        else:
            self._h5 = h5py.File(self._h5_file, 'r')

        self._unscale = unscale
        self._meta = None
        self._time_index = None

    def __repr__(self):
        msg = "{} for {}".format(self.__class__.__name__, self._h5_file)
        return msg

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

        if type is not None:
            raise

    def __len__(self):
        return self._h5['meta'].shape[0]

    def __getitem__(self, keys):
        ds, ds_slice = parse_keys(keys)

        if ds == 'time_index':
            out = self._get_time_index(*ds_slice)
        elif ds == 'meta':
            out = self._get_meta(*ds_slice)
        elif 'SAM' in ds:
            site = ds_slice[0]
            if isinstance(site, int):
                out = self._get_SAM_df(ds, site)
            else:
                msg = "Can only extract SAM DataFrame for a single site"
                raise HandlerRuntimeError(msg)
        else:
            out = self._get_ds(ds, *ds_slice)

        return out

    @property
    def dsets(self):
        """
        Datasets available in h5_file

        Returns
        -------
        list
            List of datasets in h5_file
        """
        return list(self._h5)

    @property
    def shape(self):
        """
        Resource shape (timesteps, sites)
        shape = (len(time_index), len(meta))

        Returns
        -------
        shape : tuple
            Shape of resource variable arrays (timesteps, sites)
        """
        _shape = (self._h5['time_index'].shape[0], self._h5['meta'].shape[0])
        return _shape

    @property
    def meta(self):
        """
        Meta data DataFrame

        Returns
        -------
        meta : pandas.DataFrame
            Resource Meta Data
        """
        if self._meta is None:
            self._meta = pd.DataFrame(self._h5['meta'][...])

        return self._meta

    @property
    def time_index(self):
        """
        DatetimeIndex

        Returns
        -------
        time_index : pandas.DatetimeIndex
            Resource datetime index
        """
        if self._time_index is None:
            ti = self._h5['time_index'][...].astype(str)
            self._time_index = pd.to_datetime(ti)

        return self._time_index

    def get_attrs(self, dset=None):
        """
        Get h5 attributes either from file or dataset

        Parameters
        ----------
        dset : str
            Dataset to get attributes for, if None get file (global) attributes

        Returns
        -------
        attrs : dict
            Dataset or file attributes
        """
        if dset is None:
            attrs = dict(self._h5.attrs)
        else:
            attrs = dict(self._h5[dset].attrs)

        return attrs

    def get_dset_properties(self, dset):
        """
        Get dataset properties (shape, dtype, chunks)

        Parameters
        ----------
        dset : str
            Dataset to get scale factor for

        Returns
        -------
        shape : tuple
            Dataset array shape
        dtype : str
            Dataset array dtype
        chunks : tuple
            Dataset chunk size
        """
        ds = self._h5[dset]
        return ds.shape, ds.dtype, ds.chunks

    def get_scale(self, dset):
        """
        Get dataset scale factor

        Parameters
        ----------
        dset : str
            Dataset to get scale factor for

        Returns
        -------
        float
            Dataset scale factor, used to unscale int values to floats
        """
        return self._h5[dset].attrs.get(self.SCALE_ATTR, 1)

    def get_units(self, dset):
        """
        Get dataset units

        Parameters
        ----------
        dset : str
            Dataset to get units for

        Returns
        -------
        str
            Dataset units, None if not defined
        """
        return self._h5[dset].attrs.get(self.UNIT_ATTR, None)

    def _get_time_index(self, *ds_slice):
        """
        Extract and convert time_index to pandas Datetime Index

        Examples
        --------
        self['time_index', 1]
            - Get a single timestep This returns a Timestamp
        self['time_index', :10]
            - Get the first 10 timesteps
        self['time_index', [1, 3, 5, 7, 9]]
            - Get a list of timesteps

        Parameters
        ----------
        ds_slice : tuple of int | list | slice
            tuple describing slice of time_index to extract

        Returns
        -------
        time_index : pandas.DatetimeIndex
            Vector of datetime stamps
        """
        time_index = self._h5['time_index'][ds_slice[0]]
        time_index: np.array
        return pd.to_datetime(time_index.astype(str))

    def _get_meta(self, *ds_slice):
        """
        Extract and convert meta to a pandas DataFrame

        Examples
        --------
        self['meta', 1]
            - Get site 1
        self['meta', :10]
            - Get the first 10 sites
        self['meta', [1, 3, 5, 7, 9]]
            - Get the first 5 odd numbered sites
        self['meta', :, 'timezone']
            - Get timezone for all sites
        self['meta', :, ['latitude', 'longitdue']]
            - Get ('latitude', 'longitude') for all sites

        Parameters
        ----------
        ds_slice : tuple of int | list | slice
            Pandas slicing describing which sites and columns to extract

        Returns
        -------
        meta : pandas.Dataframe
            Dataframe of location meta data
        """
        sites = ds_slice[0]
        if isinstance(sites, int):
            sites = slice(sites, sites + 1)

        meta = self._h5['meta'][sites]

        if isinstance(sites, slice):
            if sites.stop:
                sites = list(range(*sites.indices(sites.stop)))
            else:
                sites = list(range(len(meta)))

        meta = pd.DataFrame(meta, index=sites)
        if len(ds_slice) == 2:
            meta = meta[ds_slice[1]]

        return meta

    def _get_SAM_df(self, ds_name, site):
        """
        Placeholder for get_SAM_df method that it resource specific

        Parameters
        ----------
        ds_name : str
            'Dataset' name == SAM
        site : int
            Site to extract SAM DataFrame for
        """

    def _get_ds(self, ds_name, *ds_slice):
        """
        Extract data from given dataset

        Examples
        --------
        self['dni', :, 1]
            - Get 'dni'timeseries for site 1
        self['dni', ::2, :]
            - Get hourly 'dni' timeseries for all sites (NSRDB)
        self['windspeed_100m', :, [1, 3, 5, 7, 9]]
            - Get 'windspeed_100m' timeseries for select sites


        Parameters
        ----------
        ds_name : str
            Variable dataset to be extracted
        ds_slice : tuple of int | list | slice
            tuple describing slice of dataset array to extract

        Returns
        -------
        ds : ndarray
            ndarray of variable timeseries data
            If unscale, returned in native units else in scaled units
        """
        if ds_name not in self.dsets:
            raise HandlerKeyError('{} not in {}'
                                  .format(ds_name, self.dsets))

        ds = self._h5[ds_name]
        out = ds[ds_slice]
        if self._unscale:
            scale_factor = ds.attrs.get(self.SCALE_ATTR, 1)
            out = out.astype('float32')
            out /= scale_factor

        return out

    def close(self):
        """
        Close h5 instance
        """
        self._h5.close()

    @classmethod
    def preload_SAM(cls, h5_file, project_points, **kwargs):
        """
        Placeholder for classmethod that will pre-load project_points for SAM

        Parameters
        ----------
        h5_file : str
            h5_file to extract resource from
        project_points : reV.config.ProjectPoints
            Projects points to be pre-loaded from Resource for SAM
        """


class SolarResource(Resource):
    """
    Class to handle Solar Resource .h5 files
    """
    def _get_SAM_df(self, ds_name, site):
        """
        Get SAM wind resource DataFrame for given site

        Parameters
        ----------
        ds_name : str
            'Dataset' name == SAM
        site : int
            Site to extract SAM DataFrame for

        Returns
        -------
        res_df : pandas.DataFrame
            time-series DataFrame of resource variables needed to run SAM
        """
        if not self._unscale:
            raise HandlerValueError("SAM requires unscaled values")

        res_df = pd.DataFrame(index=self.time_index)
        res_df.name = "{}-{}".format(ds_name, site)
        for var in ['dni', 'dhi', 'wind_speed', 'air_temperature']:
            var_array = self._get_ds(var, slice(None, None, None), site)
            res_df[var] = SAMResource.check_units(var, var_array)

        return res_df

    @classmethod
    def preload_SAM(cls, h5_file, project_points, clearsky=False,
                    **kwargs):
        """
        Placeholder for classmethod that will pre-load project_points for SAM

        Parameters
        ----------
        h5_file : str
            h5_file to extract resource from
        project_points : reV.config.ProjectPoints
            Projects points to be pre-loaded from Resource for SAM
        clearsky : bool
            Boolean flag to pull clearsky instead of real irradiance
        kwargs : dict
            Kwargs to pass to cls

        Returns
        -------
        SAM_res : SAMResource
            Instance of SAMResource pre-loaded with Solar resource for sites
            in project_points
        """
        with cls(h5_file, **kwargs) as res:
            SAM_res = SAMResource(project_points, res['time_index'])
            sites_slice = project_points.sites_as_slice
            SAM_res['meta'] = res['meta', sites_slice]
            for var in SAM_res.var_list:
                ds = var
                if clearsky and var in ['dni', 'dhi']:
                    ds = 'clearsky_{}'.format(var)

                SAM_res[var] = res[ds, :, sites_slice]

        return SAM_res


class NSRDB(SolarResource):
    """
    Class to handle NSRDB .h5 files
    """
    ADD_ATTR = 'psm_add_offset'
    SCALE_ATTR = 'psm_scale_factor'
    UNIT_ATTR = 'psm_units'

    def _get_ds(self, ds_name, *ds_slice):
        """
        Extract data from given dataset

        Examples
        --------
        self['dni', :, 1]
            - Get 'dni'timeseries for site 1
        self['dni', ::2, :]
            - Get hourly 'dni' timeseries for all sites (NSRDB)

        Parameters
        ----------
        ds_name : str
            Variable dataset to be extracted
        ds_slice : tuple of int | list | slice
            tuple describing slice of dataset array to extract

        Returns
        -------
        ds : ndarray
            ndarray of variable timeseries data
            If unscale, returned in native units else in scaled units
        """

        if ds_name not in self.dsets:
            raise HandlerKeyError('{} not in {}'
                                  .format(ds_name, self.dsets))

        ds = self._h5[ds_name]
        out = ds[ds_slice]
        if self._unscale:
            scale_factor = ds.attrs.get(self.SCALE_ATTR, 1)
            adder = ds.attrs.get(self.ADD_ATTR, 0)
            out = out.astype('float32')

            if adder != 0:
                # special scaling for cloud properties
                out *= scale_factor
                out += adder
            else:
                out /= scale_factor

        return out

    @classmethod
    def preload_SAM(cls, h5_file, project_points, clearsky=False,
                    downscale=None, **kwargs):
        """
        Placeholder for classmethod that will pre-load project_points for SAM

        Parameters
        ----------
        h5_file : str
            h5_file to extract resource from
        project_points : reV.config.ProjectPoints
            Projects points to be pre-loaded from Resource for SAM
        clearsky : bool
            Boolean flag to pull clearsky instead of real irradiance
        downscale : NoneType | str
            Option for NSRDB resource downscaling to higher temporal
            resolution. Expects a string in the Pandas frequency format,
            e.g. '5min'.
        kwargs : dict
            Kwargs to pass to cls

        Returns
        -------
        SAM_res : SAMResource
            Instance of SAMResource pre-loaded with Solar resource for sites
            in project_points
        """
        with cls(h5_file, **kwargs) as res:
            SAM_res = SAMResource(project_points, res['time_index'])
            sites_slice = project_points.sites_as_slice
            SAM_res['meta'] = res['meta', sites_slice]

            if not downscale:
                for var in SAM_res.var_list:
                    ds = var
                    if clearsky and var in ['dni', 'dhi']:
                        ds = 'clearsky_{}'.format(var)

                    SAM_res[var] = res[ds, :, sites_slice]
            else:
                # contingent import to avoid dependencies
                from reV.utilities.downscale import downscale_nsrdb
                SAM_res = downscale_nsrdb(SAM_res, res, project_points,
                                          downscale)

        return SAM_res


class WindResource(Resource):
    """
    Class to handle Wind Resource .h5 files
    """
    def __init__(self, h5_file, unscale=True):
        """
        Parameters
        ----------
        h5_file : str
            Path to .h5 resource file
        unscale : bool
            Boolean flag to automatically unscale variables on extraction
        """
        self._heights = None
        super().__init__(h5_file, unscale=unscale)

    @staticmethod
    def _parse_name(ds_name):
        """
        Extract dataset name and height from dataset name

        Parameters
        ----------
        ds_name : str
            Dataset name

        Returns
        -------
        name : str
            Variable name
        h : int | float
            Height of variable
        """
        try:
            name, h = ds_name.split('_')
            h = h.strip('m')
            try:
                h = int(h)
            except ValueError:
                h = float(h)
        except Exception:
            name = ds_name
            h = None

        return name, h

    @property
    def heights(self):
        """
        Extract available heights for pressure, temperature, windspeed, precip,
        and winddirection variables. Used for interpolation/extrapolation.

        Returns
        -------
        self._heights : list
            List of available heights for:
            windspeed, winddirection, temperature, and pressure
        """
        if self._heights is None:
            dsets = list(self._h5)
            heights = {'pressure': [],
                       'temperature': [],
                       'windspeed': [],
                       'winddirection': [],
                       'precipitationrate': []}
            for ds in dsets:
                ds_name, h = self._parse_name(ds)
                if ds_name in heights.keys():
                    heights[ds_name].append(h)

            self._heights = heights

        return self._heights

    @staticmethod
    def get_nearest_h(h, heights):
        """
        Get two nearest h values in heights.
        Determine if h is inside or outside the range of heights
        (requiring extrapolation instead of interpolation)

        Parameters
        ----------
        h : int | float
            Height value of interest
        heights : list
            List of available heights

        Returns
        -------
        nearest_h : list
            list of 1st and 2nd nearest height in heights
        extrapolate : bool
            Flag as to whether h is inside or outside heights range
        """
        if isinstance(heights, (list, tuple)):
            heights = np.array(heights)

        dist = np.abs(heights - h)
        pos = dist.argsort()[:2]
        nearest_h = np.sort(heights[pos])
        extrapolate = np.all(h < heights) or np.all(h > heights)
        if extrapolate:
            h_min, h_max = np.sort(heights)[[0, -1]]
            msg = ('{} is outside the height range'.format(h),
                   '({}, {}).'.format(h_min, h_max),
                   'Extrapolation to be used.')
            warnings.warn(' '.join(msg), ExtrapolationWarning)

        return nearest_h, extrapolate

    @staticmethod
    def power_law_interp(ts_1, h_1, ts_2, h_2, h, mean=True):
        """
        Power-law interpolate/extrapolate time-series data to height h

        Parameters
        ----------
        ts_1 : ndarray
            Time-series array at height h_1
        h_1 : int | float
            Height corresponding to time-seris ts_1
        ts_2 : ndarray
            Time-series array at height h_2
        h_2 : int | float
            Height corresponding to time-seris ts_2
        h : int | float
            Height of desired time-series
        mean : bool
            Calculate average alpha versus point by point alpha

        Returns
        -------
        out : ndarray
            Time-series array at height h
        """
        if h == h_1:
            out = ts_1
        elif h == h_2:
            out = ts_2
        else:
            if h_1 > h_2:
                h_1, h_2 = h_2, h_1
                ts_1, ts_2 = ts_2, ts_1

            if mean:
                alpha = (np.log(ts_2.mean() / ts_1.mean()) /
                         np.log(h_2 / h_1))

                if alpha < 0.06:
                    warnings.warn('Alpha is < 0.06', RuntimeWarning)
                elif alpha > 0.6:
                    warnings.warn('Alpha is > 0.6', RuntimeWarning)
            else:
                # Replace zero values for alpha calculation
                ts_1[ts_1 == 0] = 0.001
                ts_2[ts_2 == 0] = 0.001

                alpha = np.log(ts_2 / ts_1) / np.log(h_2 / h_1)
                # The Hellmann exponent varies from 0.06 to 0.6
                alpha[alpha < 0.06] = 0.06
                alpha[alpha > 0.6] = 0.6

            out = ts_1 * (h / h_1)**alpha

        return out

    @staticmethod
    def linear_interp(ts_1, h_1, ts_2, h_2, h):
        """
        Linear interpolate/extrapolate time-series data to height h

        Parameters
        ----------
        ts_1 : ndarray
            Time-series array at height h_1
        h_1 : int | float
            Height corresponding to time-seris ts_1
        ts_2 : ndarray
            Time-series array at height h_2
        h_2 : int | float
            Height corresponding to time-seris ts_2
        h : int | float
            Height of desired time-series

        Returns
        -------
        out : ndarray
            Time-series array at height h
        """
        if h == h_1:
            out = ts_1
        elif h == h_2:
            out = ts_2
        else:
            if h_1 > h_2:
                h_1, h_2 = h_2, h_1
                ts_1, ts_2 = ts_2, ts_1
            # Calculate slope for every posiiton in variable arrays
            m = (ts_2 - ts_1) / (h_2 - h_1)
            # Calculate intercept for every position in variable arrays
            b = ts_2 - m * h_2

            out = m * h + b

        return out

    @staticmethod
    def shortest_angle(a0, a1):
        """
        Calculate the shortest angle distance between a0 and a1

        Parameters
        ----------
        a0 : int | float
            angle 0 in degrees
        a1 : int | float
            angle 1 in degrees

        Returns
        -------
        da : int | float
            shortest angle distance between a0 and a1
        """
        da = (a1 - a0) % 360
        return 2 * da % 360 - da

    @staticmethod
    def circular_interp(ts_1, h_1, ts_2, h_2, h):
        """
        Circular interpolate/extrapolate time-series data to height h

        Parameters
        ----------
        ts_1 : ndarray
            Time-series array at height h_1
        h_1 : int | float
            Height corresponding to time-seris ts_1
        ts_2 : ndarray
            Time-series array at height h_2
        h_2 : int | float
            Height corresponding to time-seris ts_2
        h : int | float
            Height of desired time-series

        Returns
        -------
        out : ndarray
            Time-series array at height h
        """
        if h == h_1:
            out = ts_1
        elif h == h_2:
            out = ts_2
        else:
            h_f = (h - h_1) / (h_2 - h_1)

            da = WindResource.shortest_angle(ts_1, ts_2) * h_f
            da = np.sign(da) * (np.abs(da) % 360)

            out = (ts_2 + da) % 360

        return out

    def _get_ds(self, ds_name, *ds_slice):
        """
        Extract data from given dataset

        Parameters
        ----------
        ds_name : str
            Variable dataset to be extracted
        ds_slice : tuple of int | list | slice
            tuple describing list ds_slice to extract

        Returns
        -------
        out : ndarray
            ndarray of variable timeseries data
            If unscale, returned in native units else in scaled units
        """
        var_name, h = self._parse_name(ds_name)
        heights = self.heights[var_name]
        if h in heights:
            out = super()._get_ds(ds_name, *ds_slice)
        else:
            (h1, h2), extrapolate = self.get_nearest_h(h, heights)
            ts1 = super()._get_ds('{}_{}m'.format(var_name, h1), *ds_slice)
            ts2 = super()._get_ds('{}_{}m'.format(var_name, h2), *ds_slice)

            if (var_name == 'windspeed') and extrapolate:
                out = self.power_law_interp(ts1, h1, ts2, h2, h)
            elif var_name == 'winddirection':
                out = self.circular_interp(ts1, h1, ts2, h2, h)
            else:
                out = self.linear_interp(ts1, h1, ts2, h2, h)

        return out

    def _get_SAM_df(self, ds_name, site):
        """
        Get SAM wind resource DataFrame for given site

        Parameters
        ----------
        ds_name : str
            'Dataset' name == SAM
        site : int
            Site to extract SAM DataFrame for

        Returns
        -------
        res_df : pandas.DataFrame
            time-series DataFrame of resource variables needed to run SAM
        """
        if not self._unscale:
            raise HandlerValueError("SAM requires unscaled values")

        _, h = self._parse_name(ds_name)
        res_df = pd.DataFrame(index=self.time_index)
        res_df.name = site
        variables = ['pressure', 'temperature', 'winddirection',
                     'windspeed']
        for var in variables:
            var_name = "{}_{}m".format(var, h)
            var_array = self._get_ds(var_name, slice(None, None, None),
                                     site)
            res_df[var_name] = SAMResource.check_units(var_name, var_array)

        return res_df

    @classmethod
    def preload_SAM(cls, h5_file, project_points, require_wind_dir=False,
                    precip_rate=False, **kwargs):
        """
        Placeholder for classmethod that will pre-load project_points for SAM

        Parameters
        ----------
        h5_file : str
            h5_file to extract resource from
        project_points : reV.config.ProjectPoints
            Projects points to be pre-loaded from Resource for SAM
        require_wind_dir : bool
            Boolean flag as to whether wind direction will be loaded from
            WindResource or will be filled with zeros
        precip_rate : bool
            Boolean flag as to whether precipitationrate_0m will be preloaded
        kwargs : dict
            Kwargs to pass to cls

        Returns
        -------
        SAM_res : SAMResource
            Instance of SAMResource pre-loaded with Solar resource for sites
            in project_points
        """
        with cls(h5_file, **kwargs) as res:
            SAM_res = SAMResource(project_points, res['time_index'],
                                  require_wind_dir=require_wind_dir)
            sites_slice = project_points.sites_as_slice
            SAM_res['meta'] = res['meta', sites_slice]
            var_list = SAM_res.var_list
            if not require_wind_dir:
                var_list.remove('winddirection')

            h = project_points.h
            if isinstance(h, (int, float)):
                for var in var_list:
                    ds_name = "{}_{}m".format(var, h)
                    SAM_res[var] = res[ds_name, :, sites_slice]
            else:
                _, unq_idx = np.unique(h, return_inverse=True)
                unq_h = sorted(list(set(h)))

                site_list = np.array(project_points.sites)
                height_slices = {}
                for i, h_i in enumerate(unq_h):
                    pos = np.where(unq_idx == i)[0]
                    height_slices[h_i] = (site_list[pos], pos)

                for var in var_list:
                    for h_i, (h_pos, sam_pos) in height_slices.items():
                        ds_name = '{}_{}m'.format(var, h_i)
                        SAM_res[var, :, sam_pos] = res[ds_name, :, h_pos]

            if precip_rate:
                var = 'precipitationrate'
                ds_name = '{}_0m'.format(var)
                SAM_res.append_var_list(var)
                SAM_res[var] = res[ds_name, :, sites_slice]

        return SAM_res
