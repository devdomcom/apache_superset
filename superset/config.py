# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""The main config file for Superset

All configuration in this file can be overridden by providing a superset_config
in your PYTHONPATH as there is a ``from superset_config import *``
at the end of this file.
"""

# mypy: ignore-errors
# pylint: disable=too-many-lines
from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
from collections import OrderedDict
from contextlib import contextmanager
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from importlib.resources import files
from typing import Any, Callable, Iterator, Literal, TYPE_CHECKING, TypedDict

import click
from celery.schedules import crontab
from flask import Blueprint
from flask_appbuilder.security.manager import AUTH_DB
from flask_caching.backends.base import BaseCache
from pandas import Series
from pandas._libs.parsers import STR_NA_VALUES
from sqlalchemy.engine.url import URL
from sqlalchemy.orm.query import Query

from superset.advanced_data_type.plugins.internet_address import internet_address
from superset.advanced_data_type.plugins.internet_port import internet_port
from superset.advanced_data_type.types import AdvancedDataType
from superset.constants import CHANGE_ME_SECRET_KEY
from superset.jinja_context import BaseTemplateProcessor
from superset.key_value.types import JsonKeyValueCodec
from superset.stats_logger import DummyStatsLogger
from superset.superset_typing import CacheConfig
from superset.tasks.types import ExecutorType
from superset.themes.types import Theme
from superset.utils import core as utils
from superset.utils.core import NO_TIME_RANGE, parse_boolean_string, QuerySource
from superset.utils.encrypt import SQLAlchemyUtilsAdapter
from superset.utils.log import DBEventLogger
from superset.utils.logging_configurator import DefaultLoggingConfigurator

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from flask_appbuilder.security.sqla import models
    from sqlglot import Dialect, Dialects  # pylint: disable=disallowed-sql-import

    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    DialectExtensions = dict[str, Dialects | type[Dialect]]

# Realtime stats logger, a StatsD implementation exists
STATS_LOGGER = DummyStatsLogger()

# By default will log events to the metadata database with `DBEventLogger`
# Note that you can use `StdOutEventLogger` for debugging
# Note that you can write your own event logger by extending `AbstractEventLogger`
# https://github.com/apache/superset/blob/master/superset/utils/log.py
EVENT_LOGGER = DBEventLogger()

SUPERSET_LOG_VIEW = True

# This config is used to enable/disable the folowing security menu items:
# List Users, List Roles, List Groups
SUPERSET_SECURITY_VIEW_MENU = True

BASE_DIR = str(files("superset"))
if "SUPERSET_HOME" in os.environ:
    DATA_DIR = os.environ["SUPERSET_HOME"]
else:
    DATA_DIR = os.path.expanduser("~/.superset")

# ---------------------------------------------------------
# Superset specific config
# ---------------------------------------------------------
VERSION_INFO_FILE = str(files("superset") / "static/version_info.json")
PACKAGE_JSON_FILE = str(files("superset") / "static/assets/package.json")


# Multiple favicons can be specified here. The "href" property
# is mandatory, but "sizes," "type," and "rel" are optional.
# For example:
# {
#     "href":path/to/image.png",
#     "sizes": "16x16",
#     "type": "image/png"
#     "rel": "icon"
# },
FAVICONS = [{"href": "/static/assets/images/favicon.png"}]


def _try_json_readversion(filepath: str) -> str | None:
    try:
        with open(filepath) as f:
            return json.load(f).get("version")
    except Exception:  # pylint: disable=broad-except
        return None


def _try_json_readsha(filepath: str, length: int) -> str | None:
    try:
        with open(filepath) as f:
            return json.load(f).get("GIT_SHA")[:length]
    except Exception:  # pylint: disable=broad-except
        return None


#
# If True, we will skip the call to load the logger config found in alembic.init
#
ALEMBIC_SKIP_LOG_CONFIG = False

# Depending on the context in which this config is loaded, the
# version_info.json file may or may not be available, as it is
# generated on install via setup.py. In the event that we're
# actually running Superset, we will have already installed,
# therefore it WILL exist. When unit tests are running, however,
# it WILL NOT exist, so we fall back on reading package.json
VERSION_STRING = _try_json_readversion(VERSION_INFO_FILE) or _try_json_readversion(
    PACKAGE_JSON_FILE
)

VERSION_SHA_LENGTH = 8
VERSION_SHA = _try_json_readsha(VERSION_INFO_FILE, VERSION_SHA_LENGTH)

# Build number is shown in the About section if available. This
# can be replaced at build time to expose build information.
BUILD_NUMBER = None

# default viz used in chart explorer & SQL Lab explore
DEFAULT_VIZ_TYPE = "table"

# default row limit when requesting chart data
ROW_LIMIT = 50000
# default row limit when requesting samples from datasource in explore view
SAMPLES_ROW_LIMIT = 1000
# default row limit for native filters
NATIVE_FILTER_DEFAULT_ROW_LIMIT = 1000
# max rows retrieved by filter select auto complete
FILTER_SELECT_ROW_LIMIT = 10000

# SupersetClient HTTP retry configuration
# Controls retry behavior for all HTTP requests made through SupersetClient
# This helps handle transient server errors (like 502 Bad Gateway) automatically
SUPERSET_CLIENT_RETRY_ATTEMPTS = 3  # Maximum number of retry attempts
SUPERSET_CLIENT_RETRY_DELAY = 1000  # Initial retry delay in milliseconds
SUPERSET_CLIENT_RETRY_BACKOFF_MULTIPLIER = 2  # Exponential backoff multiplier
SUPERSET_CLIENT_RETRY_MAX_DELAY = 10000  # Maximum retry delay cap in milliseconds
SUPERSET_CLIENT_RETRY_JITTER_MAX = 1000  # Maximum random jitter in milliseconds
# HTTP status codes that should trigger retries (502, 503, 504 gateway errors)
SUPERSET_CLIENT_RETRY_STATUS_CODES = [502, 503, 504]
# default time filter in explore
# values may be "Last day", "Last week", "<ISO date> : now", etc.
DEFAULT_TIME_FILTER = NO_TIME_RANGE

# This is an important setting, and should be lower than your
# [load balancer / proxy / envoy / kong / ...] timeout settings.
# You should also make sure to configure your WSGI server
# (gunicorn, nginx, apache, ...) timeout setting to be <= to this setting
SUPERSET_WEBSERVER_TIMEOUT = int(timedelta(minutes=1).total_seconds())

# this 2 settings are used by dashboard period force refresh feature
# When user choose auto force refresh frequency
# < SUPERSET_DASHBOARD_PERIODICAL_REFRESH_LIMIT
# they will see warning message in the Refresh Interval Modal.
# please check PR #9886
SUPERSET_DASHBOARD_PERIODICAL_REFRESH_LIMIT = 0
SUPERSET_DASHBOARD_PERIODICAL_REFRESH_WARNING_MESSAGE = None

SUPERSET_DASHBOARD_POSITION_DATA_LIMIT = 65535
CUSTOM_SECURITY_MANAGER = None
SQLALCHEMY_TRACK_MODIFICATIONS = False
# ---------------------------------------------------------

# Your App secret key. Make sure you override it on superset_config.py
# or use `SUPERSET_SECRET_KEY` environment variable.
# Use a strong complex alphanumeric string and use a tool to help you generate
# a sufficiently random sequence, ex: openssl rand -base64 42"
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY") or CHANGE_ME_SECRET_KEY

# The SQLAlchemy connection string.
SQLALCHEMY_DATABASE_URI = (
    f"""sqlite:///{os.path.join(DATA_DIR, "superset.db")}?check_same_thread=false"""
)

# SQLALCHEMY_DATABASE_URI = 'mysql://myapp@localhost/myapp'
# SQLALCHEMY_DATABASE_URI = 'postgresql://root:password@localhost/myapp'

# This config is exposed through flask-sqlalchemy, and can be used to set your metadata
# database connection settings. You can use this to set arbitrary connection settings
# that may be specific to the database engine you are using.
# Note that you can use this to set the isolation level of your database, as in
# `SQLALCHEMY_ENGINE_OPTIONS = {"isolation_level": "READ COMMITTED"}`
# Also note that we recommend READ COMMITTED for regular operation.
# Find out more here https://flask-sqlalchemy.palletsprojects.com/en/3.1.x/config/
SQLALCHEMY_ENGINE_OPTIONS = {}

# In order to hook up a custom password store for all SQLALCHEMY connections
# implement a function that takes a single argument of type 'sqla.engine.url',
# returns a password and set SQLALCHEMY_CUSTOM_PASSWORD_STORE.
#
# example:
# def lookup_password(url):
#     return 'secret'
# SQLALCHEMY_CUSTOM_PASSWORD_STORE = lookup_password
SQLALCHEMY_CUSTOM_PASSWORD_STORE = None

#
# The EncryptedFieldTypeAdapter is used whenever we're building SqlAlchemy models
# which include sensitive fields that should be app-encrypted BEFORE sending
# to the DB.
#
# Note: the default impl leverages SqlAlchemyUtils' EncryptedType, which defaults
#  to AesEngine that uses AES-128 under the covers using the app's SECRET_KEY
#  as key material. Do note that AesEngine allows for queryability over the
#  encrypted fields.
#
#  To change the default engine you need to define your own adapter:
#
# e.g.:
#
# class AesGcmEncryptedAdapter(
#     AbstractEncryptedFieldAdapter
# ):
#     def create(
#         self,
#         app_config: Optional[Dict[str, Any]],
#         *args: List[Any],
#         **kwargs: Optional[Dict[str, Any]],
#     ) -> TypeDecorator:
#         if app_config:
#             return EncryptedType(
#                 *args, app_config["SECRET_KEY"], engine=AesGcmEngine, **kwargs
#             )
#         raise Exception("Missing app_config kwarg")
#
#
#  SQLALCHEMY_ENCRYPTED_FIELD_TYPE_ADAPTER = AesGcmEncryptedAdapter
SQLALCHEMY_ENCRYPTED_FIELD_TYPE_ADAPTER = (  # pylint: disable=invalid-name
    SQLAlchemyUtilsAdapter
)

# Extends the default SQLGlot dialects with additional dialects
SQLGLOT_DIALECTS_EXTENSIONS: DialectExtensions | Callable[[], DialectExtensions] = {}

# The limit of queries fetched for query search
QUERY_SEARCH_LIMIT = 1000

# Flask-WTF flag for CSRF
WTF_CSRF_ENABLED = True

# Add endpoints that need to be exempt from CSRF protection
WTF_CSRF_EXEMPT_LIST = [
    "superset.views.core.log",
    "superset.views.core.explore_json",
    "superset.charts.data.api.data",
    "superset.dashboards.api.cache_dashboard_screenshot",
]

# Whether to run the web server in debug mode or not
DEBUG = parse_boolean_string(os.environ.get("FLASK_DEBUG"))
FLASK_USE_RELOAD = True

# Enable profiling of Python calls. Turn this on and append ``?_instrument=1``
# to the page to see the call stack.
PROFILING = False

# Superset allows server-side python stacktraces to be surfaced to the
# user when this feature is on. This may have security implications
# and it's more secure to turn it off in production settings.
SHOW_STACKTRACE = False

# Use all X-Forwarded headers when ENABLE_PROXY_FIX is True.
# When proxying to a different port, set "x_port" to 0 to avoid downstream issues.
ENABLE_PROXY_FIX = False
PROXY_FIX_CONFIG = {"x_for": 1, "x_proto": 1, "x_host": 1, "x_port": 1, "x_prefix": 1}

