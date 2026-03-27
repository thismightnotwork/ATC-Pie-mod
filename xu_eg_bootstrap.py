#!/usr/bin/env python3
"""
xu_eg_bootstrap.py

Automatically downloads and installs IVAO XU EG-Sector-File nav data into
ATC-pie's CONFIG directory the first time an EG* location is launched.

Data sourced from: https://github.com/IVAO-XU/EG-Sector-File
Licensed under the terms of that repository. This script only fetches
and reformats the data for ATC-pie; it does not redistribute the raw files.
"""

import os
import sys
import shutil
import zipfile
import tempfile
import urllib.request
from pathlib import Path

# ---- Paths ----------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent
_CONFIG = _ROOT / 'CONFIG'
_NAV    = _CONFIG / 'nav'
_AD     = _CONFIG / 'ad'
_BG     = _CONFIG / 'bg'
_MARKER = _NAV / '.xu_eg_installed'

# ---- Remote source --------------------------------------------------------

_EG_ZIP_URL = (
    'https://github.com/IVAO-XU/EG-Sector-File/archive/refs/heads/master.zip'
)
_EG_PREFIX = 'EG-Sector-File-master/Include/egxx/eg-nav/'
_ISC_PREFIX = 'EG-Sector-File-master/'

# ---- Navaid / fix / airway file lists ------------------------------------

_NAVAID_FILES = [
    'egxx-vor.vor',
    'egxx-foreign-vor.vor',
    'egxx-ndb.ndb',
    'egxx-foreign-ndb.ndb',
    'egxx-military-vor.vor',
    'egxx-military-ndb.ndb',
]

_FIX_FILES = [
    'egxx-fix.fix',
    'egxx-foreign-fix.fix',
    'egxx-procedure-fix.fix',
    'egxx-military-fix.fix',
    'egxx-military-procedure-fix.fix',
]

_AWY_FILES = [
    'egxx-low-airways.lairway',
    'egxx-high-airways.hairway',
]

_APT_FILE = 'egxx-apt.apt'
_ISC_FILE = 'egxx.isc'


def _merge_text_files(sources):
    """Read and concatenate a list of Path objects, skipping missing files."""
    parts = []
    for src in sources:
        if src.exists():
            parts.append(src.read_text(encoding='utf-8', errors='replace'))
        else:
            print('[xu_eg_bootstrap] WARNING: expected file not found: %s' % src.name,
                  file=sys.stderr)
    return '\n'.join(parts)


def _download_and_extract():
    """Download EG-Sector-File ZIP and extract eg-nav + egxx.isc."""
    print('[xu_eg_bootstrap] Downloading IVAO XU EG-Sector-File…')
    tmp_zip = _CONFIG / '_EG-Sector-File.zip'
    tmp_zip.parent.mkdir(parents=True, exist_ok=True)

    try:
        urllib.request.urlretrieve(_EG_ZIP_URL, tmp_zip)
    except Exception as exc:
        raise RuntimeError(
            'Failed to download EG-Sector-File from GitHub: %s' % exc
        ) from exc

    print('[xu_eg_bootstrap] Extracting…')
    extract_dir = _CONFIG / '_EG-Sector-File-master'
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    with zipfile.ZipFile(tmp_zip, 'r') as zf:
        # extract eg-nav folder
        nav_members = [m for m in zf.namelist() if m.startswith(_EG_PREFIX)]
        # extract egxx.isc (for background sector extraction)
        isc_members = [
            m for m in zf.namelist()
            if m == _ISC_PREFIX + _ISC_FILE
        ]
        zf.extractall(_CONFIG, nav_members + isc_members)

    tmp_zip.unlink(missing_ok=True)

    # Rename extracted top-level folder to our expected name
    extracted_top = _CONFIG / 'EG-Sector-File-master'
    if extracted_top.exists() and extracted_top != extract_dir:
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extracted_top.rename(extract_dir)

    return extract_dir / 'Include' / 'egxx' / 'eg-nav'


def _install_nav_data(eg_nav):
    """Write CONFIG/nav/navaid.dat, fix.dat, awy.dat from XU eg-nav files."""
    _NAV.mkdir(parents=True, exist_ok=True)

    navaid_text = _merge_text_files([eg_nav / f for f in _NAVAID_FILES])
    if navaid_text.strip():
        (_NAV / 'navaid.dat').write_text(navaid_text, encoding='utf-8')
        print('[xu_eg_bootstrap] Written CONFIG/nav/navaid.dat')

    fix_text = _merge_text_files([eg_nav / f for f in _FIX_FILES])
    if fix_text.strip():
        (_NAV / 'fix.dat').write_text(fix_text, encoding='utf-8')
        print('[xu_eg_bootstrap] Written CONFIG/nav/fix.dat')

    awy_text = _merge_text_files([eg_nav / f for f in _AWY_FILES])
    if awy_text.strip():
        (_NAV / 'awy.dat').write_text(awy_text, encoding='utf-8')
        print('[xu_eg_bootstrap] Written CONFIG/nav/awy.dat')


