from flask import Blueprint, render_template, url_for, request, g


from sfa_dash.api_interface import (users, observations, forecasts,
                                    cdf_forecasts, cdf_forecast_groups,
                                    outages)
from sfa_dash.blueprints.aggregates import AggregatesView, AggregateView
from sfa_dash.blueprints.base import BaseView
from sfa_dash.blueprints.dash import DataDashView
from sfa_dash.blueprints.data_listing import DataListingView
from sfa_dash.blueprints.delete import DeleteConfirmation
from sfa_dash.blueprints.reports import (ReportsView, ReportView,
                                         ReportOutageView,
                                         DeleteReportView,
                                         DownloadReportView)
from sfa_dash.blueprints.sites import SingleSiteView, SitesListingView
from sfa_dash.blueprints.util import download_timeseries
from sfa_dash.errors import DataRequestException
from sfa_dash.filters import human_friendly_datatype


class SingleObjectView(DataDashView):
    """View for a single data object of type observation, forecast
    or cdf_forecast.
    """
    template = 'data/asset.html'

    def __init__(self, data_type):
        """Configures instance variables of the view based on data type. See
        the Notes section for a description of instance variables.

        Parameters
        ----------
        data_type: str
            The singular name of the type of data to be displayed.
            e.g. 'observation'.
            The `data_type` can be configured when registering a url rule,
                e.g.
                <blueprint>.add_url_rule(
                    SingleObjectView.as_view('observations',
                                             data_type='observation'))
                Examples can be found at the bottom of this file.

        Raises
        ------
        ValueError
            If an unconfigured data_type is passed.

        Notes
        -----
        instance variables
            data_type: str
                The type of data to be displayed by the view.

            metadata_template: str
                The path to the template in `sfa_dash/templates/data/metadata`
                used for rendering the object's metadata.
            id_key: str
                The key used to reference the object's uuid. For example,
                observations have an id_key of 'observation_id'.
            plot_type: str
                The type of plot to insert. This is passed as the `type_` param
                to the `sfa_dash.blueprints.utils.timeseries_adapter` function.
                See also `sfa_dash.blueprints.base.insert_plot`.
            human_label: str
                The common name of the solar forecast arbiter name. See
                `sfa_dash.filters.data_type_mapping`.
        """
        self.data_type = data_type
        if data_type == 'forecast':
            self.api_handle = forecasts
            self.metadata_template = 'data/metadata/forecast_metadata.html'
            self.id_key = 'forecast_id'
            self.plot_type = 'forecast'
        elif data_type == 'cdf_forecast':
            self.api_handle = cdf_forecasts
            self.metadata_template = 'data/metadata/cdf_forecast_metadata.html'
            self.id_key = 'forecast_id'
            self.plot_type = 'forecast'
        elif data_type == 'observation':
            self.api_handle = observations
            self.metadata_template = 'data/metadata/observation_metadata.html'
            self.id_key = 'observation_id'
            self.plot_type = 'observation'
        else:
            raise ValueError('Invalid data_type.')
        self.human_label = human_friendly_datatype(self.data_type)

    def get_breadcrumb(self):
        """See BaseView.get_breadcrumb.
        """
        breadcrumb = []
        if self.data_type == 'cdf_forecast':
            listing_view = 'cdf_forecast_groups'
        else:
            listing_view = f'{self.data_type}s'
        # Insert site/aggregate link if available
        if self.metadata.get('site') is not None:
            breadcrumb.append(('Sites', url_for('data_dashboard.sites')))
            breadcrumb.append(
                (self.metadata['site']['name'],
                 url_for(
                     'data_dashboard.site_view',
                     uuid=self.metadata['site_id']))
            )
            breadcrumb.append(
                (f'{self.human_label}s',
                 url_for(
                     f'data_dashboard.{listing_view}',
                     site_id=self.metadata['site_id']))
            )
        elif self.metadata.get('aggregate') is not None:
            breadcrumb.append(
                ('Aggregates',
                 url_for('data_dashboard.aggregates'))
            )
            breadcrumb.append(
                (self.metadata['aggregate']['name'],
                 url_for(
                    'data_dashboard.aggregate_view',
                    uuid=self.metadata['aggregate_id']))
            )
            breadcrumb.append(
                (f'{self.human_label}s',
                 url_for(
                     f'data_dashboard.{listing_view}',
                     aggregate_id=self.metadata['aggregate_id']))
            )
        else:
            breadcrumb.append(
                (f'{self.human_label}s',
                 url_for(
                     f'data_dashboard.{listing_view}'))
            )
        # Insert a parent link for cdf_forecasts
        if self.data_type == 'cdf_forecast':
            breadcrumb.append(
                (self.metadata['name'],
                 url_for(
                     f'data_dashboard.cdf_forecast_group_view',
                     uuid=self.metadata['parent']))
            )
            breadcrumb.append(
                (self.metadata['constant_value'],
                 url_for(
                     f'data_dashboard.{self.data_type}_view',
                     uuid=self.metadata[self.id_key]))
            )
        else:
            breadcrumb.append(
                (self.metadata['name'],
                 url_for(
                     f'data_dashboard.{self.data_type}_view',
                     uuid=self.metadata[self.id_key]))
            )
        return breadcrumb

    def set_template_args(self, uuid, **kwargs):
        """Insert necessary template arguments. See data/asset.html in the
        template folder for how these are layed out.
        """
        self.template_args = {}
        self.set_timerange()
        start, end = self.parse_start_end_from_querystring()
        try:
            self.set_site_or_aggregate_metadata()
        except DataRequestException:
            self.template_args.update({'plot': None})
        else:
            self.insert_plot(uuid, start, end)
        finally:
            self.set_site_or_aggregate_link()
        self.template_args['current_path'] = request.path
        self.template_args['subnav'] = self.format_subnav(**kwargs)
        self.template_args['breadcrumb'] = self.breadcrumb_html(
            self.get_breadcrumb())
        self.template_args['metadata_block'] = render_template(
            self.metadata_template,
            **self.metadata)
        self.template_args['metadata'] = self.safe_metadata()
        self.template_args['uuid'] = self.metadata[self.id_key]
        self.template_args['upload_link'] = url_for(
            f'forms.upload_{self.data_type}_data',
            uuid=self.metadata[self.id_key])

        if self.data_type != 'cdf_forecast':
            self.template_args['update_link'] = url_for(
                f'forms.update_{self.data_type}',
                uuid=self.metadata[self.id_key])

            self.template_args['delete_link'] = url_for(
                f'data_dashboard.delete_{self.data_type}',
                uuid=self.metadata[self.id_key])
        else:
            # update allowed actions based on parent cdf_forecast_group
            allowed = users.actions_on(self.metadata['parent'])
            g.allowed_actions = allowed['actions']

        self.template_args['start'] = start.isoformat()
        self.template_args['end'] = end.isoformat()

        self.template_args['data_type'] = self.data_type
        self.template_args.update(kwargs)

    def get(self, uuid, **kwargs):
        # Attempt a request for the object's metadata. On an error,
        # inject the errors into the template arguments and skip
        # any further processing.
        try:
            self.metadata = self.api_handle.get_metadata(uuid)
        except DataRequestException as e:
            return render_template(self.template, errors=e.errors)
        else:
            self.set_template_args(uuid, **kwargs)
        return render_template(self.template, **self.template_args)

    def post(self, uuid):
        """Data download endpoint.
        """
        try:
            data_response = download_timeseries(self, uuid)
        except DataRequestException as e:
            self.flash_api_errors(e)
            return self.get(uuid)
        else:
            return data_response