# Configuration for scheduling queries from SQL Lab.
SCHEDULED_QUERIES: dict[str, Any] = {}

# FAB Rate limiting: this is a security feature for preventing DDOS attacks. The
# feature is on by default to make Superset secure by default, but you should
# fine tune the limits to your needs. You can read more about the different
# parameters here: https://flask-limiter.readthedocs.io/en/stable/configuration.html
RATELIMIT_ENABLED = os.environ.get("SUPERSET_ENV") == "production"
RATELIMIT_APPLICATION = "50 per second"
AUTH_RATE_LIMITED = True
AUTH_RATE_LIMIT = "5 per second"
# A storage location conforming to the scheme in storage-scheme. See the limits
# library for allowed values: https://limits.readthedocs.io/en/stable/storage.html
# RATELIMIT_STORAGE_URI = "redis://host:port"
# A callable that returns the unique identity of the current request.
# RATELIMIT_REQUEST_IDENTIFIER = flask.Request.endpoint

# ------------------------------
# GLOBALS FOR APP Builder
# ------------------------------
# Uncomment to setup Your App name
APP_NAME = "Superset"

# Specify the App icon
APP_ICON = "/static/assets/images/superset-logo-horiz.png"

# Specify where clicking the logo would take the user'
# Default value of None will take you to '/superset/welcome'
# You can also specify a relative URL e.g. '/superset/welcome' or '/dashboards/list'
# or you can specify a full URL e.g. 'https://foo.bar'
LOGO_TARGET_PATH = None

# Specify tooltip that should appear when hovering over the App Icon/Logo
LOGO_TOOLTIP = ""

# Specify any text that should appear to the right of the logo
LOGO_RIGHT_TEXT: Callable[[], str] | str = ""

# Enables SWAGGER UI for superset openapi spec
# ex: http://localhost:8080/swagger/v1
FAB_API_SWAGGER_UI = True

# ----------------------------------------------------
# AUTHENTICATION CONFIG
# ----------------------------------------------------
# The authentication type
# AUTH_OID : Is for OpenID
# AUTH_DB : Is for database (username/password)
# AUTH_LDAP : Is for LDAP
# AUTH_REMOTE_USER : Is for using REMOTE_USER from web server
AUTH_TYPE = AUTH_DB

# Uncomment to setup Full admin role name
# AUTH_ROLE_ADMIN = 'Admin'

# Uncomment to setup Public role name, no authentication needed
# AUTH_ROLE_PUBLIC = 'Public'

# Will allow user self registration
# AUTH_USER_REGISTRATION = True

# The default user self registration role
# AUTH_USER_REGISTRATION_ROLE = "Public"

# When using LDAP Auth, setup the LDAP server
# AUTH_LDAP_SERVER = "ldap://ldapserver.new"

# Uncomment to setup OpenID providers example for OpenID authentication
# OPENID_PROVIDERS = [
#    { 'name': 'Yahoo', 'url': 'https://open.login.yahoo.com/' },
#    { 'name': 'Flickr', 'url': 'https://www.flickr.com/<username>' },
# ]
# ---------------------------------------------------
# Roles config
# ---------------------------------------------------
# Grant public role the same set of permissions as for a selected builtin role.
# This is useful if one wants to enable anonymous users to view
# dashboards. Explicit grant on specific datasets is still required.
PUBLIC_ROLE_LIKE: str | None = None

# ---------------------------------------------------
# Babel config for translations
# ---------------------------------------------------
# Setup default language
BABEL_DEFAULT_LOCALE = "en"
# Your application default translation path
BABEL_DEFAULT_FOLDER = "superset/translations"
# The allowed translation for your app
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "es": {"flag": "es", "name": "Spanish"},
    "it": {"flag": "it", "name": "Italian"},
    "fr": {"flag": "fr", "name": "French"},
    "zh": {"flag": "cn", "name": "Chinese"},
    "zh_TW": {"flag": "tw", "name": "Traditional Chinese"},
    "ja": {"flag": "jp", "name": "Japanese"},
    "de": {"flag": "de", "name": "German"},
    "pl": {"flag": "pl", "name": "Polish"},
    "pt": {"flag": "pt", "name": "Portuguese"},
    "pt_BR": {"flag": "br", "name": "Brazilian Portuguese"},
    "ru": {"flag": "ru", "name": "Russian"},
    "ko": {"flag": "kr", "name": "Korean"},
    "sk": {"flag": "sk", "name": "Slovak"},
    "sl": {"flag": "si", "name": "Slovenian"},
    "nl": {"flag": "nl", "name": "Dutch"},
    "uk": {"flag": "uk", "name": "Ukranian"},
}
# Turning off i18n by default as translation in most languages are
# incomplete and not well maintained.
LANGUAGES = {}


# Override the default d3 locale format
# Default values are equivalent to
# D3_FORMAT = {
#     "decimal": ".",           # - decimal place string (e.g., ".").
#     "thousands": ",",         # - group separator string (e.g., ",").
#     "grouping": [3],          # - array of group sizes (e.g., [3]), cycled as needed.
#     "currency": ["$", ""]     # - currency prefix/suffix strings (e.g., ["$", ""])
# }
# https://github.com/d3/d3-format/blob/main/README.md#formatLocale
class D3Format(TypedDict, total=False):
    decimal: str
    thousands: str
    grouping: list[int]
    currency: list[str]


D3_FORMAT: D3Format = {}

# Override the default mapbox tiles
# Default values are equivalent to
# DECKGL_BASE_MAP = [
#   ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', 'Streets (OSM)'],
#   ['https://tile.osm.ch/osm-swiss-style/{z}/{x}/{y}.png', 'Topography (OSM)'],
#   ['mapbox://styles/mapbox/streets-v9', 'Streets'],
#   ['mapbox://styles/mapbox/dark-v9', 'Dark'],
#   ['mapbox://styles/mapbox/light-v9', 'Light'],
#   ['mapbox://styles/mapbox/satellite-streets-v9', 'Satellite Streets'],
#   ['mapbox://styles/mapbox/satellite-v9', 'Satellite'],
#   ['mapbox://styles/mapbox/outdoors-v9', 'Outdoors'],
# ]
# for adding your own map tiles, you can use the following format:
# - tile:// + your_personal_url or openstreetmap_url
#   example:
#   DECKGL_BASE_MAP = [
#       ['tile://https://c.tile.openstreetmap.org/{z}/{x}/{y}.png', 'OpenStreetMap']
#    ]
# Enable CORS and set map url in origins option.
# Add also map url in connect-src of TALISMAN_CONFIG variable
DECKGL_BASE_MAP: list[list[str, str]] = None


# Override the default d3 locale for time format
# Default values are equivalent to
# D3_TIME_FORMAT = {
#     "dateTime": "%x, %X",
#     "date": "%-m/%-d/%Y",
#     "time": "%-I:%M:%S %p",
#     "periods": ["AM", "PM"],
#     "days": ["Sunday", "Monday", "Tuesday", "Wednesday",
#              "Thursday", "Friday", "Saturday"],
#     "shortDays": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
#     "months": ["January", "February", "March", "April",
#                "May", "June", "July", "August",
#                "September", "October", "November", "December"],
#     "shortMonths": ["Jan", "Feb", "Mar", "Apr",
#                     "May", "Jun", "Jul", "Aug",
#                     "Sep", "Oct", "Nov", "Dec"]
# }
# https://github.com/d3/d3-time-format/tree/main#locales
class D3TimeFormat(TypedDict, total=False):
    date: str
    dateTime: str
    time: str
    periods: list[str]
    days: list[str]
    shortDays: list[str]
    months: list[str]
    shortMonths: list[str]


D3_TIME_FORMAT: D3TimeFormat = {}

CURRENCIES = ["USD", "EUR", "GBP", "INR", "MXN", "JPY", "CNY"]

# ---------------------------------------------------
# Feature flags
# ---------------------------------------------------
# Feature flags that are set by default go here. Their values can be
# overwritten by those specified under FEATURE_FLAGS in superset_config.py
# For example, DEFAULT_FEATURE_FLAGS = { 'FOO': True, 'BAR': False } here
# and FEATURE_FLAGS = { 'BAR': True, 'BAZ': True } in superset_config.py
# will result in combined feature flags of { 'FOO': True, 'BAR': True, 'BAZ': True }
DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    # When using a recent version of Druid that supports JOINs turn this on
    "DRUID_JOINS": False,
    "DYNAMIC_PLUGINS": False,
    "ENABLE_TEMPLATE_PROCESSING": False,
    # Allow for javascript controls components
    # this enables programmers to customize certain charts (like the
    # geospatial ones) by inputting javascript in controls. This exposes
    # an XSS security vulnerability
    "ENABLE_JAVASCRIPT_CONTROLS": False,  # deprecated
    # When this feature is enabled, nested types in Presto will be
    # expanded into extra columns and/or arrays. This is experimental,
    # and doesn't work with all nested types.
    "PRESTO_EXPAND_DATA": False,
    # Exposes API endpoint to compute thumbnails
    "THUMBNAILS": False,
    # Enables the endpoints to cache and retrieve dashboard screenshots via webdriver.
    # Requires configuring Celery and a cache using THUMBNAIL_CACHE_CONFIG.
    "ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS": False,
    # Generate screenshots (PDF or JPG) of dashboards using the web driver.
    # When disabled, screenshots are generated on the fly by the browser.
    # This feature flag is used by the download feature in the dashboard view.
    # It is dependent on ENABLE_DASHBOARD_SCREENSHOT_ENDPOINT being enabled.
    "ENABLE_DASHBOARD_DOWNLOAD_WEBDRIVER_SCREENSHOT": False,
    "TAGGING_SYSTEM": False,
    "SQLLAB_BACKEND_PERSISTENCE": True,
    "LISTVIEWS_DEFAULT_CARD_VIEW": False,
    # When True, this escapes HTML (rather than rendering it) in Markdown components
    "ESCAPE_MARKDOWN_HTML": False,
    "DASHBOARD_VIRTUALIZATION": True,
    # This feature flag is stil in beta and is not recommended for production use.
    "GLOBAL_ASYNC_QUERIES": False,
    "EMBEDDED_SUPERSET": False,
    # Enables Alerts and reports new implementation
    "ALERT_REPORTS": False,
    "ALERT_REPORT_TABS": False,
    "ALERT_REPORT_SLACK_V2": False,
    "DASHBOARD_RBAC": False,
    "ENABLE_ADVANCED_DATA_TYPES": False,
    # Enabling ALERTS_ATTACH_REPORTS, the system sends email and slack message
    # with screenshot and link
    # Disables ALERTS_ATTACH_REPORTS, the system DOES NOT generate screenshot
    # for report with type 'alert' and sends email and slack message with only link;
    # for report with type 'report' still send with email and slack message with
    # screenshot and link
    "ALERTS_ATTACH_REPORTS": True,
    # Allow users to export full CSV of table viz type.
    # This could cause the server to run out of memory or compute.
    "ALLOW_FULL_CSV_EXPORT": False,
    "ALLOW_ADHOC_SUBQUERY": False,
    "USE_ANALOGOUS_COLORS": False,
    # Apply RLS rules to SQL Lab queries. This requires parsing and manipulating the
    # query, and might break queries and/or allow users to bypass RLS. Use with care!
    "RLS_IN_SQLLAB": False,
    # Try to optimize SQL queries — for now only predicate pushdown is supported.
    "OPTIMIZE_SQL": False,
    # When impersonating a user, use the email prefix instead of the username
    "IMPERSONATE_WITH_EMAIL_PREFIX": False,
    # Enable caching per impersonation key (e.g username) in a datasource where user
    # impersonation is enabled
    "CACHE_IMPERSONATION": False,
    # Enable caching per user key for Superset cache (not database cache impersonation)
    "CACHE_QUERY_BY_USER": False,
    # Enable sharing charts with embedding
    "EMBEDDABLE_CHARTS": True,
    "DRILL_TO_DETAIL": True,  # deprecated
    "DRILL_BY": True,
    "DATAPANEL_CLOSED_BY_DEFAULT": False,
    # When you open the dashboard, the filter panel will be closed
    "FILTERBAR_CLOSED_BY_DEFAULT": False,
    # The feature is off by default, and currently only supported in Presto and Postgres,  # noqa: E501
    # and Bigquery.
    # It also needs to be enabled on a per-database basis, by adding the key/value pair
    # `cost_estimate_enabled: true` to the database `extra` attribute.
    "ESTIMATE_QUERY_COST": False,
    # Allow users to enable ssh tunneling when creating a DB.
    # Users must check whether the DB engine supports SSH Tunnels
    # otherwise enabling this flag won't have any effect on the DB.
    "SSH_TUNNELING": False,
    "AVOID_COLORS_COLLISION": True,
    # Do not show user info in the menu
    "MENU_HIDE_USER_INFO": False,
    # Allows users to add a ``superset://`` DB that can query across databases. This is
    # an experimental feature with potential security and performance risks, so use with
    # caution. If the feature is enabled you can also set a limit for how much data is
    # returned from each database in the ``SUPERSET_META_DB_LIMIT`` configuration value
    # in this file.
    "ENABLE_SUPERSET_META_DB": False,
    # Set to True to replace Selenium with Playwright to execute reports and thumbnails.
    # Unlike Selenium, Playwright reports support deck.gl visualizations
    # Enabling this feature flag requires installing "playwright" pip package
    "PLAYWRIGHT_REPORTS_AND_THUMBNAILS": False,
    # Set to True to enable experimental chart plugins
    "CHART_PLUGINS_EXPERIMENTAL": False,
    # Regardless of database configuration settings, force SQLLAB to run async
    # using Celery
    "SQLLAB_FORCE_RUN_ASYNC": False,
    # Set to True to to enable factory resent CLI command
    "ENABLE_FACTORY_RESET_COMMAND": False,
    # Whether Superset should use Slack avatars for users.
    # If on, you'll want to add "https://avatars.slack-edge.com" to the list of allowed
    # domains in your TALISMAN_CONFIG
    "SLACK_ENABLE_AVATARS": False,
    # Adds a theme editor as a modal dialog in the navbar. Allows people to type in JSON
    # Enables CSS Templates functionality in Settings menu and dashboard forms.
    # When disabled, users can still add custom CSS to dashboards but cannot use
    # pre-built CSS templates.
    "CSS_TEMPLATES": True,
    # Allow users to optionally specify date formats in email subjects, which will
    # be parsed if enabled
    "DATE_FORMAT_IN_EMAIL_SUBJECT": False,
    # Allow metrics and columns to be grouped into (potentially nested) folders in the
    # chart builder
    "DATASET_FOLDERS": False,
    # Enable Table V2 Viz plugin
    "AG_GRID_TABLE_ENABLED": False,
    # Enable Table v2 time comparison feature
    "TABLE_V2_TIME_COMPARISON_ENABLED": False,
}

