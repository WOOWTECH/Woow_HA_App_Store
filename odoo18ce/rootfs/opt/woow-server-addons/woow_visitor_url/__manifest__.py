{
    "name": "Woow Visitor URL",
    "summary": "Website visitor tracking records the Canonical URL, not the host the request arrived on",
    "description": """
Loaded through server_wide_modules by the Woow Odoo 18 add-on, never
installed in a database. It rebuilds the URL Odoo's website visitor
tracking stores on the website's Canonical URL, so a page view opened
through Ingress does not record the Home Assistant host. It ships no
models, data or views.
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
