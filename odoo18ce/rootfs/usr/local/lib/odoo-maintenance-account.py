#!/usr/bin/env python3
"""One-shot maintenance account from /config/bootstrap-user.json.

odoo-maintenance-bootstrap pipes this file into ``odoo shell -d <default_db>
--no-http`` after it has validated the file. Inputs arrive in the environment:

    ODOO_MAINT_USER_LOGIN     login to create or update
    ODOO_MAINT_USER_PASSWORD  password (at least 20 characters, checked by the bootstrap)
    ODOO_MAINT_USER_ADMIN     "true" grants Settings and Access Rights, anything else revokes them
"""
import os

login = os.environ.get("ODOO_MAINT_USER_LOGIN", "").strip()
password = os.environ.get("ODOO_MAINT_USER_PASSWORD", "")
admin = os.environ.get("ODOO_MAINT_USER_ADMIN", "false").lower() == "true"

Users = env["res.users"].sudo().with_context(no_reset_password=True)  # noqa: F821 - injected by odoo shell
user = Users.search([("login", "=", login)], limit=1)
values = {
    "name": "HA Ingress E2E",
    "login": login,
    "password": password,
    "active": True,
    "share": False,
}
if user:
    user.write(values)
else:
    user = Users.create(values)
internal = env.ref("base.group_user")  # noqa: F821
access_rights = env.ref("base.group_erp_manager")  # noqa: F821
system = env.ref("base.group_system")  # noqa: F821
commands = [(4, internal.id)]
if admin:
    commands += [(4, access_rights.id), (4, system.id)]
else:
    commands += [(3, system.id), (3, access_rights.id)]
user.write({"groups_id": commands})
env.cr.commit()  # noqa: F821