# ------------------------------
# SSH Tunnel
# ------------------------------
# Allow users to set the host used when connecting to the SSH Tunnel
# as localhost and any other alias (0.0.0.0)
# ----------------------------------------------------------------------
#                             |
# -------------+              |    +----------+
#     LOCAL    |              |    |  REMOTE  | :22 SSH
#     CLIENT   | <== SSH ========> |  SERVER  | :8080 web service
# -------------+              |    +----------+
#                             |
#                          FIREWALL (only port 22 is open)

# ----------------------------------------------------------------------
SSH_TUNNEL_MANAGER_CLASS = "superset.extensions.ssh.SSHManager"
SSH_TUNNEL_LOCAL_BIND_ADDRESS = "127.0.0.1"
#: Timeout (seconds) for tunnel connection (open_channel timeout)
SSH_TUNNEL_TIMEOUT_SEC = 10.0
#: Timeout (seconds) for transport socket (``socket.settimeout``)
SSH_TUNNEL_PACKET_TIMEOUT_SEC = 1.0


# Feature flags may also be set via 'SUPERSET_FEATURE_' prefixed environment vars.
DEFAULT_FEATURE_FLAGS.update(
    {
        k[len("SUPERSET_FEATURE_") :]: parse_boolean_string(v)
        for k, v in os.environ.items()
        if re.search(r"^SUPERSET_FEATURE_\w+", k)
    }
)

# This function can be overridden to customize the name of the user agent
# triggering the query.
USER_AGENT_FUNC: Callable[[Database, QuerySource | None], str] | None = None

# This is merely a default.
FEATURE_FLAGS: dict[str, bool] = {}

# A function that receives a dict of all feature flags
# (DEFAULT_FEATURE_FLAGS merged with FEATURE_FLAGS)
# can alter it, and returns a similar dict. Note the dict of feature
# flags passed to the function is a deepcopy of the dict in the config,
# and can therefore be mutated without side-effect
#
# GET_FEATURE_FLAGS_FUNC can be used to implement progressive rollouts,
# role-based features, or a full on A/B testing framework.
#
# from flask import g, request
# def GET_FEATURE_FLAGS_FUNC(feature_flags_dict: Dict[str, bool]) -> Dict[str, bool]:
#     if hasattr(g, "user") and g.user.is_active:
#         feature_flags_dict['some_feature'] = g.user and g.user.get_id() == 5
#     return feature_flags_dict
GET_FEATURE_FLAGS_FUNC: Callable[[dict[str, bool]], dict[str, bool]] | None = None
# A function that receives a feature flag name and an optional default value.
# Has a similar utility to GET_FEATURE_FLAGS_FUNC but it's useful to not force the
# evaluation of all feature flags when just evaluating a single one.
#
# Note that the default `get_feature_flags` will evaluate each feature with this
# callable when the config key is set, so don't use both GET_FEATURE_FLAGS_FUNC
# and IS_FEATURE_ENABLED_FUNC in conjunction.
IS_FEATURE_ENABLED_FUNC: Callable[[str, bool | None], bool] | None = None
# A function that expands/overrides the frontend `bootstrap_data.common` object.
# Can be used to implement custom frontend functionality,
# or dynamically change certain configs.
#
# Values in `bootstrap_data.common` should have these characteristics:
# - They are not specific to a page the user is visiting
# - They do not contain secrets
#
# Takes as a parameter the common bootstrap payload before transformations.
# Returns a dict containing data that should be added or overridden to the payload.
COMMON_BOOTSTRAP_OVERRIDES_FUNC: Callable[  # noqa: E731
    [dict[str, Any]], dict[str, Any]
] = lambda data: {}

# EXTRA_CATEGORICAL_COLOR_SCHEMES is used for adding custom categorical color schemes
# example code for "My custom warm to hot" color scheme
# EXTRA_CATEGORICAL_COLOR_SCHEMES = [
#     {
#         "id": 'myVisualizationColors',
#         "description": '',
#         "label": 'My Visualization Colors',
#         "isDefault": True,
#         "colors":
#          ['#006699', '#009DD9', '#5AAA46', '#44AAAA', '#DDAA77', '#7799BB', '#88AA77',
#          '#552288', '#5AAA46', '#CC7788', '#EEDD55', '#9977BB', '#BBAA44', '#DDCCDD']
#     }]

# This is merely a default
EXTRA_CATEGORICAL_COLOR_SCHEMES: list[dict[str, Any]] = []

# ---------------------------------------------------
# Theme Configuration for Superset
# ---------------------------------------------------
# Superset supports custom theming through Ant Design's theme structure.
# This allows users to customize colors, fonts, and other UI elements.
#
# Theme Generation:
# - Use the Ant Design theme editor: https://ant.design/theme-editor
# - Export or copy the generated theme JSON and assign to the variables below
# - For detailed instructions: https://superset.apache.org/docs/configuration/theming/
#
# To expose a JSON theme editor modal that can be triggered from the navbar
# set the `ENABLE_THEME_EDITOR` feature flag to True.
#
# Theme Structure:
# Each theme should follow Ant Design's theme format.
# To create custom themes, use the Ant Design Theme Editor at https://ant.design/theme-editor
# and copy the generated JSON configuration.
#
# Example theme definition:
# THEME_DEFAULT = {
#       "token": {
#            "colorPrimary": "#2893B3",
#            "colorSuccess": "#5ac189",
#            "colorWarning": "#fcc700",
#            "colorError": "#e04355",
#            "fontFamily": "'Inter', Helvetica, Arial",
#            ... # other tokens
#       },
#       ... # other theme properties
# }


# Default theme configuration
# Leave empty to use Superset's default theme
THEME_DEFAULT: Theme = {"algorithm": "default"}

# Dark theme configuration
# Applied when user selects dark mode
THEME_DARK: Theme = {"algorithm": "dark"}

# Theme behavior and user preference settings
# Controls how themes are applied and what options users have
# - enforced: Forces the default theme always, overriding all other settings
# - allowSwitching: Allows users to manually switch between default and dark themes.
# - allowOSPreference: Allows the app to automatically use the system's preferred theme mode  # noqa: E501
#
# Example:
THEME_SETTINGS = {
    "enforced": False,  # If True, forces the default theme and ignores user preferences  # noqa: E501
    "allowSwitching": True,  # Allows user to switch between themes (default and dark)  # noqa: E501
    "allowOSPreference": True,  # Allows the app to Auto-detect and set system theme preference  # noqa: E501
}

# Custom font configuration
# Load external fonts at runtime without rebuilding the application
# Example:
# CUSTOM_FONT_URLS = [
#     "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
#     "https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;500&display=swap",
# ]
CUSTOM_FONT_URLS: list[str] = []

# ---------------------------------------------------
# EXTRA_SEQUENTIAL_COLOR_SCHEMES is used for adding custom sequential color schemes
# EXTRA_SEQUENTIAL_COLOR_SCHEMES =  [
#     {
#         "id": 'warmToHot',
#         "description": '',
#         "isDiverging": True,
#         "label": 'My custom warm to hot',
#         "isDefault": True,
#         "colors":
#          ['#552288', '#5AAA46', '#CC7788', '#EEDD55', '#9977BB', '#BBAA44', '#DDCCDD',
#          '#006699', '#009DD9', '#5AAA46', '#44AAAA', '#DDAA77', '#7799BB', '#88AA77']
#     }]

# This is merely a default
EXTRA_SEQUENTIAL_COLOR_SCHEMES: list[dict[str, Any]] = []

# User used to execute cache warmup tasks
# By default, the cache is warmed up using the primary owner. To fall back to using
# a fixed user (admin in this example), use the following configuration:
#
# from superset.tasks.types import ExecutorType, FixedExecutor
#
# CACHE_WARMUP_EXECUTORS = [ExecutorType.OWNER, FixedExecutor("admin")]
CACHE_WARMUP_EXECUTORS = [ExecutorType.OWNER]

