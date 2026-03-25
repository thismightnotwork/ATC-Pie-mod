# This file is part of the ATC-pie project,
# an air traffic control simulation program.
#
# Copyright (C) 2015 Michael Filhol
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from sys import stderr
from datetime import datetime, timedelta, timezone

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QTcpSocket

from ai.aircraft import pitch_factor

from base.acft import Aircraft, Xpdr
from base.fpl import FPL
from base.params import Heading, AltFlSpec, Speed, distance_travelled
from base.util import some, rounded, m2NM

from ext.fgfs import FGFS_model_position
from ext.fgms import mk_fgms_position_packet, FGMS_prop_XPDR_capability, FGMS_prop_XPDR_code, \
    FGMS_prop_XPDR_ident, FGMS_prop_XPDR_alt, FGMS_prop_XPDR_gnd, FGMS_prop_XPDR_ias, FGMS_prop_XPDR_mach

from session.config import settings
from session.env import env

# ---------- Constants ----------

# Use the same protocol revision your OpenFSD accepts from VRC (100)
protocol_version = '100'  # VRC-style proto on your OpenFSD
init_connection_timeout = 3000  # ms
min_dist_for_hdg_update = m2NM * .1
max_time_for_pos_update = timedelta(seconds=5)
min_height_for_neg_pitch = 100  # ft
speed_estimation_factor_airborne = .9
speed_estimation_factor_onGround = .75
min_height_for_airborne = 50  # ft
allowed_FPL_DEP_time_delay = timedelta(hours=5)

# VRC-style client identity, from your tcpdump / working main.py
# $IDEGKK_TWR:SERVER:de1e:VRC 1.2.6:1:2:1:272337954:6eba0f94eae6e734ce3068d7b06772ed
VRC_CLIENT_ID_HEX = "de1e"
VRC_CLIENT_NAME = "VRC 1.2.6"
VRC_NETWORK_ID = "1"
VRC_SIM_TYPE = "2"
VRC_UNIQUE_NUM = "272337954"
VRC_TOKEN_HASH = "6eba0f94eae6e734ce3068d7b06772ed"

# -------------------------------

# received prefix -> number of fields to split from left
recv_prefixes_fmt = {
    '#AA': 6,
    '#AP': 7,
    '#DA': 2,
    '#DL': 4,
    '#DP': 2,
    '#TM': 3,
    '$AR': 4,
    '$CQ': 3,
    '$CR': 4,
    '$ER': 5,
    '$FP': 17,
    '$HO': 3,
    '%': 8,
    '@': 10,
}


def secure_field(s):
    return s.replace(':', ' ').replace('\n', ' ')


def FPL_16_fields(fpl):
    spd = fpl[FPL.TAS]
    eet = fpl[FPL.EET]
    cr_alt = fpl[FPL.CRUISE_ALT]
    if eet is None:
        eetH = eetM = ''
    else:
        minutes = rounded(eet.total_seconds() / 60)
        full_hours = int(minutes / 60)
        eetH = str(full_hours)
        eetM = str(minutes - 60 * full_hours)
    dep_time = ''
    fpldep = fpl[FPL.TIME_OF_DEP]
    if fpldep is not None:
        tnow = settings.session_manager.clockTime()
        if tnow < fpldep + allowed_FPL_DEP_time_delay < tnow + timedelta(days=1):
            dep_time = '%02d%02d' % (fpldep.hour, fpldep.minute)
    return [
        some(fpl[FPL.CALLSIGN], ''),
        {'IFR': 'I', 'VFR': 'V'}.get(fpl[FPL.FLIGHT_RULES], ''),
        some(fpl[FPL.ACFT_TYPE], ''),
        ('' if spd is None else '%d' % spd.kt()),
        some(fpl[FPL.ICAO_DEP], ''),
        dep_time,
        '',
        ('' if cr_alt is None else cr_alt.toStr()),
        some(fpl[FPL.ICAO_ARR], ''),
        eetH,
        eetM,
        '',
        '',
        some(fpl[FPL.ICAO_ALT], ''),
        some(fpl[FPL.COMMENTS], ''),
        some(fpl[FPL.ROUTE], ''),
    ]


def FPL_from_fields(callsign, destFSD, rules, acft, spd, depAD,
                    dep1, dep2, cruise, destAD, eetH, eetM, fob1, fob2, altAD, rmk, route):
    fpl = FPL()
    fpl[FPL.CALLSIGN] = callsign
    fpl[FPL.ICAO_DEP] = depAD
    fpl[FPL.ICAO_ARR] = destAD
    fpl[FPL.ICAO_ALT] = altAD
    try:
        fpl[FPL.CRUISE_ALT] = AltFlSpec.fromStr(cruise)
    except ValueError:
        pass
    fpl[FPL.ROUTE] = route
    fpl[FPL.COMMENTS] = rmk
    fpl[FPL.FLIGHT_RULES] = {'I': 'IFR', 'V': 'VFR'}.get(rules)
    filtered_acft_split = [s for s in acft.split('/', maxsplit=2) if len(s) > 1]
    if len(filtered_acft_split) == 1:
        fpl[FPL.ACFT_TYPE] = filtered_acft_split[0]
    tnow = settings.session_manager.clockTime()
    try:
        tdep = datetime(tnow.year, tnow.month, tnow.day,
                        hour=int(dep1[:2]), minute=int(dep1[2:]), tzinfo=timezone.utc)
        if tnow - allowed_FPL_DEP_time_delay > tdep:
            tdep += timedelta(days=1)
        fpl[FPL.TIME_OF_DEP] = tdep
    except ValueError:
        pass
    try:
        hh = int(eetH)
        mm = int(eetM)
        if hh != 0 or mm != 0:
            fpl[FPL.EET] = timedelta(hours=hh, minutes=mm)
    except ValueError:
        pass
    try:
        fpl[FPL.TAS] = Speed(int(spd))
    except ValueError:
        pass
    return fpl


