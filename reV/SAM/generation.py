# -*- coding: utf-8 -*-
"""reV-to-SAM generation interface module.

Wraps the NREL-PySAM pvwattsv5, windpower, and tcsmolensalt modules with
additional reV features.
"""
import copy
import gc
import os
import logging
import numpy as np
import pandas as pd
from warnings import warn
import PySAM.Pvwattsv5 as pysam_pv
import PySAM.Windpower as pysam_wind
import PySAM.TcsmoltenSalt as pysam_csp

from reV import TESTDATADIR
from reV.handlers.resource import Resource
from reV.utilities.exceptions import SAMInputWarning, SAMExecutionError
from reV.utilities.curtailment import curtail
from reV.utilities.utilities import mean_irrad
from reV.SAM.SAM import SAM
from reV.SAM.econ import LCOE, SingleOwner


logger = logging.getLogger(__name__)


class Generation(SAM):
    """Base class for SAM generation simulations."""

    @staticmethod
    def _get_res_mean(res_file, res_df, output_request):
        """Get the resource annual means.

        Parameters
        ----------
        res_file : str
            Resource file with full path.
        res_df : pd.DataFrame
            2D table with resource data. Available columns must have solar_vars
        output_request : list
            Outputs to retrieve from SAM.

        Returns
        -------
        res_mean : dict
            Dictionary object with variables for resource means.
        out_req_nomeans : list
            Output request list with the resource mean entries removed.
        """

        out_req_nomeans = copy.deepcopy(output_request)
        res_mean = None

        if 'ws_mean' in out_req_nomeans:
            out_req_nomeans.remove('ws_mean')
            res_mean = {}
            res_mean['ws_mean'] = res_df['windspeed'].mean()

        else:
            if 'dni_mean' in out_req_nomeans:
                out_req_nomeans.remove('dni_mean')
                res_mean = {}
                res_mean['dni_mean'] = mean_irrad(res_df['dni'])

            if 'ghi_mean' in out_req_nomeans:
                out_req_nomeans.remove('ghi_mean')
                if res_mean is None:
                    res_mean = {}

                if 'ghi' in res_df:
                    res_mean['ghi_mean'] = mean_irrad(res_df['ghi'])
                else:
                    with Resource(res_file) as res:
                        res_mean['ghi_mean'] = mean_irrad(
                            res['ghi', :, res_df.name])

        return res_mean, out_req_nomeans

    @staticmethod
    def tz_check(parameters, meta):
        """Check timezone input and use json config tz if not in resource meta.

        Parameters
        ----------
        parameters : dict
            SAM model input parameters.
        meta : pd.DataFrame
            1D table with resource meta data.

        Returns
        -------
        meta : pd.DataFrame
            1D table with resource meta data. If meta was not originally set in
            the resource meta data, but was set as "tz" or "timezone" in the
            SAM model input parameters json file, timezone will be added to
            this instance of meta.
        """

        if meta is not None:
            if 'timezone' not in meta:
                if 'tz' in parameters:
                    meta['timezone'] = int(parameters['tz'])
                elif 'timezone' in parameters:
                    meta['timezone'] = int(parameters['timezone'])
                else:
                    msg = ('Need timezone input to run SAM gen. Not found in '
                           'resource meta or technology json input config.')
                    raise SAMExecutionError(msg)
        return meta

    def cf_mean(self):
        """Get mean capacity factor (fractional) from SAM.

        Returns
        -------
        output : float
            Mean capacity factor (fractional).
        """
        return self['capacity_factor'] / 100

    def cf_profile(self):
        """Get hourly capacity factor (frac) profile in orig timezone.

        Returns
        -------
        cf_profile : np.ndarray
            1D numpy array of capacity factor profile.
            Datatype is float32 and array length is 8760*time_interval.
        """
        return self.gen_profile() / self.parameters['system_capacity']

    def annual_energy(self):
        """Get annual energy generation value in kWh from SAM.

        Returns
        -------
        output : float
            Annual energy generation (kWh).
        """
        return self['annual_energy']

    def energy_yield(self):
        """Get annual energy yield value in kwh/kw from SAM.

        Returns
        -------
        output : float
            Annual energy yield (kwh/kw).
        """
        return self['kwh_per_kw']

    def gen_profile(self):
        """Get AC inverter power generation profile (orig timezone) in kW.

        Returns
        -------
        output : np.ndarray
            1D array of hourly AC inverter power generation in kW.
            Datatype is float32 and array length is 8760*time_interval.
        """
        gen = np.array(self['ac'], dtype=np.float32) / 1000
        # Roll back to native timezone if resource meta has a timezone
        if self._meta is not None:
            if 'timezone' in self.meta:
                gen = np.roll(gen, -1 * int(self.meta['timezone']
                                            * self.time_interval))
        return gen

    def poa(self):
        """Get plane-of-array irradiance profile (orig timezone) in W/m2.

        Returns
        -------
        output : np.ndarray
            1D array of plane-of-array irradiance in W/m2.
            Datatype is float32 and array length is 8760*time_interval.
        """
        poa = np.array(self['poa'], dtype=np.float32)
        # Roll back to native timezone if resource meta has a timezone
        if self._meta is not None:
            if 'timezone' in self.meta:
                poa = np.roll(poa, -1 * int(self.meta['timezone']
                                            * self.time_interval))
        return poa

    def collect_outputs(self):
        """Collect SAM gen output_request."""

        output_lookup = {'cf_mean': self.cf_mean,
                         'cf_profile': self.cf_profile,
                         'annual_energy': self.annual_energy,
                         'energy_yield': self.energy_yield,
                         'gen_profile': self.gen_profile,
                         'poa': self.poa,
                         }

        super().collect_outputs(output_lookup)

    def _gen_exec(self):
        """Run SAM generation with possibility for follow on econ analysis."""

        lcoe_out_req = None
        so_out_req = None
        if 'lcoe_fcr' in self.output_request:
            lcoe_out_req = self.output_request.pop(
                self.output_request.index('lcoe_fcr'))
        elif 'ppa_price' in self.output_request:
            so_out_req = self.output_request.pop(
                self.output_request.index('ppa_price'))

        self.assign_inputs()
        self.execute()
        self.collect_outputs()

        if lcoe_out_req is not None:
            self.parameters['annual_energy'] = self.annual_energy()
            lcoe = LCOE(self.parameters, output_request=(lcoe_out_req,))
            lcoe.assign_inputs()
            lcoe.execute()
            lcoe.collect_outputs()
            self.outputs.update(lcoe.outputs)

        elif so_out_req is not None:
            self.parameters['gen'] = self.gen_profile()
            so = SingleOwner(self.parameters, output_request=(so_out_req,))
            so.assign_inputs()
            so.execute()
            so.collect_outputs()
            self.outputs.update(so.outputs)

    @classmethod
    def reV_run(cls, points_control, res_file, output_request=('cf_mean',),
                downscale=None):
        """Execute SAM generation based on a reV points control instance.

        Parameters
        ----------
        points_control : config.PointsControl
            PointsControl instance containing project points site and SAM
            config info.
        res_file : str
            Resource file with full path.
        output_request : list | tuple
            Outputs to retrieve from SAM.
        downscale : NoneType | str
            Option for NSRDB resource downscaling to higher temporal
            resolution. Expects a string in the Pandas frequency format,
            e.g. '5min'.

        Returns
        -------
        out : dict
            Nested dictionaries where the top level key is the site index,
            the second level key is the variable name, second level value is
            the output variable value.
        """

        # initialize output dictionary
        out = {}

        # Get the SAM resource object
        resources = SAM.get_sam_res(res_file,
                                    points_control.project_points,
                                    points_control.project_points.tech,
                                    downscale=downscale)

        # run resource through curtailment filter if applicable
        curtailment = points_control.project_points.curtailment
        if curtailment is not None:
            resources = curtail(resources, curtailment)

        # Use resource object iterator
        for res_df, meta in resources:

            # get SAM inputs from project_points based on the current site
            site = res_df.name
            _, inputs = points_control.project_points[site]

            res_mean, out_req_nomeans = cls._get_res_mean(res_file, res_df,
                                                          output_request)

            # iterate through requested sites.
            sim = cls(resource=res_df, meta=meta, parameters=inputs,
                      output_request=out_req_nomeans)
            sim._gen_exec()

            # collect outputs to dictout
            out[site] = sim.outputs

            if res_mean is not None:
                out[site].update(res_mean)

            del res_df, meta, sim

        del resources
        gc.collect()
        return out