# ---------------------------------------------------
# Thumbnail config (behind feature flag)
# ---------------------------------------------------
# By default, thumbnails are rendered per user, and will fall back to the Selenium
# user for anonymous users. Similar to Alerts & Reports, thumbnails
# can be configured to always be rendered as a fixed user. See
# `superset.tasks.types.ExecutorType` for a full list of executor options.
# To always use a fixed user account (admin in this example, use the following
# configuration:
#
# from superset.tasks.types import ExecutorType, FixedExecutor
#
# THUMBNAIL_EXECUTORS = [FixedExecutor("admin")]
THUMBNAIL_EXECUTORS = [ExecutorType.CURRENT_USER]

# By default, thumbnail digests are calculated based on various parameters in the
# chart/dashboard metadata, and in the case of user-specific thumbnails, the
# username. To specify a custom digest function, use the following config parameters
# to define callbacks that receive
# 1. the model (dashboard or chart)
# 2. the executor type (e.g. ExecutorType.FIXED_USER)
# 3. the executor's username (note, this is the executor as defined by
# `THUMBNAIL_EXECUTORS`; the executor is only equal to the currently logged in
# user if the executor type is equal to `ExecutorType.CURRENT_USER`)
# and return the final digest string:
THUMBNAIL_DASHBOARD_DIGEST_FUNC: (
    Callable[[Dashboard, ExecutorType, str], str | None] | None
) = None
THUMBNAIL_CHART_DIGEST_FUNC: Callable[[Slice, ExecutorType, str], str | None] | None = (
    None
)

THUMBNAIL_CACHE_CONFIG: CacheConfig = {
    "CACHE_TYPE": "NullCache",
    "CACHE_DEFAULT_TIMEOUT": int(timedelta(days=7).total_seconds()),
    "CACHE_NO_NULL_WARNING": True,
}
THUMBNAIL_ERROR_CACHE_TTL = int(timedelta(days=1).total_seconds())

# Time before selenium times out after trying to locate an element on the page and wait
# for that element to load for a screenshot.
SCREENSHOT_LOCATE_WAIT = int(timedelta(seconds=10).total_seconds())
# Time before selenium times out after waiting for all DOM class elements named
# "loading" are gone.
SCREENSHOT_LOAD_WAIT = int(timedelta(minutes=1).total_seconds())
# Selenium destroy retries
SCREENSHOT_SELENIUM_RETRIES = 5
# Give selenium an headstart, in seconds
SCREENSHOT_SELENIUM_HEADSTART = 3
# Wait for the chart animation, in seconds
SCREENSHOT_SELENIUM_ANIMATION_WAIT = 5
# Replace unexpected errors in screenshots with real error messages
SCREENSHOT_REPLACE_UNEXPECTED_ERRORS = False
# Max time to wait for error message modal to show up, in seconds
SCREENSHOT_WAIT_FOR_ERROR_MODAL_VISIBLE = 5
# Max time to wait for error message modal to close, in seconds
SCREENSHOT_WAIT_FOR_ERROR_MODAL_INVISIBLE = 5
# Event that Playwright waits for when loading a new page
# Possible values: "load", "commit", "domcontentloaded", "networkidle"
# Docs: https://playwright.dev/python/docs/api/class-page#page-goto-option-wait-until
SCREENSHOT_PLAYWRIGHT_WAIT_EVENT = "domcontentloaded"
# Default timeout for Playwright browser context for all operations
SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT = int(
    timedelta(seconds=60).total_seconds() * 1000
)

# ---------------------------------------------------
# Image and file configuration
# ---------------------------------------------------
# The file upload folder, when using models with files
UPLOAD_FOLDER = BASE_DIR + "/static/uploads/"
UPLOAD_CHUNK_SIZE = 4096

# ---------------------------------------------------
# Cache configuration
# ---------------------------------------------------
# Default cache timeout, applies to all cache backends unless specifically overridden in
# each cache config.
CACHE_DEFAULT_TIMEOUT = int(timedelta(days=1).total_seconds())

# Default cache for Superset objects
CACHE_CONFIG: CacheConfig = {"CACHE_TYPE": "NullCache"}

# Cache for datasource metadata and query results
DATA_CACHE_CONFIG: CacheConfig = {"CACHE_TYPE": "NullCache"}

# Cache for dashboard filter state. `CACHE_TYPE` defaults to `SupersetMetastoreCache`
# that stores the values in the key-value table in the Superset metastore, as it's
# required for Superset to operate correctly, but can be replaced by any
# `Flask-Caching` backend.
FILTER_STATE_CACHE_CONFIG: CacheConfig = {
    "CACHE_TYPE": "SupersetMetastoreCache",
    "CACHE_DEFAULT_TIMEOUT": int(timedelta(days=90).total_seconds()),
    # Should the timeout be reset when retrieving a cached value?
    "REFRESH_TIMEOUT_ON_RETRIEVAL": True,
    # The following parameter only applies to `MetastoreCache`:
    # How should entries be serialized/deserialized?
    "CODEC": JsonKeyValueCodec(),
}

# Cache for explore form data state. `CACHE_TYPE` defaults to `SupersetMetastoreCache`
# that stores the values in the key-value table in the Superset metastore, as it's
# required for Superset to operate correctly, but can be replaced by any
# `Flask-Caching` backend.
EXPLORE_FORM_DATA_CACHE_CONFIG: CacheConfig = {
    "CACHE_TYPE": "SupersetMetastoreCache",
    "CACHE_DEFAULT_TIMEOUT": int(timedelta(days=7).total_seconds()),
    # Should the timeout be reset when retrieving a cached value?
    "REFRESH_TIMEOUT_ON_RETRIEVAL": True,
    # The following parameter only applies to `MetastoreCache`:
    # How should entries be serialized/deserialized?
    "CODEC": JsonKeyValueCodec(),
}

# store cache keys by datasource UID (via CacheKey) for custom processing/invalidation
STORE_CACHE_KEYS_IN_METADATA_DB = False

# CORS Options
# NOTE: enabling this requires installing the cors-related python dependencies
# `pip install .[cors]` or `pip install apache_superset[cors]`, depending
ENABLE_CORS = True
CORS_OPTIONS: dict[Any, Any] = {
    "origins": [
        "https://tile.openstreetmap.org",
        "https://tile.osm.ch",
    ]
}

# Sanitizes the HTML content used in markdowns to allow its rendering in a safe manner.
# Disabling this option is not recommended for security reasons. If you wish to allow
# valid safe elements that are not included in the default sanitization schema, use the
# HTML_SANITIZATION_SCHEMA_EXTENSIONS configuration.
HTML_SANITIZATION = True

# Use this configuration to extend the HTML sanitization schema.
# By default we use the GitHub schema defined in
# https://github.com/syntax-tree/hast-util-sanitize/blob/main/lib/schema.js
# For example, the following configuration would allow the rendering of the
# style attribute for div elements and the ftp protocol in hrefs:
# HTML_SANITIZATION_SCHEMA_EXTENSIONS = {
#   "attributes": {
#     "div": ["style"],
#   },
#   "protocols": {
#     "href": ["ftp"],
#   }
# }
# Be careful when extending the default schema to avoid XSS attacks.
HTML_SANITIZATION_SCHEMA_EXTENSIONS: dict[str, Any] = {}

# Chrome allows up to 6 open connections per domain at a time. When there are more
# than 6 slices in dashboard, a lot of time fetch requests are queued up and wait for
# next available socket. PR #5039 added domain sharding for Superset,
# and this feature can be enabled by configuration only (by default Superset
# doesn't allow cross-domain request). This feature is deprecated, annd will be removed
# in the next major version of Superset, as enabling HTTP2 will serve the same goals.
SUPERSET_WEBSERVER_DOMAINS = None  # deprecated

# Allowed format types for upload on Database view
EXCEL_EXTENSIONS = {"xlsx", "xls"}
CSV_EXTENSIONS = {"csv", "tsv", "txt"}
COLUMNAR_EXTENSIONS = {"parquet", "zip"}
ALLOWED_EXTENSIONS = {*EXCEL_EXTENSIONS, *CSV_EXTENSIONS, *COLUMNAR_EXTENSIONS}

# CSV Options: key/value pairs that will be passed as argument to DataFrame.to_csv
# method.
# note: index option should not be overridden
CSV_EXPORT = {"encoding": "utf-8-sig"}

# Excel Options: key/value pairs that will be passed as argument to DataFrame.to_excel
# method.
# note: index option should not be overridden
EXCEL_EXPORT: dict[str, Any] = {}

# ---------------------------------------------------
# Time grain configurations
# ---------------------------------------------------
# List of time grains to disable in the application (see list of builtin
# time grains in superset/db_engine_specs/base.py).
# For example: to disable 1 second time grain:
# TIME_GRAIN_DENYLIST = ['PT1S']
TIME_GRAIN_DENYLIST: list[str] = []

# Additional time grains to be supported using similar definitions as in
# superset/db_engine_specs/base.py.
# For example: To add a new 2 second time grain:
# TIME_GRAIN_ADDONS = {'PT2S': '2 second'}
TIME_GRAIN_ADDONS: dict[str, str] = {}

# Implementation of additional time grains per engine.
# The column to be truncated is denoted `{col}` in the expression.
# For example: To implement 2 second time grain on clickhouse engine:
# TIME_GRAIN_ADDON_EXPRESSIONS = {
#     'clickhouse': {
#         'PT2S': 'toDateTime(intDiv(toUInt32(toDateTime({col})), 2)*2)'
#     }
# }
TIME_GRAIN_ADDON_EXPRESSIONS: dict[str, dict[str, str]] = {}

# Map of custom time grains and artificial join column producers used
# when generating the join key between results and time shifts.
# See superset/common/query_context_processor.get_aggregated_join_column
#
# Example of a join column producer that aggregates by fiscal year
# def join_producer(row: Series, column_index: int) -> str:
#    return row[index].strftime("%F")
#
# TIME_GRAIN_JOIN_COLUMN_PRODUCERS = {"P1F": join_producer}
TIME_GRAIN_JOIN_COLUMN_PRODUCERS: dict[str, Callable[[Series, int], str]] = {}

# ---------------------------------------------------
# List of viz_types not allowed in your environment
# For example: Disable pivot table and treemap:
#  VIZ_TYPE_DENYLIST = ['pivot_table', 'treemap']
# ---------------------------------------------------

VIZ_TYPE_DENYLIST: list[str] = []

# --------------------------------------------------
# Modules, datasources and middleware to be registered
# --------------------------------------------------
DEFAULT_MODULE_DS_MAP = OrderedDict(
    [
        ("superset.connectors.sqla.models", ["SqlaTable"]),
    ]
)
ADDITIONAL_MODULE_DS_MAP: dict[str, list[str]] = {}
ADDITIONAL_MIDDLEWARE: list[Callable[..., Any]] = []

# 1) https://docs.python-guide.org/writing/logging/
# 2) https://docs.python.org/2/library/logging.config.html

# Default configurator will consume the LOG_* settings below
LOGGING_CONFIGURATOR = DefaultLoggingConfigurator()

# Console Log Settings

LOG_FORMAT = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"
LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO

# ---------------------------------------------------
# Enable Time Rotate Log Handler
# ---------------------------------------------------
# LOG_LEVEL = DEBUG, INFO, WARNING, ERROR, CRITICAL

ENABLE_TIME_ROTATE = False
TIME_ROTATE_LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO
FILENAME = os.path.join(DATA_DIR, "superset.log")
ROLLOVER = "midnight"
INTERVAL = 1
BACKUP_COUNT = 30

