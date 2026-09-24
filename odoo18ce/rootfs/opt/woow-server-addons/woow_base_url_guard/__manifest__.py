{
    "name": "Woow Base URL Guard",
    "summary": "Stop Odoo guessing web.base.url from the request an admin logged in from",
    "description": """
Loaded through server_wide_modules by the Woow Odoo 18 add-on, never
installed in a database. It removes Odoo's automatic web.base.url guess so
that the add-on's maintenance bootstrap is the only writer of the Canonical
URL. It ships no models, data or views.
""",
    "version": "18.0.1.0.0",
    "category": "Hidden",
    "author": "WoowTech",
    "website": "https://github.com/WOOWTECH/Woow_ha_odoo",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "auto_install": False,
    "application": False,
}