def _install_ad_data(eg_nav):
    """Copy egxx-apt.apt → CONFIG/ad/EGXX.dat for airport layout data."""
    _AD.mkdir(parents=True, exist_ok=True)
    apt_src = eg_nav / _APT_FILE
    if apt_src.exists():
        dest = _AD / 'EGXX.dat'
        shutil.copy2(apt_src, dest)
        print('[xu_eg_bootstrap] Written CONFIG/ad/EGXX.dat')
    else:
        print('[xu_eg_bootstrap] WARNING: %s not found; skipping AD data.' % _APT_FILE,
              file=sys.stderr)


def _install_bg_data(extract_dir):
    """
    Run ATC-pie's own ext/sct.extract_sector() on egxx.isc to produce
    background drawing files for all EG airports, then install them
    into CONFIG/bg/.
    """
    isc_path = extract_dir / _ISC_FILE
    if not isc_path.exists():
        print('[xu_eg_bootstrap] WARNING: egxx.isc not found; skipping background extraction.',
              file=sys.stderr)
        return

    try:
        from ext.sct import extract_sector  # ATC-pie built-in
        from base.coords import EarthCoords
    except ImportError as exc:
        print('[xu_eg_bootstrap] WARNING: Could not import ATC-pie sector extractor (%s); '
              'skipping background extraction.' % exc, file=sys.stderr)
        return

    _BG.mkdir(parents=True, exist_ok=True)
    output_dir = _ROOT / 'OUTPUT'
    output_dir.mkdir(parents=True, exist_ok=True)

    # Centre on EGTT FIR (approximately central England)
    centre = EarthCoords.fromString('52d00m00sN,001d30m00sW')
    range_nm = 500  # large enough to cover EGTT + EGPX

    print('[xu_eg_bootstrap] Extracting sector backgrounds from egxx.isc…')
    try:
        extract_sector(str(isc_path), centre, range_nm)
    except Exception as exc:
        print('[xu_eg_bootstrap] WARNING: Sector extraction failed (%s); '
              'background drawings unavailable.' % exc, file=sys.stderr)
        return

    # Move produced bg-* and *.lst files from OUTPUT → CONFIG/bg
    moved = 0
    for item in output_dir.iterdir():
        if item.name.startswith('bg-') or item.suffix in ('.lst', '.extract'):
            dest = _BG / item.name
            shutil.move(str(item), dest)
            moved += 1
    if moved:
        print('[xu_eg_bootstrap] Installed %d background file(s) into CONFIG/bg/' % moved)
    else:
        print('[xu_eg_bootstrap] No background files produced by sector extraction.')


def ensure_xu_eg_data():
    """
    Entry point called from ATC-pie.py before nav data is loaded.
    On first run for any EG* location, downloads and installs:
      - CONFIG/nav/navaid.dat  (VOR + NDB)
      - CONFIG/nav/fix.dat     (all waypoints)
      - CONFIG/nav/awy.dat     (airways)
      - CONFIG/ad/EGXX.dat     (airport layouts)
      - CONFIG/bg/*            (sector background drawings)
    Subsequent launches skip this entirely via a marker file.
    """
    if _MARKER.exists():
        return  # already installed

    print('[xu_eg_bootstrap] First EG launch detected – installing XU EG sector data…')

    try:
        eg_nav = _download_and_extract()
        extract_dir = eg_nav.parents[2]  # _CONFIG/_EG-Sector-File-master
        _install_nav_data(eg_nav)
        _install_ad_data(eg_nav)
        _install_bg_data(extract_dir)

        # Write marker so this only runs once
        _MARKER.write_text('installed\n', encoding='utf-8')
        print('[xu_eg_bootstrap] XU EG sector data installed successfully.')

    except Exception as exc:
        print('[xu_eg_bootstrap] ERROR during bootstrap: %s' % exc, file=sys.stderr)
        print('[xu_eg_bootstrap] Continuing without XU EG data. '
              'Some nav data may be missing.', file=sys.stderr)