class Solar(Generation):
    """Base Class for Solar generation from SAM
    """

    def __init__(self, resource=None, meta=None, parameters=None,
                 output_request=None, drop_leap=False):
        """Initialize a SAM solar object.

        Parameters
        ----------
        resource : pd.DataFrame
            2D table with resource data. Available columns must have solar_vars
        meta : pd.DataFrame
            1D table with resource meta data.
        parameters : dict or ParametersManager()
            SAM model input parameters.
        output_request : list
            Requested SAM outputs (e.g., 'cf_mean', 'annual_energy',
            'cf_profile', 'gen_profile', 'energy_yield', 'ppa_price',
            'lcoe_fcr').
        drop_leap : bool
            Drops February 29th from the resource data.
        """

        # drop the leap day
        if drop_leap:
            resource = self.drop_leap(resource)

        parameters = self.set_latitude_tilt_az(parameters, meta)
        meta = self.tz_check(parameters, meta)

        # don't pass resource to base class, set in set_nsrdb instead.
        super().__init__(meta, parameters, output_request)

        # Set the site number using resource
        if isinstance(resource, pd.DataFrame):
            self._site = resource.name
        else:
            self._site = None

        if resource is not None and meta is not None:
            self.set_nsrdb(resource)

    def set_latitude_tilt_az(self, parameters, meta):
        """Check if tilt is specified as latitude and set tilt=lat, az=180 or 0

        Parameters
        ----------
        parameters : dict
            SAM model input parameters.
        meta : pd.DataFrame
            1D table with resource meta data.

        Returns
        -------
        parameters : dict
            SAM model input parameters. If for a pv simulation the "tilt"
            parameter was originally not present or set to 'lat' or 'latitude',
            the tilt will be set to the absolute value of the latitude found
            in meta and the azimuth will be 180 if lat>0, 0 if lat<0.
        """

        set_tilt = False
        if 'pv' in self.MODULE:
            if parameters is not None and meta is not None:
                if 'tilt' not in parameters:
                    warn('No tilt specified, setting at latitude.',
                         SAMInputWarning)
                    set_tilt = True
                else:
                    if (parameters['tilt'] == 'lat'
                            or parameters['tilt'] == 'latitude'):
                        set_tilt = True

        if set_tilt:
            # set tilt to abs(latitude)
            parameters['tilt'] = np.abs(meta['latitude'])
            if meta['latitude'] > 0:
                # above the equator, az = 180
                parameters['azimuth'] = 180
            else:
                # below the equator, az = 0
                parameters['azimuth'] = 0
            logger.debug('Tilt specified at "latitude", setting tilt to: {}, '
                         'azimuth to: {}'
                         .format(parameters['tilt'], parameters['azimuth']))
        return parameters

    def set_nsrdb(self, resource):
        """Set NSRDB resource data arrays.

        Parameters
        ----------
        resource : pd.DataFrame
            2D table with resource data. Available columns must have var_list.
        """
        time_index = resource.index
        self.time_interval = self.get_time_interval(resource.index.values)

        # map resource data names to SAM required data names
        var_map = {'dni': 'dn',
                   'dhi': 'df',
                   'ghi': 'gh',
                   'clearsky_dni': 'dn',
                   'clearsky_dhi': 'df',
                   'clearsky_ghi': 'gh',
                   'wind_speed': 'wspd',
                   'air_temperature': 'tdry',
                   'dew_point': 'tdew',
                   'surface_pressure': 'pres',
                   }

        irrad_vars = ['dn', 'df', 'gh']

        resource = resource.rename(mapper=var_map, axis='columns')
        resource = {k: np.array(v) for (k, v) in
                    resource.to_dict(orient='list').items()}

        # set resource variables
        for var, arr in resource.items():
            if var != 'time_index':

                # ensure that resource array length is multiple of 8760
                arr = np.roll(
                    self.ensure_res_len(arr),
                    int(self._meta['timezone'] * self.time_interval))

                if var in irrad_vars:
                    if np.min(arr) < 0:
                        warn('Solar irradiance variable "{}" has a minimum '
                             'value of {}. Truncating to zero.'
                             .format(var, np.min(arr)), SAMInputWarning)
                        arr = np.where(arr < 0, 0, arr)

                resource[var] = arr.tolist()

        resource['lat'] = self.meta['latitude']
        resource['lon'] = self.meta['longitude']
        resource['tz'] = self.meta['timezone']

        resource['minute'] = self.ensure_res_len(time_index.minute)
        resource['hour'] = self.ensure_res_len(time_index.hour)
        resource['year'] = self.ensure_res_len(time_index.year)
        resource['month'] = self.ensure_res_len(time_index.month)
        resource['day'] = self.ensure_res_len(time_index.day)

        self['solar_resource_data'] = resource