def freq_str(frq):
    # convert COM freq (e.g. 122.800) to 5-digit integer string without leading 1/decimal, e.g. "22800"
    return ''.join(c for c in str(frq)[1:] if c != '.')


def send_vrc_style_id_packet(socket, callsign, rating_str):
    """
    Send $ID... packet that mimics VRC 1.2.6 on your OpenFSD,
    identical pattern to main.py.
    """
    parts = [
        "$ID" + callsign,
        "SERVER",
        VRC_CLIENT_ID_HEX,
        VRC_CLIENT_NAME,
        VRC_NETWORK_ID,
        VRC_SIM_TYPE,
        rating_str,
        VRC_UNIQUE_NUM,
        VRC_TOKEN_HASH,
    ]
    line = ":".join(parts) + "\r\n"
    socket.write(line.encode("utf8"))
    print("[CLI]", line.strip(), file=stderr)


class FsdAircraft(Aircraft):
    def __init__(self, callsign, acft_type, pd_pos, pd_alt, pd_speed, pd_xpdr):
        Aircraft.__init__(self, callsign, acft_type, pd_pos, pd_alt)
        self.last_PD_time = settings.session_manager.clockTime()
        self.last_PD_coords = pd_pos
        self.last_PD_alt = pd_alt
        self.last_PD_speed = pd_speed
        self.last_PD_xpdr = pd_xpdr
        self.last_vs_ftpsec = 0
        self.last_heading = None
        self.prior_heading = None

    def updateLiveStatusWithEstimate(self):
        if self.last_heading is None:
            return
        dt = min(settings.session_manager.clockTime() - self.last_PD_time, max_time_for_pos_update)
        deg_offset = 0 if self.prior_heading is None else self.last_heading.diff(self.prior_heading) / 2
        spd_fact = speed_estimation_factor_airborne if self.last_PD_alt >= env.elevation(self.last_PD_coords) + min_height_for_airborne else speed_estimation_factor_onGround
        est_pos = self.last_PD_coords.moved(self.last_heading + deg_offset, distance_travelled(dt, self.last_PD_speed * spd_fact))
        est_alt = max(self.last_PD_alt + dt.total_seconds() * self.last_vs_ftpsec / 2, env.elevation(est_pos))
        self.updateLiveStatus(est_pos, est_alt, self.last_PD_xpdr)

    def updatePdStatus(self, pd_pos, pd_alt, pd_speed, pd_xpdr):
        tnow = settings.session_manager.clockTime()
        self.last_vs_ftpsec = (pd_alt - self.last_PD_alt) / (tnow - self.last_PD_time).total_seconds()
        if self.last_PD_coords.distanceTo(pd_pos) >= min_dist_for_hdg_update:
            self.prior_heading = self.last_heading
            self.last_heading = self.last_PD_coords.headingTo(pd_pos)
        else:
            self.prior_heading = None
        self.updateLiveStatus(pd_pos, pd_alt, pd_xpdr)
        self.last_PD_time = tnow
        self.last_PD_coords = pd_pos
        self.last_PD_alt = pd_alt
        self.last_PD_speed = pd_speed
        self.last_PD_xpdr = pd_xpdr

    def fgmsPositionPacket(self):
        pdct = {FGMS_prop_XPDR_capability: 1}
        try:
            pdct[FGMS_prop_XPDR_code] = self.last_PD_xpdr[Xpdr.CODE]
        except KeyError:
            pass
        try:
            pdct[FGMS_prop_XPDR_ident] = self.last_PD_xpdr[Xpdr.IDENT]
        except KeyError:
            pass
        try:
            pdct[FGMS_prop_XPDR_alt] = int(self.last_PD_xpdr[Xpdr.ALT].ft1013())
        except KeyError:
            pass
        try:
            pdct[FGMS_prop_XPDR_gnd] = self.last_PD_xpdr[Xpdr.GND]
        except KeyError:
            pass
        try:
            pdct[FGMS_prop_XPDR_ias] = int(self.last_PD_xpdr[Xpdr.IAS].kt())
        except KeyError:
            pass
        try:
            pdct[FGMS_prop_XPDR_mach] = self.last_PD_xpdr[Xpdr.MACH]
        except KeyError:
            pass
        acft_coords = self.liveCoords()
        acft_amsl = self.liveRealAlt()
        acft_hdg = some(self.last_heading, Heading(0, True))
        model, coords, amsl = FGFS_model_position(self.aircraft_type, acft_coords, acft_amsl, acft_hdg)
        deg_pitch = 0 if self.last_vs_ftpsec < 0 and acft_amsl < env.elevation(acft_coords) + min_height_for_neg_pitch \
            else pitch_factor * 60 * self.last_vs_ftpsec
        return mk_fgms_position_packet(self.identifier, model, coords, amsl,
                                       hdg=acft_hdg.trueAngle(), pitch=deg_pitch, roll=0, properties=pdct)