# Custom logger for auditing queries. This can be used to send ran queries to a
# structured immutable store for auditing purposes. The function is called for
# every query ran, in both SQL Lab and charts/dashboards.
# def QUERY_LOGGER(
#     database,
#     query,
#     schema=None,
#     client=None,
#     security_manager=None,
#     log_params=None,
# ):
#     pass
QUERY_LOGGER = None

# Set this API key to enable Mapbox visualizations
MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")

# Maximum number of rows returned for any analytical database query
SQL_MAX_ROW = 100000

# Maximum number of rows for any query with Server Pagination in Table Viz type
TABLE_VIZ_MAX_ROW_SERVER = 500000


# Maximum number of rows displayed in SQL Lab UI
# Is set to avoid out of memory/localstorage issues in browsers. Does not affect
# exported CSVs
DISPLAY_MAX_ROW = 10000

# Default row limit for SQL Lab queries. Is overridden by setting a new limit in
# the SQL Lab UI
DEFAULT_SQLLAB_LIMIT = 1000

# The limit for the Superset Meta DB when the feature flag ENABLE_SUPERSET_META_DB is on
SUPERSET_META_DB_LIMIT: int | None = 1000

# Adds a warning message on sqllab save query and schedule query modals.
SQLLAB_SAVE_WARNING_MESSAGE = None
SQLLAB_SCHEDULE_WARNING_MESSAGE = None

# Max payload size (MB) for SQL Lab to prevent browser hangs with large results.
SQLLAB_PAYLOAD_MAX_MB = None

# Force refresh while auto-refresh in dashboard
DASHBOARD_AUTO_REFRESH_MODE: Literal["fetch", "force"] = "force"
# Dashboard auto refresh intervals
DASHBOARD_AUTO_REFRESH_INTERVALS = [
    [0, "Don't refresh"],
    [10, "10 seconds"],
    [30, "30 seconds"],
    [60, "1 minute"],
    [300, "5 minutes"],
    [1800, "30 minutes"],
    [3600, "1 hour"],
    [21600, "6 hours"],
    [43200, "12 hours"],
    [86400, "24 hours"],
]

# This is used as a workaround for the alerts & reports scheduler task to get the time
# celery beat triggered it, see https://github.com/celery/celery/issues/6974 for details
CELERY_BEAT_SCHEDULER_EXPIRES = timedelta(weeks=1)

# Default celery config is to use SQLA as a broker, in a production setting
# you'll want to use a proper broker as specified here:
# https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html


class CeleryConfig:  # pylint: disable=too-few-public-methods
    broker_url = "sqla+sqlite:///celerydb.sqlite"
    imports = (
        "superset.sql_lab",
        "superset.tasks.scheduler",
        "superset.tasks.thumbnails",
        "superset.tasks.cache",
        "superset.tasks.slack",
    )
    result_backend = "db+sqlite:///celery_results.sqlite"
    worker_prefetch_multiplier = 1
    task_acks_late = False
    task_annotations = {
        "sql_lab.get_sql_results": {
            "rate_limit": "100/s",
        },
    }
    beat_schedule = {
        "reports.scheduler": {
            "task": "reports.scheduler",
            "schedule": crontab(minute="*", hour="*"),
            "options": {"expires": int(CELERY_BEAT_SCHEDULER_EXPIRES.total_seconds())},
        },
        "reports.prune_log": {
            "task": "reports.prune_log",
            "schedule": crontab(minute=0, hour=0),
        },
        # Uncomment to enable pruning of the query table
        # "prune_query": {
        #     "task": "prune_query",
        #     "schedule": crontab(minute=0, hour=0, day_of_month=1),
        #     "kwargs": {"retention_period_days": 180},
        # },
        # Uncomment to enable pruning of the logs table
        # "prune_logs": {
        #     "task": "prune_logs",
        #     "schedule": crontab(minute="*", hour="*"),
        #     "kwargs": {"retention_period_days": 180},
        # },
        # Uncomment to enable Slack channel cache warm-up
        # "slack.cache_channels": {
        #     "task": "slack.cache_channels",
        #     "schedule": crontab(minute="0", hour="*"),
        # },
    }


CELERY_CONFIG: type[CeleryConfig] | None = CeleryConfig

# Set celery config to None to disable all the above configuration
# CELERY_CONFIG = None

# Additional static HTTP headers to be served by your Superset server. Note
# Flask-Talisman applies the relevant security HTTP headers.
#
# DEFAULT_HTTP_HEADERS: sets default values for HTTP headers. These may be overridden
# within the app
# OVERRIDE_HTTP_HEADERS: sets override values for HTTP headers. These values will
# override anything set within the app
DEFAULT_HTTP_HEADERS: dict[str, Any] = {}
OVERRIDE_HTTP_HEADERS: dict[str, Any] = {}
HTTP_HEADERS: dict[str, Any] = {}

# The db id here results in selecting this one as a default in SQL Lab
DEFAULT_DB_ID = None

# Timeout duration for SQL Lab synchronous queries
SQLLAB_TIMEOUT = int(timedelta(seconds=30).total_seconds())

# Timeout duration for SQL Lab query validation
SQLLAB_VALIDATION_TIMEOUT = int(timedelta(seconds=10).total_seconds())

# SQLLAB_DEFAULT_DBID
SQLLAB_DEFAULT_DBID = None

# The MAX duration a query can run for before being killed by celery.
SQLLAB_ASYNC_TIME_LIMIT_SEC = int(timedelta(hours=6).total_seconds())

# Some databases support running EXPLAIN queries that allow users to estimate
# query costs before they run. These EXPLAIN queries should have a small
# timeout.
SQLLAB_QUERY_COST_ESTIMATE_TIMEOUT = int(timedelta(seconds=10).total_seconds())

# Timeout duration for SQL Lab fetching query results by the resultsKey.
# 0 means no timeout.
SQLLAB_QUERY_RESULT_TIMEOUT = 0

# The cost returned by the databases is a relative value; in order to map the cost to
# a tangible value you need to define a custom formatter that takes into consideration
# your specific infrastructure. For example, you could analyze queries a posteriori by
# running EXPLAIN on them, and compute a histogram of relative costs to present the
# cost as a percentile, this step is optional as every db engine spec has its own
# query cost formatter, but it you wanna customize it you can define it inside the config:  # noqa: E501

# def postgres_query_cost_formatter(
#     result: List[Dict[str, Any]]
# ) -> List[Dict[str, str]]:
#     # 25, 50, 75% percentiles
#     percentile_costs = [100.0, 1000.0, 10000.0]
#
#     out = []
#     for row in result:
#         relative_cost = row["Total cost"]
#         percentile = bisect.bisect_left(percentile_costs, relative_cost) + 1
#         out.append({
#             "Relative cost": relative_cost,
#             "Percentile": str(percentile * 25) + "%",
#         })
#
#     return out
#
# QUERY_COST_FORMATTERS_BY_ENGINE: {"postgresql": postgres_query_cost_formatter}
QUERY_COST_FORMATTERS_BY_ENGINE: dict[
    str, Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
] = {}

# Flag that controls if limit should be enforced on the CTA (create table as queries).
SQLLAB_CTAS_NO_LIMIT = False

# This allows you to define custom logic around the "CREATE TABLE AS" or CTAS feature
# in SQL Lab that defines where the target schema should be for a given user.
# Database `CTAS Schema` has a precedence over this setting.
# Example below returns a username and CTA queries will write tables into the schema
# name `username`
# SQLLAB_CTAS_SCHEMA_NAME_FUNC = lambda database, user, schema, sql: user.username
# This is move involved example where depending on the database you can leverage data
# available to assign schema for the CTA query:
# def compute_schema_name(database: Database, user: User, schema: str, sql: str) -> str:
#     if database.name == 'mysql_payments_slave':
#         return 'tmp_superset_schema'
#     if database.name == 'presto_gold':
#         return user.username
#     if database.name == 'analytics':
#         if 'analytics' in [r.name for r in user.roles]:
#             return 'analytics_cta'
#         else:
#             return f'tmp_{schema}'
# Function accepts database object, user object, schema name and sql that will be run.
SQLLAB_CTAS_SCHEMA_NAME_FUNC: (
    None | (Callable[[Database, models.User, str, str], str])
) = None

# If enabled, it can be used to store the results of long-running queries
# in SQL Lab by using the "Run Async" button/feature
RESULTS_BACKEND: BaseCache | None = None

# Use PyArrow and MessagePack for async query results serialization,
# rather than JSON. This feature requires additional testing from the
# community before it is fully adopted, so this config option is provided
# in order to disable should breaking issues be discovered.
RESULTS_BACKEND_USE_MSGPACK = True

# The S3 bucket where you want to store your external hive tables created
# from CSV files. For example, 'companyname-superset'
CSV_TO_HIVE_UPLOAD_S3_BUCKET = None

# The directory within the bucket specified above that will
# contain all the external tables
CSV_TO_HIVE_UPLOAD_DIRECTORY = "EXTERNAL_HIVE_TABLES/"


# Function that creates upload directory dynamically based on the
# database used, user and schema provided.
def CSV_TO_HIVE_UPLOAD_DIRECTORY_FUNC(  # pylint: disable=invalid-name  # noqa: N802
    database: Database,
    user: models.User,  # pylint: disable=unused-argument
    schema: str | None,
) -> str:
    # Note the final empty path enforces a trailing slash.
    return os.path.join(
        CSV_TO_HIVE_UPLOAD_DIRECTORY, str(database.id), schema or "", ""
    )


# The namespace within hive where the tables created from
# uploading CSVs will be stored.
UPLOADED_CSV_HIVE_NAMESPACE: str | None = None


# Function that computes the allowed schemas for the CSV uploads.
# Allowed schemas will be a union of schemas_allowed_for_file_upload
# db configuration and a result of this function.
def allowed_schemas_for_csv_upload(  # pylint: disable=unused-argument
    database: Database,
    user: models.User,
) -> list[str]:
    return [UPLOADED_CSV_HIVE_NAMESPACE] if UPLOADED_CSV_HIVE_NAMESPACE else []


ALLOWED_USER_CSV_SCHEMA_FUNC = allowed_schemas_for_csv_upload

# Values that should be treated as nulls for the csv uploads.
CSV_DEFAULT_NA_NAMES = list(STR_NA_VALUES)

# A dictionary of items that gets merged into the Jinja context for
# SQL Lab. The existing context gets updated with this dictionary,
# meaning values for existing keys get overwritten by the content of this
# dictionary. Exposing functionality through JINJA_CONTEXT_ADDONS has security
# implications as it opens a window for a user to execute untrusted code.
# It's important to make sure that the objects exposed (as well as objects attached
# to those objects) are harmless. We recommend only exposing simple/pure functions that
# return native types.
JINJA_CONTEXT_ADDONS: dict[str, Callable[..., Any]] = {}

# A dictionary of macro template processors (by engine) that gets merged into global
# template processors. The existing template processors get updated with this
# dictionary, which means the existing keys get overwritten by the content of this
# dictionary. The customized addons don't necessarily need to use Jinja templating
# language. This allows you to define custom logic to process templates on a per-engine
# basis. Example value = `{"presto": CustomPrestoTemplateProcessor}`
CUSTOM_TEMPLATE_PROCESSORS: dict[str, type[BaseTemplateProcessor]] = {}

# Roles that are controlled by the API / Superset and should not be changed
# by humans.
ROBOT_PERMISSION_ROLES = ["Public", "Gamma", "Alpha", "Admin", "sql_lab"]

CONFIG_PATH_ENV_VAR = "SUPERSET_CONFIG_PATH"

