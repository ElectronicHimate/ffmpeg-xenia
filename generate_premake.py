import os
import re

template_header = """
-----------------------------------------------------------------------
---- Automatically generated by generate_premake.py. Do not edit ! ----
-----------------------------------------------------------------------

project("{}")
  uuid("{}")
  kind("StaticLib")
  language("C")
  ffmpeg_common()

  filter("files:not wmaprodec.c")
    warnings "Off"
  filter({{}})
"""

templates = {}
templates['libavutil'] = template_header.format('libavutil', '19216035-F781-4F15-B009-213B7E3A18AC')

templates['libavcodec'] =  template_header.format('libavcodec', '9DB2830C-D326-48ED-B4CC-08EA6A1B7272') + """
  links({
    "libavutil",
  })
"""
class Config():
    def __init__(self, os, arch, config_h, premake_filters):
        self.os = os
        self.arch = arch
        self.config_h = config_h
        self.premake_filters = premake_filters
        self.key_values = []

supported_configs = [
    Config('windows', 'x86_64' , 'config_windows_x86_64.h' , 'platforms:Windows-x86_64'),
    Config('windows', 'aarch64', 'config_windows_aarch64.h', 'platforms:Windows-ARM64'),
    Config('linux'  , 'x86_64' , 'config_linux_x86_64.h'   , 'platforms:Linux'),
    Config('android', 'x86_64' , 'config_android_x86_64.h' , 'platforms:Android-x86_64'),
    Config('android', 'aarch64', 'config_android_aarch64.h', 'platforms:Android-ARM64'),
]

def are_list_items_identical(list_a, list_b):
    set_a = set(list_a)
    if len(set_a) != len(list_b):
        return False
    for a in set_a:
        if a not in list_b:
            return False
    return True

# gets the config defines from the generated header
def parse_config(file_name):
    conf = {}
    # platform configs mostly differ in HAVE_*, which we are not interested in
    with open(file_name, 'r') as c:
        for line in c:
            split = line.rstrip().split(' ' , 2)
            if len(split) != 3:
                continue
            if split[0] != '#define':
                continue
            key = split[1]
            val = split[2]
            if val[0] == '"' and val[-1] == '"':
                val = val[1:-1]
            else:
                try:
                    val = int(val)
                except ValueError:
                    pass
            conf[key] = val
    return conf

def parse_configs():
    for config in supported_configs:
        config.key_values = parse_config(config.config_h)

# Adapted from distutils.sysconfig.parse_makefile
# Regexes needed for parsing Makefile (and similar syntaxes,
# like old-style Setup files).
_variable_rx = re.compile(r"([a-zA-Z][a-zA-Z0-9\-_]+)\s*(\+?)=\s*(.*)")
_variable_conditional_rx = re.compile(r"([a-zA-Z][a-zA-Z0-9\-_]+)-\$\(([a-zA-Z][a-zA-Z0-9\-_]+)\)\s*(\+?)=\s*(.*)")
_findvar1_rx = re.compile(r"\$\(([A-Za-z][A-Za-z0-9\-_]*)\)")
_findvar2_rx = re.compile(r"\${([A-Za-z][A-Za-z0-9\-_]*)}")
def parse_makefile(fn, conf, g=None):
    """Parse a Makefile-style file.

    A dictionary containing name/value pairs is returned.  If an
    optional dictionary is passed in as the second argument, it is
    used instead of a new dictionary.
    """
    from distutils.text_file import TextFile
    fp = TextFile(fn, strip_comments=1, skip_blanks=1, join_lines=1, errors="surrogateescape")

    if g is None:
        g = {}
    done = {}
    notdone = {}

    while True:
        line = fp.readline()
        if line is None: # eof
            break
        n = cond = app = v = None
        m = _variable_rx.match(line)
        if m:
            n, app, v = m.group(1, 2, 3)
        else:
            m = _variable_conditional_rx.match(line)
            if m:
                n, cond, app, v = m.group(1, 2, 3, 4)

        if v:
            v = v.strip()

            # `$$' is a literal `$' in make
            tmpv = v.replace('$$', '')


            if cond:
                boolean = cond in conf and conf[cond]
                n += ('-yes' if boolean else '-no')

            if "$" in tmpv:
                notdone[n] = v
            else:
                v = v.replace('$$', '$')
                if app:
                    if n not in done:
                        done[n] = v
                    else:
                        done[n] += ' ' + v
                else:
                    done[n] = v

    # hacky. just assume they were all +=
    notdone_done = {}
    # do variable interpolation here
    while notdone:
        for name in list(notdone):
            value = notdone[name]
            m = _findvar1_rx.search(value) or _findvar2_rx.search(value)
            if m:
                n = m.group(1)
                found = True
                if n in done:
                    item = str(done[n])
                elif n in notdone:
                    # get it on a subsequent round
                    found = False
                elif n in os.environ:
                    # do it like make: fall back to environment
                    item = os.environ[n]

                else:
                    notdone_done[n] = item = ""
                if found:
                    after = value[m.end():]
                    value = value[:m.start()] + item + after
                    if "$" in after:
                        notdone[name] = value
                    else:
                        notdone_done[name] = value
                        del notdone[name]
            else:
                # bogus variable reference; just drop it since we can't deal
                del notdone[name]
    for k in notdone_done:
        if k in done:
            done[k] += ' ' + notdone_done[k]
        else:
            done[k] = notdone_done[k]

    fp.close()

    # strip spurious spaces
    for k, v in done.items():
        if isinstance(v, str):
            done[k] = v.strip()

    # save the results in the global dictionary
    g.update(done)
    return g