class SingleCDFForecastGroupView(SingleObjectView):
    template = 'data/cdf_forecast.html'
    metadata_template = 'data/metadata/cdf_forecast_group_metadata.html'
    human_label = human_friendly_datatype('cdf_forecast')
    api_handle = cdf_forecast_groups
    plot_type = 'probabilistic_forecast'

    def __init__(self):
        pass

    def get_breadcrumb(self, **kwargs):
        """See BaseView.get_breadcrumb.
        """
        breadcrumb = []
        if self.metadata.get('site') is not None:
            # If the site is accessible, add /sites/<site name>
            # to the breadcrumb.
            breadcrumb.append(('Sites', url_for('data_dashboard.sites')))
            breadcrumb.append(
                (self.metadata['site']['name'],
                 url_for(
                     'data_dashboard.site_view',
                     uuid=self.metadata['site_id']))
            )
            breadcrumb.append(
                (f'{self.human_label}s',
                 url_for(
                     'data_dashboard.cdf_forecast_groups',
                     site_id=self.metadata['site_id']))
            )
        elif self.metadata.get('aggregate') is not None:
            breadcrumb.append(
                ('Aggregates', url_for('data_dashboard.aggregates'))
            )
            breadcrumb.append(
                (self.metadata['aggregate']['name'],
                 url_for(
                     'data_dashboard.aggregate_view',
                     uuid=self.metadata['aggregate_id']))
            )
            breadcrumb.append(
                (f'{self.human_label}s',
                 url_for(
                     f'data_dashboard.cdf_forecast_groups',
                     aggregate_id=self.metadata['aggregate_id']))
            )
        else:
            breadcrumb.append(
                (f'{self.human_label}s',
                 url_for('data_dashboard.cdf_forecast_groups'))
            )
        breadcrumb.append(
            (self.metadata['name'],
             url_for(
                 'data_dashboard.cdf_forecast_group_view',
                 uuid=self.metadata['forecast_id']))
        )
        return breadcrumb

    def set_template_args(self, **kwargs):
        """Insert necessary template arguments. See data/asset.html in the
        template folder for how these are layed out.
        """
        self.template_args = {}
        self.set_timerange()
        start, end = self.parse_start_end_from_querystring()
        try:
            self.set_site_or_aggregate_metadata()
        except DataRequestException:
            self.template_args.update({'plot': None})
        else:
            self.insert_plot(self.metadata['forecast_id'], start, end)
        finally:
            self.set_site_or_aggregate_link()
        self.template_args['current_path'] = request.path
        self.template_args['subnav'] = self.format_subnav(**kwargs)
        self.template_args['breadcrumb'] = self.breadcrumb_html(
            self.get_breadcrumb())
        self.template_args['metadata_block'] = render_template(
            self.metadata_template,
            **self.metadata)
        self.template_args['metadata'] = self.safe_metadata()
        constant_values = self.metadata['constant_values']
        self.template_args['constant_values'] = constant_values
        self.template_args['delete_link'] = url_for(
            f'data_dashboard.delete_cdf_forecast_group',
            uuid=self.metadata['forecast_id'])
        self.template_args['update_link'] = url_for(
            f'forms.update_cdf_forecast_group',
            uuid=self.metadata['forecast_id'])

        self.template_args['start'] = start.isoformat()
        self.template_args['end'] = end.isoformat()

    def get(self, uuid, **kwargs):
        try:
            self.metadata = cdf_forecast_groups.get_metadata(uuid)
        except DataRequestException as e:
            return render_template(self.template, errors=e.errors)
        else:
            self.set_template_args()
        return render_template(self.template, **self.template_args)


