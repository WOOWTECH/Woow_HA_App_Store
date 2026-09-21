#!/usr/bin/env python3
from pathlib import Path
import yaml
cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config.yaml').read_text())
assert cfg['stage'] == 'stable'
assert cfg['ingress'] is True
assert cfg['ingress_panel'] is True
assert cfg['ingress_port'] == 8098
assert cfg['panel_admin'] is False
assert cfg['panel_title'] == 'Woow Collabora'
assert cfg['options']['collabora_url'] == 'http://homeassistant:9981'
print('Collabora admin proxy config checks passed')