def premake_files(files, libname):
    # .o rule order from ffbuild:
    extensions = [
        '.c',
        '.cpp',
        '.m',
        '.S',
        '.asm',
        '.rc',
    ]
    s = '  files({\n'
    for f in files:
        match = re.search('^(.*).o$', f)
        if match:
            for ext in extensions:
                f2 = match.group(1) + ext
                if os.path.exists(os.path.join(libname, f2)):
                    f = f2
                    break
            if f.endswith('.o'):
                print('Error: could not resolve source for OBJ "{}".'.format(f))
        s += '    "{}",\n'.format(f)
    s += '  })\n'
    return s

def premake_filter(filters = None):
    f = '  filter({'
    if filters and len(filters):
        f += '"'
        # Concatenate sorted (for consistency) filters
        f += ' or '.join(sorted(filters))
        f += '"'
    f += '})\n'
    return f

def generate_premake(configs, libname):
    M = 'Makefile'

    makefiles = [
        (os.path.join(libname, M)           , configs),
        # Original Makefiles are always included but since symbols are never used we can ignore them:
        (os.path.join(libname, 'aarch64', M), list(filter(lambda config: config.arch == 'aarch64', configs))),
        (os.path.join(libname, 'x86' , M)   , list(filter(lambda config: config.arch == 'x86_64', configs))),
    ]

    # Makefile variables that contain source files - conditionals from arch.mak
    file_blocks = [
        ('HEADERS'          , None),
        ('ARCH_HEADERS'     , None),
        ('BUILT_HEADERS'    , None),
        ('OBJS'             , None),

        ('ARMV5TE-OBJS'     , 'HAVE_ARMV5TE'),
        ('ARMV6-OBJS'       , 'HAVE_ARMV6'),
        ('ARMV8-OBJS'       , 'HAVE_ARMV8'),
        ('VFP-OBJS'         , 'HAVE_VFP'),
        ('NEON-OBJS'        , 'HAVE_NEON'),

        ('MMX-OBJS'         , 'HAVE_MMX'),
        ('X86ASM-OBJS'      , 'HAVE_X86ASM'),
    ]

    # Cache tree of parsed makefile variables
    ms = {}
    for makefile in makefiles:
        ms2 = {}
        for config in configs:
            ms2[config] = parse_makefile(makefile[0], config.key_values)
        ms[makefile[0]] = ms2

    with open(os.path.join(libname, 'premake5.lua'), 'w') as premake:
        premake.write(templates[libname])
        for makefile in makefiles:
            premake.write('\n  -- {}:\n'.format(makefile[0].replace('\\', '/')))
            for file_block in file_blocks:
                files = {}
                for config in makefile[1]:
                    if file_block[1] and ((not file_block[1] in config.key_values) or (not config.key_values[file_block[1]])):
                        continue
                    m = ms[makefile[0]][config]
                    fb = file_block[0]
                    for _ in range(2):
                        if fb in m:
                            for file in m[fb].split():
                                if file not in files:
                                    files[file] = { config }
                                else:
                                    files[file].add(config)
                        fb += '-yes' # Evaluated conditionals

                if len(files):
                    # Get unique config groups
                    config_sets = []
                    for file_configs in files.values():
                        is_new = True
                        for config_set in config_sets:
                            if are_list_items_identical(config_set, file_configs):
                                is_new = False
                                break
                        if is_new:
                            config_sets.append(file_configs)
                    # Make common files come first
                    config_sets = sorted(config_sets, key=lambda x: -len(x))

                    premake.write('  --   {}:\n'.format(file_block[0]))

                    # Write file lists with applied filters
                    filter_used = False
                    for config_set in config_sets:
                        if not are_list_items_identical(config_set, configs): # no filter for common files
                            filter_used = True
                            premake.write(premake_filter([config.premake_filters for config in config_set]))
                        premake.write(premake_files([filename for filename, file_configs in files.items() if are_list_items_identical(config_set, file_configs)], libname))
                    if filter_used:
                        premake.write(premake_filter())

if __name__ == '__main__':
    parse_configs()
    for libname in templates:
        generate_premake(supported_configs, libname)