class SystemOutageView(BaseView):
    template = "outages.html"

    def set_template_args(self):
        self.template_args = {}
        try:
            system_outages = outages.list_outages()
        except DataRequestException as e:
            self.template_args['errors'] = e.errors
        else:
            self.template_args['outages'] = system_outages


class AccessView(DataDashView):
    template = 'data/access.html'


class TrialsView(DataDashView):
    template = 'data/trials.html'


# Url Rule Registration
# The url rules here are broken into sections based on their function.
# For instance, all views that display a tabulated listing of metadata
# are grouped under 'Listing pages'. The view names for each section
# follow a pattern that you should follow when adding new views. The
# patterns help to ensure predictable arguments when calling the
# built-in flask url_for() function.
data_dash_blp = Blueprint('data_dashboard', 'data_dashboard')

# Listing pages
# view name pattern: '<data_type>s'
data_dash_blp.add_url_rule(
    '/sites/',
    view_func=SitesListingView.as_view('sites'))
data_dash_blp.add_url_rule(
    '/observations/',
    view_func=DataListingView.as_view('observations', data_type='observation'))
data_dash_blp.add_url_rule(
    '/forecasts/single/',
    view_func=DataListingView.as_view('forecasts', data_type='forecast'))
data_dash_blp.add_url_rule(
    '/forecasts/cdf/',
    view_func=DataListingView.as_view('cdf_forecast_groups',
                                      data_type='cdf_forecast_group'))