# If a callable is specified, it will be called at app startup while passing
# a reference to the Flask app. This can be used to alter the Flask app
# in whatever way.
# example: FLASK_APP_MUTATOR = lambda x: x.before_request = f
FLASK_APP_MUTATOR = None

# smtp server configuration
SMTP_HOST = "localhost"
SMTP_STARTTLS = True
SMTP_SSL = False
SMTP_USER = "superset"
SMTP_PORT = 25
SMTP_PASSWORD = "superset"  # noqa: S105
SMTP_MAIL_FROM = "superset@superset.com"
# If True creates a default SSL context with ssl.Purpose.CLIENT_AUTH using the
# default system root CA certificates.
SMTP_SSL_SERVER_AUTH = False
ENABLE_CHUNK_ENCODING = False

# Whether to bump the logging level to ERROR on the flask_appbuilder package
# Set to False if/when debugging FAB related issues like
# permission management
SILENCE_FAB = True

FAB_ADD_SECURITY_VIEWS = True
FAB_ADD_SECURITY_API = True
FAB_ADD_SECURITY_PERMISSION_VIEW = False
FAB_ADD_SECURITY_VIEW_MENU_VIEW = False
FAB_ADD_SECURITY_PERMISSION_VIEWS_VIEW = False

# The link to a page containing common errors and their resolutions
# It will be appended at the bottom of sql_lab errors.
TROUBLESHOOTING_LINK = ""

# CSRF token timeout, set to None for a token that never expires
WTF_CSRF_TIME_LIMIT = int(timedelta(weeks=1).total_seconds())

# This link should lead to a page with instructions on how to gain access to a
# Datasource. It will be placed at the bottom of permissions errors.
PERMISSION_INSTRUCTIONS_LINK = ""

# Integrate external Blueprints to the app by passing them to your
# configuration. These blueprints will get integrated in the app
BLUEPRINTS: list[Blueprint] = []

# Provide a callable that receives a tracking_url and returns another
# URL. This is used to translate internal Hadoop job tracker URL
# into a proxied one


# Transform SQL query tracking url for Hive and Presto engines. You may also
# access information about the query itself by adding a second parameter
# to your transformer function, e.g.:
#   TRACKING_URL_TRANSFORMER = (
#       lambda url, query: url if is_fresh(query) else None
#   )
# pylint: disable-next=unnecessary-lambda-assignment
TRACKING_URL_TRANSFORMER = lambda url: url  # noqa: E731


# customize the polling time of each engine
DB_POLL_INTERVAL_SECONDS: dict[str, int] = {}

# Interval between consecutive polls when using Presto Engine
# See here: https://github.com/dropbox/PyHive/blob/8eb0aeab8ca300f3024655419b93dad926c1a351/pyhive/presto.py#L93  # noqa: E501
PRESTO_POLL_INTERVAL = int(timedelta(seconds=1).total_seconds())

# Allow list of custom authentications for each DB engine.
# Example:
# from your.module import AuthClass
# from another.extra import auth_method
#
# ALLOWED_EXTRA_AUTHENTICATIONS: Dict[str, Dict[str, Callable[..., Any]]] = {
#     "trino": {
#         "custom_auth": AuthClass,
#         "another_auth_method": auth_method,
#     },
# }
ALLOWED_EXTRA_AUTHENTICATIONS: dict[str, dict[str, Callable[..., Any]]] = {}

# The id of a template dashboard that should be copied to every new user
DASHBOARD_TEMPLATE_ID = None


# A context manager that wraps the call to `create_engine`. This can be used for many
# things, such as chrooting to prevent 3rd party drivers to access the filesystem, or
# setting up custom configuration for database drivers.
@contextmanager
def engine_context_manager(  # pylint: disable=unused-argument
    database: Database,
    catalog: str | None,
    schema: str | None,
) -> Iterator[None]:
    yield None


ENGINE_CONTEXT_MANAGER = engine_context_manager

# A callable that allows altering the database connection URL and params
# on the fly, at runtime. This allows for things like impersonation or
# arbitrary logic. For instance you can wire different users to
# use different connection parameters, or pass their email address as the
# username. The function receives the connection uri object, connection
# params, the username, and returns the mutated uri and params objects.
# Example:
#   def DB_CONNECTION_MUTATOR(uri, params, username, security_manager, source):
#       user = security_manager.find_user(username=username)
#       if user and user.email:
#           uri.username = user.email
#       return uri, params
#
# Note that the returned uri and params are passed directly to sqlalchemy's
# as such `create_engine(url, **params)`
DB_CONNECTION_MUTATOR = None


# A callable that is invoked for every invocation of DB Engine Specs
# which allows for custom validation of the engine URI.
# See: superset.db_engine_specs.base.BaseEngineSpec.validate_database_uri
# Example:
#   def DB_ENGINE_URI_VALIDATOR(sqlalchemy_uri: URL):
#       if not <some condition>:
#           raise Exception("URI invalid")
#
DB_SQLA_URI_VALIDATOR: Callable[[URL], None] | None = None

# A set of disallowed SQL functions per engine. This is used to restrict the use of
# unsafe SQL functions in SQL Lab and Charts. The keys of the dictionary are the engine
# names, and the values are sets of disallowed functions.
DISALLOWED_SQL_FUNCTIONS: dict[str, set[str]] = {
    # PostgreSQL functions that could reveal sensitive information
    "postgresql": {
        # System information functions
        "current_database",
        "current_schema",
        "current_user",
        "session_user",
        "current_setting",
        "version",
        # Network/server information functions
        "inet_client_addr",
        "inet_client_port",
        "inet_server_addr",
        "inet_server_port",
        # File system functions
        "pg_read_file",
        "pg_ls_dir",
        "pg_read_binary_file",
        # XML functions that can execute SQL
        "database_to_xml",
        "database_to_xmlschema",
        "query_to_xml",
        "query_to_xmlschema",
        "table_to_xml",
        "table_to_xml_and_xmlschema",
        "query_to_xml_and_xmlschema",
        "table_to_xmlschema",
        # Other potentially dangerous functions
        "pg_sleep",
        "pg_terminate_backend",
    },
    # MySQL functions and variables that could reveal sensitive information
    "mysql": {
        # Functions
        "database",
        "schema",
        "current_user",
        "session_user",
        "system_user",
        "user",
        "version",
        "connection_id",
        "load_file",
        "sleep",
        "benchmark",
        "kill",
    },
    # SQLite functions that could reveal sensitive information
    "sqlite": {
        "sqlite_version",
        "sqlite_source_id",
        "sqlite_offset",
        "sqlite_compileoption_used",
        "sqlite_compileoption_get",
        "load_extension",
    },
    # Microsoft SQL Server functions
    "mssql": {
        "db_name",
        "suser_sname",
        "user_name",
        "host_name",
        "host_id",
        "suser_id",
        "system_user",
        "current_user",
        "original_login",
        "xp_cmdshell",
        "xp_regread",
        "xp_fileexist",
        "xp_dirtree",
        "serverproperty",
        "is_srvrolemember",
        "has_dbaccess",
        "fn_virtualfilestats",
        "fn_servershareddrives",
    },
    # Clickhouse functions
    "clickhouse": {
        "currentUser",
        "currentDatabase",
        "hostName",
        "currentRoles",
        "version",
        "buildID",
        "url",
        "filesystemPath",
        "getOSInformation",
        "getMacro",
        "getSetting",
    },
}


# A function that intercepts the SQL to be executed and can alter it.
# A common use case for this is around adding some sort of comment header to the SQL
# with information such as the username and worker node information
#
#    def SQL_QUERY_MUTATOR(
#        sql,
#        security_manager=security_manager,
#        database=database,
#    ):
#        dttm = datetime.now().isoformat()
#        return f"-- [SQL LAB] {user_name} {dttm}\n{sql}"
#
# NOTE: For backward compatibility, you can unpack any of the above arguments in your
# function definition, but keep the **kwargs as the last argument to allow new args
# to be added later without any errors.
# NOTE: whatever you in this function DOES NOT affect the cache key, so ideally this function  # noqa: E501
# is "functional", as in deterministic from its input.
def SQL_QUERY_MUTATOR(  # pylint: disable=invalid-name,unused-argument  # noqa: N802
    sql: str, **kwargs: Any
) -> str:
    return sql


# A variable that chooses whether to apply the SQL_QUERY_MUTATOR before or after splitting the input query  # noqa: E501
# It allows for using the SQL_QUERY_MUTATOR function for more than comments
# Usage: If you want to apply a change to every statement to a given query, set MUTATE_AFTER_SPLIT = True  # noqa: E501
# An example use case is if data has role based access controls, and you want to apply
# a SET ROLE statement alongside every user query. Changing this variable maintains
# functionality for both the SQL_Lab and Charts.
MUTATE_AFTER_SPLIT = False


# Boolean config that determines if alert SQL queries should also be mutated or not.
MUTATE_ALERT_QUERY = False


# This allows for a user to add header data to any outgoing emails. For example,
# if you need to include metadata in the header or you want to change the specifications
# of the email title, header, or sender.
def EMAIL_HEADER_MUTATOR(  # pylint: disable=invalid-name,unused-argument  # noqa: N802
    msg: MIMEMultipart, **kwargs: Any
) -> MIMEMultipart:
    return msg


# Define a list of usernames to be excluded from all dropdown lists of users
# Owners, filters for created_by, etc.
# The users can also be excluded by overriding the get_exclude_users_from_lists method
# in security manager
EXCLUDE_USERS_FROM_LISTS: list[str] | None = None

# For database connections, this dictionary will remove engines from the available
# list/dropdown if you do not want these dbs to show as available.
# The available list is generated by driver installed, and some engines have multiple
# drivers.
# e.g., DBS_AVAILABLE_DENYLIST: Dict[str, Set[str]] = {"databricks": {"pyhive", "pyodbc"}}  # noqa: E501
DBS_AVAILABLE_DENYLIST: dict[str, set[str]] = {}

# This auth provider is used by background (offline) tasks that need to access
# protected resources. Can be overridden by end users in order to support
# custom auth mechanisms
MACHINE_AUTH_PROVIDER_CLASS = "superset.utils.machine_auth.MachineAuthProvider"

