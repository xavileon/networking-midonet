# Copyright (C) 2015 Midokura SARL
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from midonet.neutron.client import base as c_base

from neutron.api import extensions as neutron_extensions
from neutron import i18n
from neutron.plugins.common import constants as const
from neutron_fwaas.db.firewall import firewall_db
from neutron_fwaas import extensions
from neutron_fwaas.services.firewall import fwaas_plugin as fw_plugin

from oslo_config import cfg
from oslo_log import helpers as log_helpers
from oslo_log import log as logging
from oslo_utils import excutils

LOG = logging.getLogger(__name__)
_LE = i18n._LE
_LW = i18n._LW


class _MidonetFirewallDriver(object):
    """FWaaS driver for MidoNet that implements the RPC API

    The driver does not actually do any RPC, but simply proxies the API calls
    to the MidoNet side.  This design was chosen instead of implementing the
    FWaaS plugin methods because these methods get as input more complete data
    on the firewall object, including its rules and the routers
    associated/disassociated.  The downside is that each request might get
    bloated unnecessarily.  We will revisit the design when such problem
    arises.
    """

    def __init__(self, client, callbacks):
        self.client = client
        self.callbacks = callbacks
        self.plugin = callbacks.plugin

    @log_helpers.log_method_call
    def create_firewall(self, context, firewall):
        # This method is called outside of DB transaction
        try:
            self.client.create_firewall(context, firewall)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to create a firewall %(fw_id)s "
                              "in Midonet: %(err)s"),
                          {"fw_id": firewall["id"], "err": ex})
                try:
                    self.plugin.delete_db_firewall_object(context,
                                                          firewall['id'])
                except Exception:
                    LOG.exception(_LE("Failed to delete firewall %s"),
                                  firewall['id'])

        self.callbacks.set_firewall_status(context, firewall['id'],
                                           const.ACTIVE)

    @log_helpers.log_method_call
    def update_firewall(self, context, firewall):
        # This method is called outside of DB transaction
        try:
            self.client.update_firewall(context, firewall)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to update a firewall %(fw_id)s "
                              "in Midonet: %(err)s"),
                          {"fw_id": firewall["id"], "err": ex})
                try:
                    self.callbacks.set_firewall_status(context, firewall['id'],
                                                       const.ERROR)
                except Exception:
                    LOG.exception(_LE("Failed to update firewall status %s"),
                                  firewall['id'])

        self.callbacks.set_firewall_status(context, firewall['id'],
                                           const.ACTIVE)

    @log_helpers.log_method_call
    def delete_firewall(self, context, firewall):
        # This method is called outside of DB transaction
        try:
            self.client.delete_firewall(context, firewall)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to delete a firewall %(fw_id)s "
                              "in Midonet: %(err)s"),
                          {"fw_id": firewall["id"], "err": ex})
                try:
                    self.callbacks.set_firewall_status(context, firewall['id'],
                                                       const.ERROR)
                except Exception:
                    LOG.exception(_LE("Failed to update firewall status %s"),
                                  firewall['id'])

        self.callbacks.firewall_deleted(context, firewall['id'])


class MidonetFirewallPlugin(fw_plugin.FirewallPlugin):

    """Implementation of the Neutron Firewall Service Plugin.

    This class manages the workflow of FWaaS request/response.
    DB related updates, including router insertion logics, are handled by
    fw_plugin.FirewallPlugin.
    """

    def __init__(self):
        """Override initialization to avoid any RPC setup as MidoNet does not
        rely on any agent to implement FWaaS.  Instead, set the rpc handling
        to the _MidonetFirewallDriver class so that it handles the FWaaS update
        events.
        """

        # Register the FWaaS extensions path
        neutron_extensions.append_api_extensions_path(extensions.__path__)

        # Although callbacks are unnecessary in midonet, use FirewallCallbacks
        # because it contains useful methods for DB updates.
        self.callbacks = fw_plugin.FirewallCallbacks(self)
        self.client = c_base.load_client(cfg.CONF.MIDONET)
        self.agent_rpc = _MidonetFirewallDriver(self.client, self.callbacks)
        self.endpoints = [self.callbacks]  # So that tests don't complain
        firewall_db.subscribe()