data_dash_blp.add_url_rule(
    '/reports/',
    view_func=ReportsView.as_view('reports'))
data_dash_blp.add_url_rule(
    '/aggregates/',
    view_func=AggregatesView.as_view('aggregates'))

# Views for a single piece of metadata
# view name pattern: '<data_type>_view'
data_dash_blp.add_url_rule(
    '/sites/<uuid>/',
    view_func=SingleSiteView.as_view('site_view'))
data_dash_blp.add_url_rule(
    '/observations/<uuid>',
    view_func=SingleObjectView.as_view(
        'observation_view', data_type='observation'))
data_dash_blp.add_url_rule(
    '/forecasts/single/<uuid>',
    view_func=SingleObjectView.as_view(
        'forecast_view', data_type='forecast'))
data_dash_blp.add_url_rule(
    '/forecasts/cdf/single/<uuid>',
    view_func=SingleObjectView.as_view(
        'cdf_forecast_view', data_type='cdf_forecast'))
data_dash_blp.add_url_rule(
    '/forecasts/cdf/<uuid>',
    view_func=SingleCDFForecastGroupView.as_view('cdf_forecast_group_view'))
data_dash_blp.add_url_rule(
    '/reports/<uuid>',
    view_func=ReportView.as_view('report_view'))
data_dash_blp.add_url_rule(
    '/aggregates/<uuid>',
    view_func=AggregateView.as_view('aggregate_view'))


# Download forms
data_dash_blp.add_url_rule(
    '/reports/<uuid>/download/html',
    view_func=DownloadReportView.as_view(
        'download_report_html', format_='html'))
data_dash_blp.add_url_rule(
    '/reports/<uuid>/download/pdf',
    view_func=DownloadReportView.as_view(
        'download_report_pdf', format_='pdf'))


# Deletion forms
# View name pattern: 'delete_<data_type>'
data_dash_blp.add_url_rule(
    '/sites/<uuid>/delete',
    view_func=DeleteConfirmation.as_view('delete_site', data_type='site'))
data_dash_blp.add_url_rule(
    '/observations/<uuid>/delete',
    view_func=DeleteConfirmation.as_view(
        'delete_observation', data_type='observation'))
data_dash_blp.add_url_rule(
    '/forecasts/single/<uuid>/delete',
    view_func=DeleteConfirmation.as_view(
        'delete_forecast', data_type='forecast'))
data_dash_blp.add_url_rule(
    '/forecasts/cdf/<uuid>/delete',
    view_func=DeleteConfirmation.as_view(
        'delete_cdf_forecast_group', data_type='cdf_forecast_group'))
data_dash_blp.add_url_rule(
    '/reports/<uuid>/delete',
    view_func=DeleteReportView.as_view('delete_report'))
data_dash_blp.add_url_rule(
    '/aggregates/<uuid>/delete',
    view_func=DeleteConfirmation.as_view(
        'delete_aggregate', data_type='aggregate'))

# Outage information
data_dash_blp.add_url_rule(
    '/outages',
    view_func=SystemOutageView.as_view('outages'))

data_dash_blp.add_url_rule(
    '/reports/<uuid>/outages',
    view_func=ReportOutageView.as_view('report_outage_view'))
