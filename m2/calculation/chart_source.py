"""Owner-qualified immutable natal loading shared by distinct techniques."""
import swisseph as swe

from m2.calculation.ephemeris import ephemeris
from m2.charts import Charts


class NatalChartSource:
    def __init__(self, store):
        self.charts = Charts(store)

    def selected_natal(self, session, chart_id):
        """Validate one immutable natal version against its source and engine."""
        chart = self.charts.get_chart(session, chart_id)
        if chart['source_status'] != 'current':
            return chart, None, 'unsupported_stale_birth_source'
        natal = chart['result'].get('natal')
        if not natal or natal['status'] not in ('complete', 'partial_unsupported_houses'):
            return chart, None, 'unsupported_uncertain_birth_time_or_non_natal_chart'
        if chart['engine_version'] != swe.version or natal['ephemeris_sha256'] != ephemeris(
                include_chiron=chart['result']['profile']['settings'].get('include_chiron', False)):
            raise ValueError('Natal and transit engine/data versions differ')
        return chart, natal, None