class PV(Solar):
    """Photovoltaic (PV) generation with pvwattsv5.
    """
    MODULE = 'pvwattsv5'
    PYSAM = pysam_pv

    def __init__(self, resource=None, meta=None, parameters=None,
                 output_request=None):
        """Initialize a SAM solar PV object.

        Parameters
        ----------
        resource : pd.DataFrame
            2D table with resource data. Available columns must have solar_vars
        meta : pd.DataFrame
            1D table with resource meta data.
        parameters : dict or ParametersManager()
            SAM model input parameters.
        output_request : list
            Requested SAM outputs (e.g., 'cf_mean', 'annual_energy',
            'cf_profile', 'gen_profile', 'energy_yield', 'ppa_price',
            'lcoe_fcr').
        """
        super().__init__(resource=resource, meta=meta, parameters=parameters,
                         output_request=output_request)

    @property
    def default(self):
        """Get the executed default pysam PVWATTS object.

        Returns
        -------
        _default : PySAM.Pvwattsv5
            Executed pvwatts pysam object.
        """
        if self._default is None:
            res_file = os.path.join(
                TESTDATADIR,
                'SAM/USA AZ Phoenix Sky Harbor Intl Ap (TMY3).csv')
            self._default = pysam_pv.default('PVWattsNone')
            self._default.LocationAndResource.solar_resource_file = res_file
            self._default.execute()
        return self._default