# ---------------------------------------------------
# Alerts & Reports
# ---------------------------------------------------
# Used for Alerts/Reports (Feature flask ALERT_REPORTS) to set the size for the
# sliding cron window size, should be synced with the celery beat config minus 1 second
ALERT_REPORTS_CRON_WINDOW_SIZE = 59
ALERT_REPORTS_WORKING_TIME_OUT_KILL = True
# Which user to attempt to execute Alerts/Reports as. By default,
# execute as the primary owner of the alert/report (giving priority to the last
# modifier and then the creator if either is contained within the list of owners,
# otherwise the first owner will be used).
#
# To first try to execute as the creator in the owners list (if present), then fall
# back to the creator, then the last modifier in the owners list (if present), then the
# last modifier, then an owner and finally the "admin" user, set as follows:
#
# from superset.tasks.types import ExecutorType, FixedExecutor
#
# ALERT_REPORTS_EXECUTORS = [
#     ExecutorType.CREATOR_OWNER,
#     ExecutorType.CREATOR,
#     ExecutorType.MODIFIER_OWNER,
#     ExecutorType.MODIFIER,
#     ExecutorType.OWNER,
#     FixedExecutor("admin"),
# ]
ALERT_REPORTS_EXECUTORS: list[ExecutorType] = [ExecutorType.OWNER]
# if ALERT_REPORTS_WORKING_TIME_OUT_KILL is True, set a celery hard timeout
# Equal to working timeout + ALERT_REPORTS_WORKING_TIME_OUT_LAG
ALERT_REPORTS_WORKING_TIME_OUT_LAG = int(timedelta(seconds=10).total_seconds())
# if ALERT_REPORTS_WORKING_TIME_OUT_KILL is True, set a celery hard timeout
# Equal to working timeout + ALERT_REPORTS_WORKING_SOFT_TIME_OUT_LAG
ALERT_REPORTS_WORKING_SOFT_TIME_OUT_LAG = int(timedelta(seconds=1).total_seconds())
# Default values that user using when creating alert
ALERT_REPORTS_DEFAULT_WORKING_TIMEOUT = 3600
ALERT_REPORTS_DEFAULT_RETENTION = 90
ALERT_REPORTS_DEFAULT_CRON_VALUE = "0 0 * * *"  # every day
# If set to true no notification is sent, the worker will just log a message.
# Useful for debugging
ALERT_REPORTS_NOTIFICATION_DRY_RUN = False
# Max tries to run queries to prevent false errors caused by transient errors
# being returned to users. Set to a value >1 to enable retries.
ALERT_REPORTS_QUERY_EXECUTION_MAX_TRIES = 1
# Custom width for screenshots
ALERT_REPORTS_MIN_CUSTOM_SCREENSHOT_WIDTH = 600
ALERT_REPORTS_MAX_CUSTOM_SCREENSHOT_WIDTH = 2400
# Set a minimum interval threshold between executions (for each Alert/Report)
# Value should be an integer i.e. int(timedelta(minutes=5).total_seconds())
# You can also assign a function to the config that returns the expected integer
ALERT_MINIMUM_INTERVAL = int(timedelta(minutes=0).total_seconds())
REPORT_MINIMUM_INTERVAL = int(timedelta(minutes=0).total_seconds())

# A custom prefix to use on all Alerts & Reports emails
EMAIL_REPORTS_SUBJECT_PREFIX = "[Report] "

# The text for call-to-action link in Alerts & Reports emails
EMAIL_REPORTS_CTA = "Explore in Superset"

# Slack API token for the superset reports, either string or callable
SLACK_API_TOKEN: Callable[[], str] | str | None = None
SLACK_PROXY = None
SLACK_CACHE_TIMEOUT = int(timedelta(days=1).total_seconds())

# The webdriver to use for generating reports. Use one of the following
# firefox
#   Requires: geckodriver and firefox installations
#   Limitations: can be buggy at times
# chrome:
#   Requires: headless chrome
#   Limitations: unable to generate screenshots of elements
WEBDRIVER_TYPE = "firefox"

# Window size - this will impact the rendering of the data
WEBDRIVER_WINDOW = {
    "dashboard": (1600, 2000),
    "slice": (3000, 1200),
    "pixel_density": 1,
}

# An optional override to the default auth hook used to provide auth to the offline
# webdriver (when using Selenium) or browser context (when using Playwright - see
# PLAYWRIGHT_REPORTS_AND_THUMBNAILS feature flag)
WEBDRIVER_AUTH_FUNC = None

# Any config options to be passed as-is to the webdriver
WEBDRIVER_CONFIGURATION = {
    "options": {"capabilities": {}, "preferences": {}, "binary_location": ""},
    "service": {"log_output": "/dev/null", "service_args": [], "port": 0, "env": {}},
}

# Additional args to be passed as arguments to the config object
# Note: If using Chrome, you'll want to add the "--marionette" arg.
WEBDRIVER_OPTION_ARGS = ["--headless"]

# The base URL to query for accessing the user interface
WEBDRIVER_BASEURL = "http://0.0.0.0:8080/"
# The base URL for the email report hyperlinks.
WEBDRIVER_BASEURL_USER_FRIENDLY = WEBDRIVER_BASEURL
# Time selenium will wait for the page to load and render for the email report.
EMAIL_PAGE_RENDER_WAIT = int(timedelta(seconds=30).total_seconds())

# Send user to a link where they can report bugs
BUG_REPORT_URL = None
BUG_REPORT_TEXT = "Report a bug"
BUG_REPORT_ICON = None  # Recommended size: 16x16

# Send user to a link where they can read more about Superset
DOCUMENTATION_URL = None
DOCUMENTATION_TEXT = "Documentation"
DOCUMENTATION_ICON = None  # Recommended size: 16x16

# What is the Last N days relative in the time selector to:
# 'today' means it is midnight (00:00:00) in the local timezone
# 'now' means it is relative to the query issue time
# If both start and end time is set to now, this will make the time
# filter a moving window. By only setting the end time to now,
# start time will be set to midnight, while end will be relative to
# the query issue time.
DEFAULT_RELATIVE_START_TIME = "today"
DEFAULT_RELATIVE_END_TIME = "today"

# Configure which SQL validator to use for each engine
SQL_VALIDATORS_BY_ENGINE = {
    "presto": "PrestoDBSQLValidator",
    "postgresql": "PostgreSQLValidator",
}

# A list of preferred databases, in order. These databases will be
# displayed prominently in the "Add Database" dialog. You should
# use the "engine_name" attribute of the corresponding DB engine spec
# in `superset/db_engine_specs/`.
PREFERRED_DATABASES: list[str] = [
    "PostgreSQL",
    "Presto",
    "MySQL",
    "SQLite",
    # etc.
]
# When adding a new database we try to connect to it. Depending on which parameters are
# incorrect this could take a couple minutes, until the SQLAlchemy driver pinging the
# database times out. Instead of relying on the driver timeout we can specify a shorter
# one here.
TEST_DATABASE_CONNECTION_TIMEOUT = timedelta(seconds=30)

# Details needed for databases that allows user to authenticate using personal OAuth2
# tokens. See https://github.com/apache/superset/issues/20300 for more information. The
# scope and URIs are usually optional.
# NOTE that if you change the id, scope, or URIs in this file, you probably need to purge  # noqa: E501
# the existing tokens from the database. This needs to be done by running a query to
# delete the existing tokens.
DATABASE_OAUTH2_CLIENTS: dict[str, dict[str, Any]] = {
    # "Google Sheets": {
    #     "id": "XXX.apps.googleusercontent.com",
    #     "secret": "GOCSPX-YYY",
    #     "scope": " ".join(
    #         [
    #             "https://www.googleapis.com/auth/drive.readonly",
    #             "https://www.googleapis.com/auth/spreadsheets",
    #             "https://spreadsheets.google.com/feeds",
    #         ]
    #     ),
    #     "authorization_request_uri": "https://accounts.google.com/o/oauth2/v2/auth",
    #     "token_request_uri": "https://oauth2.googleapis.com/token",
    # },
}

# OAuth2 state is encoded in a JWT using the alogorithm below.
DATABASE_OAUTH2_JWT_ALGORITHM = "HS256"

# By default the redirect URI points to /api/v1/database/oauth2/ and doesn't have to be
# specified. If you're running multiple Superset instances you might want to have a
# proxy handling the redirects, since redirect URIs need to be registered in the OAuth2
# applications. In that case, the proxy can forward the request to the correct instance
# by looking at the `default_redirect_uri` attribute in the OAuth2 state object.
# DATABASE_OAUTH2_REDIRECT_URI = "http://localhost:8088/api/v1/database/oauth2/"

# Timeout when fetching access and refresh tokens.
DATABASE_OAUTH2_TIMEOUT = timedelta(seconds=30)

# Enable/disable CSP warning
CONTENT_SECURITY_POLICY_WARNING = True

# Do you want Talisman enabled?
TALISMAN_ENABLED = utils.cast_to_boolean(os.environ.get("TALISMAN_ENABLED", True))
TALISMAN_ENABLED = False

# If you want Talisman, how do you want it configured??
# For more information on setting up Talisman, please refer to
# https://superset.apache.org/docs/configuration/networking-settings/#changing-flask-talisman-csp

TALISMAN_CONFIG = {
    "content_security_policy": {
        "base-uri": ["'self'"],
        "default-src": ["'self'"],
        "img-src": [
            "'self'",
            "blob:",
            "data:",
            "https://apachesuperset.gateway.scarf.sh",
            "https://static.scarf.sh/",
            # "https://cdn.brandfolder.io", # Uncomment when SLACK_ENABLE_AVATARS is True  # noqa: E501
            "ows.terrestris.de",
            "https://cdn.document360.io",
        ],
        "worker-src": ["'self'", "blob:"],
        "connect-src": [
            "'self'",
            "https://api.mapbox.com",
            "https://events.mapbox.com",
            "https://tile.openstreetmap.org",
            "https://tile.osm.ch",
        ],
        "object-src": "'none'",
        "style-src": [
            "'self'",
            "'unsafe-inline'",
        ],
        "script-src": ["'self'", "'strict-dynamic'"],
    },
    "content_security_policy_nonce_in": ["script-src"],
    "force_https": False,
    "session_cookie_secure": False,
}
# React requires `eval` to work correctly in dev mode
TALISMAN_DEV_CONFIG = {
    "content_security_policy": {
        "base-uri": ["'self'"],
        "default-src": ["'self'"],
        "img-src": [
            "'self'",
            "blob:",
            "data:",
            "https://apachesuperset.gateway.scarf.sh",
            "https://static.scarf.sh/",
            "https://cdn.brandfolder.io",
            "ows.terrestris.de",
            "https://cdn.document360.io",
        ],
        "worker-src": ["'self'", "blob:"],
        "connect-src": [
            "'self'",
            "https://api.mapbox.com",
            "https://events.mapbox.com",
            "https://tile.openstreetmap.org",
            "https://tile.osm.ch",
        ],
        "object-src": "'none'",
        "style-src": [
            "'self'",
            "'unsafe-inline'",
        ],
        "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
    },
    "content_security_policy_nonce_in": ["script-src"],
    "force_https": False,
    "session_cookie_secure": False,
}

#
# Flask session cookie options
#
# See https://flask.palletsprojects.com/en/1.1.x/security/#set-cookie-options
# for details
#
SESSION_COOKIE_HTTPONLY = True  # Prevent cookie from being read by frontend JS?
SESSION_COOKIE_SECURE = False  # Prevent cookie from being transmitted over non-tls?
SESSION_COOKIE_SAMESITE: Literal["None", "Lax", "Strict"] | None = "Lax"
# Whether to use server side sessions from flask-session or Flask secure cookies
SESSION_SERVER_SIDE = False
# Example config using Redis as the backend for server side sessions
# from flask_session import RedisSessionInterface
#
# SESSION_SERVER_SIDE = True
# SESSION_TYPE = "redis"
# SESSION_REDIS = Redis(host="localhost", port=6379, db=0)
#
# Other possible config options and backends:
# # https://flask-session.readthedocs.io/en/latest/config.html

# Cache static resources.
SEND_FILE_MAX_AGE_DEFAULT = int(timedelta(days=365).total_seconds())

# URI to database storing the example data, points to
# SQLALCHEMY_DATABASE_URI by default if set to `None`
SQLALCHEMY_EXAMPLES_URI = (
    "sqlite:///" + os.path.join(DATA_DIR, "examples.db") + "?check_same_thread=false"
)

# Optional prefix to be added to all static asset paths when rendering the UI.
# This is useful for hosting assets in an external CDN, for example
STATIC_ASSETS_PREFIX = ""