class FsdConnection(QObject):
    cmdReceived = pyqtSignal(str, list)
    connectionDropped = pyqtSignal()

    def __init__(self, parent):
        QObject.__init__(self, parent)
        self.socket = None
        self.strinbuf = ''

    def initOK(self):
        self.socket = QTcpSocket(self)
        self.socket.disconnected.connect(self.socketDisconnected)
        self.socket.readyRead.connect(self.receiveBytes)
        self.socket.connectToHost(settings.FSD_server_host, settings.FSD_server_port)
        if self.socket.waitForConnected(init_connection_timeout):
            # Read $DI banner ($DISERVER:CLIENT:...) [FSD docs]
            self.socket.waitForReadyRead(init_connection_timeout)
            banner = bytes(self.socket.readAll()).decode('utf8', errors='ignore')
            print("[SRV]", banner.strip(), file=stderr)

            rating_str = str(settings.FSD_rating)

            # VRC-style $ID
            send_vrc_style_id_packet(self.socket, settings.my_callsign, rating_str)

            # VRC-style #AA ATC login
            self.sendLinePacket(
                '#AA' + settings.my_callsign,
                'SERVER',
                settings.MP_social_name,
                settings.FSD_cid,
                settings.FSD_password,
                rating_str,
                protocol_version
            )
        else:
            self.socket = None
        return self.isConnected()

    def socketDisconnected(self):
        self.socket = None
        self.connectionDropped.emit()

    def isConnected(self):
        return self.socket is not None and self.socket.state() == QAbstractSocket.ConnectedState

    def shutdown(self):
        self.sendLinePacket('#DA' + settings.my_callsign, 'SERVER')
        self.socket.disconnectFromHost()

    def sendLinePacket(self, *fields, lastVerbatim=False):
        safe_fields = [secure_field(s) for s in fields[:-1]]
        if len(fields) > 0:
            safe_fields.append(fields[-1] if lastVerbatim else secure_field(fields[-1]))
        line = ':'.join(safe_fields)
        self.socket.write((line + '\r\n').encode('utf8'))
        print('[CLI]', line, file=stderr)

    def receiveBytes(self):
        self.strinbuf += bytes(self.socket.readAll()).decode('utf8')
        while '\n' in self.strinbuf:
            fsd_line, self.strinbuf = self.strinbuf.split('\n', maxsplit=1)
            fsd_line = fsd_line.rstrip('\r')
            print('[SRV]', fsd_line, file=stderr)
            try:
                cmd, reqlen = next((prefix, nf) for prefix, nf in recv_prefixes_fmt.items()
                                   if fsd_line.startswith(prefix))
                self.cmdReceived.emit(cmd, fsd_line[len(cmd):].split(':', maxsplit=(reqlen - 1)))
            except StopIteration:
                print('Unhandled packet:', fsd_line, file=stderr)

    # -------- ATC Position (%) per FSD docs --------

    def sendPositionUpdate(self):
        coords = env.radarPos()

        if settings.publicised_frequency is None:
            freqs_field = "0"
        else:
            freqs_field = freq_str(settings.publicised_frequency)

        facility_type = "3"
        vis_range = str(settings.FSD_visibility_range)
        rating_str = str(settings.FSD_rating)
        lat_str = "%f" % coords.lat
        lon_str = "%f" % coords.lon

        self.sendLinePacket(
            "%" + settings.my_callsign,
            freqs_field,
            facility_type,
            vis_range,
            rating_str,
            lat_str,
            lon_str,
            "0",
        )

    # --- METAR / TEXT basic implementations ---

    def sendMetarRequest(self, station):
        self.sendLinePacket(
            "$AX" + settings.my_callsign,
            "SERVER",
            "METAR",
            station
        )

    def sendTextMsg(self, msg, frq=None):
        if msg.isPrivate():
            self.sendLinePacket("#TM" + msg.sender(), msg.recipient(),
                                msg.txtOnly(), lastVerbatim=True)
        elif frq is None:
            self.sendLinePacket("#TM" + msg.sender(), "*A",
                                msg.txtOnly(), lastVerbatim=True)
        else:
            self.sendLinePacket("#TM" + msg.sender(), "@" + freq_str(frq),
                                msg.txtMsg(), lastVerbatim=True)

    # --- Keep other advanced packets disabled for now ---

    def sendQuery(self, requestee, query):
        return

    def sendQueryResponse(self, requester, query, response):
        return

    def sendFpl(self, fpl):
        return

    def sendFplAmendment(self, fpl):
        return

    def sendNonAtcPieHandover(self, recipient, callsign):
        return