class CSP(Solar):
    """Concentrated Solar Power (CSP) generation
    """
    MODULE = 'tcsmolten_salt'
    PYSAM = pysam_csp

    def __init__(self, resource=None, meta=None, parameters=None,
                 output_request=None):
        """Initialize a SAM concentrated solar power (CSP) object.
        """
        super().__init__(resource=resource, meta=meta, parameters=parameters,
                         output_request=output_request)

    @property
    def default(self):
        """Get the executed default pysam CSP object.

        Returns
        -------
        _default : PySAM.TcsmoltenSalt
            Executed TcsmoltenSalt pysam object.
        """
        if self._default is None:
            res_file = os.path.join(
                TESTDATADIR,
                'SAM/USA AZ Phoenix Sky Harbor Intl Ap (TMY3).csv')
            self._default = pysam_csp.default('MSPTSingleOwner')
            self._default.LocationAndResource.solar_resource_file = res_file
            self._default.execute()
        return self._default


class Wind(Generation):
    """Base class for Wind generation from SAM
    """
    MODULE = 'windpower'
    PYSAM = pysam_wind

    def __init__(self, resource=None, meta=None, parameters=None,
                 output_request=None, drop_leap=False):
        """Initialize a SAM wind object.

        Parameters
        ----------
        resource : pd.DataFrame
            2D table with resource data. Available columns must have wind_vars
        meta : pd.DataFrame
            1D table with resource meta data.
        parameters : dict
            SAM model input parameters.
        output_request : list
            Requested SAM outputs (e.g., 'cf_mean', 'annual_energy',
            'cf_profile', 'gen_profile', 'energy_yield', 'ppa_price',
            'lcoe_fcr').
        drop_leap : bool
            Drops February 29th from the resource data.
        """

        # drop the leap day
        if drop_leap:
            resource = self.drop_leap(resource)

        meta = self.tz_check(parameters, meta)

        # don't pass resource to base class, set in set_wtk instead.
        super().__init__(meta, parameters, output_request)

        # Set the site number using resource
        if isinstance(resource, pd.DataFrame):
            self._site = resource.name
        else:
            self._site = None

        if resource is not None and meta is not None:
            self.set_wtk(resource)

    def gen_profile(self):
        """Get AC inverter power generation profile (orig timezone) in kW.

        Returns
        -------
        output : np.ndarray
            1D array of hourly AC inverter power generation in kW.
            Datatype is float32 and array length is 8760*time_interval.
        """
        gen = np.array(self['gen'], dtype=np.float32)
        # Roll back to native timezone if resource meta has a timezone
        if self._meta is not None:
            if 'timezone' in self.meta:
                gen = np.roll(gen, -1 * int(self.meta['timezone']
                                            * self.time_interval))
        return gen

    def set_wtk(self, resource):
        """Set WTK resource data arrays.

        Parameters
        ----------
        resource : pd.DataFrame
            2D table with resource data. Available columns must have var_list.
        """

        data_dict = {}
        var_list = ['temperature', 'pressure', 'windspeed', 'winddirection']
        time_index = resource.index
        self.time_interval = self.get_time_interval(resource.index.values)

        data_dict['fields'] = [1, 2, 3, 4]
        data_dict['heights'] = 4 * [self.parameters['wind_turbine_hub_ht']]

        if 'rh' in resource:
            # set relative humidity for icing.
            rh = np.roll(self.ensure_res_len(resource['rh'].values),
                         int(self.meta['timezone'] * self.time_interval),
                         axis=0)
            data_dict['rh'] = rh.tolist()

        # must be set as matrix in [temperature, pres, speed, direction] order
        # ensure that resource array length is multiple of 8760
        # roll the truncated resource array to local timezone
        temp = np.roll(self.ensure_res_len(resource[var_list].values),
                       int(self.meta['timezone'] * self.time_interval), axis=0)
        data_dict['data'] = temp.tolist()

        resource['lat'] = self.meta['latitude']
        resource['lon'] = self.meta['longitude']
        resource['tz'] = self.meta['timezone']
        resource['elev'] = self.meta['elevation']

        data_dict['minute'] = self.ensure_res_len(time_index.minute)
        data_dict['hour'] = self.ensure_res_len(time_index.hour)
        data_dict['year'] = self.ensure_res_len(time_index.year)
        data_dict['month'] = self.ensure_res_len(time_index.month)
        data_dict['day'] = self.ensure_res_len(time_index.day)

        # add resource data to self.data and clear
        self['wind_resource_data'] = data_dict

    @property
    def default(self):
        """Get the executed default pysam WindPower object.

        Returns
        -------
        _default : PySAM.Windpower
            Executed Windpower pysam object.
        """
        if self._default is None:
            res_file = os.path.join(
                TESTDATADIR, 'SAM/WY Southern-Flat Lands.csv')
            self._default = pysam_wind.default('WindPowerNone')
            self._default.WindResourceFile.wind_resource_filename = res_file
            self._default.execute()
        return self._default


class LandBasedWind(Wind):
    """Onshore wind generation
    """

    def __init__(self, resource=None, meta=None, parameters=None,
                 output_request=None):
        """Initialize a SAM land based wind object.
        """
        super().__init__(resource=resource, meta=meta, parameters=parameters,
                         output_request=output_request)


class OffshoreWind(LandBasedWind):
    """Offshore wind generation
    """

    def __init__(self, resource=None, meta=None, parameters=None,
                 output_request=None):
        """Initialize a SAM offshore wind object.
        """
        super().__init__(resource=resource, meta=meta, parameters=parameters,
                         output_request=output_request)