# Some sqlalchemy connection strings can open Superset to security risks.
# Typically these should not be allowed.
PREVENT_UNSAFE_DB_CONNECTIONS = True

# If true all default urls on datasets will be handled as relative URLs by the frontend
PREVENT_UNSAFE_DEFAULT_URLS_ON_DATASET = True

# Define a list of allowed URLs for dataset data imports (v1).
# Simple example to only allow URLs that belong to certain domains:
# ALLOWED_IMPORT_URL_DOMAINS = [
#     r"^https://.+\.domain1\.com\/?.*", r"^https://.+\.domain2\.com\/?.*"
# ]
DATASET_IMPORT_ALLOWED_DATA_URLS = [r".*"]

# Path used to store SSL certificates that are generated when using custom certs.
# Defaults to temporary directory.
# Example: SSL_CERT_PATH = "/certs"
SSL_CERT_PATH: str | None = None

# SQLA table mutator, every time we fetch the metadata for a certain table
# (superset.connectors.sqla.models.SqlaTable), we call this hook
# to allow mutating the object with this callback.
# This can be used to set any properties of the object based on naming
# conventions and such. You can find examples in the tests.

# pylint: disable-next=unnecessary-lambda-assignment
SQLA_TABLE_MUTATOR = lambda table: table  # noqa: E731


# Global async query config options.
# Requires GLOBAL_ASYNC_QUERIES feature flag to be enabled.
GLOBAL_ASYNC_QUERY_MANAGER_CLASS = (
    "superset.async_events.async_query_manager.AsyncQueryManager"
)
GLOBAL_ASYNC_QUERIES_REDIS_STREAM_PREFIX = "async-events-"
GLOBAL_ASYNC_QUERIES_REDIS_STREAM_LIMIT = 1000
GLOBAL_ASYNC_QUERIES_REDIS_STREAM_LIMIT_FIREHOSE = 1000000
GLOBAL_ASYNC_QUERIES_REGISTER_REQUEST_HANDLERS = True
GLOBAL_ASYNC_QUERIES_JWT_COOKIE_NAME = "async-token"
GLOBAL_ASYNC_QUERIES_JWT_COOKIE_SECURE = False
GLOBAL_ASYNC_QUERIES_JWT_COOKIE_SAMESITE: None | (Literal["None", "Lax", "Strict"]) = (
    None
)
GLOBAL_ASYNC_QUERIES_JWT_COOKIE_DOMAIN = None
GLOBAL_ASYNC_QUERIES_JWT_SECRET = "test-secret-change-me"  # noqa: S105
GLOBAL_ASYNC_QUERIES_TRANSPORT: Literal["polling", "ws"] = "polling"
GLOBAL_ASYNC_QUERIES_POLLING_DELAY = int(
    timedelta(milliseconds=500).total_seconds() * 1000
)
GLOBAL_ASYNC_QUERIES_WEBSOCKET_URL = "ws://127.0.0.1:8080/"

# Global async queries cache backend configuration options:
# - Set 'CACHE_TYPE' to 'RedisCache' for RedisCacheBackend.
# - Set 'CACHE_TYPE' to 'RedisSentinelCache' for RedisSentinelCacheBackend.
GLOBAL_ASYNC_QUERIES_CACHE_BACKEND = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_HOST": "localhost",
    "CACHE_REDIS_PORT": 6379,
    "CACHE_REDIS_USER": "",
    "CACHE_REDIS_PASSWORD": "",
    "CACHE_REDIS_DB": 0,
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_REDIS_SENTINELS": [("localhost", 26379)],
    "CACHE_REDIS_SENTINEL_MASTER": "mymaster",
    "CACHE_REDIS_SENTINEL_PASSWORD": None,
    "CACHE_REDIS_SSL": False,  # True or False
    "CACHE_REDIS_SSL_CERTFILE": None,
    "CACHE_REDIS_SSL_KEYFILE": None,
    "CACHE_REDIS_SSL_CERT_REQS": "required",
    "CACHE_REDIS_SSL_CA_CERTS": None,
}

# Embedded config options
GUEST_ROLE_NAME = "Public"
GUEST_TOKEN_JWT_SECRET = "test-guest-secret-change-me"  # noqa: S105
GUEST_TOKEN_JWT_ALGO = "HS256"  # noqa: S105
GUEST_TOKEN_HEADER_NAME = "X-GuestToken"  # noqa: S105
GUEST_TOKEN_JWT_EXP_SECONDS = 300  # 5 minutes
# Audience for the Superset guest token used in embedded mode.
# Can be a string or a callable. Defaults to WEBDRIVER_BASEURL.
# When generating the guest token, ensure the
# payload's `aud` matches GUEST_TOKEN_JWT_AUDIENCE.
GUEST_TOKEN_JWT_AUDIENCE: Callable[[], str] | str | None = None

# A callable that can be supplied to do extra validation of guest token configuration
# for example certain RLS parameters:
# lambda x: len(x['rls']) == 1 and "tenant_id=" in x['rls'][0]['clause']
#
# Takes the GuestTokenUser dict as an argument
# Return False from the callable to return a HTTP 400 to the user.

GUEST_TOKEN_VALIDATOR_HOOK = None

# A SQL dataset health check. Note if enabled it is strongly advised that the callable
# be memoized to aid with performance, i.e.,
#
#    @cache_manager.cache.memoize(timeout=0)
#    def DATASET_HEALTH_CHECK(datasource: SqlaTable) -> Optional[str]:
#        if (
#            datasource.sql and
#            len(SQLScript(datasource.sql).tables) == 1
#        ):
#            return (
#                "This virtual dataset queries only one table and therefore could be "
#                "replaced by querying the table directly."
#            )
#
#        return None
#
# Within the FLASK_APP_MUTATOR callable, i.e., once the application and thus cache have
# been initialized it is also necessary to add the following logic to blow the cache for
# all datasources if the callback function changed.
#
#    def FLASK_APP_MUTATOR(app: Flask) -> None:
#        name = "DATASET_HEALTH_CHECK"
#        func = app.config[name]
#        code = func.uncached.__code__.co_code
#
#        if cache_manager.cache.get(name) != code:
#            cache_manager.cache.delete_memoized(func)
#            cache_manager.cache.set(name, code, timeout=0)
#
DATASET_HEALTH_CHECK: Callable[[SqlaTable], str] | None = None

# the advanced data type key should correspond to that set in the column metadata
ADVANCED_DATA_TYPES: dict[str, AdvancedDataType] = {
    "internet_address": internet_address,
    "port": internet_port,
}

# By default, the Welcome page features all charts and dashboards the user has access
# to. This can be changed to show only examples, or a custom view
# by providing the title and a FAB filter:
# WELCOME_PAGE_LAST_TAB = (
#     "Xyz",
#     [{"col": 'created_by', "opr": 'rel_o_m', "value": 10}],
# )
WELCOME_PAGE_LAST_TAB: Literal["examples", "all"] | tuple[str, list[dict[str, Any]]] = (
    "all"
)

# Max allowed size for a zipped file
ZIPPED_FILE_MAX_SIZE = 100 * 1024 * 1024  # 100MB
# Max allowed compression ratio for a zipped file
ZIP_FILE_MAX_COMPRESS_RATIO = 200.0

# Configuration for environment tag shown on the navbar. Setting 'text' to '' will hide the tag.  # noqa: E501
# 'color' can either be a hex color code, or a dot-indexed theme color (e.g. error.base)
ENVIRONMENT_TAG_CONFIG = {
    "variable": "SUPERSET_ENV",
    "values": {
        "debug": {
            "color": "error.base",
            "text": "flask-debug",
        },
        "development": {
            "color": "error.base",
            "text": "Development",
        },
        "production": {
            "color": "",
            "text": "",
        },
    },
}


# Extra related query filters make it possible to limit which objects are shown
# in the UI. For examples, to only show "admin" or users starting with the letter "b" in
# the "Owners" dropdowns, you could add the following in your config:
# def user_filter(query: Query, *args, *kwargs):
#     from superset import security_manager
#
#     user_model = security_manager.user_model
#     filters = [
#         user_model.username == "admin",
#         user_model.username.ilike("b%"),
#     ]
#     return query.filter(or_(*filters))
#
#  EXTRA_RELATED_QUERY_FILTERS = {"user": user_filter}
#
# Similarly, to restrict the roles in the "Roles" dropdown you can provide a custom
# filter callback for the "role" key.
class ExtraRelatedQueryFilters(TypedDict, total=False):
    role: Callable[[Query], Query]
    user: Callable[[Query], Query]


EXTRA_RELATED_QUERY_FILTERS: ExtraRelatedQueryFilters = {}


# Extra dynamic query filters make it possible to limit which objects are shown
# in the UI before any other filtering is applied. Useful for example when
# considering to filter using Feature Flags along with regular role filters
# that get applied by default in our base_filters.
# For example, to only show a database starting with the letter "b"
# in the "Database Connections" list, you could add the following in your config:
# def initial_database_filter(query: Query, *args, *kwargs):
#     from superset.models.core import Database
#
#     filter = Database.database_name.startswith('b')
#     return query.filter(filter)
#
#  EXTRA_DYNAMIC_QUERY_FILTERS = {"database": initial_database_filter}
class ExtraDynamicQueryFilters(TypedDict, total=False):
    databases: Callable[[Query], Query]


EXTRA_DYNAMIC_QUERY_FILTERS: ExtraDynamicQueryFilters = {}


# The migrations that add catalog permissions might take a considerably long time
# to execute as it has to create permissions to all schemas and catalogs from all
# other catalogs accessible by the credentials. This flag allows to skip the
# creation of these secondary perms, and focus only on permissions for the default
# catalog. These secondary permissions can be created later by editing the DB
# connection via the UI (without downtime).
CATALOGS_SIMPLIFIED_MIGRATION: bool = False


# When updating a DB connection or manually triggering a perm sync, the command
# happens in sync mode. If you have a celery worker configured, it's recommended
# to change below config to ``True`` to run this process in async mode. A DB
# connection might have hundreds of catalogs with thousands of schemas each, which
# considerably increases the time to process it. Running it in async mode prevents
# keeping a web API call open for this long.
SYNC_DB_PERMISSIONS_IN_ASYNC_MODE: bool = False


# -------------------------------------------------------------------
# *                WARNING:  STOP EDITING  HERE                    *
# -------------------------------------------------------------------
# Don't add config values below this line since local configs won't be
# able to override them.
if CONFIG_PATH_ENV_VAR in os.environ:
    # Explicitly import config module that is not necessarily in pythonpath; useful
    # for case where app is being executed via pex.
    cfg_path = os.environ[CONFIG_PATH_ENV_VAR]
    try:
        module = sys.modules[__name__]
        spec = importlib.util.spec_from_file_location("superset_config", cfg_path)
        override_conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(override_conf)
        for key in dir(override_conf):
            if key.isupper():
                setattr(module, key, getattr(override_conf, key))

        click.secho(f"Loaded your LOCAL configuration at [{cfg_path}]", fg="cyan")
    except Exception:
        logger.exception(
            "Failed to import config for %s=%s", CONFIG_PATH_ENV_VAR, cfg_path
        )
        raise
elif importlib.util.find_spec("superset_config"):
    try:
        # pylint: disable=import-error,wildcard-import,unused-wildcard-import
        import superset_config
        from superset_config import *  # noqa: F403, F401

        click.secho(
            f"Loaded your LOCAL configuration at [{superset_config.__file__}]",
            fg="cyan",
        )
    except Exception:
        logger.exception("Found but failed to import local superset_config")
        raise
